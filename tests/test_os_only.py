"""Sadece-OS (WinCC-only) girdi: .mcp kökte / alt klasörde, kopya eşleşmesi, prob (sentetik, .s7p yok)."""
import zipfile
from pathlib import Path

import pytest

from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.discovery import discover
from pcs7_analyzer.probes import wincc_probe
from pcs7_analyzer.readiness import KISMEN, backup_coverage
from pcs7_analyzer.source import open_source

FILES = {"P.mcp": b"V07.03.20.04", "GraCS/a.pdl": b"x", "GraCS/@PG_X.pdl": b"y", "ScriptLib/m.bmo": b"z",
         "ScriptAct/g.bac": b"z", "PC1/PAS/c.pas": b"z"}


def _tree(root: Path, files=FILES) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _check(o):
    assert (o.n_files, o.custom_pictures, o.faceplates_and_templates) == (6, 1, 1)
    assert (o.vbs_modules, o.vbs_actions, o.c_actions) == (1, 1, 1)
    assert o.wincc_build == "V07.03.20.04"


@pytest.mark.parametrize("sub", ["", "x/Sub"])
def test_mcp_root_and_nested(tmp_path, sub):
    root = _tree(tmp_path / "Proj1" / sub if sub else tmp_path / "Proj1")
    (tmp_path / "Proj1").mkdir(exist_ok=True)
    d = discover(tmp_path / "Proj1")
    assert len(d.os_projects) == 1
    o = d.os_projects[0]
    _check(o)
    assert o.name == ("Proj1" if not sub else "Sub")
    an = analyze(tmp_path / "Proj1")
    op = an.os_projects[0]
    assert (op.pictures["custom"], op.pictures["faceplate"], len(op.scripts)) == (1, 1, 2)
    assert not op.in_es


def test_mcp_root_zip_name(tmp_path):
    z = tmp_path / "MyOs.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for rel, data in FILES.items():
            zf.writestr(rel, data)
    d = discover(z)
    _check(d.os_projects[0])
    assert d.os_projects[0].name == "MyOs"


def test_unmatched_copy_is_partial_not_var(tmp_path):
    _tree(tmp_path / "Copy1")
    an = analyze(tmp_path)
    assert an.unmatched_os_copies and not an.os_diffs
    assert any("eşleşmedi" in w for w in an.warnings)
    row = next(r for r in backup_coverage(an) if r[0].startswith("OS PC'den"))
    assert row[1] == KISMEN and "tahmin edilmez" in row[3]


def test_probe_counts_and_mask(tmp_path):
    _tree(tmp_path / "SecretCustomer")
    with open_source(tmp_path) as src:
        out = "\n".join(wincc_probe(src))
    assert ".mcp sayısı: 1" in out and "gracs=var (2)" in out and "scriptlib=var (1)" in out
    assert "pas=var (1)" in out and "archivemanager=yok" in out
    assert "SecretCustomer" not in out and "yapi_tanisi" in out


def test_probe_catches_own_error():
    class Bad:
        @property
        def entries(self):
            raise OSError("x")
    out = wincc_probe(Bad())
    assert out == ["- wincc_probe: okunamadı (OSError)"]
