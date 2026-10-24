"""Referans Word raporundan (.docx / .dotx) SADECE yapı çıkarır: stil kullanımı, başlık ağacı, tablo düzeni, vurgu.

Amaç: müşteri verisi içeren, elle düzenlenmiş referans raporu geliştiriciye göstermeden rapor stilini ayarlamak.
Çıktıda gövde paragraf metni, başlık satırı dışındaki hücre metni, sayılar ve docProps/core.xml (author, company,
title…) YOKTUR. Başlık ve tablo başlık satırı metinleri `mask_text` ile maskelenir. Bkz. docs/spec/docx_style.md.

    python -m pcs7_analyzer.docx_style <referans.docx> [-o reference_style.json]

Sadece standart kütüphane (zipfile + xml.etree). Deterministik: aynı dosya -> aynı JSON (anahtarlar sıralı).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

SCHEMA_VERSION = "1"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
EP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
OFFICE_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _wval(el, attr: str = "val"):
    return None if el is None else el.get(w(attr))


# --- maskeleme ---------------------------------------------------------------------------------------------------
# Kural (deterministik, belgelenmiş):
#  1. Metin boşluklardan token'lara bölünür.
#  2. İçinde rakam olan token -> "#" (sayı, tarih, versiyon, tag numarası…).
#  3. İçinde 3+ ardışık büyük harf olan bir harf grubu varsa ve bu grup GENERIC_WORDS'te değilse token -> "X"
#     (proje / tesis / müşteri kısaltmaları: ACME_PLANT, DEMO_MP, SRV1…). Harf grupları harf olmayan
#     karakterlerle ayrılır ("ACME_PLANT" -> ACME, PLANT); token'daki HER grup whitelist'te olmalı.
#  4. Diğer token'lar olduğu gibi kalır (küçük harf / Title-case kelimeler: "Genel", "değerlendirme").
GENERIC_WORDS = frozenset({
    # görevde istenen genel bölüm kelimeleri
    "ÖZET", "PROJE", "ENVANTERİ", "RİSKLER", "REFERANSLAR", "TABLO", "EK", "AS", "OS", "HW", "PCS", "SIMATIC",
    "WINCC", "APL", "SFC", "CPU", "CP",
    # genel teknik terimler (müşteriye özel değil)
    "MLFB", "GSD", "PDM", "STEP", "SQL", "OPC", "VBS", "CFC", "SCL", "STL", "FBD", "LAD", "TCP", "ET", "PN", "DP",
    "ES", "FW", "SP", "RT", "PO", "IO", "HMI", "DCS", "PLC", "BLOCKER", "RİSK", "BİLGİ", "KANIT", "ÇIKARIM", "VERİ",
    "YOK", "VAR", "SONUÇ", "GİRİŞ", "EKLER", "NOT", "NOTLAR", "AÇIK", "KONULAR", "ZORLUKLAR", "REFERANS",
})


def _has_upper_run(s: str) -> bool:
    run = 0
    for c in s:
        run = run + 1 if (c.isalpha() and c.isupper()) else 0
        if run >= 3:
            return True
    return False


_EDGE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)


def mask_token(tok: str) -> str:
    """Baştaki/sondaki noktalama korunur ("1:" -> "#:"), çekirdek maskelenir."""
    lead, core, trail = _EDGE.match(tok).groups()
    if any(c.isdigit() for c in tok):
        return f"{lead}#{trail}"
    for g in re.findall(r"[^\W\d_]+", core):
        if _has_upper_run(g) and g.upper() not in GENERIC_WORDS:
            return f"{lead}X{trail}"
    return tok


def mask_text(text: str) -> str:
    return " ".join(mask_token(t) for t in text.split())


def _words(text: str) -> int:
    """Kelime = harf veya rakam içeren token ("|", "→" sayılmaz)."""
    return sum(1 for t in text.split() if any(c.isalnum() for c in t))


# --- XML okuma ---------------------------------------------------------------------------------------------------
def _parse(z: zipfile.ZipFile, name: str):
    """Part'ı parse eder; yoksa None. Bozuk XML -> ValueError (Türkçe mesaj)."""
    try:
        data = z.read(name)
    except KeyError:
        return None
    except (zipfile.BadZipFile, OSError, RuntimeError) as e:
        raise ValueError(f"Word dosyasındaki '{name}' bölümü okunamadı: {e}") from e
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data[:4096]:
        raise ValueError(f"Word dosyasındaki '{name}' bölümü DOCTYPE/ENTITY içeriyor; güvenlik nedeniyle okunmadı.")
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"Word dosyasındaki '{name}' bölümünün XML'i bozuk ({e}); dosya Word'de açılıp "
                         f"yeniden kaydedilmeli.") from e


