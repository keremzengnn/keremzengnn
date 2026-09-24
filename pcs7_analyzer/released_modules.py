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
            return MatchResult(mlfb, fw, MatchStatus.NOT_FOUND)
        listed_fws = {e.fw for e in entries if e.fw}
        if fw and listed_fws and fw not in listed_fws:
            return MatchResult(mlfb, fw, MatchStatus.LISTED_FW_DIFFERS, entries)
        return MatchResult(mlfb, fw, MatchStatus.LISTED, entries)
