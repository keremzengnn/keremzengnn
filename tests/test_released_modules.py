from pcs7_analyzer.released_modules import MatchStatus, ReleasedModules, normalize_mlfb


def _load(tmp_path):
    p = tmp_path / "rm.csv"
    p.write_text("mlfb,fw,status,note\n"
                 "6ES7 414-5HM06-0AB0,V6.0,released,\n"
                 "6ES7 321-1BH01-0AA0,,discontinued 10/2004,hala listede\n", encoding="utf-8")
    return ReleasedModules.load(p)


def test_normalize():
    assert normalize_mlfb(" 6es7 414-5HM06-0AB0 ") == "6ES7414-5HM06-0AB0"


def test_match(tmp_path):
    rm = _load(tmp_path)
    assert rm.match("6ES7414-5HM06-0AB0", "V6.0").status is MatchStatus.LISTED
    assert rm.match("6ES7 414-5HM06-0AB0", "V6.1").status is MatchStatus.LISTED_FW_DIFFERS
    assert rm.match("6ES7 321-1BH01-0AA0", "V1.0").status is MatchStatus.LISTED   # FW listede yok -> kontrol edilemez


def test_not_listed_is_never_compatible(tmp_path):
    """H-Sync modülü (960-1AA06) gibi aksesuarlar listede yok -> 'bulunamadı', 'uyumlu' değil."""
    r = _load(tmp_path).match("6ES7 960-1AA06-0XA0")
    assert r.status is MatchStatus.NOT_FOUND
    assert "bulunamadı" in r.status.value


def test_extract_rows_from_manual_text():
    from pcs7_analyzer.released_extract import extract_rows
    text = """CPU 414-5H  6ES7 414-5HM06-0AB0  V6.0  V6.0.3
SM 321 DI32  6ES7 321-1BH01-0AA0  discontinued 10/2004
Page 12
IM 153-2 6ES7153-2BA10-0XB0 V4.0"""
    rows = extract_rows(text)
    assert ("6ES7 414-5HM06-0AB0", "V6.0") in {(r["mlfb"], r["fw"]) for r in rows}
    assert ("6ES7 414-5HM06-0AB0", "V6.0.3") in {(r["mlfb"], r["fw"]) for r in rows}
    assert next(r for r in rows if r["mlfb"].startswith("6ES7 321"))["status"] == "discontinued 10/2004"
    assert any(r["mlfb"] == "6ES7153-2BA10-0XB0" for r in rows)
    assert not any("960-1AA06" in r["mlfb"] for r in rows)
