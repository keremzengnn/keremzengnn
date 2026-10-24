"""docx_style: referans Word raporundan sadece yapı; metin / müşteri adı / sayı çıktıya sızmaz. Sentetik docx ile."""
import json
import zipfile

import pytest

from pcs7_analyzer import docx_style
from pcs7_analyzer.docx_style import extract_style, mask_text

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
EP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
SECRET = "GizliMusteriMetni_Zeta"


def _style(sid, name, extra=""):
    return f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>{extra}</w:style>'


def _p(style, text, ppr="", rpr=""):
    st = f'<w:pStyle w:val="{style}"/>' if style else ""
    return f'<w:p><w:pPr>{st}{ppr}</w:pPr><w:r>{f"<w:rPr>{rpr}</w:rPr>" if rpr else ""}<w:t>{text}</w:t></w:r></w:p>'


def _tc(text, tcpr=""):
    return f'<w:tc>{f"<w:tcPr>{tcpr}</w:tcPr>" if tcpr else ""}<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>'


def make_docx(path, broken=False):
    styles = (f'<w:styles {W}>' + _style("Titel", "Title") + _style("berschrift1", "heading 1")
              + _style("berschrift2", "heading 2") + _style("Kapitel", "Kapitel", '<w:pPr><w:outlineLvl w:val="2"/></w:pPr>')
              + _style("Beschriftung", "caption") + _style("Normal", "Normal") + "</w:styles>")
    table = ('<w:tbl><w:tblPr><w:tblStyle w:val="Siemens"/></w:tblPr><w:tblGrid><w:gridCol w:w="2000"/>'
             '<w:gridCol w:w="3000"/><w:gridCol w:w="4000"/></w:tblGrid>'
             '<w:tr><w:trPr><w:tblHeader/></w:trPr>' + _tc("ACME_PLANT 2024") + _tc("Station") + _tc("CPU FW", '<w:shd w:val="clear" w:fill="009999"/>') + '</w:tr>'
             '<w:tr><w:trPr><w:cantSplit/></w:trPr>' + _tc(f"{SECRET} 987654") + _tc("hücre bir iki") + _tc("x") + '</w:tr>'
             '</w:tbl>')
    body = (_p("Titel", "ACME_PLANT Upgrade 2024")
            + _p("berschrift1", "ÖZET")
            + _p("Normal", f"Gövde metni {SECRET} 135792468", rpr='<w:highlight w:val="yellow"/><w:color w:val="FF0000"/>')
            + _p("Normal", "Madde", ppr='<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
            + _p("berschrift2", "Tablo 1: Genel değerlendirme")
            + table
            + _p("Beschriftung", "Tablo 2: ACME_PLANT donanım")
            + '<w:p><w:r><w:br w:type="page"/></w:r><w:r><w:lastRenderedPageBreak/><w:t>sonra</w:t></w:r></w:p>'
            + _p("Kapitel", "Ekler")
            + _p("Normal", "Direkt başlık", ppr='<w:outlineLvl w:val="0"/>')
            + '<w:sectPr/>')
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>'
    if broken:
        doc = doc.replace("</w:body>", "")
    hdr = f'<w:hdr {W}><w:p><w:r><w:t>Ad Soyad | Departman | 2025-01-01</w:t></w:r></w:p></w:hdr>'
    app = f'<Properties xmlns="{EP}"><Pages>7</Pages><Company>ACME Corp</Company></Properties>'
    core = '<cp:coreProperties xmlns:cp="x"><dc:creator xmlns:dc="y">Gizli Yazar</dc:creator></cp:coreProperties>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/header1.xml", hdr)
        z.writestr("docProps/app.xml", app)
        z.writestr("docProps/core.xml", core)
    return path


@pytest.fixture
def small(tmp_path):
    return extract_style(make_docx(tmp_path / "ref.docx"))


def test_outline(small):
    o = [(h["level"], h["style"], h["text_masked"]) for h in small["outline"]]
    assert o == [(0, "Titel", "X Upgrade #"), (1, "berschrift1", "ÖZET"), (2, "berschrift2", "Tablo #: Genel değerlendirme"),
                 (3, "Kapitel", "Ekler"), (1, "Normal", "Direkt başlık")]
    assert small["schema_version"] == "1"


def test_tables(small):
    assert len(small["tables"]) == 1
    t = small["tables"][0]
    assert (t["n_rows"], t["n_cols"], t["style"], t["col_widths"]) == (2, 3, "Siemens", [2000, 3000, 4000])
    assert t["header"] == ["X #", "Station", "CPU FW"]
    assert t["rows_repeat_header"] and t["cant_split"]
    assert t["caption_masked"] == "Tablo #: X donanım"
    assert t["max_words_per_cell"] == 3


def test_no_leak(small):
    s = json.dumps(small, ensure_ascii=False)
    for bad in (SECRET, "ACME", "2024", "987654", "135792468", "Gizli", "Ad Soyad", "2025", "Gövde", "hücre", "Corp"):
        assert bad not in s, bad


def test_highlight_formatting_sections(small):
    assert small["highlight"]["run_highlight"] == {"yellow": 1}
    assert small["highlight"]["cell_shading"] == {"009999": 1}
    assert small["direct_formatting"]["color"] == 1
    sec = small["sections"]
    assert (sec["explicit_page_breaks"], sec["last_rendered_page_breaks"], sec["section_breaks"], sec["app_pages"]) == (1, 1, 1, 7)
    assert small["stats"]["list_paragraphs"] == 1 and small["stats"]["table_paragraphs"] == 6
    assert small["header_footer"] == [{"part": "word/header1.xml", "kind": "header", "paragraphs": 1, "words": 4}]
    assert small["paragraph_styles"]["Normal"] == 3


def test_mask_rule():
    assert mask_text("PROJE ENVANTERİ") == "PROJE ENVANTERİ"
    assert mask_text("SIMATIC PCS 7 V8.1 DEMO_MP") == "SIMATIC PCS # # X"
    assert mask_text("AS-Envanteri OS_SRV1 (ACME).") == "AS-Envanteri # (X)."


def test_errors_and_missing(tmp_path):
    with pytest.raises(ValueError, match="bozuk"):
        extract_style(make_docx(tmp_path / "b.docx", broken=True))
    (tmp_path / "n.docx").write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="açılamadı"):
        extract_style(tmp_path / "n.docx")
    with zipfile.ZipFile(tmp_path / "e.dotx", "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    r = extract_style(tmp_path / "e.dotx")
    assert r["outline"] == [] and r["tables"] == [] and r["header_footer"] == []


def test_cli(tmp_path, capsys):
    out = tmp_path / "o" / "s.json"
    out.parent.mkdir()
    assert docx_style.main([str(make_docx(tmp_path / "ref.docx")), "-o", str(out)]) == 0
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["schema_version"] == "1" and len(d["tables"]) == 1
    assert docx_style.main([str(tmp_path / "yok.docx"), "-o", str(out)]) == 2


def test_demo_report(tmp_path):
    from pcs7_analyzer.analyze import analyze
    from pcs7_analyzer.demo import build_demo_project
    from pcs7_analyzer.report import ReportMeta, build_document
    from pcs7_analyzer.word import render_docx
    from tests.test_word import make_template

    bk = build_demo_project(tmp_path)
    an = analyze(bk, released_csv=tmp_path / "released_demo.csv")
    out = render_docx(an, build_document(an, full=False), ReportMeta(author="Ad Soyad", department="DEP", date="2026-09-24"),
                      make_template(tmp_path / "t.dotx"), tmp_path / "r.docx")
    r = extract_style(out)
    assert r["outline"][0]["level"] == 0 and r["outline"][0]["style"] == "Titel"
    texts = [h["text_masked"] for h in r["outline"] if h["level"] == 1]
    assert texts == ["Sonuç: Proje upgrade edilebilir, zorluklar var", "Proje bilgileri", "Zorluklar", "Referans dokümanlar"]
    assert r["paragraph_styles"]["Topline"] == 3                     # ÖZET / PROJE ENVANTERİ / RİSKLER etiketleri
    assert len(r["tables"]) == 7 and all(t["n_cols"] >= 2 for t in r["tables"])
    assert all(t["rows_repeat_header"] for t in r["tables"])
    assert any((t["caption_masked"] or "").startswith("Tablo #") for t in r["tables"])
    s = json.dumps(r, ensure_ascii=False)
    assert "DEMO_MP" not in s and "Ad Soyad" not in s
