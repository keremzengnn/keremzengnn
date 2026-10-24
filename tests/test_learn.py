"""learn (R7): üretilen vs düzenlenmiş rapor.docx yapısal fark + öneriler; müşteri metni çıktıya sızmaz."""
import json
import zipfile

import pytest

from pcs7_analyzer import learn

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SECRET = "GizliMusteriMetni_Omega"
LONG = " ".join(f"kelime{i}" for i in range(40))


def _p(style, text, rpr=""):
    st = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{st}<w:r>{f"<w:rPr>{rpr}</w:rPr>" if rpr else ""}<w:t>{text}</w:t></w:r></w:p>'


def _tc(text):
    return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"


def _tbl(header, rows, style="Siemens"):
    trs = "<w:tr>" + "".join(_tc(h) for h in header) + "</w:tr>"
    trs += "".join("<w:tr>" + "".join(_tc(c) for c in r) + "</w:tr>" for r in rows)
    return f'<w:tbl><w:tblPr><w:tblStyle w:val="{style}"/></w:tblPr>{trs}</w:tbl>'


def _write(path, body):
    styles = (f'<w:styles {W}>'
              '<w:style w:type="paragraph" w:styleId="berschrift1"><w:name w:val="heading 1"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="berschrift2"><w:name w:val="heading 2"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>')
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}<w:sectPr/></w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
    return path


HDR = ["Station", "CPU", "Aksiyon"]
ROWS = [[f"{SECRET} AS{i}", "CPU 410-5H", f"firewall kontrol {LONG[:30]}"] for i in range(4)]


def make_generated(path):
    body = (_p("berschrift1", "ÖZET")
            + _p("Normal", f"{SECRET} {LONG}", rpr='<w:highlight w:val="yellow"/>')
            + _p("Normal", "firewall ve compile gerekli. firewall ayarı.", rpr='<w:highlight w:val="yellow"/>')
            + _p("berschrift1", "PROJE ENVANTERİ")
            + _tbl(HDR, ROWS)
            + _p("berschrift2", "Detay ACME_PLANT")
            + _p("Normal", f"Detay metni {SECRET}")
            + _p("berschrift1", "RİSKLER")
            + _p("Normal", "risk metni bir iki üç"))
    return _write(path, body)


def make_edited(path):
    rows = [[r[0], r[1]] for r in ROWS[:2]]
    body = (_p("berschrift1", "ÖZET")
            + _p("Normal", f"{SECRET} kısa özet")
            + _p("Normal", "güvenlik duvarı ve compile gerekli. güvenlik duvarı ayarı.")
            + _p("berschrift1", "PROJE ENVANTERİ")
            + _tbl(HDR[:2], rows)
            + _p("berschrift1", "RİSKLER")
            + _p("Normal", "risk metni bir iki üç"))
    return _write(path, body)


@pytest.fixture
def diff(tmp_path):
    return learn.compare(make_generated(tmp_path / "g.docx"), make_edited(tmp_path / "e.docx"))


def test_removed_section(diff):
    assert [s["heading"] for s in diff["sections"]["removed"]] == ["Detay X"]
    assert diff["sections"]["added"] == [] and diff["sections"]["renamed"] == []


def test_removed_column_and_rows(diff):
    t = diff["tables"]["matched"]
    assert len(t) == 1 and t[0]["table"] == 1
    assert t[0]["removed_columns"] == ["Aksiyon"] and t[0]["added_columns"] == []
    assert t[0]["n_rows"] == {"generated": 5, "edited": 3, "delta": -2}
    assert t[0]["avg_words_per_cell"]["delta"] < 0
    assert t[0]["section"] == "PROJE ENVANTERİ"


def test_shortened_paragraphs(diff):
    sh = {s["heading"]: s["words"] for s in diff["sections"]["shortened"]}
    assert list(sh) == ["ÖZET"]
    assert sh["ÖZET"]["generated"] == 47 and sh["ÖZET"]["edited"] == 11


def test_terms_highlight_styles(diff):
    terms = diff["terms"]
    assert terms["english_disappeared"] == ["firewall"]
    assert terms["turkish_appeared"] == ["güvenlik duvarı"]
    assert terms["replaced"] == [{"english": "firewall", "turkish": "güvenlik duvarı",
                                  "english_delta": -6, "turkish_delta": 2}]
    assert diff["highlight"]["run_highlight"] == {"yellow": {"generated": 2, "edited": 0, "delta": -2}}
    assert diff["styles"]["berschrift2"]["delta"] == -1


def test_suggestions(diff):
    s = learn.suggestions(diff)
    assert "'Detay X' bölümünü kaldır (seviye 2, 3 kelime)" in s
    assert "Tablo 1 'Aksiyon' sütununu çıkar" in s
    assert any(x.startswith("'ÖZET' bölüm metnini kısalt") for x in s)
    assert any("'firewall' yerine 'güvenlik duvarı'" in x for x in s)
    assert s == learn.suggestions(diff)


def test_no_leak_and_deterministic(tmp_path, capsys):
    g, e = make_generated(tmp_path / "g.docx"), make_edited(tmp_path / "e.docx")
    out = tmp_path / "out"
    assert learn.main(["--generated", str(g), "--edited", str(e), "-o", str(out)]) == 0
    printed = capsys.readouterr().out
    p = out / "style_suggestions.json"
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["applied"] is False and "onaylamalı" in data["_header"] and "onaylamalı" in printed
    for bad in (SECRET, "ACME", "kelime1", "410", "kısa özet", "risk metni", "g.docx", str(tmp_path)):
        assert bad not in raw, bad
        assert bad not in printed.replace(str(p), ""), bad
    assert learn.main(["--generated", str(g), "--edited", str(e), "-o", str(out)]) == 0
    assert p.read_text(encoding="utf-8") == raw


def test_identical_and_errors(tmp_path):
    g = make_generated(tmp_path / "g.docx")
    d = learn.compare(g, g)
    assert learn.suggestions(d) == []
    assert d["tables"]["matched"][0]["changed"] is False
    (tmp_path / "bad.docx").write_bytes(b"no zip")
    assert learn.main(["--generated", str(g), "--edited", str(tmp_path / "bad.docx"), "-o", str(tmp_path)]) == 2
