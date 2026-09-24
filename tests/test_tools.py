import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("ebc", Path(__file__).parents[1] / "tools" / "extract_block_changes.py")
ebc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ebc)


def test_parse_apl_rows():
    text = "5.1Version 10.0\nCntOhScFB18036YesNoYes\nByt2DigVFC47810NoNoNew Block\nFbAnInFB181310YesNoYes\n" \
           "5.2Version 10.0 SP1\nMonAnSFB19126.1NoNoYes\n"
    rows = ebc.parse_apl(text)
    assert [(r["section"], r["name"], r["kind"], r["number"], r["version"], r["interface_change"]) for r in rows] == [
        ("10.0", "CntOhSc", "FB", "1803", "6", "yes"), ("10.0", "Byt2DigV", "FC", "478", "10", "new"),
        ("10.0", "FbAnIn", "FB", "1813", "10", "yes"), ("10.0 SP1", "MonAnS", "FB", "1912", "6.1", "no")]


def test_parse_basis_rows():
    text = "### **6.1 Version 10.0** \n|CPU_RT|FB128|10.0|Yes|Yes|\n|CPU_RES|FB446|10.0|New block||\n|ChkREAL|FC260|10.0|No|Yes|\n"
    rows = ebc.parse_basis(text)
    assert [(r["name"], r["number"], r["interface_change"]) for r in rows] == [("CPU_RT", "128", "yes"),
                                                                               ("CPU_RES", "446", "new"), ("ChkREAL", "260", "no")]


def test_shipped_block_changes_csv():
    import csv
    p = Path(__file__).parents[1] / "pcs7_analyzer" / "data" / "block_changes_V10.0SP2.csv"
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    names = {(r["library"], r["name"]) for r in rows if r["interface_change"] == "yes"}
    assert ("APL", "MotL") in names and ("Basis", "CPU_RT") in names and ("APL", "Intlk16") in names
