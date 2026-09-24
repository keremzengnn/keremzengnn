"""
Released Modules List Manual (PDF veya ondan kopyalanmış metin) -> data/released_modules_<ver>.csv taslağı.

  python -m pcs7_analyzer.released_extract <manual.pdf|manual.txt|manual.md> -o released_modules_V10.0SP2.csv

PDF için `pip install pypdf` gerekir (metin dosyası için gerekmez).
Çıktı bir TASLAKTIR: tablo sayfaları PDF'ten bozuk çıkabilir. Satır sayısını ve özellikle aksesuarları
(ör. H-Sync 6ES7 960-1AA06) elle kontrol edin. Listede olmayan modül analizde "bulunamadı" olarak raporlanır.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

MLFB = re.compile(r"\b(6(?:ES|GK|AV|SL|EP|DL|AG|XV)\d ?[0-9A-Z]{3}-[0-9A-Z]{4,5}-[0-9A-Z]{4})\b")
FW = re.compile(r"\bV\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\b")
DISC = re.compile(r"discontinued[^,;\n]*?(\d{2}/\d{4})", re.I)


def extract_rows(text: str) -> list[dict]:
    rows, seen = [], set()
    for line in text.splitlines():
        mlfbs = MLFB.findall(line)
        if not mlfbs:
            continue
        fws = FW.findall(line)
        disc = DISC.search(line)
        status = f"discontinued {disc.group(1)}" if disc else "listed"
        for m in mlfbs:
            for fw in fws or [""]:
                key = (m, fw)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"mlfb": m, "fw": fw, "status": status, "note": line.strip()[:120]})
    return rows


_MD_SEC = re.compile(r"^#{2,4}\s*\*\*(\d+(?:\.\d+)*\s+[^*]+)\*\*")
_DATE = re.compile(r"\b(\d{2})/\s*(\d{2})\b")


def _clean(cell: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<br>|\*\*|‐", lambda m: "" if m.group() in ("**", "‐") else " ", cell)).strip()


def extract_rows_markdown(text: str) -> list[dict]:
    """
    Released Modules List Manual'ın Markdown dönüşümü: tablolar '|Product name|Article no.<br>FW|Brief|F|C|R|T|'.
    Bölüm başlığı (ör. '21.6 H-CPU as of 12/11 (as of PCS 7 V8.0)') not'a yazılır. T sütunundaki tarih = discontinuation.
    """
    rows, seen, section = [], set(), ""
    for line in text.splitlines():
        m = _MD_SEC.match(line.strip())
        if m:
            section = m.group(1).strip()
            continue
        if not line.startswith("|"):
            continue
        cells = line.strip().strip("|").split("|")
        if len(cells) < 2 or "**" in cells[0]:      # başlık satırı
            continue
        ai = next((i for i in (1, 0) if i < len(cells) and MLFB.search(cells[i].replace("‐", "-"))), None)
        if ai is None:
            continue
        art = cells[ai].replace("‐", "-")
        mlfbs = MLFB.findall(art)
        fws = [f for f in re.findall(r"\bV\d+(?:\.(?:\d+|x))*(?:\.x)?\b", art)] or [""]
        tail = " ".join(cells[ai + 2:])
        dm = _DATE.search(tail.replace("<br>", ""))
        status = f"discontinued {dm.group(1)}/{dm.group(2)}" if dm else "listed"
        note = f"{section} | {_clean(cells[0]) if ai == 1 else _clean(cells[1])}"
        for mlfb in mlfbs:
            for fw in fws:
                key = (mlfb.replace(" ", ""), fw)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"mlfb": mlfb, "fw": fw, "status": status, "note": note[:160]})
    # Tablo dışında (ör. dipnot "orderable via article number …") geçen MLFB'ler de eklenir
    got = {r["mlfb"].replace(" ", "") for r in rows}
    for m in MLFB.findall(text.replace("‐", "-")):
        if m.replace(" ", "") not in got:
            got.add(m.replace(" ", ""))
            rows.append({"mlfb": m, "fw": "", "status": "listed", "note": "tablo dışı metinde geçiyor (dipnot) - teyit edilmeli"})
    return rows


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("PDF için: pip install pypdf  (veya PDF'ten metni kopyalayıp .txt verin)")
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manual", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    a = ap.parse_args(argv)
    text = read_text(a.manual)
    rows = extract_rows_markdown(text) if a.manual.suffix.lower() == ".md" else extract_rows(text)
    with a.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["mlfb", "fw", "status", "note"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} satır -> {a.out}. ELLE KONTROL EDİN (eksik sayfa / aksesuar).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
