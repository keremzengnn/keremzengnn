"""
Released Modules List Manual (PDF veya ondan kopyalanmış metin) -> data/released_modules_<ver>.csv taslağı.

  python -m pcs7_analyzer.released_extract <manual.pdf|manual.txt> -o released_modules_V10.0SP2.csv

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
    rows = extract_rows(read_text(a.manual))
    with a.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["mlfb", "fw", "status", "note"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} satır -> {a.out}. ELLE KONTROL EDİN (eksik sayfa / aksesuar).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
