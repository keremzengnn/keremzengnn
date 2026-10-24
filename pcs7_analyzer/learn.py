"""R7 "learn": aracın ÜRETTİĞİ rapor.docx ile kullanıcının DÜZENLEDİĞİ hali arasındaki yapısal fark + öneriler.

Müşteri içeriği çıktıya girmez: gövde / hücre metni yok; başlık ve tablo başlık satırı `docx_style.mask_text` ile
maskeli; terim değişimi sadece `data/glossary.json` terimlerinin SAYILARI. Dosya adı / path çıktıya yazılmaz.
Öneriler otomatik uygulanmaz, hiçbir config'e yazılmaz: kullanıcı onaylar. Bkz. docs/spec/learn.md.

    python -m pcs7_analyzer.learn --generated rapor.docx --edited rapor_duzenlenmis.docx [-o çıktı_klasörü]

Sadece standart kütüphane. Deterministik: aynı girdi -> aynı JSON (sort_keys, zaman damgası yok).
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from .docx_style import (_main_part, _own_text, _parse, _pstyle, _Styles, _words, extract_style,
                         mask_text, w)

SCHEMA_VERSION = "1"
GLOSSARY = Path(__file__).with_name("data") / "glossary.json"
PREAMBLE = "(başlık öncesi)"
HEADER_NOTE = ("ÖNERİ: otomatik uygulanmaz, hiçbir ayara / config'e yazılmaz. Her öneriyi kullanıcı gözden geçirip "
               "onaylamalı. Çıktıda müşteri metni yoktur (başlıklar maskeli, terimler sadece sayı).")
# öneri eşikleri
SHORTEN_RATIO = 0.2      # bölüm metni / hücre kelime ortalaması en az %20 azaldıysa
SHORTEN_MIN_WORDS = 5    # ve en az 5 kelime


# --- okuma -------------------------------------------------------------------------------------------------------
def _load_glossary(path=None) -> dict:
    try:
        g = json.loads(Path(path or GLOSSARY).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        g = {}
    return {"keep_english": sorted({t.strip() for t in g.get("keep_english", []) if t.strip()}),
            "forbidden_translations": {k: v for k, v in sorted((g.get("forbidden_translations") or {}).items())}}


def _term_re(term: str):
    return re.compile(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)")


def _scan(docx_path, glossary: dict) -> dict:
    """Bölüm (başlık) listesi, bölüm başına kelime / paragraf sayısı, tablo -> bölüm, glossary terim sayıları."""
    path = Path(docx_path)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ValueError(f"Word dosyası açılamadı (geçerli bir .docx değil): {path.name} ({e})") from e
    with z:
        styles = _Styles(_parse(z, "word/styles.xml"))
        doc = _parse(z, _main_part(z))
    body = doc.find(w("body")) if doc is not None else None
    sections = [{"level": None, "key": PREAMBLE, "words": 0, "paragraphs": 0}]
    texts = []
    table_section = []
    if body is not None:
        tbl_sec = {}

        def walk(el, in_table):
            for c in el:
                if c.tag == w("tbl"):
                    tbl_sec[id(c)] = len(sections) - 1
                    walk(c, True)
                elif c.tag == w("p"):
                    para(c, in_table)
                    walk(c, in_table)          # textbox içindeki paragraf / tablolar
                else:
                    walk(c, in_table)

        def para(p, in_table):
            text = _own_text(p)
            texts.append(text)
            n = _words(text)
            if in_table:
                return
            ppr = p.find(w("pPr"))
            lvl = styles.level(_pstyle(p))
            ol = ppr.find(w("outlineLvl")) if ppr is not None else None
            olv = ol.get(w("val")) if ol is not None else None
            if olv is not None and olv.isdigit() and int(olv) < 9:
                lvl = int(olv) + 1
            if lvl is not None and n:
                sections.append({"level": lvl, "key": mask_text(text), "words": 0, "paragraphs": 0})
            elif n:
                sections[-1]["words"] += n
                sections[-1]["paragraphs"] += 1

        walk(body, False)
        table_section = [tbl_sec.get(id(t)) for t in body.iter(w("tbl"))]
    blob = "\n".join(texts).casefold()
    eng = {t: len(_term_re(t).findall(blob)) for t in glossary["keep_english"]}
    tr = {t: len(_term_re(t).findall(blob)) for t in glossary["forbidden_translations"]}
    return {"sections": sections, "table_section": table_section, "english": eng, "turkish": tr}


# --- karşılaştırma -----------------------------------------------------------------------------------------------
def _align(a: list, b: list):
    """difflib ile hizalama: (op, i_list, j_list); 'replace' blokları sırayla eşlenir."""
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    return sm.get_opcodes()


def _pct(old, new):
    return round((new - old) * 100.0 / old, 1) if old else None


def _counter_diff(a: dict, b: dict) -> dict:
    out = {}
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k, 0), b.get(k, 0)
        if x != y:
            out[k] = {"generated": x, "edited": y, "delta": y - x}
    return out


def _compare_sections(ga: dict, ea: dict):
    gs, es = ga["sections"], ea["sections"]
    ka = [(s["level"], s["key"]) for s in gs]
    kb = [(s["level"], s["key"]) for s in es]
    removed, added, renamed, matched = [], [], [], []   # matched: (gi, ej)
    for op, i1, i2, j1, j2 in _align(ka, kb):
        if op == "equal":
            matched += list(zip(range(i1, i2), range(j1, j2)))
            continue
        gi, ej = list(range(i1, i2)), list(range(j1, j2))
        if op == "replace":
            # aynı seviyede sırayla eşleşenler = yeniden adlandırma
            pairs = []
            jj = list(ej)
            for i in gi:
                k = next((j for j in jj if es[j]["level"] == gs[i]["level"]), None)
                if k is not None:
                    pairs.append((i, k))
                    jj = jj[jj.index(k) + 1:]
            for i, j in pairs:
                renamed.append({"level": gs[i]["level"], "from": gs[i]["key"], "to": es[j]["key"]})
                matched.append((i, j))
            gi = [i for i in gi if i not in {p[0] for p in pairs}]
            ej = [j for j in ej if j not in {p[1] for p in pairs}]
        removed += [{"level": gs[i]["level"], "heading": gs[i]["key"], "words": gs[i]["words"]} for i in gi]
        added += [{"level": es[j]["level"], "heading": es[j]["key"], "words": es[j]["words"]} for j in ej]
    matched.sort()
    changes = []
    for i, j in matched:
        a, b = gs[i], es[j]
        if (a["words"], a["paragraphs"]) != (b["words"], b["paragraphs"]):
            changes.append({"heading": b["key"], "level": b["level"],
                            "words": {"generated": a["words"], "edited": b["words"], "delta": b["words"] - a["words"],
                                      "pct": _pct(a["words"], b["words"])},
                            "paragraphs": {"generated": a["paragraphs"], "edited": b["paragraphs"],
                                           "delta": b["paragraphs"] - a["paragraphs"]}})
    shortened = [c for c in changes if c["words"]["delta"] < 0]
    return removed, added, renamed, changes, shortened


def _compare_tables(gst: dict, est: dict, gscan: dict, escan: dict):
    gt, et = gst["tables"], est["tables"]
    ha = [tuple(t["header"]) for t in gt]
    hb = [tuple(t["header"]) for t in et]
    pairs, removed, added = [], [], []
    for op, i1, i2, j1, j2 in _align(ha, hb):
        gi, ej = list(range(i1, i2)), list(range(j1, j2))
        if op in ("equal", "replace"):
            n = min(len(gi), len(ej))
            pairs += list(zip(gi[:n], ej[:n]))
            gi, ej = gi[n:], ej[n:]
        removed += gi
        added += ej

    def sec_of(scan, idx):
        ts = scan["table_section"]
        s = ts[idx] if idx < len(ts) else None
        return scan["sections"][s]["key"] if s is not None else None

    out = []
    for i, j in pairs:
        a, b = gt[i], et[j]
        ca, cb = Counter(a["header"]), Counter(b["header"])
        rem = sorted((ca - cb).elements())
        add = sorted((cb - ca).elements())
        d = {"table": i + 1, "edited_table": j + 1, "section": sec_of(gscan, i), "header": b["header"],
             "removed_columns": rem, "added_columns": add,
             "n_cols": {"generated": a["n_cols"], "edited": b["n_cols"]},
             "n_rows": {"generated": a["n_rows"], "edited": b["n_rows"], "delta": b["n_rows"] - a["n_rows"]},
             "avg_words_per_cell": {"generated": a["avg_words_per_cell"], "edited": b["avg_words_per_cell"],
                                    "delta": round(b["avg_words_per_cell"] - a["avg_words_per_cell"], 2)},
             "style": {"generated": a["style"], "edited": b["style"]}}
        d["changed"] = bool(rem or add or d["n_rows"]["delta"] or d["avg_words_per_cell"]["delta"]
                            or a["style"] != b["style"] or a["n_cols"] != b["n_cols"])
        out.append(d)
    rem_t = [{"table": i + 1, "header": gt[i]["header"], "n_rows": gt[i]["n_rows"], "section": sec_of(gscan, i)}
             for i in removed]
    add_t = [{"edited_table": j + 1, "header": et[j]["header"], "n_rows": et[j]["n_rows"], "section": sec_of(escan, j)}
             for j in added]
    return out, rem_t, add_t


def _compare_terms(gscan: dict, escan: dict, glossary: dict) -> dict:
    eng = _counter_diff(gscan["english"], escan["english"])
    tr = _counter_diff(gscan["turkish"], escan["turkish"])
    pairs = []
    for t_tr, t_en in glossary["forbidden_translations"].items():
        d_tr = tr.get(t_tr, {}).get("delta", 0)
        d_en = eng.get(t_en, {}).get("delta", 0)
        if d_tr > 0:
            pairs.append({"english": t_en, "turkish": t_tr, "english_delta": d_en, "turkish_delta": d_tr})
    return {"english_terms": eng, "turkish_terms": tr, "replaced": pairs,
            "english_disappeared": sorted(k for k, v in eng.items() if v["delta"] < 0),
            "turkish_appeared": sorted(k for k, v in tr.items() if v["delta"] > 0)}


def compare(generated_docx, edited_docx, glossary_path=None) -> dict:
    """Yapısal fark (schema_version "1"). Metin içermez; başlık / tablo başlıkları maskeli. ValueError: okunamayan dosya."""
    glossary = _load_glossary(glossary_path)
    gst, est = extract_style(generated_docx), extract_style(edited_docx)
    gscan, escan = _scan(generated_docx, glossary), _scan(edited_docx, glossary)
    removed, added, renamed, changes, shortened = _compare_sections(gscan, escan)
    tables, rem_t, add_t = _compare_tables(gst, est, gscan, escan)
    hl = {k: _counter_diff(gst["highlight"][k], est["highlight"][k]) for k in sorted(gst["highlight"])}
    gs, es = gst["stats"], est["stats"]
    return {
        "schema_version": SCHEMA_VERSION,
        "note": HEADER_NOTE,
        "sections": {"generated": len(gscan["sections"]) - 1, "edited": len(escan["sections"]) - 1,
                     "removed": removed, "added": added, "renamed": renamed,
                     "word_changes": changes, "shortened": shortened},
        "tables": {"generated": len(gst["tables"]), "edited": len(est["tables"]),
                   "matched": tables, "removed": rem_t, "added": add_t},
        "terms": _compare_terms(gscan, escan, glossary),
        "highlight": hl,
        "styles": _counter_diff(gst["paragraph_styles"], est["paragraph_styles"]),
        "direct_formatting": _counter_diff(gst["direct_formatting"], est["direct_formatting"]),
        "stats": {k: {"generated": gs[k], "edited": es[k], "delta": round(es[k] - gs[k], 2)}
                  for k in sorted(gs) if gs[k] != es[k]},
    }


# --- öneriler ----------------------------------------------------------------------------------------------------
def _short(old: float, new: float) -> bool:
    return old > 0 and (old - new) >= max(SHORTEN_MIN_WORDS if isinstance(old, int) else 0, old * SHORTEN_RATIO)


def suggestions(diff: dict) -> list[str]:
    """Türkçe öneri listesi (deterministik sıra). Sadece öneri; hiçbir şey uygulanmaz."""
    out = []
    sec = diff["sections"]
    for s in sec["removed"]:
        out.append(f"'{s['heading']}' bölümünü kaldır (seviye {s['level']}, {s['words']} kelime)")
    for s in sec["added"]:
        out.append(f"'{s['heading']}' bölümünü ekle (seviye {s['level']}, kullanıcı eklemiş)")
    for s in sec["renamed"]:
        out.append(f"'{s['from']}' başlığını '{s['to']}' olarak değiştir")
    for c in sec["shortened"]:
        wd = c["words"]
        if _short(wd["generated"], wd["edited"]):
            out.append(f"'{c['heading']}' bölüm metnini kısalt ({wd['generated']} -> {wd['edited']} kelime, "
                       f"%{wd['pct']})")
    tb = diff["tables"]
    for t in tb["removed"]:
        where = f" ('{t['section']}' bölümü)" if t["section"] else ""
        out.append(f"Tablo {t['table']}{where} tablosunu kaldır")
    for t in tb["added"]:
        where = f" ('{t['section']}' bölümü)" if t["section"] else ""
        out.append(f"Yeni tablo ekle{where}: sütunlar {', '.join(repr(h) for h in t['header'])}")
    for t in tb["matched"]:
        n = t["table"]
        for col in t["removed_columns"]:
            out.append(f"Tablo {n} '{col}' sütununu çıkar")
        for col in t["added_columns"]:
            out.append(f"Tablo {n}'e '{col}' sütununu ekle")
        r = t["n_rows"]
        if r["delta"] < 0:
            out.append(f"Tablo {n} satır sayısını azalt / filtrele ({r['generated']} -> {r['edited']} satır)")
        elif r["delta"] > 0:
            out.append(f"Tablo {n} satır eklenmiş ({r['generated']} -> {r['edited']}): eksik bilgi var mı kontrol et")
        a = t["avg_words_per_cell"]
        if _short(a["generated"], a["edited"]):
            out.append(f"Tablo {n} hücre metnini kısalt (ortalama {a['generated']} -> {a['edited']} kelime/hücre)")
        if t["style"]["generated"] != t["style"]["edited"]:
            out.append(f"Tablo {n} stilini '{t['style']['edited']}' yap (şu an '{t['style']['generated']}')")
    for p in diff["terms"]["replaced"]:
        out.append(f"Kullanıcı '{p['english']}' yerine '{p['turkish']}' kullanmış (+{p['turkish_delta']}); sözlük "
                   f"kuralı keep_english: '{p['english']}' çevrilmez, sözlüğü değil kullanıcıyla teyit et")
    paired = {p["english"] for p in diff["terms"]["replaced"]}
    for t in diff["terms"]["english_disappeared"]:
        if t not in paired:
            d = diff["terms"]["english_terms"][t]
            out.append(f"'{t}' terimi azalmış ({d['generated']} -> {d['edited']}): ilgili metin gereksiz olabilir")
    for kind, d in diff["highlight"].items():
        for val, v in d.items():
            verb = "azalt" if v["delta"] < 0 else "artır"
            out.append(f"Vurgu ({kind} '{val}') kullanımını {verb} ({v['generated']} -> {v['edited']})")
    for sid, v in diff["styles"].items():
        out.append(f"'{sid}' stil kullanımı değişmiş ({v['generated']} -> {v['edited']} paragraf)")
    return out


def write_suggestions(diff: dict, out_dir) -> Path:
    """`style_suggestions.json` yazar (sadece out_dir'e; config'e asla). Dönüş: dosya yolu."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "style_suggestions.json"
    data = {"_header": HEADER_NOTE, "schema_version": SCHEMA_VERSION, "applied": False,
            "suggestions": suggestions(diff), "diff": diff}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pcs7_analyzer.learn",
                                 description="Üretilen ve kullanıcının düzenlediği Word raporunu yapısal olarak "
                                             "karşılaştırır, öneri üretir (metin çıktıya girmez, otomatik uygulanmaz).")
    ap.add_argument("--generated", required=True, help="aracın ürettiği rapor.docx")
    ap.add_argument("--edited", required=True, help="kullanıcının düzenlediği rapor.docx")
    ap.add_argument("-o", "--output", default=".", help="çıktı klasörü (varsayılan: %(default)s)")
    a = ap.parse_args(argv)
    try:
        diff = compare(a.generated, a.edited)
    except ValueError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2
    p = write_suggestions(diff, a.output)
    sug = suggestions(diff)
    print(HEADER_NOTE)
    for s in sug:
        print(f"- {s}")
    print(f"Yazıldı: {p}  ({len(sug)} öneri)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
