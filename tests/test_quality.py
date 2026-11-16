"""Veri kalitesi (quality.py), report_ir entegrasyonu, index satırı, bozuk zip (BadArchive)."""
import json
from types import SimpleNamespace

import pytest

from pcs7_analyzer import __version__, confirm, index_page, quality
from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.report import build_document
from pcs7_analyzer.report_ir import build_ir
from pcs7_analyzer.source import BadArchive, open_source


@pytest.fixture(scope="module")
def an(tmp_path_factory):
    root = tmp_path_factory.mktemp("q_demo")
    return analyze(build_demo_project(root), released_csv=root / "released_demo.csv")


def test_compute_counts(an):
    q = quality.compute(an)
    assert q["hw_total"] == len(an.stations) and q["hw_sure"] == sum(1 for s in an.stations if s.kind == "cfg")
    assert q["folders_total"] == len(an.as_folders) and q["folders_sure"] <= q["folders_total"]
    assert q["confirm"] == len(confirm.collect(an))
    assert q["warnings"] == len(an.warnings)


def test_line_format_and_clean():
    q = {"hw_sure": 3, "hw_total": 5, "folders_sure": 12, "folders_total": 15, "confirm": 17, "warnings": 0}
    s = quality.line(q)
    assert s == "Veri kalitesi: HW kesin 3/5 · Block klasörü eşleşmesi 12/15 · Teyit edilecek noktalar 17"
    assert confirm.is_clean(s)
    assert quality.line({"confirm": 2}) == "Veri kalitesi: Teyit edilecek noktalar 2"


def test_ir_has_quality_and_version(an):
    ir = build_ir(an, build_document(an, full=False))
    assert ir["tool_version"] == __version__
    assert ir["quality"] == quality.compute(an)


def test_index_shows_quality(tmp_path):
    q = {"hw_sure": 1, "hw_total": 2, "folders_sure": 0, "folders_total": 0, "confirm": 4, "warnings": 0}
    (tmp_path / "report_ir.json").write_text(json.dumps({"stats": {}, "quality": q}), encoding="utf-8")
    assert any(x.startswith("Veri kalitesi: HW kesin 1/2") for x in index_page.summary_lines(tmp_path))


def test_inventory_summary_has_quality(tmp_path):
    inv = SimpleNamespace(source="s", created="c", discovery=None, folder_as={"a": "AS1 (x)", "b": "AS2 (ÇIKARIM)"},
                          confirm=[1], warnings=[])
    index_page.write_inventory_summary(inv, tmp_path)
    q = json.loads((tmp_path / "envanter_ozet.json").read_text(encoding="utf-8"))["quality"]
    assert (q["folders_sure"], q["folders_total"], q["confirm"]) == (1, 2, 1)


def test_bad_zip_raises_badarchive(tmp_path):
    p = tmp_path / "bozuk.zip"
    p.write_bytes(b"PK\x03\x04 bu bir zip degil")
    with pytest.raises(BadArchive) as ei:
        open_source(p)
    assert "bozuk" in str(ei.value)
    t = tmp_path / "kesik.zip"
    t.write_bytes(b"PK\x05\x06" + b"\x00" * 10)    # eksik end-of-central-directory
    with pytest.raises(BadArchive):
        open_source(t)
