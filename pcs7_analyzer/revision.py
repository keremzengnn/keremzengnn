"""Revizyon farkı (PROMPT_EK_RAPOR_KALITESI R7): önceki rapor klasörünün findings.json'u ile karşılaştırma.

Anahtar = check_id + scope + title (Finding ID sıralamaya bağlı olduğu için anahtar değildir).
Sonuç: Yeni / Kapanan / Değişen (durum, önem, güven, detay) bulgular -> `revizyon.md` + report_ir.json `revision`.
"""
from __future__ import annotations

import json
from pathlib import Path

FIELDS = ("status", "severity", "guven", "detail")


def _key(f: dict) -> tuple:
    return (f.get("check_id", ""), f.get("scope", ""), f.get("title", ""))


def load_findings(folder: Path) -> list[dict]:
    p = Path(folder) / "findings.json"
    if not p.exists():
        raise FileNotFoundError(f"önceki rapor klasöründe findings.json yok: {folder}")
    return json.loads(p.read_text(encoding="utf-8"))


def previous_revision(folder: Path) -> int:
    p = Path(folder) / "report_ir.json"
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("revision", 0))
    except (OSError, ValueError):
        return 0


def diff(old: list[dict], new: list[dict]) -> dict:
    o = {_key(f): f for f in old}
    n = {_key(f): f for f in new}
    changed = []
    for k in sorted(set(o) & set(n)):
        ch = {fld: (o[k].get(fld), n[k].get(fld)) for fld in FIELDS if o[k].get(fld) != n[k].get(fld)}
        if ch:
            changed.append({"key": list(k), "fid": n[k].get("fid", ""), "changes": ch})
    return {"new": [n[k] for k in sorted(set(n) - set(o))],
            "closed": [o[k] for k in sorted(set(o) - set(n))],
            "changed": changed}


def _label(f: dict) -> str:
    t = f.get("title") or f.get("check_id", "")
    return t + (f" ({f['scope']})" if f.get("scope") else "")


def render(d: dict, prev: Path, rev: int) -> str:
    lines = [f"# Revizyon r{rev}: önceki rapora göre değişenler", "", f"Önceki: {Path(prev).name}", "",
             f"- Yeni bulgu: {len(d['new'])}", f"- Kapanan bulgu: {len(d['closed'])}",
             f"- Değişen bulgu: {len(d['changed'])}", ""]
    if d["new"]:
        lines += ["## Yeni bulgular", "", "| ID | Bulgu | Durum | Önem |", "|---|---|---|---|"]
        lines += [f"| {f.get('fid', '-')} | {_label(f)} | {f.get('status', '')} | {f.get('severity', '-')} |" for f in d["new"]]
        lines.append("")
    if d["closed"]:
        lines += ["## Kapanan bulgular", "", "| Önceki ID | Bulgu | Durum |", "|---|---|---|"]
        lines += [f"| {f.get('fid', '-')} | {_label(f)} | {f.get('status', '')} |" for f in d["closed"]]
        lines.append("")
    if d["changed"]:
        lines += ["## Değişen bulgular", "", "| ID | Bulgu | Değişiklik |", "|---|---|---|"]
        for c in d["changed"]:
            k = c["key"]
            what = "; ".join(f"{fld}: {a} → {b}" if fld != "detail" else "detay değişti"
                             for fld, (a, b) in c["changes"].items())
            lines.append(f"| {c['fid'] or '-'} | {k[2] or k[0]}{f' ({k[1]})' if k[1] else ''} | {what} |")
    return "\n".join(lines) + "\n"


__all__ = ["diff", "load_findings", "previous_revision", "render"]
