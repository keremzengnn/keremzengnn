"""Envanter: kompakt block sayfaları ('Block klasörleri' + 'Özel bloklar'); standart library'ler tek tek listelenmez."""
import re

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
    assert sh.headers == ["Proje", "AS / S7 program", "Block sayısı", "Library'ler", "Dikkat edilecek block"]
    assert "2 boş block klasörü listelenmedi" in sh.note
    assert "DEMO_MP/AS01/ombstx/offline/00000001" in sh.note             # Klasör sütunu yok: yollar notta
    assert not any("00000002" in str(r) for r in sh.rows)                # boş klasör satırı yok
    as01 = next(r for r in sh.rows if r[0] == "DEMO_MP/AS01")
    assert as01[1] == "-"                                                # demo AS01: ID zinciri yok
    assert re.fullmatch(r"(FB \d+)( · FC \d+)?( · DB \d+)?( · OB \d+)?", as01[2])    # tek 'Block sayısı'
    assert "APL V8.0 – 1 block tipi; APL V8.1 – 2 block tipi; APL V8.2 – 1 block tipi" in as01[3]
    pos = [as01[3].index(f"APL V{v} –") for v in ("8.0", "8.1", "8.2", "9.1", "10.0")]
    assert pos == sorted(pos)                                            # sürümler sayısal sıralı (V10.0 sonda)
    assert "(APL: karışık versiyon)" in as01[3] and "Basis Library V8.1 – 1 block tipi" in as01[3]
    assert "CFC ELEMENTA" not in as01[3] and "ES_MAP" not in as01[3] and "CFC generated" not in as01[3]
    assert as01[3].split("; ")[-1].startswith("diğer Siemens: ")       # en sonda tek 'diğer Siemens: N'
    assert as01[4].startswith("Custom ") and " · şifreli-Siemens dışı " in as01[4] and " · tanınmayan author " in as01[4]
    assert "Logic Matrix 2" in as01[4]
    as02 = next(r for r in sh.rows if r[0] == "AS02")
    assert "F-System 4" in as02[4]
    assert "Custom 0 · şifreli-Siemens dışı 0 · tanınmayan author 0" in as02[4]     # risk kategorileri hep görünür
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
    assert not authors & {"AdvLib80", "AdvLib81", "AdvLib82", "DRIVER81", "ES_MAP"}     # ES_SFC = SFC kategorisi (WP1)
    s = _special(inv, "DEMO_MP/AS01")
    for key in (("FB", 1827), ("FB", 1851), ("FC", 256), ("FC", 1)):
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
    ("SFC_FB", "ES_SFC", False, "", "SFC"),
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
    ("PUMP_CTRL", "BM", True, "", "Custom"),
    ("PUMP_CTRL", "ZZZ", True, "", "Şifreli, Siemens dışı"),
    ("PUMP_CTRL", "ZZZ", False, "", "Tanınmayan author"),
    ("F_TRIG", "", False, "", None),
])
def test_special_category(name, author, protected, symbol, cat):
    assert I.special_category(_b(name, author), protected, symbol) == cat


def test_unknown_authors_one_line_in_note(inv):
    note = inv.sheet("Özel bloklar").note
    unk = {r[6] for r in inv.sheet("Özel bloklar").rows if r[2] == "Tanınmayan author"}
    assert unk and "Tanınmayan author'lar" in note and all(a in note for a in unk)
    assert note.count("Tanınmayan author'lar") == 1                       # tek satır
