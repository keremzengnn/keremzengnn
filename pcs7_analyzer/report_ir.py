"""Report IR (ara temsil): `build_document` çıktısı -> `report_ir.json`.

İçerik kararları `report.build_document` içinde verilir; renderer'lar (HTML / MD / Word) aynı doküman modelini biçimler.
IR bu modelin serileştirilmiş hâlidir + Finding ID bağları + istatistik + `omitted` (rapora girmeyen bulgular).
QA (`qa.py`) ve revizyon farkı (`--compare-to`) IR üzerinden çalışır. Bkz. docs/DECISIONS.md "Report IR".

Determinizm: `generated_at` dışında aynı girdi -> byte düzeyinde aynı JSON (anahtarlar sıralı).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

SCHEMA_VERSION = "1"

# Profil -> doküman modu. teklif / musteri = Word müşteri raporu (full=False), muhendis = HTML çalışma raporu.
PROFILES = {"teklif": False, "musteri": False, "muhendis": True}

_FID = re.compile(r"\bF-\d{3,}\b")


def input_hash(entries) -> str:
    """Kaynak indeksinin özeti (rel + boyut): aynı backup -> aynı hash; dosya içeriği okunmaz."""
    h = hashlib.sha256()
    for e in sorted(entries, key=lambda x: x.rel):
        h.update(f"{e.rel}\t{e.size}\n".encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def _assumption(text: str) -> bool:
    from .word import is_assumption
    return is_assumption(text)


def _sentence(text: str) -> dict:
    return {"type": "sentence", "text": text, "finding_ids": sorted(set(_FID.findall(text))),
            "assumption": _assumption(text)}


def _block(b) -> dict:
    from .report import Bullets, Note, Para, Table
    if isinstance(b, Table):
        rows = []
        for i, r in enumerate(b.rows):
            ids = b.row_ids[i] if i < len(b.row_ids) else []
            cells = [{"text": str(c), "assumption": _assumption(str(c)),
                      "finding_ids": sorted(set(_FID.findall(str(c))))} for c in r]
            rows.append({"cells": cells, "finding_ids": sorted(set(ids) | {x for c in cells for x in c["finding_ids"]})})
        return {"type": "table", "columns": list(b.headers), "caption": b.caption, "rows": rows}
    if isinstance(b, Bullets):
        return {"type": "list", "items": [_sentence(x) for x in b.items]}
    if isinstance(b, (Para, Note)):
        d = _sentence(b.text)
        d["type"] = "note" if isinstance(b, Note) else "sentence"
        return d
    return {"type": type(b).__name__.lower(), "text": getattr(b, "text", "")}


def stats(an) -> dict:
    from .readiness import finding_status
    by_status: dict[str, int] = {}
    for f in an.findings:
        st = finding_status(f)
        by_status[st] = by_status.get(st, 0) + 1
    return {"findings": len(an.findings), "by_status": dict(sorted(by_status.items())),
            "not_checked": len(an.not_checked), "stations": len(an.stations),
            "os_projects": len(an.os_projects), "block_folders": len(an.block_folders),
            "unknown": len(an.unknown)}


def build_ir(an, doc: list, profile: str = "teklif", src_hash: str = "", project_meta: dict | None = None) -> dict:
    from .report import Heading, Topline
    sections: list[dict] = []
    cur = None
    topline = ""
    for b in doc:
        if isinstance(b, Topline):
            topline = b.text
            continue
        if isinstance(b, Heading) and b.level == 1 or cur is None:
            title = b.text if isinstance(b, Heading) else ""
            cur = {"id": f"s{len(sections) + 1:02d}", "title": title, "part": topline, "blocks": []}
            sections.append(cur)
            if isinstance(b, Heading):
                continue
        if isinstance(b, Heading):
            cur["blocks"].append({"type": "heading", "level": b.level, "text": b.text})
        else:
            cur["blocks"].append(_block(b))
    shown = set()
    for s in sections:
        for b in s["blocks"]:
            for r in b.get("rows", []):
                shown.update(r["finding_ids"])
            shown.update(b.get("finding_ids", []))
            for it in b.get("items", []):
                shown.update(it["finding_ids"])
    omitted = [{"finding_id": f.fid, "check_id": f.check_id, "severity": f.severity.value,
                "reason": "profil dışı (detay Excel 'Bulgular')"} for f in an.findings if f.fid and f.fid not in shown]
    return {"schema_version": SCHEMA_VERSION, "profile": profile, "project_meta": project_meta or {},
            "generated_at": datetime.now().isoformat(timespec="seconds"), "input_hash": src_hash,
            "sections": sections, "finding_ids": sorted(f.fid for f in an.findings if f.fid),
            "stats": stats(an), "omitted": omitted}


def dumps(ir: dict) -> str:
    return json.dumps(ir, ensure_ascii=False, indent=1, sort_keys=True, default=str)


__all__ = ["build_ir", "dumps", "input_hash", "stats", "PROFILES", "SCHEMA_VERSION"]