def _main_part(z: zipfile.ZipFile) -> str:
    rels = _parse(z, "_rels/.rels")
    if rels is not None:
        for r in rels.findall(f"{{{REL_NS}}}Relationship"):
            if r.get("Type") == OFFICE_DOC_REL and r.get("Target"):
                return r.get("Target").lstrip("/")
    return "word/document.xml"


def _own_text(el) -> str:
    """Paragrafın kendi metni (iç içe textbox paragrafları hariç)."""
    out = []

    def rec(e):
        for c in e:
            if c.tag == w("p"):
                continue
            if c.tag == w("t"):
                out.append(c.text or "")
            elif c.tag in (w("tab"), w("br"), w("cr")):
                out.append(" ")
            else:
                rec(c)
    rec(el)
    return "".join(out)


def _iter_paras(el, in_table=False):
    """Belge sırasıyla (paragraf, tablo_içinde) üretir; textbox içindeki paragraflar da (bir kez) gelir."""
    for c in el:
        if c.tag == w("p"):
            yield c, in_table
            yield from _iter_paras(c, in_table)
        elif c.tag == w("tbl"):
            yield from _iter_paras(c, True)
        else:
            yield from _iter_paras(c, in_table)


class _Styles:
    """styles.xml: styleId -> isim, basedOn, outlineLvl; başlık seviyesi çözümü."""
    _HEAD = re.compile(r"^(heading|überschrift|berschrift|başlık|baslik|titre|titolo)\s*(\d)$", re.I)

    def __init__(self, root):
        self.name, self.based, self.outline = {}, {}, {}
        if root is None:
            return
        for s in root.findall(w("style")):
            sid = s.get(w("styleId"))
            if not sid:
                continue
            self.name[sid] = _wval(s.find(w("name"))) or ""
            self.based[sid] = _wval(s.find(w("basedOn")))
            ol = s.find(f"{w('pPr')}/{w('outlineLvl')}")
            if ol is not None and (_wval(ol) or "").isdigit():
                self.outline[sid] = int(_wval(ol))

    def level(self, sid: str | None):
        """Title -> 0, Heading N -> N, outlineLvl k (<9) -> k+1; değilse None."""
        seen = set()
        cur = sid
        while cur and cur not in seen:
            seen.add(cur)
            for cand in (self.name.get(cur, ""), cur):
                c = cand.strip()
                if c.lower() in ("title", "titel", "başlık", "puesto"):
                    return 0
                m = self._HEAD.match(c)
                if m:
                    return int(m.group(2))
            if cur in self.outline and self.outline[cur] < 9:
                return self.outline[cur] + 1
            cur = self.based.get(cur)
        return None

    def is_caption(self, sid: str | None) -> bool:
        if not sid:
            return False
        txt = f"{sid} {self.name.get(sid, '')}".lower()
        return any(k in txt for k in ("caption", "beschriftung", "resim yazısı", "légende", "didascalia"))


def _pstyle(p):
    return _wval(p.find(f"{w('pPr')}/{w('pStyle')}"))


