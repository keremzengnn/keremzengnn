"""Kaynak (klasör / zip): uzun path'ler ve bozuk girdi durumunda çökmeme."""
import zipfile

from pcs7_analyzer.parsers.subblk import lang_name
from pcs7_analyzer.source import open_source

DEEP = "/".join(["Multiproject_Klasoru_Uzun_Isim_" + str(i) for i in range(8)])   # ~270 karakter


def test_long_paths_folder_and_zip(tmp_path):
    root = tmp_path / "bk"
    rel = f"{DEEP}/ombstx/offline/00000001/SUBBLK.DBF"
    from pcs7_analyzer.source import long_path
    target = long_path(root / rel)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"abc")
    with open_source(root) as src:
        assert [e.rel for e in src.entries] == [rel]
        assert src.materialize(rel).read_bytes() == b"abc"
    z = tmp_path / "bk.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(rel, b"xyz")
    with open_source(z) as src:
        assert src.materialize(rel).read_bytes() == b"xyz"


def test_lang_name():
    assert lang_name("00001") == "STL"
    assert lang_name("00004") == "SCL"
    assert lang_name("00099") == "kod 99"
    assert lang_name("") == "" and lang_name("00000") == ""


def test_stage_failure_does_not_stop_analysis(tmp_path, monkeypatch):
    from pcs7_analyzer import analyze as A
    from pcs7_analyzer.demo import build_demo_project

    def boom(*a, **k):
        raise RuntimeError("beklenmeyen format")
    monkeypatch.setattr(A, "_analyze_os", boom)
    an = A.analyze(build_demo_project(tmp_path))
    assert any("OS projeleri bölümü tamamlanamadı" in w for w in an.warnings)
    assert an.stations and an.block_folders and an.findings


def test_run_writes_log_and_survives_output_failure(tmp_path, monkeypatch):
    from pcs7_analyzer import cli, excel_report
    from pcs7_analyzer.demo import build_demo_project

    def boom(*a, **k):
        raise RuntimeError("excel hatası")
    monkeypatch.setattr(excel_report, "write_excel", boom)
    src = build_demo_project(tmp_path / "d")
    out = tmp_path / "out"
    p = cli.run(src, out, log=lambda m: None)
    assert p.name == "rapor.html" and p.exists()
    log = (out / "log.txt").read_text(encoding="utf-8")
    assert "rapor.xlsx üretilemedi" in log
    assert not (out / "rapor.xlsx").exists()


def test_mlfb_describe():
    from pcs7_analyzer.mlfb_info import SRC_FAMILY, SRC_LIST, describe, label
    assert describe("6ES7 321-1BL00-0AA0") == ("SM321 DI 32xDC24V", SRC_LIST)
    assert describe("6ES7321-1BL00-0AA0")[0] == "SM321 DI 32xDC24V"       # boşluksuz yazım
    assert describe("6ES7 960-1AA06-0XA0")[1] == SRC_FAMILY                 # listede yok -> aile
    assert describe("6ES7 999-9XX99-0AA0") == ("", "")                      # bilinmiyor: tahmin yok
    assert label("6ES7 153-2BA10-0XB0") == "6ES7 153-2BA10-0XB0 (ET 200M- IM 153-2)"
