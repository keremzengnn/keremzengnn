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
    assert names[:2] == ["Mevcut durum", "Hardware"] and names[-1] == "Uyarılar"
    for n in ("Projeler", "Block klasörleri", "Özel bloklar", "OS projeleri"):
        assert n in names
    for gone in ("Bloklar", "Instance sayıları", "Library özeti", "DB family", "S7 program ↔ AS"):
        assert gone not in names


def test_current_state(inv_out):
    inv, _ = inv_out
    rows = {(r[0], r[1]): r[2] for r in inv.sheet("Mevcut durum").rows}
    assert rows[("Yazılım", "PCS 7")] == "V8.1"
    assert "V5.5 SP4" in rows[("Yazılım", "STEP 7")] and "AS01" in rows[("Yazılım", "STEP 7")]
    # eski kopya (ESKI_BACKUP) özete katılmaz: APL sayıları çift sayılmaz
    assert rows[("Library", "APL")].startswith("V8.0: 1 block (AS01)") and "ESKI_BACKUP" not in rows[("Library", "APL")]
    assert "karışık versiyon" in rows[("Library", "APL")]
    assert rows[("Library", "Custom FB")].startswith("3 FB") and "(AS01 1, AS02 3)" in rows[("Library", "Custom FB")]
    assert rows[("Hardware", "AS01")].startswith("CPU 414-5H PN/DP V6.0, CP 443-1 V3.0")
    assert "F-capable" in rows[("Hardware", "AS02")] and "F-capable" not in rows[("Hardware", "AS01")]
    assert any(k[0] == "Not" and "ESKI_BACKUP" in v for k, v in rows.items())


def test_blocks_and_instances(inv_out):
    inv, _ = inv_out
    rows = [r for r in inv.sheet("Özel bloklar").rows if r[0] == "DEMO_MP/AS01"]
    b = {r[4]: r for r in rows}
    assert 1827 not in b                                  # APL (Intlk16) tek tek listelenmez
    assert b[1990][5] == "SINAMICS_G120" and b[1990][2] == "Custom" and b[1990][8] == 1


def test_symbols_full_list_from_backup(inv_out):
    """SYMLIST.DBF backup içinden: block sembolleri + I/O sembolleri, doğru block klasörüne eşlenmiş."""
    inv, _ = inv_out
    sym = next(s for s in inv.symbol_sheets if s.name == "Semboller")      # semboller.xlsx (envanterde değil)
    rows = [r for r in sym.rows if r[0] == "DEMO_MP/AS01/YDBs/1/SYMLIST.DBF"]
    ops = {r[3]: r for r in rows}
    assert ops["Intlk16"][4] == "FB 1827"
    assert ops["Motor_Run"][4] == "I 0.0" and ops["Motor_Run"][5] == "BOOL"
    assert ops["Intlk16"][2].startswith("DEMO_MP/AS01/ombstx/offline/00000001")


def test_hw_from_backup_and_export(inv_out):
    inv, _ = inv_out
    # .s7h taraması okunur ama export'u olan station için Hardware sayfasına girmez
    assert any(r[3] == "6ES7 414-5HM06-0AB0" and r[4] == "V6.0" for r in inv.hw_scan)
    hw = inv.sheet("Hardware").rows
    assert any(r[0] == "AS01" and r[1] == "CPU" and r[2] == "6ES7 414-5HM06-0AB0" and r[3] == "CPU 414-5H PN/DP"
               and r[4] == "V6.0" and r[6] == "HW export" for r in hw)
    assert not any(r[6] != "HW export" for r in hw)


def test_os_projects_one_row(inv_out):
    inv, _ = inv_out
    rows = {(r[0], r[2]): r for r in inv.sheet("OS projeleri").rows}
    assert rows[("OS_SRV1", "ES")][1] == "server" and rows[("OS_SRV1", "OS PC kopyası")][5] == 5
    assert rows[("OS_SRV1_StBy", "ES")][1] == "standby"


def test_outputs_and_xlsx(inv_out):
    inv, out = inv_out
    for n in ("envanter.xlsx", "envanter.html", "yapi_tanisi.txt"):
        assert (out / n).stat().st_size > 0
    with zipfile.ZipFile(out / "envanter.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        assert 'name="Semboller"' not in wb and len([n for n in z.namelist() if n.startswith("xl/worksheets/")]) == len(inv.sheets)
    with zipfile.ZipFile(out / "semboller.xlsx") as z:
        assert 'name="Semboller"' in z.read("xl/workbook.xml").decode("utf-8")
        assert "Motor_Run" in z.read("xl/worksheets/sheet1.xml").decode()


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
