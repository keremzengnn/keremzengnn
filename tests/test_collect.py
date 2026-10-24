"""Paketle (--collect): paket orijinal backup ile aynı analiz sonucunu vermeli, büyük dosyalar pakete girmemeli."""
import json
import shutil
import zipfile

from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.cli import main
from pcs7_analyzer.collect import MANIFEST, collect, needed
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.inventory import build_inventory
from pcs7_analyzer.report import render_json


def _comparable(an):
    d = json.loads(render_json(an))
    for k in ("source", "created", "warnings"):
        d.pop(k, None)
    d.get("discovery", {}).pop("root", None)
    d.get("discovery", {}).pop("warnings", None)
    return d


def test_needed_rules():
    assert needed("MP/AS01/ombstx/offline/00000001/SUBBLK.DBT", 400_000_000)
    assert needed("MP/AS01/hOmSave7/s7hstatx/x.s7h", 10)
    assert needed("MP/OS/wincproj/SRV1/SRV1.mcp", 10)
    assert needed("MP/OS/wincproj/SRV1/ScriptLib/Module1.bmo", 10)
    assert not needed("MP/OS/wincproj/SRV1/SRV1.mdf", 10)
    assert not needed("MP/OS/wincproj/SRV1/GraCS/Tank.pdl", 10)
    assert not needed("MP/OS/wincproj/SRV1/TemplateControl.cfg", 10)
    assert needed("exports/AS01.cfg", 10)


def test_package_gives_same_analysis(tmp_path):
    bk = build_demo_project(tmp_path / "d")
    # iç içe zip de olsun
    inner = tmp_path / "inner"
    shutil.copytree(bk / "DEMO_MP" / "AS02", inner / "AS02")
    shutil.make_archive(str(bk / "ESKI_AS02"), "zip", inner)
    z = tmp_path / "paket.zip"
    st = collect(bk, z, log=lambda m: None)
    assert 0 < st["included"] < st["files"] and not st["errors"]
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
    assert MANIFEST in names
    assert not any(n.lower().endswith((".pdl", ".mdf", ".ldf")) for n in names)
    assert _comparable(analyze(bk)) == _comparable(analyze(z))
    inv_a, inv_b = build_inventory(bk), build_inventory(z)
    sa = {s.name: s.rows for s in inv_a.sheets if s.name not in ("Özet", "Uyarılar")}
    sb = {s.name: s.rows for s in inv_b.sheets if s.name not in ("Özet", "Uyarılar")}
    assert sa == sb


def test_cli_collect(tmp_path, capsys):
    bk = build_demo_project(tmp_path / "d")
    out = tmp_path / "o"
    assert main([str(bk), "--collect", "-o", str(out)]) == 0
    assert (out / f"{bk.name}_paket.zip").exists()
