"""
Gerçek proje üzerinde regression testleri.

Müşteri verisi (backup ve beklenen sayılar) repoya GİRMEZ. Çalıştırmak için:
  PCS7_TEST_PROJECT=<backup klasörü>
  tests/regression/expected_local.json   (gitignore'da; şablon: expected_example.json)
"""
import json
import os
from pathlib import Path

import pytest

from pcs7_analyzer.parsers import parse_subblk

EXPECTED = Path(__file__).parent / "regression" / "expected_local.json"
PROJECT = os.environ.get("PCS7_TEST_PROJECT")

pytestmark = pytest.mark.skipif(not (PROJECT and EXPECTED.exists()),
                                reason="PCS7_TEST_PROJECT ve expected_local.json gerekli")


def _cases():
    if not EXPECTED.exists():
        return []
    return [pytest.param(c, id=c["id"]) for c in json.loads(EXPECTED.read_text(encoding="utf-8"))["block_folders"]]


@pytest.mark.parametrize("case", _cases())
def test_block_folder(case):
    bf = parse_subblk(Path(PROJECT) / case["path"] / "SUBBLK.DBF")
    for k, v in case.get("counts", {}).items():
        assert bf.counts.get(k, 0) == v, k
    for fb, n in case.get("instances", {}).items():
        assert bf.instances_per_fb[("FB", int(fb))] == n, f"FB{fb}"
    for author in case.get("authors_present", []):
        assert any(b.author == author for b in bf.blocks), author


def test_wincc_and_os():
    """Gerçek projede WinCC export / SFC / client grubu beklenenleri (expected_local.json'da varsa)."""
    exp = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if not any(k in exp for k in ("wincc", "sfc_charts", "client_groups")):
        pytest.skip("expected_local.json'da wincc/sfc_charts/client_groups yok")
    from pcs7_analyzer.analyze import analyze
    an = analyze(Path(PROJECT), extra_exports=[Path(p) for p in exp.get("exports", [])])
    for os_name, v in exp.get("wincc", {}).items():
        if os_name.startswith("_"):
            continue
        w = an.wincc[os_name]
        assert (w.dm_tag, w.dm_structtag, w.alarms) == (v["dm_tag"], v["dm_structtag"], v["alarms"]), os_name
    for os_name, n in exp.get("sfc_charts", {}).items():
        assert next(o.sfc["charts"] for o in an.os_projects if o.info.name == os_name and o.in_es) == n
    if "client_groups" in exp:
        assert len(an.client_groups) == exp["client_groups"]
