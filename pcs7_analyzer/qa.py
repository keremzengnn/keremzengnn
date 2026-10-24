"""Rapor QA kapısı (PROMPT_EK_RAPOR_KALITESI R8): üretilmiş çıktılar üzerinde otomatik kalite kontrolleri.

Girdi: rapor klasörü (report_ir.json, findings.json, rapor.md, rapor.docx, rapor.xlsx; olmayan atlanır, not düşülür).
Çıktı: `qa_report.md`; HATA varsa `python -m pcs7_analyzer qa <klasör>` çıkış kodu 1.
Kontroller tek listede (`QA_CHECKS`): yeni kontrol = bir fonksiyon + bir satır.
"""
from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

HATA, UYARI = "HATA", "UYARI"
CELL_WORD_LIMIT = 25
PLACEHOLDERS = re.compile(r"\b(TODO|TBD|FIXME|XXX|lorem ipsum|lorem)\b|(?<![\w/])N/A(?![\w/])", re.I)
EXCEL_ERRORS = ("#REF!", "#NAME?", "#DIV/0!", "#VALUE!", "#N/A", "#NUM!", "#NULL!")
SECRET_PATTERNS = [(re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "IP adresi"),
                   (re.compile(r"(?i)\b(password|passwd|şifre|parola)\s*[:=]\s*\S+"), "şifre")]
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Issue:
    level: str
    check: str
    message: str
    where: str = ""


@dataclass
class QaInput:
    folder: Path
    ir: dict | None = None
    findings: list | None = None
    md: str | None = None
    docx: dict | None = None          # {"paras": [...], "tables": [...], "runs": [...]}
    xlsx: dict | None = None          # {sheet: [[cell, ...], ...]}
    missing: list[str] = field(default_factory=list)


# ---------------- okuma ----------------
def _read_docx(p: Path) -> dict:
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(p) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{_W}body")
    runs, paras, tables = [], [], []
    for r in body.iter(f"{_W}r"):
        t = "".join(x.text or "" for x in r.iter(f"{_W}t"))
        rpr = r.find(f"{_W}rPr")
        runs.append({"text": t,
                     "highlight": rpr is not None and rpr.find(f"{_W}highlight") is not None,
                     "direct": [tag for tag in ("rFonts", "color", "sz")
                                if rpr is not None and rpr.find(f"{_W}{tag}") is not None]})
    for para in body.iter(f"{_W}p"):
        paras.append("".join(x.text or "" for x in para.iter(f"{_W}t")))
    for i, tbl in enumerate(body.iter(f"{_W}tbl")):
        trs = tbl.findall(f"{_W}tr")
        cells = [["\n".join("".join(x.text or "" for x in p.iter(f"{_W}t")) for p in tc.findall(f"{_W}p"))
                  for tc in tr.findall(f"{_W}tc")] for tr in trs]
        head = trs[0].find(f"{_W}trPr") if trs else None
        tables.append({"index": i + 1, "cells": cells,
                       "repeat_header": head is not None and head.find(f"{_W}tblHeader") is not None,
                       "cant_split": all(tr.find(f"{_W}trPr") is not None and
                                         tr.find(f"{_W}trPr").find(f"{_W}cantSplit") is not None for tr in trs[1:])})
    body_paras = ["".join(x.text or "" for x in p.iter(f"{_W}t")) for p in body.findall(f"{_W}p")]
    return {"runs": runs, "paras": paras, "body_paras": body_paras, "tables": tables}


def _read_xlsx(p: Path) -> dict:
    import xml.etree.ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    out = {}
    with zipfile.ZipFile(p) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{ns}t")) for si in sroot.findall(f"{ns}si")]
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        for sh in wb.iter(f"{ns}sheet"):
            target = targets.get(sh.get(f"{rel}id"), "")
            path = "xl/" + target.lstrip("/").removeprefix("xl/")
            root = ET.fromstring(z.read(path))
            rows = []
            for row in root.iter(f"{ns}row"):
                vals = []
                for c in row.findall(f"{ns}c"):
                    t = c.get("t")
                    if t == "inlineStr":
                        v = "".join(x.text or "" for x in c.iter(f"{ns}t"))
                    else:
                        ve = c.find(f"{ns}v")
                        v = ve.text if ve is not None else ""
                        if t == "s" and v:
                            v = shared[int(v)]
                    ref = re.match(r"[A-Z]+", c.get("r") or "")
                    if ref:     # boş hücreler yazılmaz: sütunu referanstan al (kaymasın)
                        ci = 0
                        for ch in ref.group():
                            ci = ci * 26 + ord(ch) - 64
                        vals += [""] * (ci - 1 - len(vals))
                    vals.append(v or "")
                rows.append(vals)
            out[sh.get("name")] = rows
    return out


