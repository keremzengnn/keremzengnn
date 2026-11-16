import json
import zipfile

from pcs7_analyzer import cli, support_bundle


def _out(tmp_path):
    out = tmp_path / "rapor"
    out.mkdir()
    (out / "log.txt").write_text(r"Okunuyor C:\Musteri\Fabrika_X\Proje1\ombstx\offline\0000000A\SUBBLK.DBF hata" + "\n"
                                 "yol /home/kerem/Musteri_Y/proje/x.s7p\n", encoding="utf-8")
    (out / "findings.json").write_text(json.dumps([]), encoding="utf-8")
    for n in ("rapor.docx", "rapor.xlsx", "rapor.html", "rapor.md", "SUBBLK.DBF", "musteri.s7p"):
        (out / n).write_bytes(b"gizli")
    return out


def test_allowlist_only_and_masked(tmp_path):
    out = _out(tmp_path)
    z, listed = support_bundle.build(out, tmp_path / "d.zip")
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
        text = zf.read("log.txt").decode("utf-8")
    assert "log.txt" in names and "findings.json" not in names
    assert not {n for n in names if n.lower().endswith(support_bundle.FORBIDDEN_SUFFIXES)}
    assert names <= set(support_bundle.ALLOWED) | {"_destek_paketi.txt"}
    for secret in ("Fabrika_X", "Musteri", "kerem", "Musteri_Y"):
        assert secret not in text
    assert "SUBBLK.DBF" in text
    assert [n for n, _ in listed] == ["log.txt"]


def test_traceback_source_paths_kept_customer_masked(tmp_path):
    out = tmp_path / "rapor"
    out.mkdir()
    (out / "log.txt").write_text(
        'Traceback (most recent call last):\n'
        '  File "C:\\Users\\kerem\\app\\pcs7_analyzer\\cli.py", line 123, in run\n'
        '    x()\n'
        '  File "/opt/musteriZ/pcs7_analyzer/parsers/subblk.py", line 45, in parse\n'
        'OSError: C:\\Musteri\\Fabrika_X\\Proje1\\ombstx\\offline\\0000000A\\SUBBLK.DBF\n', encoding="utf-8")
    z, _ = support_bundle.build(out, tmp_path / "d.zip")
    with zipfile.ZipFile(z) as zf:
        text = zf.read("log.txt").decode("utf-8")
    assert 'File "pcs7_analyzer/cli.py", line 123' in text
    assert 'File "pcs7_analyzer/parsers/subblk.py", line 45' in text
    for secret in ("kerem", "musteriZ", "Fabrika_X", "Musteri"):
        assert secret not in text


def test_report_files_excluded_from_bundle(tmp_path):
    out = tmp_path / "cikti"
    cli.main(["--demo", str(tmp_path / "d2"), "-o", str(out)])
    assert (out / "findings.json").is_file() and (out / "report_ir.json").is_file()
    z, _ = support_bundle.build(out, tmp_path / "p.zip")
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
        note = zf.read("_destek_paketi.txt").decode("utf-8")
    assert "findings.json" not in names and "report_ir.json" not in names
    assert "garantisi yoktur" in note


def test_cli_support_bundle(tmp_path, capsys):
    out = _out(tmp_path)
    dest = tmp_path / "x.zip"
    assert cli.main(["--support-bundle", str(out), "-o", str(dest)]) == 0
    assert dest.is_file()
    assert "Göndermeden önce içeriği kontrol edin" in capsys.readouterr().out


def test_cli_unexpected_error_no_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_main", lambda argv=None: 1 / 0)
    monkeypatch.setattr("pcs7_analyzer.settings.settings_path", lambda: tmp_path / "s.json")
    assert cli.main([]) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and "Beklenmeyen hata" in err
    assert "ZeroDivisionError" in (tmp_path / "log.txt").read_text(encoding="utf-8")


def test_cli_bad_zip(tmp_path, capsys):
    z = tmp_path / "bozuk.zip"
    z.write_bytes(b"bu zip degil")
    try:
        rc = cli.main([str(z), "-o", str(tmp_path / "o")])
    except SystemExit as e:
        rc = e.code
    assert rc != 0
    assert "Zip dosyası bozuk" in capsys.readouterr().err
