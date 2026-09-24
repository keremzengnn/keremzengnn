"""Uçtan uca: sahte demo backup'ı (klasör ve zip) üzerinde analiz + rapor."""
import json

import pytest

from pcs7_analyzer.analyze import analyze, staged_path_from
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.model import Severity
from pcs7_analyzer.report import render_html, render_json, render_markdown


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo")
    bk = build_demo_project(root)
    return bk, root / "released_demo.csv"


@pytest.fixture(scope="module")
def an(demo):
    bk, rel = demo
    return analyze(bk, released_csv=rel)


def _ids(an):
    return {f.check_id for f in an.findings}


def test_versions(an):
    assert an.pcs7_family == "V8.1"
    assert any("V5.5 SP4" in v.value for v in an.versions)
    assert any("WinCC V7.3" in v.value for v in an.versions)


def test_stale_backup_excluded(an):
    assert an.stale_dirs == ["ESKI_BACKUP/DEMO_MP/AS01"]
    assert not any(b.info.path.startswith("ESKI_BACKUP") for b in an.block_folders)
    assert "CONS_BACKUP_DATES" in _ids(an)


def test_stations_and_hsync_not_found(an):
    names = sorted(s.name for s in an.stations)
    assert names == ["AS01", "AS02"]
    hs = [m for m in an.hw_matches if "960-1AA06" in m.order]
    assert hs and hs[0].status.startswith("bulunamadı")
    assert "HW_RELEASED" in _ids(an)


def test_block_folders(an):
    as01 = next(b for b in an.block_folders if b.as_label == "AS01")
    assert as01.counts == {"FB": 11, "FC": 3, "DB": 23, "OB": 3}
    assert as01.fb_instances[1827] == 5
    assert as01.fb_instances[1990] == 1           # >= 0x80 byte'lı FB numarası
    assert set(as01.mixed_versions["APL"]) == {"V8.0 (1)", "V8.1 (2)", "V8.2 (1)"}
    assert {"Logic Matrix", "SFC", "PCS 7 Lib V7.1"} <= set(as01.features)
    assert {c.number for c in as01.custom_blocks} == {1990, 1993, 2500, 2501}
    assert as01.symbol_only == ["FB1994 E_AS_PUT"]
    assert "(symbol)" in next(c.name for c in as01.custom_blocks if c.number == 2500)
    assert any(b.info.is_empty for b in an.block_folders)


def test_f_system_detected_from_symbols(an):
    as02 = next(b for b in an.block_folders if b.as_label == "AS02")
    assert "F-System" in as02.features
    assert as02.f_driver_instances == 6          # F_CH_DI ×4 + F_CH_DO ×2
    assert not as02.custom_blocks                 # header'sız F-block'lar custom sayılmaz
    f = [x for x in an.findings if x.check_id == "HW_F_EXPORT_MISSING"]
    assert f and "AS02" in f[0].detail


def test_os_consistency(an):
    (d,) = an.os_diffs
    assert d.b_label == "PC_KOPYALARI/SRV1"
    assert "GraCS/Tank_2.pdl" in d.newer_b
    assert {"GraCS/Tank_New.pdl", "GraCS/@ServerButtons.pdl", "ScriptAct/Global_new.bac"} <= set(d.only_b)
    assert "GraCS/Tank_3.pdl" in d.newer_a
    assert not any("pas" in x.lower() for x in d.only_a + d.only_b)   # PC adı klasörü normalize
    f = next(x for x in an.findings if x.check_id == "CONS_ES_SERVER")
    assert f.severity is Severity.HIGH


def test_client_groups(an):
    assert len(an.client_groups) == 2
    ref = next(g for g in an.client_groups if g.is_reference)
    assert sorted(m.rsplit("/", 1)[-1] for m in ref.members) == ["OSC01", "OSC02"]
    other = next(g for g in an.client_groups if not g.is_reference)
    assert other.only_in_group == ["GraCS/@PG_APL_Message_AOTC.pdl"]


def test_os_details(an):
    srv = next(o for o in an.os_projects if o.info.name == "OS_SRV1" and o.in_es)
    assert srv.role == "server"
    assert srv.custom_typicals == ["@PCS7TypicalsDemoAPL.pdl"]
    assert srv.f_faceplates == ["@PG_SWC_MOS1.pdl"]
    assert srv.opc == ["opc/dataaccess"]


def test_expected_checks(an):
    assert {"LIB_APL_V8", "LIB_LOGIC_MATRIX", "LIB_SFC", "LIB_PCS7_V71", "LIB_F_SYSTEM", "BLK_CUSTOM",
            "BLK_SYMBOL_MISMATCH", "COMM_AS_AS", "OS_CUSTOM_TYPICALS", "OS_OPC", "HW_GSD_3RD_PARTY",
            "CONS_CLIENTS"} <= _ids(an)
    assert not an.not_checked


def test_report_structure(an):
    md = render_markdown(an)
    for h in ("## 1. Özet", "Tablo 1: Genel değerlendirme", "## 2. Proje bilgileri", "## 3. Zorluklar",
              "## 4. Teklif öncesi netleşmesi gerekenler", "## 5. Referans dokümanlar"):
        assert h in md
    assert "Upgrade yaklaşımı" not in md
    assert md.index("Tablo 1") < md.index("Planlı duruş") < md.index("## 2. Proje bilgileri")
    html = render_html(an)
    assert "#000028" in html and "#009999" in html
    assert 'class="badge high"' in html
    json.loads(render_json(an))


def test_zip_gives_same_result(demo, an, tmp_path):
    bk, rel = demo
    z = tmp_path / "b.zip"
    import zipfile
    with zipfile.ZipFile(z, "w") as zf:
        for p in sorted(bk.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(bk).as_posix())
    az = analyze(z, released_csv=rel)
    assert sorted((f.check_id, f.detail) for f in az.findings) == sorted((f.check_id, f.detail) for f in an.findings)


def test_source_not_modified(tmp_path):
    bk = build_demo_project(tmp_path)
    snap = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in bk.rglob("*"))
    analyze(bk)
    assert sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in bk.rglob("*")) == snap


def test_without_released_list(demo):
    bk, _ = demo
    a = analyze(bk)
    assert ("HW_RELEASED", "data/released_modules_<versiyon>.csv yok") in a.not_checked
    assert "kontrol edilmedi" in render_markdown(a).lower()


def test_empty_source(tmp_path):
    a = analyze(tmp_path)
    md = render_markdown(a)
    assert "PCS 7 versiyonu otomatik tespit edilemedi" in md


@pytest.mark.parametrize("fam, path", [("V8.1", ["V8.2.4", "V9.1", "V10.0 SP2"]), ("V8.2", ["V9.1", "V10.0 SP2"]),
                                       ("V9.1", ["V10.0 SP2"]), (None, ["V8.2.4", "V9.1", "V10.0 SP2"])])
def test_staged_path(fam, path):
    assert staged_path_from(fam) == path
