"""Kullanıcı ayarları (ad, departman, Word template yolu …): %APPDATA%/pcs7_analyzer/settings.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

KEYS = ("author", "department", "template", "released", "out_root", "target")


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pcs7_analyzer" / "settings.json"


def load() -> dict:
    try:
        d = json.loads(settings_path().read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k in KEYS and isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def save(values: dict) -> None:
    p = settings_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = load()
        cur.update({k: str(v) for k, v in values.items() if k in KEYS and v is not None})
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def find_template(explicit: str | None = None) -> Path | None:
    """Açık yol > ayarlardaki yol > exe/çalışma klasörü yanındaki data/*.dotx."""
    from .analyze import data_dirs
    for c in (explicit, load().get("template")):
        if c and Path(c).is_file():
            return Path(c)
    for d in data_dirs():
        if d.is_dir():
            for p in sorted(d.glob("*.dotx")):
                return p
    return None
