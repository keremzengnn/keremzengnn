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
    red = re.search(r'<c r="B\d+" s="3" t="inlineStr"><is><t xml:space="preserve">6ES7 960-1AA06', s)
    yellow = re.search(r'<c r="B\d+" s="4" t="inlineStr"><is><t xml:space="preserve">Festo CPX', s)
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


# ---------------- sıkı Excel: station bazında HW, sadece custom block, instance özeti, tekrar yok ----------------

def _table(sheet_xml):
    """[[metin / sayı, ...]] (formül önbellek değeri dahil)"""
    out = []
    for body in re.findall(r'<row r="\d+">(.*?)</row>', sheet_xml):
        row = {}
        for col, inner in re.findall(r'<c r="([A-Z]+)\d+"[^>]*?(?:/>|>(.*?)</c>)', body):
            m = re.search(r"<t[^>]*>(.*?)</t>", inner) or re.search(r"<v>(.*?)</v>", inner)
            row[col] = m.group(1) if m else ""
        out.append([row.get(c, "") for c in "ABCDEFGHIJKLMNO"])
    return out


def test_hw_one_row_per_station_mlfb_fw(xl):
    an, f = xl
    t = _table(_sheet(f, "HW_Moduller"))
    assert t[0][:5] == ["AS", "MLFB / GSD", "Model / açıklama", "FW (proje)", "Adet"]
    keys = [(r[0], r[1], r[3]) for r in t[1:]]
    assert len(keys) == len(set(keys))                                      # station + MLFB + FW tekil
    exp = {(st.name, o, fw): n for st in an.stations for (o, fw), n in st.inventory.items()}
    got = {(r[0], r[1], r[3]): int(r[4]) for r in t[1:] if r[9] == "modül"}
    assert got == exp                                                       # adet station bazında
    assert sum(got.values()) == sum(m.count for m in an.hw_matches if m.kind == "modül")
    stations = [r[0] for r in t[1:]]
    assert stations == sorted(stations)                                     # station'a göre gruplu
    assert ("AS01", "Festo CPX (CPX_059E.GSE)") in {(r[0], r[1]) for r in t[1:]}


def test_custom_blocks_only_custom(xl):
    an, f = xl
    t = _table(_sheet(f, "Custom_Blocklar"))
    blocks = {r[1] for r in t[1:]}
    assert {"FB1990", "FB1993", "FB2501"} <= blocks
    std = {f"FB{nr}" for b in an.block_folders for nr, (_, lib, _) in b.fb_library.items()
           if lib not in ("custom", "custom/unknown")}
    assert not (blocks & std), blocks & std                                 # library block'u yok
    assert all(r[0] in {b.as_label for b in an.as_folders} for r in t[1:])  # library projeleri hariç


def test_instance_summary(xl):
    an, f = xl
    t = _table(_sheet(f, "Instance_Sayilari"))
    assert t[0][:6] == ["AS", "Library", "Author", "Versiyon (author)", "FB tipi", "Instance"]
    total = sum(n for b in an.as_folders for n in b.fb_instances.values())
    assert sum(int(r[5]) for r in t[1:]) == total                           # özet kaybı yok
    n_fb = sum(len(b.fb_instances) for b in an.as_folders)
    assert len(t) - 1 < n_fb                                                # FB başına satır değil
    apl = next(r for r in t[1:] if r[0] == "AS01" and r[2] == "AdvLib81")
    assert apl[1] == "APL" and apl[3] == "V8.1" and "Pcs7DiIn ×6" in apl[6]


def test_summary_findings_counts_no_detail(xl):
    from pcs7_analyzer.readiness import findings_rows
    an, f = xl
    s = _sheet(f, "Ozet")
    assert re.search(r'<f>COUNTIF\(Bulgular!\$C\$2:\$C\$\d+,"RİSK"\)</f>', s)
    t = _table(s)
    risk = next(r for r in t if r[0] == "RİSK")
    assert int(risk[1]) == sum(1 for r in findings_rows(an) if r[2] == "RİSK")
    flat = " ".join(" ".join(r) for r in t)
    assert "F-001" in flat                                                  # Yüksek bulgu ID ile
    assert an.findings[0].detail[:40] not in flat                           # detay Bulgular'da, tekrar yok


def test_open_items_no_duplicates(xl):
    _, f = xl
    t = _table(_sheet(f, "Acik_Konular_Kaynak"))
    konu = [r[1].strip().lower() for r in t[1:]]
    assert len(konu) == len(set(konu))
    assert "Kontrol edilemedi" not in {r[0] for r in t}                     # Bulgular'da VERİ YOK


def test_widths_and_freeze_all_sheets(xl):
    _, f = xl
    names = re.findall(r'<sheet name="([^"]+)"', f["xl/workbook.xml"])
    for i, name in enumerate(names, 1):
        s = f[f"xl/worksheets/sheet{i}.xml"]
        widths = [float(w) for w in re.findall(r'width="([\d.]+)"', s)]
        assert widths and max(widths) <= 102, name
        if name != "OS_WinCC":
            assert 'state="frozen"' in s, name
