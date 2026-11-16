"""Veri kalitesi sayıları: ne kadarı backup'tan kesin okundu. Sadece sayı; yöntem anlatılmaz.

`compute(an)` -> {"hw_sure", "hw_total", "folders_sure", "folders_total", "confirm", "warnings"}.
`line(q)` -> 'Veri kalitesi: HW kesin 3/5 · Block klasörü eşleşmesi 12/15 · Teyit edilecek noktalar 17'.
"""
from __future__ import annotations

from .model import Confidence


def compute(an) -> dict:
    stations = list(getattr(an, "stations", []) or [])
    folders = list(getattr(an, "as_folders", []) or [])
    try:
        from .confirm import collect
        n_confirm = len(collect(an))
    except Exception:  # noqa: BLE001 - kalite özeti raporu durdurmaz
        n_confirm = 0
    return {"hw_sure": sum(1 for s in stations if s.kind == "cfg"), "hw_total": len(stations),
            "folders_sure": sum(1 for b in folders if b.mapping_confidence == Confidence.HIGH.value),
            "folders_total": len(folders), "confirm": n_confirm,
            "warnings": len(getattr(an, "warnings", []) or [])}


def line(q: dict) -> str:
    parts = []
    if q.get("hw_total"):
        parts.append(f"HW kesin {q['hw_sure']}/{q['hw_total']}")
    if q.get("folders_total"):
        parts.append(f"Block klasörü eşleşmesi {q['folders_sure']}/{q['folders_total']}")
    parts.append(f"Teyit edilecek noktalar {q.get('confirm', 0)}")
    return "Veri kalitesi: " + " · ".join(parts)
