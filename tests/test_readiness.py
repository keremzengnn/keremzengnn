"""Backup yeterlilik, teklif girdileri, güven etiketleri ve DIAGNOSTICS entegrasyonu (demo projesiyle)."""
import zipfile

from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.collect import collect
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.excel_report import SHEETS, write_excel
from pcs7_analyzer.readiness import backup_coverage, findings_rows, quote_inputs
from pcs7_analyzer.report import build_document, render_html

ERRORLOG = ("2024-03-01 10:00:00.11 Server      Microsoft SQL Server 2014 (SP3) - 12.0.6024.0 (Intel X86)\r\n"
            "2024-03-01 10:00:00.12 Server      Registry startup parameters: \r\n"
            "\t -g512\r\n"
            "2024-03-01 11:00:00.00 spid51      Error: 823, Severity: 24, State: 2.\r\n"
            "2024-03-01 11:00:00.00 spid51      The operating system returned error 21 to SQL Server.\r\n")


def test_coverage_and_inputs(tmp_path):
    an = analyze(build_demo_project(tmp_path))
    cov = {r[0]: r for r in backup_coverage(an)}
    assert cov["Multiproject / proje (.s7f / .s7p)"][1] == "Var"
    assert cov["HW Config export (.cfg)"][1] == "Var"
    assert cov["Lisans (PO, archive tag, ALM key)"][1] == "VERİ YOK"
    assert cov["DIAGNOSTICS (SQL ERRORLOG, evtx, WinCC diagnose)"][1] == "Yok"
    q = {r[0]: r[1] for r in quote_inputs(an)}
    assert q["AS (HW station)"].startswith("2 station") and "AS02" in q["F-System"]
    rows = findings_rows(an)
    assert {r[4] for r in rows if r[2] != "VERİ YOK"} <= {"KANIT", "ÇIKARIM"}
    assert all(r[0].startswith("F-") and r[6] != "-" for r in rows if r[2] in ("BLOCKER", "RİSK"))
    md = render_html(an, build_document(an))
    assert "Backup içeriği ve yeterlilik" in md and "Teklif için girdiler" in md and "Ek C: Bulgular" in md
    assert "Diagnostics (server fail)" not in md
    assert not any(f.check_id == "PROJ_MIN_VERSION" for f in an.findings)           # V8.1 >= V7.1 SP4
    assert any(f.check_id == "LIB_F_SYSTEM" and "şart sağlanıyor" in f.detail for f in an.findings)


def test_diagnostics_integration(tmp_path):
    bk = build_demo_project(tmp_path / "d")
    log = bk / "DIAGNOSTICS" / "MSSQL" / "Log"
    log.mkdir(parents=True)
    (log / "ERRORLOG").write_bytes(b"\xff\xfe" + ERRORLOG.encode("utf-16-le"))
    (bk / "DIAGNOSTICS" / "Application.evtx").write_bytes(b"ElfFile\x00" + b"\x00" * 100)
    an = analyze(bk)
    assert an.diag is not None and an.diag.sql["bits"] == "32"
    assert any("823" in f.detail for f in an.diag.findings)
    html = render_html(an, build_document(an))
    assert "Diagnostics (server fail)" in html and "-g512" in html
    xl = tmp_path / "r.xlsx"
    write_excel(an, xl)
    with zipfile.ZipFile(xl) as z:
        wb = z.read("xl/workbook.xml").decode()
    assert all(f'name="{s}"' in wb for s in SHEETS) and 'name="Diagnostics"' in wb
    pkg = tmp_path / "p.zip"
    collect(bk, pkg, log=lambda m: None)
    with zipfile.ZipFile(pkg) as z:
        assert "DIAGNOSTICS/MSSQL/Log/ERRORLOG" in z.namelist()
    assert analyze(pkg).diag.sql["bits"] == "32"


def test_comm_std_and_min_version(tmp_path):
    from pcs7_analyzer.checks import CHECKS, NotChecked
    an = analyze(build_demo_project(tmp_path))
    comm = [f for f in an.findings if f.check_id == "COMM_STD"]
    assert comm and "SEND_R" in comm[0].detail and "VERİ YOK" in comm[0].detail
    chk = next(c for c in CHECKS if c.id == "PROJ_MIN_VERSION")
    an.pcs7_family = "V7.0"
    assert chk.func(chk, an)[0].blocking
    an.pcs7_family = None
    try:
        chk.func(chk, an)
        raise AssertionError("NotChecked bekleniyordu")
    except NotChecked:
        pass
