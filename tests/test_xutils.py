"""XUTILS cross-reference (call tree) okuyucu: sentetik STEP 7 V5 dosyalarıyla (müşteri verisi yok)."""
import zipfile
from types import SimpleNamespace

from dbfwriter import SUBBLK_FIELDS, block, write_dbf
from pcs7_analyzer._dbfwriter import write_project_links, write_xutils
from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.collect import needed
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.parsers import xutils
from pcs7_analyzer.parsers.xutils import call_tree, callers_text, find_xutils_dirs, map_sets_to_folders, read_all
from pcs7_analyzer.report import render_json
from pcs7_analyzer.source import open_source

CALLS = [(8, 35, 12, 7, 66), (8, 1, 14, 20, 66)] + [(12, 7, 14, 10, 66)] * 3 + \
        [(12, 7, 10, 100, 80), (14, 10, 14, 20, 66), (12, 9, 14, 10, 64), (12, 7, 13, 20, 66)]
BLOCKS = [(14, 10, 4), (14, 20, 4), (12, 7, 4), (12, 9, 4), (8, 1, 4), (8, 35, 4)]


def _proj(root, *, toi=None, folders=(("00000011", (10, 20)),), progs=None):
    proj = root / "MP" / "P1"
    proj.mkdir(parents=True)
    (proj / "P1.s7p").write_bytes(b"x")
    for hx, fbs in folders:
        d = proj / "ombstx" / "offline" / hx
        d.mkdir(parents=True)
        write_dbf(d / "SUBBLK.DBF", SUBBLK_FIELDS, [block("00004", n, "F", f"X{n}", author="BM") for n in fbs],
                  memo="db4")
    if progs:
        write_project_links(proj, progs)
    write_xutils(proj, 1, CALLS, BLOCKS, toi=toi, name="Prog_A", xr_records=5)
    return proj


def test_reader_and_call_tree(tmp_path):
    _proj(tmp_path)
    with open_source(tmp_path) as src:
        dirs = find_xutils_dirs(src)
        assert list(dirs) == ["MP/P1/XUTILS/1"]
        info = dirs["MP/P1/XUTILS/1"]
        assert info["xr"].endswith("XR000001.DBF") and info["overview"].endswith("CT112001.DBF")
        (xs,) = read_all(src)
    assert xs.n_ct == len(CALLS) and xs.n_bs == len(BLOCKS) and xs.bad_records == 0
    assert xs.set_no == 1 and xs.set_name == "Prog_A"
    assert xs.optypes == {66: 7, 80: 1, 64: 1}
    assert xs.fb_numbers() == {10, 20}
    fb = call_tree(xs, "FB")
    assert fb[10] == [("FC", 7, 3), ("FC", 9, 1)]
    assert fb[20] == [("FB", 10, 1), ("OB", 1, 1)]
    assert call_tree(xs, "FB", ops={66})[10] == [("FC", 7, 3)]
    assert call_tree(xs, "FC")[7] == [("OB", 35, 1)]
    assert call_tree(xs, "SFC")[20] == [("FC", 7, 1)]
    assert call_tree(xs, "DB")[100] == [("FC", 7, 1)]


def test_callers_text():
    b = SimpleNamespace(callers={10: [("FC", 7, 3), ("FC", 9, 1), ("FB", 30, 1), ("OB", 1, 1)]},
                        fc_callers={7: [("OB", 35, 1), ("OB", 100, 1)]})
    assert callers_text(b, 10) == "FC7 (runtime group?, OB35/OB100) ×3, FC9, FB30 (multi-instance?), +1"
    assert callers_text(b, 99) == ""
    assert callers_text(SimpleNamespace(), 10) == ""


def test_mapping_by_fb_overlap(tmp_path):
    _proj(tmp_path, folders=(("00000011", (10, 20)), ("00000012", (500, 501))))
    an = analyze(tmp_path)
    by = {b.info.path.rsplit("/", 1)[-1]: b for b in an.block_folders}
    assert by["00000011"].callers[10] == [("FC", 7, 3), ("FC", 9, 1)]
    assert by["00000011"].callers_confidence == "low" and "heuristic" in by["00000011"].callers_source
    assert not by["00000012"].callers
    assert an.xutils[0]["fb_jaccard"] == 1.0 and an.xutils[0]["confidence"] == "low"
    assert "edges" not in an.xutils[0]                          # rapor.json'a kenar listesi girmez
    render_json(an)


