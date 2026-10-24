import re
import zipfile

import pytest

from pcs7_analyzer.analyze import ManualInputs, analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.excel_report import SHEETS, write_excel


@pytest.fixture(scope="module")
def xl(tmp_path_factory):
    root = tmp_path_factory.mktemp("x")
    an = analyze(build_demo_project(root),
                 manual=ManualInputs(per_mp={"DEMO_MP": {"as_rt_po": "250", "os_po": "230", "archive_tags": "50"}}))
    p = write_excel(an, root / "rapor.xlsx")
    with zipfile.ZipFile(p) as z:
        return an, {n: z.read(n).decode("utf-8") for n in z.namelist()}


def _sheet(files, name):
    idx = SHEETS.index(name) + 1
    return files[f"xl/worksheets/sheet{idx}.xml"]


def test_eight_sheets_in_order(xl):
    _, f = xl
    assert re.findall(r'<sheet name="([^"]+)"', f["xl/workbook.xml"]) == SHEETS


def test_styles_petrol_arial_numfmt(xl):
    _, f = xl
    st = f["xl/styles.xml"]
    assert 'rgb="FF009999"' in st and 'val="Arial"' in st and 'numFmtId="3"' in st


def test_summary_formulas(xl):
    _, f = xl
    s = _sheet(f, "Ozet")
    assert "COUNTIFS(ENG_SRV1_Farklar!$A$2" in s and '"Alarm metni"' in s
    assert re.search(r"<f>SUM\(B\d+:B\d+\)</f>", s)                 # lisans toplamı
    assert ">250<" in s and ">230<" in s                            # MP bazında manuel PO
    assert "pane" in s                                              # freeze


def test_hw_colors_and_columns(xl):
    _, f = xl
    s = _sheet(f, "HW_Moduller")
    assert "Listedeki FW" in s and "FW uyumu" in s and "Discontinued" in s
    red = re.search(r'<row r="\d+"><c r="A\d+" s="3" t="inlineStr"><is><t xml:space="preserve">6ES7 960-1AA06', s)
    yellow = re.search(r'<c r="A\d+" s="4" t="inlineStr"><is><t xml:space="preserve">Festo CPX', s)
    assert red and yellow
    assert "autoFilter" in s


def test_diff_sheet_single_list_with_category(xl):
    an, f = xl
    s = _sheet(f, "ENG_SRV1_Farklar")
    for cat in ("Picture / script", "Connection", "Tag", "Alarm", "Alarm metni"):
        assert f">{cat}<" in s
    assert "Tank XX level high | Tank 3 level high" in s


def test_os_wincc_sections(xl):
    _, f = xl
    s = _sheet(f, "OS_WinCC")
    for x in ("A) OS projeleri", "B) Connection ve tag sayıları", "C) Alarm class / area", "D) SFC / Logic Matrix",
              "SUMIF(", "Emerson DeltaV", "kurulu, kullanılmıyor", "6 chart"):
        assert x in s, x


def test_open_items_sheet(xl):
    _, f = xl
    s = _sheet(f, "Acik_Konular_Kaynak")
    assert "Müşteri sorusu" in s and "Manuel giriş" in s and "A5E52547272-AD" in s


# ---------------- R6: durum renkleri, boş sayfa yok, header, formül referansları ----------------

def _rows(sheet_xml):
    """[(satır no, {kolon: (stil, metin)})]"""
    out = []
    for rn, body in re.findall(r'<row r="(\d+)">(.*?)</row>', sheet_xml):
        cells = {}
        for col, st, txt in re.findall(r'<c r="([A-Z]+)\d+"(?: s="(\d+)")?[^>]*?(?:/>|>(?:<is><t[^>]*>(.*?)</t></is>)?)',
                                       body):
            cells[col] = (int(st or 0), txt)
        out.append((int(rn), cells))
    return out