def load(folder: Path) -> QaInput:
    folder = Path(folder)
    q = QaInput(folder)

    def opt(name, fn):
        p = folder / name
        if not p.exists():
            q.missing.append(name)
            return None
        return fn(p)
    q.ir = opt("report_ir.json", lambda p: json.loads(p.read_text(encoding="utf-8")))
    q.findings = opt("findings.json", lambda p: json.loads(p.read_text(encoding="utf-8")))
    q.md = opt("rapor.md", lambda p: p.read_text(encoding="utf-8"))
    q.docx = opt("rapor.docx", _read_docx)
    q.xlsx = opt("rapor.xlsx", _read_xlsx)
    return q


def _glossary() -> dict:
    p = Path(__file__).with_name("data") / "glossary.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _texts(q: QaInput):
    """(yer, metin) çiftleri: rapor.md satırları + Word paragrafları."""
    if q.md:
        for i, line in enumerate(q.md.splitlines(), 1):
            yield f"rapor.md:{i}", line
    if q.docx:
        for i, p in enumerate(q.docx["paras"], 1):
            yield f"rapor.docx ¶{i}", p


# ---------------- kontroller ----------------
def qa_placeholders(q):
    for where, t in _texts(q):
        m = PLACEHOLDERS.search(t)
        if m:
            yield Issue(HATA, "PLACEHOLDER", f"yer tutucu metin: '{m.group()}'", where)


def qa_actions(q):
    for f in q.findings or []:
        if f.get("status") in ("BLOCKER", "RİSK") and not f.get("action"):
            yield Issue(HATA, "NO_ACTION", f"{f.get('fid') or f.get('check_id')}: {f.get('status')} bulgunun aksiyonu yok",
                        "findings.json")


def qa_glossary(q):
    bad = _glossary().get("forbidden_translations", {})
    for where, t in _texts(q):
        low = t.lower()
        for k, v in bad.items():
            if re.search(rf"(?<!\w){re.escape(k)}", low):
                yield Issue(HATA, "GLOSSARY", f"yasak çeviri '{k}' -> '{v}' kullanılmalı", where)


def qa_counts(q):
    """IR stats == findings.json == Excel 'Bulgular' (durum bazında)."""
    sources = {}
    if q.findings is not None:
        sources["findings.json"] = Counter(f.get("status") for f in q.findings)
    if q.ir is not None:
        st = q.ir.get("stats", {})
        c = Counter(st.get("by_status", {}))
        if st.get("not_checked"):
            c["VERİ YOK"] = st["not_checked"]
        sources["report_ir.json"] = c
    if q.xlsx and "Bulgular" in q.xlsx:
        rows = q.xlsx["Bulgular"]
        col = rows[0].index("Durum") if rows and "Durum" in rows[0] else 2
        sources["rapor.xlsx/Bulgular"] = Counter(r[col] for r in rows[1:] if len(r) > col and r[col])
    if len(sources) < 2:
        return
    names = list(sources)
    ref = sources[names[0]]
    for n in names[1:]:
        if +sources[n] != +ref:
            yield Issue(HATA, "COUNTS", f"bulgu sayıları tutmuyor: {names[0]} {dict(sorted(ref.items()))} ≠ "
                                        f"{n} {dict(sorted(sources[n].items()))}", n)


def qa_highlight(q):
    if not q.docx:
        return
    from .word import is_assumption
    miss = [r["text"] for r in q.docx["runs"] if r["text"].strip() and is_assumption(r["text"]) and not r["highlight"]]
    if miss:
        yield Issue(HATA, "HIGHLIGHT", f"{len(miss)} varsayım / çıkarım metni sarı değil (ilk: '{miss[0][:60]}')",
                    "rapor.docx")


def qa_direct_format(q):
    if not q.docx:
        return
    n = Counter(t for r in q.docx["runs"] for t in r["direct"])
    if n:
        yield Issue(HATA, "DIRECT_FORMAT", f"şablon stili yerine doğrudan biçim (run): {dict(n)}", "rapor.docx")


def qa_excel_errors(q):
    for sheet, rows in (q.xlsx or {}).items():
        for i, r in enumerate(rows, 1):
            for v in r:
                if str(v).strip() in EXCEL_ERRORS:
                    yield Issue(HATA, "EXCEL_ERROR", f"formül hatası {v}", f"rapor.xlsx/{sheet} satır {i}")


