"""fmt_num / fmt_date: rapor metni Türkçe biçim (DECISIONS 'Sayı ve tarih biçimi')."""
from datetime import date, datetime

from pcs7_analyzer.fmt import fmt_date, fmt_month, fmt_num
from pcs7_analyzer.report import ReportMeta


def test_fmt_num_thousands_dot():
    assert fmt_num(0) == "0"
    assert fmt_num(999) == "999"
    assert fmt_num(1234) == "1.234"
    assert fmt_num(1234567) == "1.234.567"
    assert fmt_num(-12345) == "-12.345"
    assert fmt_num(2000.0) == "2.000"
    assert fmt_num("45678") == "45.678"


def test_fmt_num_leaves_non_integers_alone():
    assert fmt_num(30.5) == "30.5"          # ondalık: binlik değil
    assert fmt_num("V8.1") == "V8.1"
    assert fmt_num("6ES7 410-5HX08-0AB0") == "6ES7 410-5HX08-0AB0"
    assert fmt_num(None) == "-"


def test_fmt_date():
    assert fmt_date(date(2026, 10, 24)) == "24.10.2026"
    assert fmt_date(datetime(2026, 1, 2, 13, 5)) == "02.01.2026"
    assert fmt_date("2026-10-24") == "24.10.2026"
    assert fmt_date("") == ""
    assert fmt_date(None) == ""
    assert fmt_date("bilinmiyor") == "bilinmiyor"
    ts = datetime(2025, 3, 7, 12).timestamp()
    assert fmt_date(ts) == "07.03.2025"
    assert fmt_month(ts) == "03.2025"


def test_meta_date_stays_iso():
    d = ReportMeta().date
    assert d == date.today().isoformat()      # veri ISO, sadece görüntüde GG.AA.YYYY
    assert fmt_date(d) == f"{date.today():%d.%m.%Y}"


def test_markdown_header_uses_tr_date(tmp_path):
    from pcs7_analyzer.analyze import analyze
    from pcs7_analyzer.demo import build_demo_project
    from pcs7_analyzer.report import render_markdown
    root = build_demo_project(tmp_path / "demo")
    an = analyze(root)
    md = render_markdown(an, meta=ReportMeta(author="A", date="2026-10-24"))
    assert "A | 24.10.2026" in md
    assert "2026-10-24" not in md.splitlines()[2]