def test_mapping_by_link_toi(tmp_path):
    progs = [{"id": 3, "name": "Prog_A", "folder_id": 0x12, "cpu_id": 900, "cpu_name": "CPU 417-4H",
              "station_id": 0x21, "station_name": "ST_N"}]
    # TOI = S7 program ID 3 -> block klasörü 0x12; FB seti çelişiyor -> unknown'a not
    _proj(tmp_path, toi=3, folders=(("00000011", (10, 20)), ("00000012", (500,))), progs=progs)
    an = analyze(tmp_path)
    by = {b.info.path.rsplit("/", 1)[-1]: b for b in an.block_folders}
    assert by["00000012"].callers and "TOI=3" in by["00000012"].callers_source
    assert not by["00000011"].callers
    assert any(e.module == "xutils" and "çelişiyor" in e.reason for e in an.unknown.entries)


def test_no_match_is_unknown(tmp_path):
    _proj(tmp_path, folders=(("00000011", (500, 501)),))
    an = analyze(tmp_path)
    assert not an.block_folders[0].callers
    assert any(e.module == "xutils" and "eşlenemedi" in e.reason for e in an.unknown.entries)


def test_bad_records_and_unknown_optype(tmp_path):
    proj = _proj(tmp_path)
    write_xutils(proj, 2, [(12, 7, 14, 10, 66), ("", 7, 14, 10, 66), (12, 7, 14, 11, 99)], [(14, 10, 4)])
    with open_source(tmp_path) as src:
        xs = next(x for x in read_all(src) if x.set_no == 2)
    assert xs.bad_records == 1 and xs.n_ct == 3
    assert any("OPTYPE" in u and "99" in u for u in xs.unknown)


def test_broken_ct_does_not_crash(tmp_path):
    proj = _proj(tmp_path)
    (proj / "XUTILS" / "1" / "CT000001.DBF").write_bytes(b"\x03garbage")
    an = analyze(tmp_path)
    assert any(e.module == "xutils" for e in an.unknown.entries)


def test_collect_needed_rules():
    assert needed("MP/P1/XUTILS/1/CT000001.DBF", 900_000_000)
    assert needed("MP/P1/XUTILS/1/BS000001.DBF", 10)
    assert needed("MP/P1/XUTILS/1/CTL00001.DBF", 10)
    assert needed("MP/P1/XUTILS/1/XRL00001.DBF", 10)
    assert needed("MP/P1/xutils/CT112001.DBF", 10)
    assert not needed("MP/P1/XUTILS/1/XR000001.DBF", 10)


def test_demo_and_zip(tmp_path):
    bk = build_demo_project(tmp_path / "d")
    an = analyze(bk)
    as01 = next(b for b in an.block_folders if b.info.path.endswith("AS01/ombstx/offline/00000001"))
    as02 = next(b for b in an.block_folders if b.info.path.endswith("0000000A"))
    assert callers_text(as01, 2501) == "FC1 (runtime group?, OB35)"
    assert callers_text(as01, 1993) == "FB2501 (multi-instance?)"
    assert as01.callers[1827] == [("FC", 1, 5)]
    assert "TOI=7" in as02.callers_source and as02.callers[351] == [("FC", 5, 4)]
    assert all(x["project"].startswith("DEMO_MP/") for x in an.xutils)      # eski backup kopyası dışarıda
    z = tmp_path / "demo.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in sorted(bk.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(bk).as_posix())
    an2 = analyze(z)
    as01z = next(b for b in an2.block_folders if b.info.path.endswith("AS01/ombstx/offline/00000001"))
    assert as01z.callers == as01.callers


def test_map_without_blockmap():
    xs = xutils.XutilsSet(dir="P/XUTILS/1", project="P")
    xs.edges[("FC", 1, "FB", 10, 66)] = 1
    b = SimpleNamespace(info=SimpleNamespace(path="P/ombstx/offline/00000001"), fb_numbers=[10], counts={"FB": 1})
    assert map_sets_to_folders([xs], [b], None)["p/ombstx/offline/00000001"] is xs