def qa_empty_sections(q):
    for s in (q.ir or {}).get("sections", []):
        if s.get("title") and not s.get("blocks"):
            yield Issue(HATA, "EMPTY_SECTION", f"boş bölüm: '{s['title']}'", "report_ir.json")


def qa_omitted_blocker(q):
    ids = {f.get("fid") for f in q.findings or [] if f.get("status") == "BLOCKER"}
    for o in (q.ir or {}).get("omitted", []):
        if o.get("finding_id") in ids:
            yield Issue(HATA, "OMITTED_BLOCKER", f"BLOCKER rapora girmedi: {o['finding_id']}", "report_ir.json")


def qa_mask(q):
    if (q.ir or {}).get("profile") != "musteri":
        return
    for where, t in _texts(q):
        for rx, what in SECRET_PATTERNS:
            if rx.search(t):
                yield Issue(HATA, "MASK", f"maskelenmemiş {what}", where)


def qa_cell_words(q):
    if not q.docx:
        return
    for t in q.docx["tables"]:
        over = [c for row in t["cells"][1:] for c in row if len(c.split()) > CELL_WORD_LIMIT]
        if over:
            yield Issue(UYARI, "CELL_WORDS", f"Tablo {t['index']}: {len(over)} hücre > {CELL_WORD_LIMIT} kelime "
                                             f"(en uzun {max(len(c.split()) for c in over)})", "rapor.docx")


def qa_table_layout(q):
    if not q.docx:
        return
    for t in q.docx["tables"]:
        if len(t["cells"]) > 1 and not t["repeat_header"]:
            yield Issue(UYARI, "TABLE_HEADER", f"Tablo {t['index']}: başlık satırı tekrar etmiyor", "rapor.docx")
        if len(t["cells"]) > 1 and not t["cant_split"]:
            yield Issue(UYARI, "TABLE_SPLIT", f"Tablo {t['index']}: satır sayfa arasında bölünebilir", "rapor.docx")


def qa_repeats(q):
    if not q.docx:
        return
    # tablo hücreleri hariç (aynı değerin farklı satırlarda geçmesi normal)
    seen = Counter(p.strip() for p in q.docx.get("body_paras", []) if len(p.split()) >= 6)
    for s, n in sorted(seen.items()):
        if n > 1:
            yield Issue(UYARI, "REPEAT", f"aynı cümle {n} kez: '{s[:70]}'", "rapor.docx")


QA_CHECKS = [qa_placeholders, qa_actions, qa_glossary, qa_counts, qa_highlight, qa_direct_format, qa_excel_errors,
             qa_empty_sections, qa_omitted_blocker, qa_mask, qa_cell_words, qa_table_layout, qa_repeats]


def run_qa(folder: Path) -> tuple[list[Issue], QaInput]:
    q = load(folder)
    issues: list[Issue] = []
    for chk in QA_CHECKS:
        try:
            issues += list(chk(q))
        except Exception as e:  # noqa: BLE001 - bir kontrolün hatası diğerlerini durdurmaz
            issues.append(Issue(UYARI, chk.__name__, f"kontrol çalışmadı ({type(e).__name__}: {e})"))
    return issues, q


def render(issues: list[Issue], q: QaInput) -> str:
    n = Counter(i.level for i in issues)
    lines = ["# QA raporu", "", f"Sonuç: **{'GEÇMEDİ' if n[HATA] else 'GEÇTİ'}** — {n[HATA]} hata, {n[UYARI]} uyarı", ""]
    if q.missing:
        lines += [f"Kontrol edilemeyen çıktı (dosya yok): {', '.join(q.missing)}", ""]
    if issues:
        lines += ["| Seviye | Kontrol | Mesaj | Yer |", "|---|---|---|---|"]
        for i in sorted(issues, key=lambda x: (x.level != HATA, x.check)):
            lines.append(f"| {i.level} | {i.check} | {i.message.replace('|', '/')} | {i.where} |")
    lines += ["", "Kontroller: " + ", ".join(c.__name__.removeprefix("qa_") for c in QA_CHECKS)]
    return "\n".join(lines) + "\n"


def write_report(folder: Path) -> tuple[Path, int]:
    """qa_report.md yazar; (yol, hata sayısı) döndürür."""
    issues, q = run_qa(folder)
    p = Path(folder) / "qa_report.md"
    p.write_text(render(issues, q), encoding="utf-8")
    return p, sum(1 for i in issues if i.level == HATA)


__all__ = ["run_qa", "write_report", "render", "Issue", "QA_CHECKS", "HATA", "UYARI"]
