"""Envanter: kompakt block sayfaları ('Block klasörleri' + 'Özel bloklar'); standart library'ler tek tek listelenmez."""
import pytest

from pcs7_analyzer import inventory as I
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.discovery import discover_source
from pcs7_analyzer.parsers.subblk import BlockHeader
from pcs7_analyzer.source import open_source


@pytest.fixture(scope="module")
def inv(tmp_path_factory):
    src = open_source(build_demo_project(tmp_path_factory.mktemp("invb")))
    d = discover_source(src)
    inv = I.Inventory(source="demo", created="", discovery=d)
    I._blocks(src, d, inv, lambda m: None)
    I._programs(src, d, inv)            # no-op: zincir _blocks'ta çözüldü, ayrı sayfa yok
    return inv


def _special(inv, proj):
    return {(r[3], r[4]): r for r in inv.sheet("Özel bloklar").rows if r[0] == proj}


def test_only_two_block_sheets(inv):
    assert [s.name for s in inv.sheets] == ["Block klasörleri", "Özel bloklar"]
    assert inv.blockmap_diag and inv.block_data


def test_folders_compact(inv):
    sh = inv.sheet("Block klasörleri")
    assert sh.headers == ["Proje", "AS / S7 program", "Klasör", "FB", "FC", "DB", "OB", "Library'ler", "Özel block",
                          "Custom"]
    assert "2 boş block klasörü listelenmedi" in sh.note
    assert not any(r[2].endswith("00000002") for r in sh.rows)          # boş klasör satırı yok
    as01 = next(r for r in sh.rows if r[2] == "DEMO_MP/AS01/ombstx/offline/00000001")
    assert as01[1] == "-"                                                # demo AS01: ID zinciri yok
    assert "APL V8.0: 1, V8.1: 2, V8.2: 1 (karışık versiyon)" in as01[7] and "Basis Library V8.1: 1" in as01[7]
    assert as01[9] == 4 and as01[8] == 8                                 # 3 custom + 1 header'sız; + GET, LM×2, SEND_R
    as02 = next(r for r in sh.rows if r[2] == "DEMO_MP/AS02/ombstx/offline/0000000A")
    assert as02[1].startswith("AS02 (S7 program AS02_Prog, CPU 414-5H, S7-400H")   # eski 'S7 program ↔ AS' bilgisi
    assert inv.folder_as["DEMO_MP/AS02/ombstx/offline/0000000A"] == as02[1]


def test_special_blocks_custom_and_comm(inv):
    s = _special(inv, "DEMO_MP/AS01")
    assert s[("FB", 1990)][2] == "Custom" and s[("FB", 1990)][5] == "SINAMICS_G120" and s[("FB", 1990)][6] == "BM"
    assert s[("FB", 1990)][7] == "SCL" and s[("FB", 1990)][8] == 1
    assert s[("FB", 1993)][2] == "Custom" and s[("FB", 1993)][7] == "STL"
    assert s[("FB", 2500)][2] == "Header'sız" and s[("FB", 2500)][5] == "E_AUTSIMRST (symbol)"
    assert s[("SFB", 14)][2] == "Haberleşme" and s[("SFB", 14)][5] == "GET" and s[("SFB", 14)][8] == 1
    assert s[("FB", 60)][2] == "PCS 7 Library V7.1"
    assert s[("FB", 1700)][2] == "Logic Matrix"


def test_standard_libraries_not_listed(inv):
    rows = inv.sheet("Özel bloklar").rows
    authors = {r[6] for r in rows}
    assert not authors & {"AdvLib80", "AdvLib81", "AdvLib82", "DRIVER81", "ES_MAP", "ES_SFC"}
    s = _special(inv, "DEMO_MP/AS01")
    for key in (("FB", 1827), ("FB", 1851), ("FB", 300), ("FC", 256), ("FC", 1)):
        assert key not in s


def test_f_system_summarized(inv):
    f = [r for r in inv.sheet("Özel bloklar").rows if r[0] == "AS02" and r[2] == "F-System"]
    assert len(f) == 2                                                   # author başına tek satır
    hl = next(r for r in f if r[3] == "FB")
    assert hl[4] == "FB351, FB352, FB353" and hl[5] == "3 block (özet)" and hl[8] == 7


def _b(name="", author="", kind="FB", nr=1):
    return BlockHeader(kind, nr, "", name, "1.0", author, "00001")


@pytest.mark.parametrize("name,author,protected,symbol,cat", [
    ("MotL", "AdvLib91", False, "", None),
    ("IL_BS", "AdvLibIL", False, "", None),
    ("SEL_R", "DRIVER91", False, "", None),
    ("SFC_FB", "ES_SFC", False, "", None),
    ("R_TRIG", "", False, "", None),
    ("TSEND", "", False, "", "Haberleşme"),
    ("PUT", "SIMATIC", False, "", "Haberleşme"),
    ("MB_CPCLI", "SIEMENS", False, "", "Modbus"),
    ("XYZ", "SIEMENS", False, "", "Siemens add-on"),
    ("LM_Node", "AdvLibLM", False, "", "Logic Matrix"),
    ("", "", False, "F_CH_DI", "F-System"),
    ("", "", False, "TCON", "Haberleşme"),
    ("", "", False, "", "Header'sız"),
    ("PUMP_CTRL", "BM", False, "", "Custom"),
    ("PUMP_CTRL", "BM", True, "", "Know-how protected custom"),
    ("F_TRIG", "", False, "", None),
])
def test_special_category(name, author, protected, symbol, cat):
    assert I.special_category(_b(name, author), protected, symbol) == cat
