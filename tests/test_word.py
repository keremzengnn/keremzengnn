"""Word çıktısı: gerçek template repoda yok; aynı yapıda minimal sahte bir .dotx ile test edilir."""
import zipfile
import xml.dom.minidom

import pytest

from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.report import ReportMeta, build_document
from pcs7_analyzer.word import TemplateError, render_docx, split_body, style_ids

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _style(sid, name, typ="paragraph"):
    return f'<w:style w:type="{typ}" w:styleId="{sid}"><w:name w:val="{name}"/></w:style>'


def _p(style, text, extra=""):
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{extra}</w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'


SECT_MAIN = ('<w:sectPr><w:headerReference w:type="default" r:id="rId11"/><w:footerReference w:type="default" r:id="rId12"/>'
             '<w:pgSz w:w="11906" w:h="16838"/><w:titlePg/></w:sectPr>')


def make_template(path):
    styles = (f'<w:styles {W}>' + _style("Titel", "Title") + _style("TitleTopline", "Title Topline")
              + _style("TitleSubline", "Title Subline") + _style("Topline", "Topline") + _style("berschrift1", "heading 1")
              + _style("berschrift2", "heading 2") + _style("Listenabsatz", "List Paragraph") + _style("TableHead", "Table Head")
              + _style("TableText", "Table Text") + _style("Beschriftung", "caption") + _style("Fett", "Strong", "character")
              + _style("Siemens", "Siemens", "table") + "</w:styles>")
    body = ('<w:p/><w:p><w:r><w:drawing>cover<w:p><w:r><w:t>textbox</w:t></w:r></w:p></w:drawing></w:r></w:p>'
            + _p("TitleTopline", "Title Topline") + _p("Titel", "Title cover")
            + '<w:p><w:pPr><w:pStyle w:val="TitleSubline"/></w:pPr><w:r><w:t>Lorem</w:t></w:r><w:r><w:br w:type="page"/></w:r></w:p>'
            + _p("berschrift1", "Headline Lorem")
            + '<w:tbl><w:tblPr><w:tblStyle w:val="Siemens"/><w:tblW w:w="5000" w:type="pct"/><w:tblLook w:val="01E0"/></w:tblPr>'
              '<w:tr><w:tc><w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            + f'<w:p><w:pPr>{SECT_MAIN}</w:pPr></w:p>' + _p("TextonBack", "Back page")
            + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>')
    doc = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>'
    ct = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
          'wordprocessingml.template.main+xml"/></Types>')
    hdr = f'<w:hdr {W}><w:p><w:r><w:t>Author | Department | YYYY-MM-DD</w:t></w:r></w:p></w:hdr>'
    ftr = f'<w:ftr {W}><w:p><w:r><w:t>Restricted | © Siemens 20XX</w:t></w:r></w:p></w:ftr>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/header1.xml", hdr)
        z.writestr("word/footer1.xml", ftr)
    return path


@pytest.fixture(scope="module")
def docx(tmp_path_factory):
    root = tmp_path_factory.mktemp("w")
    bk = build_demo_project(root)
    an = analyze(bk, released_csv=root / "released_demo.csv")
    tpl = make_template(root / "t.dotx")
    out = render_docx(an, build_document(an, full=False), ReportMeta(author="Ad Soyad", department="DEP", date="2026-09-24"),
                      tpl, root / "r.docx")
    with zipfile.ZipFile(out) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_valid_xml_and_content_type(docx):
    for n, x in docx.items():
        xml.dom.minidom.parseString(x.encode("utf-8"))
    assert "document.main+xml" in docx["[Content_Types].xml"]
    assert "template.main+xml" not in docx["[Content_Types].xml"]


def test_cover_and_header_footer(docx):
    d = docx["word/document.xml"]
    assert "DEMO_MP  |  SIMATIC PCS 7" in d
    assert "Upgrade Ön" in d and "V8.1 → " in d and '<w:rStyle w:val="Fett"/></w:rPr><w:t xml:space="preserve">V10.0 SP2' in d
    assert "Proje backup&apos;ı" in d or "Proje backup'ı" in d
    assert "cover" in d and "textbox" in d                       # kapak görseli / textbox korunur
    assert "Ad Soyad | DEP | 2026-09-24" in docx["word/header1.xml"]
    assert "Restricted | © Siemens 2026" in docx["word/footer1.xml"]


def test_body_structure(docx):
    d = docx["word/document.xml"]
    assert "Headline Lorem" not in d and "Back page" not in d   # örnek içerik ve arka kapak atıldı
    body = d[d.index("<w:body>") + 8:d.rindex("</w:body>")]
    kids = split_body(body)
    assert kids[-1].startswith("<w:sectPr") and 'r:id="rId11"' in kids[-1]
    assert sum(1 for k in kids if k.startswith("<w:sectPr")) == 1
    order = ["ÖZET", "Sonuç: Proje upgrade edilebilir", "Tablo 1: Genel değerlendirme", "PROJE ENVANTERİ",
             "Tablo 2: AS envanteri", "Tablo 3: OS yapısı", "Tablo 4: Yazılım içeriği", "RİSKLER", "Zorluklar",
             "Tablo 5: Zorluklar ve etkileri", "Referans dokümanlar"]
    pos = [d.index(x) for x in order]
    assert pos == sorted(pos)
    assert "Teklif öncesi" not in d and "Ek A" not in d          # Word = müşteri raporu (PDF yapısı)
    assert d.count("<w:tbl>") == 6
    assert 'w:val="Topline"' in d and 'w:val="berschrift1"' in d and 'w:val="TableHead"' in d


def test_split_body_nested():
    kids = split_body('<w:p/><w:p><w:r><w:t>a</w:t></w:r><w:p>in</w:p></w:p><w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl><w:sectPr/>')
    assert len(kids) == 4


def test_style_ids():
    assert style_ids('<w:style w:type="paragraph" w:styleId="berschrift1"><w:name w:val="heading 1"/>'
                     '<w:aliases w:val="Headline 1"/></w:style>')["headline 1"] == "berschrift1"


def test_bad_template(tmp_path):
    p = tmp_path / "x.dotx"
    p.write_bytes(b"not a zip")
    with pytest.raises(TemplateError):
        render_docx(None, [], ReportMeta(), p, tmp_path / "o.docx")


def test_embedded_template_is_found_and_valid(tmp_path):
    from pcs7_analyzer.settings import find_template
    from pcs7_analyzer.word import DocxBuilder
    p = find_template()
    assert p is not None and p.name == "report_template.dotx"
    b = DocxBuilder(p)
    assert b.sid("title topline") and b.sid("table head") and b.sid("heading 1") and b.sid("list paragraph")
    assert "docProps/thumbnail.emf" not in b.files
