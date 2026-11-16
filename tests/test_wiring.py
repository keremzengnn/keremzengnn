"""Bağlantılar: instance çözümleme nedenleri -> unknown, DBT formatı -> yapi_tanisi, XUTILS çağıranları -> Excel / envanter."""
import copy
import re
import zipfile
from types import SimpleNamespace

import pytest

from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.excel_report import SHEETS, write_excel
from pcs7_analyzer.inventory import build_inventory, diagnostics
from pcs7_analyzer.parsers.subblk import INSTANCE_ISSUE_KIND
from pcs7_analyzer.parsers.xutils import _ablative, fc_callers_text
from pcs7_analyzer.source import open_source


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    root = tmp_path_factory.mktemp("w")
    return root, build_demo_project(root / "d")


@pytest.fixture(scope="module")
def an(demo):
    return analyze(demo[1])


def test_unresolved_reasons_recorded_per_reason(an):
    as01 = next(b for b in an.block_folders if b.info.path.endswith("AS01/ombstx/offline/00000001"))
    assert as01.unresolved_reasons.get(INSTANCE_ISSUE_KIND) == 1 and as01.memo_format == "db4"
    assert as01.memo_block_size == 512
    rows = [e for e in an.unknown.entries if e.module == "blocks" and e.where == "SSBPART"]
    assert rows and all("≥ 8192" not in e.reason for e in rows)              # eski tek mesaj yok
    assert any(INSTANCE_ISSUE_KIND in e.reason and "DB122" in e.raw for e in rows)


def test_yapi_tanisi_memo_format(demo):
    with open_source(demo[1]) as src:
        txt = diagnostics(src)
    assert re.search(r"SUBBLK\.DBT memo formatı: dBASE IV, blok 512", txt)
    assert "DEMO_MP" not in txt.split("memo formatı", 1)[1].splitlines()[0]   # path maskeli


def test_ablative_and_fc_callers_text():
    assert [_ablative(n) for n in (35, 1, 30, 100, 82, 86, 40)] == ["ten", "den", "dan", "den", "den", "dan", "tan"]
    b = SimpleNamespace(fc_callers={7: [("OB", 35, 1)], 8: [("FC", 7, 2), ("FB", 3, 1)],
                                    9: [("OB", 1, 1), ("FC", 2, 1)]})
    assert fc_callers_text(b, 7) == "OB35'ten çağrılıyor (runtime group)"
    assert fc_callers_text(b, 8) == "FC7 ×2, FB3"
    assert fc_callers_text(b, 9) == "OB1'den çağrılıyor (runtime group), FC2"
    assert fc_callers_text(b, 99) == "" and fc_callers_text(SimpleNamespace(), 7) == ""


def test_excel_custom_blocks_caller_column(demo, an):
    # çağıran bilgisi doğrulanmış değil: Custom_Blocklar'da sütun yok, 'Teyit_Edilecekler' sayfasında aksiyon olarak
    p = write_excel(an, demo[0] / "rapor.xlsx")
    with zipfile.ZipFile(p) as z:
        s = z.read(f"xl/worksheets/sheet{SHEETS.index('Custom_Blocklar') + 1}.xml").decode("utf-8")
        names = re.findall(r'<sheet name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8"))
        t = z.read(f"xl/worksheets/sheet{names.index('Teyit_Edilecekler') + 1}.xml").decode("utf-8")
    assert "Çağıran" not in s and "ÇIKARIM" not in s
    assert "FC1 (runtime group, OB35)" in t


def test_excel_no_caller_column_without_xutils(an, tmp_path):
    an = copy.deepcopy(an)                                   # modül fixture'ı değişmesin
    for b in an.block_folders:
        b.callers, b.fc_callers = {}, {}
    p = write_excel(an, tmp_path / "r.xlsx")
    with zipfile.ZipFile(p) as z:
        s = z.read(f"xl/worksheets/sheet{SHEETS.index('Custom_Blocklar') + 1}.xml").decode("utf-8")
    assert "Çağıran" not in s


def test_inventory_special_blocks_caller_column(demo):
    inv = build_inventory(demo[1])
    sh = inv.sheet("Özel bloklar")
    # çağıran bilgisi kesin değil: envanterde sütun yok, tek teyit maddesi
    assert not any("Çağıran" in h for h in sh.headers)
    assert all(len(r) == len(sh.headers) for r in sh.rows)
    assert any(c.topic == "Çağıran block'lar" for c in inv.confirm)
