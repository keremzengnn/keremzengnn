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
