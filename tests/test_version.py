import re
import tomllib
from pathlib import Path

import pcs7_analyzer

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def test_semver_format():
    assert SEMVER.match(pcs7_analyzer.__version__)


def test_changelog_first_version_matches():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[(\d+\.\d+\.\d+[^\]]*)\]", text, re.M)
    assert m, "CHANGELOG.md'de sürüm başlığı yok"
    assert m.group(1) == pcs7_analyzer.__version__


def test_pyproject_version_in_sync():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == pcs7_analyzer.__version__
