"""Envanter sadeleştirme: .s7h adet tekilleştirme, OS client grupları, 'build tespit edilemedi', xlsx widths/note."""
import zipfile

from pcs7_analyzer import inventory as I
from pcs7_analyzer.discovery import OsProjectInfo
from pcs7_analyzer.inventory import Inventory, Sheet, write_xlsx

MLFB_CPU, MLFB_CP, MLFB_IM = "6ES7 414-5HM06-0AB0", "6GK7 443-1EX30-0XE0", "6ES7 152-1AA00-0AB0"


def _inv(scan):
    return Inventory(source="x", created="t", discovery=None, hw_scan=scan)


def test_s7h_cpu_cp_counted_once_per_station_file():
    inv = _inv([("P", "P/a/S1.s7h", I.SRC_S7H, MLFB_CPU, "V6.0", 1), ("P", "P/a/S2.s7h", I.SRC_S7H, MLFB_CPU, "V6.0", 1),
                ("P", "P/a/S1.s7h", I.SRC_S7H, MLFB_IM, "", 7)])
    items = I._scan_by_project(inv, set())["P"]
    assert items[("CPU", MLFB_CPU, "V6.0")][0] == 2            # iki station dosyası
    assert items[("IM", MLFB_IM, "")][0] == 7                  # diğer türler ham kayıt sayısı (çıkarım)


def test_s7h_repeated_cpu_in_one_file_is_unreliable_adet_blank():
    inv = _inv([("P", "P/a/S1.s7h", I.SRC_S7H, MLFB_CPU, "V6.0", 2), ("P", "P/a/S1.s7h", I.SRC_S7H, MLFB_CP, "V3.0", 1)])
    assert I._scan_by_project(inv, set())["P"][("CPU", MLFB_CPU, "V6.0")][0] is None     # H çifti mi, tekrar mı?
    inv.hw_stations = []
    I._hardware(inv)
    sh = inv.sheet("Hardware")
    cpu = next(r for r in sh.rows if r[1] == "CPU")
    assert cpu[5] == "" and next(r for r in sh.rows if r[1] == "CP")[5] == 1
    assert "'Adet' boş" in sh.note                              # neden notta


def test_dbf_scan_adet_blank():
    inv = _inv([("P", "P/hOmSave7/x/H.DBF", I.SRC_DBF, MLFB_CPU, "V6.0", 3)])
    assert I._scan_by_project(inv, set())["P"][("CPU", MLFB_CPU, "V6.0")][0] is None


def test_current_state_hw_line_tolerates_unknown_adet():
    line = I._hw_line({("CPU", MLFB_CPU, "CPU 414-5H", "V6.0"): None, ("IM", MLFB_IM, "", ""): 3}, [])
    assert line == "CPU 414-5H V6.0; 3 IM"


def test_wincc_build_label():
    assert I.wincc_build_label("V08.00.00.00") == "build tespit edilemedi"
    assert I.wincc_build_label("V07.03.20.04") == "V07.03.20.04" and I.wincc_build_label("") == "-"


def _os(name, build="V07.03.20.04"):
    return OsProjectInfo(path=f"MP/wincproj/{name}", project="P", mcp=f"{name}.mcp", wincc_build=build, n_files=3,
                         custom_pictures=0, faceplates_and_templates=0, vbs_modules=0, vbs_actions=0, c_actions=0,
                         newest_mtime="")


def _inv_os(clients, extra=()):
    inv = Inventory(source="x", created="t", discovery=None)
    for name, sig in clients:
        o = _os(name)
        inv.os_rows.append((o, "client", "ES"))
        inv.os_sigs[o.path] = frozenset(sig)
    for name, role in extra:
        inv.os_rows.append((_os(name, "V08.00.00.00"), role, "ES"))
    return inv


def test_client_group_same_structure_one_row():
    inv = _inv_os([(f"C{i}", {"a.pdl", "b.pdl"}) for i in range(3)])
    rows = I._os_state_rows(inv, set())
    assert len(rows) == 1 and rows[0][1] == "OS client"
    assert rows[0][2] == "3 proje (C0, C1, C2) – yapıları aynı"


def test_client_group_only_different_client_listed_separately():
    inv = _inv_os([("C0", {"a", "b"}), ("C1", {"a", "b"}), ("C2", {"a", "b", "x"})])
    val = I._os_state_rows(inv, set())[0][2]
    assert "yapıları farklı" in val and "2 proje aynı yapıda" in val
    assert "C2 (referansa göre +1 / -0 dosya)" in val and "C0 (referansa" not in val


def test_server_and_unknown_role_grouped_by_role_and_build_label():
    inv = _inv_os([], extra=[("SRV1", "server"), ("X1", "client?")])
    inv.os_sigs[inv.os_rows[1][0].path] = frozenset({"a"})
    rows = {r[1]: r[2] for r in I._os_state_rows(inv, set())}
    assert rows["OS server"].startswith("SRV1 (ES; WinCC build tespit edilemedi;")
    assert rows["OS client?"].startswith("1 proje (X1)") and "teyit" in rows["OS client?"]


def test_client_signature_ignores_pc_folder():
    assert I.client_signature({"gracs/a.pdl": (1, 0), "<pc>/pas/x.pas": (2, 0)}) == frozenset({"gracs/a.pdl"})


def test_sheet_widths_default_and_xlsx_note_widths_freeze_filter(tmp_path):
    assert Sheet("Dolu", ["A"], [[1]]).widths == []             # varsayılanlı: eski çağrı kırılmaz
    inv = Inventory(source="x", created="t", discovery=None, sheets=[
        Sheet("Bir", ["A", "B"], [[1, "x"], [2, "y"]], note="Not metni " * 40, widths=[30, 12]),
        Sheet("İki", ["A"], [["uzun metin değeri"]]), Sheet("Boş", ["A"], [])])
    p = write_xlsx(inv, tmp_path / "e.xlsx")
    with zipfile.ZipFile(p) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        s1, s2 = (z.read(f"xl/worksheets/sheet{i}.xml").decode("utf-8") for i in (1, 2))
    assert 'name="Boş"' not in wb and wb.count("<sheet ") == 2    # boş sayfa yok
    assert "Not metni" in s1                                      # note xlsx'e yazılır
    assert '<col min="1" max="1" width="32"' in s1                # widths kullanılır (30 + 2)
    assert 'state="frozen"' in s1 and "<autoFilter" in s1         # freeze + filter korunur
    assert "ySplit=\"1\"" in s2 and 'ref="A1:A2"' in s2           # notsuz sayfa: başlık 1. satır
