import zipfile

import pytest

from pcs7_analyzer.cli import main
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.inventory import build_inventory, mask_path, write_outputs


@pytest.fixture(scope="module")
def inv_out(tmp_path_factory):
    root = tmp_path_factory.mktemp("inv")
    bk = build_demo_project(root)
    inv = build_inventory(bk)
    write_outputs(inv, root / "out")
    return inv, root / "out"


def test_sheets(inv_out):
    inv, _ = inv_out
    names = [s.name for s in inv.sheets]
    assert names[0] == "Özet" and names[-1] == "Uyarılar"
    for n in ("Projeler", "HW modüller (export)", "HW (backup içi)", "Block klasörleri", "Bloklar", "Instance sayıları",
              "Library özeti", "Semboller", "OS projeleri", "OS dosyaları", "Dosya türleri"):
        assert n in names


def test_blocks_and_instances(inv_out):
    inv, _ = inv_out
    rows = [r for r in inv.sheet("Bloklar").rows if r[0] == "AS01" and r[1] == "00000001"]
    b = {r[3]: r for r in rows}
    assert b[1827][4] == "Intlk16" and b[1827][7] == "APL" and b[1827][10] == 5
    assert b[1990][10] == 1


def test_symbols_full_list_from_backup(inv_out):
    """SYMLIST.DBF backup içinden: block sembolleri + I/O sembolleri, doğru block klasörüne eşlenmiş."""
    inv, _ = inv_out
    rows = [r for r in inv.sheet("Semboller").rows if r[0] == "DEMO_MP/AS01/YDBs/1/SYMLIST.DBF"]
    ops = {r[3]: r for r in rows}
    assert ops["Intlk16"][4] == "FB 1827"
    assert ops["Motor_Run"][4] == "I 0.0" and ops["Motor_Run"][5] == "BOOL"
    assert ops["Intlk16"][2].startswith("DEMO_MP/AS01/ombstx/offline/00000001")


def test_hw_from_backup_and_export(inv_out):
    inv, _ = inv_out
    internal = inv.sheet("HW (backup içi)").rows
    assert any(r[3] == "6ES7 414-5HM06-0AB0" and r[4] == "V6.0" for r in internal)
    exp = inv.sheet("HW modüller (export)").rows
    assert any(r[3] == "6ES7 414-5HM06-0AB0" and r[6] == "CPU" for r in exp)


def test_os_files_keep_case(inv_out):
    inv, _ = inv_out
    files = inv.sheet("OS dosyaları").rows
    assert any(r[2] == "GraCS/Tank_New.pdl" and r[3] == "custom picture" for r in files)
    assert any(r[3] == "F faceplate" for r in files)


def test_outputs_and_xlsx(inv_out):
    inv, out = inv_out
    for n in ("envanter.xlsx", "envanter.html", "yapi_tanisi.txt"):
        assert (out / n).stat().st_size > 0
    with zipfile.ZipFile(out / "envanter.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        assert 'name="Semboller"' in wb and len([n for n in z.namelist() if n.startswith("xl/worksheets/")]) == len(inv.sheets)
        assert "Motor_Run" in z.read(f"xl/worksheets/sheet{[s.name for s in inv.sheets].index('Semboller') + 1}.xml").decode()


def test_diagnostics_contain_no_customer_data(inv_out):
    _, out = inv_out
    diag = (out / "yapi_tanisi.txt").read_text(encoding="utf-8")
    assert "SYMLIST.DBF" in diag and "_SKZ:C24" in diag and "SUBBLK.DBF" in diag
    for secret in ("DEMO_MP", "AS01", "Intlk16", "Motor_Run", "ESKI_BACKUP", "Tank"):
        assert secret not in diag


def test_mask_path():
    assert mask_path("Musteri/Proje1/ombstx/offline/0000000A/SUBBLK.DBF") == "offline/<hex>/SUBBLK.DBF"
    assert mask_path("Musteri/Proje1/S7RESOFF.DBF") == "<klasör>/<klasör>/S7RESOFF.DBF"
    assert mask_path("Proje/hOmSave7/s7hstatx/HOBJECT1.DBF") == "hOmSave7/s7hstatx/HOBJECT1.DBF"


def test_cli_inventory(tmp_path):
    bk = build_demo_project(tmp_path)
    assert main([str(bk), "--inventory", "-o", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "envanter.xlsx").exists() and not (tmp_path / "o" / "rapor.docx").exists()
