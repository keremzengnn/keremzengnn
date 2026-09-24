import json

import pytest

from pcs7_analyzer.cli import main


def test_discover_to_files(tmp_path):
    proj = tmp_path / "proj"
    (proj / "P").mkdir(parents=True)
    (proj / "P" / "P.s7p").write_bytes(b"")
    out = tmp_path / "out" / "r.md"
    js = tmp_path / "out" / "r.json"
    assert main([str(proj), "--discover", "--out", str(out), "--json", str(js)]) == 0
    assert "P/P.s7p" in out.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["projects"] == ["P/P.s7p"]


def test_refuses_output_inside_project(tmp_path):
    with pytest.raises(SystemExit):
        main([str(tmp_path), "--discover", "--out", str(tmp_path / "sub" / "r.md")])
    assert not (tmp_path / "sub").exists()


def test_missing_dir(tmp_path):
    with pytest.raises(SystemExit):
        main([str(tmp_path / "nope"), "--discover"])


def test_analysis_not_implemented_yet(tmp_path):
    assert main([str(tmp_path)]) == 2


def test_list_checks(capsys):
    assert main(["--list-checks"]) == 0
    assert "CONS_ES_SERVER" in capsys.readouterr().out