def _table_info(idx: int, tbl, parent_map: dict, styles: _Styles) -> dict:
    rows = tbl.findall(w("tr"))
    grid = [int(g.get(w("w"))) if (g.get(w("w")) or "").isdigit() else None
            for g in tbl.findall(f"{w('tblGrid')}/{w('gridCol')}")]
    n_cols = 0
    cell_words = []
    for tr in rows:
        cols = 0
        for tc in tr.findall(w("tc")):
            span = _wval(tc.find(f"{w('tcPr')}/{w('gridSpan')}"))
            cols += int(span) if span and span.isdigit() else 1
            cell_words.append(sum(_words(_own_text(p)) for p, _ in _iter_paras(tc)))
        n_cols = max(n_cols, cols)
    if not n_cols:
        n_cols = len(grid)
    header = []
    if rows:
        for tc in rows[0].findall(w("tc")):
            header.append(mask_text(" ".join(_own_text(p) for p, _ in _iter_paras(tc))))
    caption = None
    parent = parent_map.get(tbl)
    if parent is not None:
        sib = list(parent)
        i = sib.index(tbl)
        nxt = sib[i + 1] if i + 1 < len(sib) else None
        if nxt is not None and nxt.tag == w("p") and styles.is_caption(_pstyle(nxt)):
            caption = mask_text(_own_text(nxt))
    return {
        "index": idx,
        "n_rows": len(rows),
        "n_cols": n_cols,
        "header": header,
        "style": _wval(tbl.find(f"{w('tblPr')}/{w('tblStyle')}")),
        "col_widths": grid,
        "avg_words_per_cell": round(sum(cell_words) / len(cell_words), 2) if cell_words else 0.0,
        "max_words_per_cell": max(cell_words) if cell_words else 0,
        "rows_repeat_header": any(tr.find(f"{w('trPr')}/{w('tblHeader')}") is not None for tr in rows),
        "cant_split": any(tr.find(f"{w('trPr')}/{w('cantSplit')}") is not None for tr in rows),
        "nested": any(a.tag == w("tc") for a in _ancestors(tbl, parent_map)),
        "caption_masked": caption,
    }


def _ancestors(el, parent_map):
    cur = parent_map.get(el)
    while cur is not None:
        yield cur
        cur = parent_map.get(cur)


def _empty_result(source_name: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_kind": source_name,
        "paragraph_styles": {},
        "outline": [],
        "tables": [],
        "highlight": {"run_highlight": {}, "run_shading": {}, "paragraph_shading": {}, "cell_shading": {}},
        "direct_formatting": {"runs_total": 0, "rFonts": 0, "color": 0, "sz": 0, "b": 0, "i": 0},
        "sections": {"explicit_page_breaks": 0, "last_rendered_page_breaks": 0, "section_breaks": 0,
                     "page_break_before": 0, "app_pages": None},
        "stats": {"paragraphs": 0, "empty_paragraphs": 0, "total_words": 0, "avg_words_per_paragraph": 0.0,
                  "list_paragraphs": 0, "table_paragraphs": 0, "table_words": 0},
        "header_footer": [],
    }


def _sorted_counter(c: Counter) -> dict:
    return {k: c[k] for k in sorted(c)}


def extract_style(docx_path) -> dict:
    """Referans .docx/.dotx'ten sadece yapı bilgisi (schema_version "1"). Metin yok, sayı yok, docProps/core yok."""
    path = Path(docx_path)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError(f"Word dosyası açılamadı (geçerli bir .docx/.dotx değil): {path.name} ({e})") from e
    with z:
        res = _empty_result(path.suffix.lower().lstrip(".") or "docx")
        styles = _Styles(_parse(z, "word/styles.xml"))
        doc = _parse(z, _main_part(z))
        body = doc.find(w("body")) if doc is not None else None
        if body is not None:
            _scan_body(body, styles, res)
        # docProps/app.xml: sadece <Pages>; core.xml hiç okunmaz.
        app = _parse(z, "docProps/app.xml")
        if app is not None:
            pg = app.find(f"{{{EP_NS}}}Pages")
            if pg is not None and (pg.text or "").strip().isdigit():
                res["sections"]["app_pages"] = int(pg.text.strip())
        for name in sorted(n for n in z.namelist()
                           if re.fullmatch(r"word/(header|footer)\d*\.xml", n)):
            root = _parse(z, name)
            paras = list(_iter_paras(root)) if root is not None else []
            res["header_footer"].append({
                "part": name,
                "kind": "header" if "/header" in name else "footer",
                "paragraphs": len(paras),
                "words": sum(_words(_own_text(p)) for p, _ in paras),
            })
    return res


