"""Kompakt envanter: boş sayfa yok, tek Hardware tablosu, symbol table ayrı dosyada, Mevcut durum kısa."""
import shutil
import zipfile

import pytest

from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.inventory import Inventory, Sheet, build_inventory, render_html, write_outputs


@pytest.fixture(scope="module")
def inv_out(tmp_path_factory):
    root = tmp_path_factory.mktemp("invc")
    inv = build_inventory(build_demo_project(root))
    write_outputs(inv, root / "out")
    return inv, root / "out"


def test_no_empty_sheets(inv_out):
    inv, out = inv_out
    assert all(s.rows for s in inv.sheets)
    html = (out / "envanter.html").read_text(encoding="utf-8")
    assert "Kayıt yok" not in html


def test_removed_sheets(inv_out):
    inv, _ = inv_out
    names = {s.name for s in inv.sheets}
    for gone in ("Özet", "HW station (export)", "HW modüller (export)", "HW (backup içi)", "Semboller",
                 "Sembol kontrolleri", "OS dosyaları", "Dosya türleri"):
        assert gone not in names


def test_hardware_single_table(inv_out):
    inv, _ = inv_out
    hw = inv.sheet("Hardware")
    assert hw.headers == ["Station / Proje", "Tür", "MLFB", "Model / açıklama", "FW", "Adet", "Kaynak", "Dosya"]
    as01 = [r for r in hw.rows if r[0] == "AS01"]
    assert as01[0][1] == "CPU"                                  # station içinde CPU önce
    assert all("/" not in str(r[7]) for r in hw.rows)          # tam path yok, sadece dosya adı
    assert any(r[1] == "GSD" and r[5] == 2 for r in as01)       # aynı GSD cihaz -> Adet
    assert any(r[3].endswith("(çıkarım)") for r in hw.rows)     # MLFB ailesinden açıklama işaretli


def test_symbols_separate_file(inv_out):
    inv, out = inv_out
    with zipfile.ZipFile(out / "semboller.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
    assert 'name="Semboller"' in wb and 'name="Sembol kontrolleri"' in wb
    rows = [r for r in inv.sheet("Mevcut durum").rows if r[0] == "Symbol table"]
    assert len(rows) == 1 and "semboller.xlsx" in rows[0][2]


def test_current_state_compact(inv_out):
    inv, _ = inv_out
    rows = inv.sheet("Mevcut durum").rows
    assert len(rows) <= 40
    assert sum(1 for r in rows if r[0] == "Yazılım") == 3
    assert [r[1] for r in rows if r[0] == "Hardware"] == ["AS01", "AS02"]      # station başına tek satır
    assert all(r[0] != "OS" or r[1] for r in rows)


def test_hardware_without_export_uses_s7h_scan(tmp_path):
    bk = build_demo_project(tmp_path)
    shutil.rmtree(bk / "exports")
    inv = build_inventory(bk)
    hw = inv.sheet("Hardware").rows
    assert hw and all(r[6].startswith(".s7h taraması") for r in hw)
    assert {r[0] for r in hw} == {"AS01"}                       # ESKI_BACKUP kopyası hariç
    cur = {(r[0], r[1]): r[2] for r in inv.sheet("Mevcut durum").rows}
    assert "(backup taraması, çıkarım)" in cur[("Hardware", "AS01")]
    assert cur[("Yazılım", "STEP 7")].startswith("tespit edilemedi")


def test_render_html_skips_empty():
    inv = Inventory(source="x", created="t", discovery=None,
                    sheets=[Sheet("Dolu", ["A"], [[1]]), Sheet("Boş", ["A"], [])])
    html = render_html(inv)
    assert "Dolu" in html and "Boş" not in html and "Kayıt yok" not in html
