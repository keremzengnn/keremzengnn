"""
Ayarlar (ad, departman, Word template yolu, rapor klasörü …).

İki katman:
1. Ekip varsayılanları: exe'nin (veya Baslat.bat / repo klasörünün, ya da çalışma klasörünün) yanındaki
   `pcs7_analyzer_ayarlar.json`. Önce bu okunur; program asla buraya yazmaz. Göreli yollar dosyanın klasörüne göre.
2. Kullanıcı ayarları: %APPDATA%/pcs7_analyzer/settings.json. Boş olmayan değerler ekip varsayılanını ezer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

KEYS = ("author", "department", "template", "released", "out_root", "target", "kb_db", "last_source_dir",
        "customer")
TEAM_FILE = "pcs7_analyzer_ayarlar.json"
_PATH_KEYS = ("template", "released", "out_root", "kb_db")


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pcs7_analyzer" / "settings.json"


def team_paths() -> list[Path]:
    """Ekip varsayılanları dosyasının aranacağı yerler (ilk bulunan kullanılır)."""
    cands = []
    if os.environ.get("PCS7_ANALYZER_TEAM_SETTINGS"):
        cands.append(Path(os.environ["PCS7_ANALYZER_TEAM_SETTINGS"]))
    if getattr(sys, "frozen", False):                       # PyInstaller exe: exe'nin klasörü
        cands.append(Path(sys.executable).resolve().parent / TEAM_FILE)
    cands.append(Path(__file__).resolve().parents[1] / TEAM_FILE)  # repo kökü (Baslat.bat yanı)
    cands.append(Path.cwd() / TEAM_FILE)
    return cands


def team_file() -> Path | None:
    return next((p for p in team_paths() if p.is_file()), None)


def _read(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        return {k: v for k, v in d.items() if k in KEYS and isinstance(v, str)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load_team() -> dict:
    p = team_file()
    if p is None:
        return {}
    d = _read(p)
    for k in _PATH_KEYS:                                     # göreli yol -> ekip dosyasının klasörü
        if d.get(k) and not Path(d[k]).is_absolute():
            d[k] = str((p.parent / d[k]).resolve())
    return d


def load_user() -> dict:
    return _read(settings_path())


def load() -> dict:
    """Ekip varsayılanları + kullanıcı ayarları (boş kullanıcı değeri ekip değerini ezmez)."""
    d = load_team()
    d.update({k: v for k, v in load_user().items() if v})
    return d


def save(values: dict) -> None:
    """Sadece kullanıcı ayar dosyasına yazar (ekip dosyasına asla)."""
    p = settings_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        cur = load_user()
        cur.update({k: str(v) for k, v in values.items() if k in KEYS and v is not None})
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def find_template(explicit: str | None = None) -> Path | None:
    """Açık yol > ayarlardaki yol > data/*.dotx (exe/çalışma klasörü yanı, sonra gömülü report_template.dotx)."""
    from .analyze import data_dirs
    for c in (explicit, load().get("template")):
        if c and Path(c).is_file():
            return Path(c)
    for d in data_dirs():
        if d.is_dir():
            for p in sorted(d.glob("*.dotx")):
                return p
    return None


def find_kb(explicit: str | None = None) -> Path | None:
    """Doküman bilgi tabanı (python -m pcs7_analyzer kb build ...): açık yol > ayar > ./kb/kb.sqlite > ayar klasörü."""
    for c in (explicit, load().get("kb_db"), Path.cwd() / "kb" / "kb.sqlite", settings_path().parent / "kb.sqlite"):
        if c and Path(c).is_file():
            return Path(c)
    return None
