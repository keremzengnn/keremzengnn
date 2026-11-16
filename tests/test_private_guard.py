"""Repo public: fiyat / teklif / katalog / müşteri dosyaları repoya girmemeli (HANDOFF kural 1).
Bu test git'in izlediği dosyaların adlarına ve uzantılarına bakar; içerik taraması yerel `tools/` komutundadır."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_NAME = re.compile(r"katalog|catalog|fiyat|price|fiyatlama|^kg_", re.I)
FORBIDDEN_EXT = {".xlsm", ".zip", ".7z", ".rar", ".mdf", ".ldf", ".evtx"}
FORBIDDEN_DIRS = ("work/", "99_Work/", "10_Offers/", "20_Reports/", "Calisma/", "Anket/", "pricing_local/", "offer_local/")


def _tracked() -> list[str]:
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("git deposu yok")
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ln for ln in out.splitlines() if ln]


def test_no_private_names_tracked():
    bad = [p for p in _tracked() if FORBIDDEN_NAME.search(Path(p).name)]
    assert not bad, f"repoda fiyat/katalog adlı dosya: {bad}"


def test_no_private_dirs_or_ext_tracked():
    files = _tracked()
    bad = [p for p in files if p.startswith(FORBIDDEN_DIRS) or Path(p).suffix.lower() in FORBIDDEN_EXT]
    assert not bad, f"repoda yasak klasör/uzantı: {bad}"


def test_no_unexpected_spreadsheets_or_pdfs_tracked():
    bad = [p for p in _tracked() if Path(p).suffix.lower() in {".xlsx", ".xls", ".pdf", ".docx"}]
    assert not bad, f"repoda beklenmeyen ofis/PDF dosyası (müşteri verisi olabilir): {bad}"


def test_gitignore_protects_private_patterns():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pat in ("work/", "*katalog*", "*fiyat*", "*price*", "*.xlsm", "10_Offers/", "20_Reports/"):
        assert pat in text, f".gitignore'da {pat} yok"
