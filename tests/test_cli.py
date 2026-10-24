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


def test_subcommands_compare_and_diag(tmp_path):
    from pcs7_analyzer.cli import main
    from pcs7_analyzer.demo import build_demo_project
    a = build_demo_project(tmp_path / "a")
    assert main(["compare", str(a), str(a), "-o", str(tmp_path / "cmp")]) == 0
    assert (tmp_path / "cmp" / "fark.md").exists() and (tmp_path / "cmp" / "fark.xlsx").exists()
    d = tmp_path / "diag" / "MSSQL" / "Log"
    d.mkdir(parents=True)
    (d / "ERRORLOG").write_text("2024-01-01 10:00:00.00 spid5s      Error: 823, Severity: 24, State: 2.\n", encoding="utf-8")
    assert main(["diag", str(tmp_path / "diag"), "-o", str(tmp_path / "dout")]) == 0
    assert "823" in (tmp_path / "dout" / "diag.md").read_text(encoding="utf-8")


def test_run_writes_findings_and_unknown(tmp_path):
    import json
    from pcs7_analyzer.cli import run
    from pcs7_analyzer.demo import build_demo_project
    out = tmp_path / "o"
    run(build_demo_project(tmp_path / "d"), out, log=lambda m: None)
    fj = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert all({"status", "guven", "assumption"} <= set(x) for x in fj if "severity" in x)
    assert (out / "unknown.log").read_text(encoding="utf-8").startswith("Analiz edilemeyenler:")
    assert (out / "blockmap_tanisi.txt").exists() and (out / "envanter.xlsx").exists()


def test_cli_prints_index_and_summary(tmp_path, capsys):
    from pcs7_analyzer.demo import build_demo_project
    out = tmp_path / "o"
    assert main([str(build_demo_project(tmp_path / "d")), "-o", str(out), "--no-inventory"]) == 0
    text = capsys.readouterr().out
    assert f"Özet sayfası: {out / 'index.html'}" in text
    assert "PCS 7 versiyonu:" in text and "Bulgular: BLOCKER" in text


def test_default_out_dir_unique(tmp_path):
    from pcs7_analyzer.cli import default_out_dir
    a = default_out_dir(tmp_path / "B.zip", tmp_path / "r")
    a.mkdir(parents=True)
    assert default_out_dir(tmp_path / "B.zip", tmp_path / "r") != a


def test_team_settings_read_first(tmp_path, monkeypatch):
    import json
    from pcs7_analyzer import settings
    team = tmp_path / "team" / "pcs7_analyzer_ayarlar.json"
    team.parent.mkdir()
    team.write_text(json.dumps({"department": "DI PA", "author": "Ekip", "template": "sablon.dotx"}), encoding="utf-8")
    monkeypatch.setenv("PCS7_ANALYZER_TEAM_SETTINGS", str(team))
    assert settings.load()["department"] == "DI PA"
    assert settings.load()["template"] == str((team.parent / "sablon.dotx").resolve())
    settings.save({"author": "Ali", "department": ""})     # boş kullanıcı değeri ekip değerini ezmez
    st = settings.load()
    assert st["author"] == "Ali" and st["department"] == "DI PA"
    assert json.loads(team.read_text(encoding="utf-8"))["author"] == "Ekip"   # ekip dosyasına yazılmaz
    assert "department" not in settings.load_user() or settings.load_user()["department"] == ""
