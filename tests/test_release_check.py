import json

from pcs7_analyzer import cli, release_check


def test_missing_expected_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release_check, "EXPECTED", tmp_path / "yok.json")
    assert cli.main(["release-check", str(tmp_path)]) == 2
    assert "Beklenen değer dosyası yok" in capsys.readouterr().out


def test_pass_and_fail_exit_code(tmp_path, capsys):
    exp = tmp_path / "e.json"
    exp.write_text(json.dumps({"block_folders": [{"id": "A", "path": "yok/yol", "counts": {"FB": 1}}]}), encoding="utf-8")
    assert cli.main(["release-check", str(tmp_path), "--expected", str(exp)]) == 1
    assert "KALDI" in capsys.readouterr().out


def test_run_checks_empty(tmp_path):
    assert release_check.run_checks(tmp_path, {}) == []
