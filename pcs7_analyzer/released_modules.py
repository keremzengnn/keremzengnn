"""
Released Modules listesi (data/released_modules_<versiyon>.csv) yükleyici ve eşleştirici.

CSV kolonları: mlfb, fw, status, note   (fw boş = listede FW belirtilmemiş)
Kural: listede olmayan MLFB ASLA "uyumlu" raporlanmaz -> NOT_FOUND ("bulunamadı, teyit edilmeli").
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class MatchStatus(str, Enum):
    LISTED = "listede"
    LISTED_FW_DIFFERS = "listede, FW listede yok"
    NOT_FOUND = "bulunamadı, teyit edilmeli"


def normalize_mlfb(mlfb: str) -> str:
    return "".join(mlfb.split()).upper()


@dataclass(frozen=True)
class ReleasedEntry:
    mlfb: str
    fw: str
    status: str
    note: str


@dataclass(frozen=True)
class MatchResult:
    mlfb: str
    fw: str
    status: MatchStatus
    entries: tuple[ReleasedEntry, ...] = ()
    note: str = ""


class ReleasedModules:
    def __init__(self, entries: list[ReleasedEntry]):
        self._by_mlfb: dict[str, list[ReleasedEntry]] = {}
        for e in entries:
            self._by_mlfb.setdefault(normalize_mlfb(e.mlfb), []).append(e)

    @classmethod
    def load(cls, csv_path: Path) -> "ReleasedModules":
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
            rows = [
                ReleasedEntry(r["mlfb"].strip(), (r.get("fw") or "").strip(),
                              (r.get("status") or "").strip(), (r.get("note") or "").strip())
                for r in csv.DictReader(f) if (r.get("mlfb") or "").strip()
            ]
        return cls(rows)

    def match(self, mlfb: str, fw: str = "") -> MatchResult:
        entries = tuple(self._by_mlfb.get(normalize_mlfb(mlfb), ()))
        if not entries:
            return MatchResult(mlfb, fw, MatchStatus.NOT_FOUND, (), accessory_note(mlfb))
        if not fw or any(not e.fw for e in entries) or any(fw_matches(fw, e.fw) for e in entries):
            return MatchResult(mlfb, fw, MatchStatus.LISTED, entries)
        return MatchResult(mlfb, fw, MatchStatus.LISTED_FW_DIFFERS, entries)


def fw_matches(actual: str, listed: str) -> bool:
    """'V6.0' ~ 'V6.x' / 'V6' / 'V6.0'; 'V8.2.3' ~ 'V8.2.x'. Listede daha az hane varsa önek eşleşmesi."""
    a = actual.strip().lstrip("Vv").split(".")
    b = listed.strip().lstrip("Vv").split(".")
    for i, seg in enumerate(b):
        if seg.lower() == "x":
            return True
        if i >= len(a) or a[i] != seg:
            return False
    return True


# Released Modules listesinde yer almayan aksesuarlar (kontrol edilmeli ama "uyumsuz" değil)
ACCESSORIES = {
    "6ES7960-1AA": "H-Sync modülü (aksesuar): Released Modules listesinde yer almaz; CPU / H-System manual'ından teyit edilmeli",
    "6ES7960-1AB": "H-Sync modülü (aksesuar): Released Modules listesinde yer almaz; CPU / H-System manual'ından teyit edilmeli",
    "6ES7960-1BB": "Sync kablosu (aksesuar): Released Modules listesinde yer almaz",
}


def accessory_note(mlfb: str) -> str:
    n = normalize_mlfb(mlfb)
    return next((v for k, v in ACCESSORIES.items() if n.startswith(k)), "")
