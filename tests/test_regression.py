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
