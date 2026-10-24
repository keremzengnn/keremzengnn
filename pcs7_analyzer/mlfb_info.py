"""
MLFB -> okunur model adı ("6ES7 321-1BL00-0AA0" -> "SM321 DI 32xDC24V").

1) Released Modules listesindeki açıklama (birebir MLFB, KANIT: Siemens listesi)
2) Yoksa MLFB ailesinden genel ad (ör. "6ES7 32x" -> "SM 321 DI (S7-300 / ET 200M)"), ÇIKARIM.
Bulunamazsa boş döner; tahmin edilmez.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
SRC_LIST = "Released Modules listesi"
SRC_FAMILY = "MLFB ailesi (çıkarım)"


def norm(mlfb: str) -> str:
    return re.sub(r"[\s-]", "", (mlfb or "").upper())


@lru_cache(maxsize=1)
def _released() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(DATA_DIR.glob("released_modules_*.csv")):
        try:
            with open(p, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    note = (r.get("note") or "").strip()
                    if " | " in note:
                        desc = note.split(" | ", 1)[1].strip()
                        if desc:
                            out.setdefault(norm(r.get("mlfb", "")), desc)
        except (OSError, csv.Error):
            continue
    return out


def _cpu4(m: re.Match) -> str:
    h = "H" if m.group(3) == "H" else ""
    return f"CPU 41{m.group(1)}-{m.group(2)}{h} (S7-400{'H' if h else ''})"


# (regex normalize edilmiş MLFB üzerinde, ad üreteci) — en spesifik önce
_FAMILY: list[tuple[str, object]] = [
    (r"^6ES741(\d)(\d)(\w)", _cpu4),
    (r"^6ES731(\d)", lambda m: f"CPU 31{m.group(1)} (S7-300)"),
    (r"^6ES7960", "H-Sync modülü (FO, S7-400H)"),
    (r"^6ES7400", "Rack (S7-400 UR)"),
    (r"^6ES740[57]", "Power supply PS 40x (S7-400)"),
    (r"^6ES7307", "Power supply PS 307 (S7-300)"),
    (r"^6ES7321", "SM 321 DI (S7-300 / ET 200M)"),
    (r"^6ES7322", "SM 322 DO (S7-300 / ET 200M)"),
    (r"^6ES7323", "SM 323 DI/DO (S7-300 / ET 200M)"),
    (r"^6ES7326", "SM 326 F-DI/F-DO (ET 200M)"),
    (r"^6ES7331", "SM 331 AI (S7-300 / ET 200M)"),
    (r"^6ES7332", "SM 332 AO (S7-300 / ET 200M)"),
    (r"^6ES7334", "SM 334 AI/AO (S7-300 / ET 200M)"),
    (r"^6ES7336", "SM 336 F-AI (ET 200M)"),
    (r"^6ES734[01]", "CP 340/341 serial (S7-300)"),
    (r"^6ES735", "FM (S7-300 function module)"),
    (r"^6ES71531", "IM 153-1 (ET 200M)"),
    (r"^6ES71532", "IM 153-2 (ET 200M, redundant)"),
    (r"^6ES71534", "IM 153-4 PN (ET 200M)"),
    (r"^6ES71521", "IM 152-1 (ET 200iSP)"),
    (r"^6ES7151", "IM 151 (ET 200S)"),
    (r"^6ES71556", "IM 155-6 (ET 200SP)"),
    (r"^6ES71555", "IM 155-5 (ET 200MP)"),
    (r"^6ES71570", "DP/PA coupler / link (IM 157)"),
    (r"^6ES71317", "ET 200iSP DI"), (r"^6ES71327", "ET 200iSP DO"),
    (r"^6ES71347", "ET 200iSP AI"), (r"^6ES71357", "ET 200iSP AO"), (r"^6ES71387", "ET 200iSP modül"),
    (r"^6ES713[0-9]4", "ET 200S modül"),
    (r"^6ES713[0-9]6", "ET 200SP modül"),
    (r"^6ES7195", "Bus module / active backplane (ET 200M)"),
    (r"^6ES742", "SM 42x (S7-400 central I/O)"), (r"^6ES743", "SM 43x (S7-400 central I/O)"),
    (r"^6ES7972", "PROFIBUS repeater / connector"),
    (r"^6GK74431", "CP 443-1 (Industrial Ethernet, S7-400)"),
    (r"^6GK74435", "CP 443-5 (PROFIBUS, S7-400)"),
    (r"^6GK73431", "CP 343-1 (Industrial Ethernet, S7-300)"),
    (r"^6GK73425", "CP 342-5 (PROFIBUS, S7-300)"),
    (r"^6GK1", "SIMATIC NET network component"),
    (r"^6SL3", "SINAMICS drive"),
    (r"^6SE6", "MICROMASTER drive"),
    (r"^3RK", "ET 200 motor starter / AS-i"),
    (r"^6AV", "HMI panel"),
]


def describe(mlfb: str) -> tuple[str, str]:
    """(açıklama, kaynak). Bilinmiyorsa ('', '')."""
    n = norm(mlfb)
    if not n:
        return "", ""
    rel = _released()
    if n in rel:
        return rel[n], SRC_LIST
    for pat, name in _FAMILY:
        m = re.match(pat, n)
        if m:
            return (name(m) if callable(name) else name), SRC_FAMILY
    return "", ""


def label(mlfb: str) -> str:
    """'6ES7 321-1BL00-0AA0 (SM321 DI 32xDC24V)' — açıklama yoksa sadece MLFB."""
    d, _ = describe(mlfb)
    return f"{mlfb} ({d})" if d else mlfb


__all__ = ["describe", "label", "norm", "SRC_LIST", "SRC_FAMILY"]