def _scan_body(body, styles: _Styles, res: dict) -> None:
    parent_map = {c: p for p in body.iter() for c in p}
    pstyles = Counter()
    st = res["stats"]
    body_words = []
    for p, in_table in _iter_paras(body):
        sid = _pstyle(p)
        pstyles[sid or "(none)"] += 1
        text = _own_text(p)
        n = _words(text)
        ppr = p.find(w("pPr"))
        if ppr is not None and ppr.find(w("numPr")) is not None:
            st["list_paragraphs"] += 1
        if in_table:
            st["table_paragraphs"] += 1
            st["table_words"] += n
            continue
        st["paragraphs"] += 1
        if n:
            body_words.append(n)
        else:
            st["empty_paragraphs"] += 1
        lvl = styles.level(sid)
        ol = _wval(ppr.find(w("outlineLvl"))) if ppr is not None else None
        if ol is not None and ol.isdigit() and int(ol) < 9:
            lvl = int(ol) + 1
        if lvl is not None and n:
            res["outline"].append({"level": lvl, "style": sid, "words": n, "text_masked": mask_text(text)})
    st["total_words"] = sum(body_words)
    st["avg_words_per_paragraph"] = round(sum(body_words) / len(body_words), 2) if body_words else 0.0
    res["paragraph_styles"] = _sorted_counter(pstyles)

    res["tables"] = [_table_info(i, t, parent_map, styles) for i, t in enumerate(body.iter(w("tbl")))]

    hl = res["highlight"]
    run_hl, run_shd, p_shd, c_shd = Counter(), Counter(), Counter(), Counter()
    df = res["direct_formatting"]
    for r in body.iter(w("r")):
        df["runs_total"] += 1
        rpr = r.find(w("rPr"))
        if rpr is None:
            continue
        h = _wval(rpr.find(w("highlight")))
        if h:
            run_hl[h] += 1
        shd = rpr.find(w("shd"))
        if shd is not None and shd.get(w("fill")):
            run_shd[shd.get(w("fill"))] += 1
        for k in ("rFonts", "color", "sz", "b", "i"):
            if rpr.find(w(k)) is not None:
                df[k] += 1
    for shd in body.iter(w("shd")):
        fill = shd.get(w("fill"))
        par = parent_map.get(shd)
        if not fill or par is None:
            continue
        if par.tag == w("pPr"):
            p_shd[fill] += 1
        elif par.tag == w("tcPr"):
            c_shd[fill] += 1
    hl["run_highlight"], hl["run_shading"] = _sorted_counter(run_hl), _sorted_counter(run_shd)
    hl["paragraph_shading"], hl["cell_shading"] = _sorted_counter(p_shd), _sorted_counter(c_shd)

    sec = res["sections"]
    sec["explicit_page_breaks"] = sum(1 for b in body.iter(w("br")) if b.get(w("type")) == "page")
    sec["last_rendered_page_breaks"] = sum(1 for _ in body.iter(w("lastRenderedPageBreak")))
    sec["section_breaks"] = sum(1 for _ in body.iter(w("sectPr")))
    sec["page_break_before"] = sum(1 for b in body.iter(w("pageBreakBefore")) if _wval(b) not in ("0", "false"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pcs7_analyzer.docx_style",
                                 description="Referans Word raporundan sadece yapı (stil, başlık, tablo) çıkarır; "
                                             "metin ve müşteri verisi çıktıya girmez.")
    ap.add_argument("docx", help="referans .docx / .dotx")
    ap.add_argument("-o", "--output", default="reference_style.json", help="çıktı JSON (varsayılan: %(default)s)")
    a = ap.parse_args(argv)
    try:
        res = extract_style(a.docx)
    except ValueError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2
    out = Path(a.output)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Yazıldı: {out}  ({len(res['outline'])} başlık, {len(res['tables'])} tablo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
