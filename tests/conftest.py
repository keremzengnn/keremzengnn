import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Testler kullanıcının gerçek ayar dosyasına dokunmasın."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
