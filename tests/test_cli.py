import pytest

from pcs7_analyzer.cli import main


def _proj(tmp_path):
    proj = tmp_path / "proj"
    (proj / "P").mkdir(parents=True)
    (proj / "P" / "P.s7p").write_bytes(b"")
    return proj


def test_discover_only(tmp_path):
    out = tmp_path / "out"
    assert main([str(_proj(tmp_path)), "--discover", "-o", str(out)]) == 0
    assert "P/P.s7p" in (out / "kesif.md").read_text(encoding="utf-8")


def test_full_analysis_writes_reports(tmp_path):
    out = tmp_path / "out"
    assert main([str(_proj(tmp_path)), "-o", str(out)]) == 0
    for n in ("rapor.html", "rapor.md", "rapor.json"):
        assert (out / n).stat().st_size > 0


def test_refuses_output_inside_project(tmp_path):
    proj = _proj(tmp_path)
    with pytest.raises(SystemExit):
        main([str(proj), "-o", str(proj / "sub")])
    assert not (proj / "sub").exists()


def test_missing_source(tmp_path):
    with pytest.raises(SystemExit):
        main([str(tmp_path / "nope")])


def test_list_checks(capsys):
    assert main(["--list-checks"]) == 0
    assert "CONS_ES_SERVER" in capsys.readouterr().out


def test_demo(tmp_path):
    assert main(["--demo", str(tmp_path / "d")]) == 0
    assert (tmp_path / "d" / "rapor" / "rapor.html").exists()
