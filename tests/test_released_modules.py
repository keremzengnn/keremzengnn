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


def test_fw_matches():
    from pcs7_analyzer.released_modules import fw_matches
    assert fw_matches("V6.0", "V6.x") and fw_matches("V8.2.3", "V8.2.x") and fw_matches("V2.0", "V2.0")
    assert not fw_matches("V5.3", "V6.x") and not fw_matches("V8.1.0", "V8.2.x")


def test_markdown_extract():
    from pcs7_analyzer.released_extract import extract_rows_markdown
    md = """### **21.6 H-CPU as of 12/11 (as of PCS 7 V8.0)**
|**Product name**|**Article no.**|**Brief**|**F**|**C**|
|CPU 414-5H PN/DP|6ES7 414-5HM06-0AB0<br>V6.x|S7 CPU|W<br>P|X||
|SM321|6ES7 321-1BH01-0AA0|DI|W|X|10/<br>04|
||6ES7652-0XX00-1XD2|chip card||
1) Orderable via article number 6ES7155-6BA01-0CN0
"""
    rows = {(r["mlfb"], r["fw"]): r for r in extract_rows_markdown(md)}
    assert rows[("6ES7 414-5HM06-0AB0", "V6.x")]["note"].startswith("21.6 H-CPU")
    assert rows[("6ES7 321-1BH01-0AA0", "")]["status"] == "discontinued 10/04"
    assert ("6ES7652-0XX00-1XD2", "") in rows and ("6ES7155-6BA01-0CN0", "") in rows
