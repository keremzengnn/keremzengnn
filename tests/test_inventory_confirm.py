"""FAZ 1: envanterde belirsizlik dili yok; doğrulanamayanlar tek 'Teyit edilecekler' sayfasında (sonda)."""
import html as _html
import re
import shutil
import zipfile

import pytest

from pcs7_analyzer import confirm
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.inventory import build_inventory, write_outputs


@pytest.fixture(scope="module")
def demo_inv(tmp_path_factory):
    root = tmp_path_factory.mktemp("conf")
    inv = build_inventory(build_demo_project(root / "d"))
    write_outputs(inv, root / "out")
    return inv, root / "out"


def _sheet_texts(inv):
    """Teyit sayfası dışındaki tüm sayfaların metinleri: ad, not, başlık, hücreler."""
    for s in inv.sheets:
        if s.name == confirm.SHEET_INVENTORY:
            continue
        yield s.name
        yield s.note
        yield from s.headers
        for r in s.rows:
            yield from (str(v) for v in r)


def test_no_forbidden_pattern_in_sheets(demo_inv):
    inv, _ = demo_inv
    bad = [t for t in _sheet_texts(inv) if not confirm.is_clean(t)]
    assert bad == []


def test_no_forbidden_pattern_in_html_outside_confirm_section(demo_inv):
    _, out = demo_inv
    page = (out / "envanter.html").read_text(encoding="utf-8")
    head, _, tail = page.partition('<section id="teyit">')
    rest = tail.split("</section>", 1)[1] if tail else ""
    text = _html.unescape(re.sub(r"<[^>]+>", " ", head + rest))
    assert confirm.is_clean(text), confirm.FORBIDDEN.search(text)
    assert tail                                                      # teyit bölümü HTML'de var


def test_confirm_sheet_last_in_xlsx_and_html(demo_inv):
    inv, out = demo_inv
    assert inv.sheets[-1].name == confirm.SHEET_INVENTORY and inv.confirm
    with zipfile.ZipFile(out / "envanter.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
    names = re.findall(r'<sheet name="([^"]+)"', wb)
    assert names[-1] == _html.escape(confirm.SHEET_INVENTORY, quote=True) or names[-1] == confirm.SHEET_INVENTORY
    page = (out / "envanter.html").read_text(encoding="utf-8")
    assert page.rindex("<h2>") == page.index(f"<h2>{confirm.HEADING}</h2>")     # en sonda


def test_no_client_question_mark_and_no_unverified_as(demo_inv):
    inv, _ = demo_inv
    rows = inv.sheet("Mevcut durum").rows
    assert not any("client?" in str(c) or "?" in str(r[1]) for r in rows for c in r)
    assert all(not str(c).endswith("?") for s in inv.sheets if s.name != confirm.SHEET_INVENTORY
               for r in s.rows for c in r)


def test_confirm_items_have_actions(demo_inv):
    inv, _ = demo_inv
    assert all(c.topic and c.action for c in inv.confirm)
    assert len(inv.confirm) == len(set(inv.confirm))                  # tekrar yok


def test_without_export_hardware_sheet_not_written_but_confirm_item(tmp_path):
    bk = build_demo_project(tmp_path / "d")
    shutil.rmtree(bk / "exports")
    inv = build_inventory(bk)
    assert not inv.has("Hardware")
    hw_conf = [c for c in inv.confirm if c.topic == "Hardware"]
    assert len(hw_conf) == 1 and ".cfg" in hw_conf[0].action
    cur = {(r[0], r[1]): r[2] for r in inv.sheet("Mevcut durum").rows}
    assert cur[("Hardware", "-")] == "HW Config export yok"
    assert [t for t in _sheet_texts(inv) if not confirm.is_clean(t)] == []
    assert inv.sheets[-1].name == confirm.SHEET_INVENTORY


def test_empty_confirm_sheet_not_written():
    from pcs7_analyzer.inventory import Inventory, Sheet, _order_sheets
    inv = Inventory(source="x", created="t", discovery=None, sheets=[Sheet("Projeler", ["A"], [[1]])])
    _order_sheets(inv)
    assert [s.name for s in inv.sheets] == ["Projeler"]


def test_unclean_warning_moves_to_confirm():
    from pcs7_analyzer.inventory import Inventory, _clean_warnings
    inv = Inventory(source="x", created="t", discovery=None,
                    warnings=["Proje X: eşleşme teyit edilmeli", "Düz uyarı"])
    _clean_warnings(inv)
    assert inv.warnings == ["Düz uyarı"] and len(inv.confirm) == 1


def test_three_digit_author_not_shown_as_version():
    from pcs7_analyzer.inventory import _author_ver
    unv = set()
    assert _author_ver("AdvLb100", unv) == "AdvLb100" and unv == {"AdvLb100"}
    assert _author_ver("AdvLib91", unv) == "V9.1" and unv == {"AdvLb100"}
