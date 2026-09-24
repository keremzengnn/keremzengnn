"""
APL / Basis Library Readme'lerindeki "List of changed blocks" tablolarını CSV'ye çıkarır.

  python tools/extract_block_changes.py --apl AdvLib-Readme.md --basis BasLib-Readme.md \
         -o pcs7_analyzer/data/block_changes_V10.0SP2.csv

Girdi: Readme PDF'lerinden çevrilmiş Markdown. Çıktı kolonları:
library, section, name, kind, number, version, interface_change, sfc_contact, code_change
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

_APL_SEC = re.compile(r"^5\.\d+Version (10\.0.*)$")
_APL_ROW = re.compile(r"^([A-Za-z][\w]*?)(FB|FC)(\d+)(10(?:\.\d)?|[5-9](?:\.\d)?)(Yes|No)(Yes|No)(Yes|No|New Block)$")
_BAS_SEC = re.compile(r"^#+\s*\*\*6\.\d+ Version (10\.0[^*]*)\*\*")
_BAS_ROW = re.compile(r"^\|([A-Za-z][\w]*)\|(FB|FC)(\d+)\|([\d.]+)\|([^|]*)\|([^|]*)\|")


def parse_apl(text: str) -> list[dict]:
    rows, sec = [], ""
    for line in text.splitlines():
        s = line.strip().replace("‐", "")
        m = _APL_SEC.match(s)
        if m:
            sec = m.group(1).strip()
            continue
        m = _APL_ROW.match(s)
        if m:
            name, kind, nr, ver, iface, sfc, code = m.groups()
            new = code == "New Block"
            rows.append({"library": "APL", "section": sec, "name": name, "kind": kind, "number": nr, "version": ver,
                         "interface_change": "new" if new else iface.lower(), "sfc_contact": sfc.lower(),
                         "code_change": "new" if new else code.lower()})
    return rows


def parse_basis(text: str) -> list[dict]:
    rows, sec = [], ""
    for line in text.splitlines():
        s = line.strip()
        m = _BAS_SEC.match(s)
        if m:
            sec = m.group(1).strip()
            continue
        m = _BAS_ROW.match(s)
        if m:
            name, kind, nr, ver, iface, code = m.groups()
            iface_l = iface.lower()
            rows.append({"library": "Basis", "section": sec, "name": name, "kind": kind, "number": nr, "version": ver,
                         "interface_change": "new" if "new block" in iface_l else ("yes" if iface_l.startswith("yes") else "no"),
                         "sfc_contact": "", "code_change": "yes" if code.strip().lower().startswith("yes") else "no"})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apl", type=Path)
    ap.add_argument("--basis", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    a = ap.parse_args(argv)
    rows = []
    if a.apl:
        rows += parse_apl(a.apl.read_text(encoding="utf-8"))
    if a.basis:
        rows += parse_basis(a.basis.read_text(encoding="utf-8"))
    with a.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} satır -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