def test_new_styles_appended_indices_stable():
    from pcs7_analyzer.xlsx import STYLES, Workbook
    assert [STYLES[k] for k in ("", "header", "num", "red", "yellow", "green", "bold", "section", "wrap",
                                "red_num", "yellow_num", "bold_num")] == list(range(12))
    assert STYLES["orange"] == 12 and STYLES["gray"] == 13
    st = Workbook()._styles_xml()
    assert '<cellXfs count="14">' in st and 'rgb="FFFCE4D6"' in st and 'rgb="FF808080"' in st
    xfs = re.findall(r"<xf [^>]*fontId=\"(\d+)\" fillId=\"(\d+)\"", st.split("<cellXfs")[1])
    assert xfs[12] == ("3", "7") and xfs[13] == ("4", "0")


def test_findings_status_colors(xl):
    from pcs7_analyzer.excel_report import STATUS_STYLE
    from pcs7_analyzer.readiness import FINDINGS_COLUMNS
    from pcs7_analyzer.xlsx import STYLES, col_letter
    _, f = xl
    rows = _rows(_sheet(f, "Bulgular"))
    c_st, c_conf, c_det = (col_letter(FINDINGS_COLUMNS.index(c)) for c in ("Durum", "Güven", "Detay"))
    seen = set()
    for rn, cells in rows[1:]:
        status = cells[c_st][1]
        seen.add(status)
        assert cells[c_st][0] == STYLES[STATUS_STYLE.get(status, "")], (rn, status)
        if cells[c_conf][1] == "ÇIKARIM":
            assert cells[c_conf][0] == STYLES["yellow"] and cells[c_det][0] == STYLES["yellow"]
        elif status in ("BİLGİ",) and cells[c_conf][1] == "KANIT":
            assert cells[c_conf][0] == 0 and cells[c_det][0] == 0
    assert "RİSK" in seen


def test_header_petrol_white_bold(xl):
    _, f = xl
    st = f["xl/styles.xml"]
    assert re.search(r'<font><b/><sz val="10"/><color rgb="FFFFFFFF"/>', st)
    assert 'fgColor rgb="FF009999"' in st
    xf1 = re.findall(r"<xf [^>]*>", st.split("<cellXfs")[1])[1]
    assert 'fontId="1"' in xf1 and 'fillId="2"' in xf1
    assert re.search(r'<c r="A1" s="1"', _sheet(f, "Bulgular"))


def test_inventory_header_color_unchanged():
    from pcs7_analyzer.xlsx import Workbook
    assert Workbook().header_color == "000028"


def _check_no_empty_and_formulas(files):
    names = re.findall(r'<sheet name="([^"]+)"', files["xl/workbook.xml"])
    for i, name in enumerate(names, 1):
        s = files[f"xl/worksheets/sheet{i}.xml"]
        assert len(re.findall(r"<row ", s)) >= 2, f"{name}: sadece başlık"
        for formula in re.findall(r"<f>(.*?)</f>", s):
            for ref in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)!", formula):
                assert ref in names, (name, formula)
        assert not re.search(r"<v>#(REF|NAME|VALUE|DIV/0)", s)


def test_no_empty_sheets_and_formula_refs_demo(xl):
    _, f = xl
    _check_no_empty_and_formulas(f)


def test_no_empty_sheets_empty_backup(tmp_path):
    src = tmp_path / "bos"
    src.mkdir()
    (src / "readme.txt").write_text("x")
    an = analyze(src)
    p = write_excel(an, tmp_path / "rapor.xlsx")
    with zipfile.ZipFile(p) as z:
        files = {n: z.read(n).decode("utf-8") for n in z.namelist()}
    _check_no_empty_and_formulas(files)
    assert "Veri yok: backup'ta WinCC" in _sheet(files, "OS_WinCC")
    s = _sheet(files, "AS_Envanter")
    assert "Veri yok:" in s and "SUM(I2:I1)" not in s


def test_no_data_helper():
    from pcs7_analyzer.excel_report import _no_data
    r = _no_data([["A", "B"]], "neden")
    assert len(r) == 2 and r[1][0].v == "Veri yok: neden" and r[1][0].style == "gray"
    assert len(_no_data([["A"], ["x"]], "neden")) == 2
    r = _no_data([["S"], ["A"]], "neden", header_index=1)
    assert r[-1][0].v == "Veri yok: neden"
