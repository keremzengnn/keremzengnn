"""Block klasörü ↔ S7 program ↔ CPU ↔ station ID zinciri (sentetik STEP 7 dosyalarıyla)."""
from dbfwriter import SUBBLK_FIELDS, block, write_dbf
from pcs7_analyzer._dbfwriter import write_project_links
from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.blockmap import diagnostics, resolve
from pcs7_analyzer.source import open_source

PROGS = [{"id": 3, "name": "Prog_A", "folder_id": 0x11, "cpu_id": 900, "cpu_name": "CPU 417-4H", "station_id": 0x21,
          "station_name": "ST_NORTH", "sym_id": 4},
         {"id": 5, "name": "Prog_B", "folder_id": 0x12, "cpu_id": 901, "cpu_name": "CPU 410-5H", "station_id": 0x22,
          "station_name": "ST_SOUTH"}]


def _project(root, progs=PROGS, cfg_station=None):
    proj = root / "MP" / "P1"
    proj.mkdir(parents=True)
    (proj / "P1.s7p").write_bytes(b"x")
    for hx, nr in (("00000011", 10), ("00000012", 20)):
        d = proj / "ombstx" / "offline" / hx
        d.mkdir(parents=True)
        write_dbf(d / "SUBBLK.DBF", SUBBLK_FIELDS, [block("00004", nr, "F", "X", author="AdvLib81")], memo="db4")
    (proj / "YDBs" / "4").mkdir(parents=True)
    write_dbf(proj / "YDBs" / "4" / "SYMLIST.DBF", [("_SKZ", "C", 24), ("_OPIEC", "C", 12), ("_DATATYP", "C", 10),
                                                   ("_KOMMENTAR", "C", 80)],
              [{"_SKZ": "X", "_OPIEC": "FB    10", "_DATATYP": "FB 10", "_KOMMENTAR": ""}], memo=None)
    write_project_links(proj, progs)
    if cfg_station:
        (root / "exports").mkdir()
        (root / "exports" / "a.cfg").write_bytes(
            f'FILEVERSION "3.2"\r\n#STEP7_VERSION V5.5 SP4\r\nSTATION S7400H , "{cfg_station}"\r\n'.encode("latin1"))
    return proj


def test_chain_resolves_programs_cpus_stations(tmp_path):
    _project(tmp_path)
    with open_source(tmp_path) as src:
        bm = resolve(src, ["MP/P1"])
    a = bm.for_folder("MP/P1/ombstx/offline/00000011")
    b = bm.for_folder("mp/p1/ombstx/offline/00000012")
    assert (a.program_name, a.cpu_name, a.station_name, a.station_type) == ("Prog_A", "CPU 417-4H", "ST_NORTH", "S7-400H")
    assert a.symbol_table == "MP/P1/YDBs/4/SYMLIST.DBF" and b.symbol_table is None
    assert b.station_name == "ST_SOUTH" and not bm.unknown


def test_labels_in_analysis_and_confidence(tmp_path):
    _project(tmp_path, cfg_station="ST_NORTH")
    an = analyze(tmp_path)
    by = {b.info.path.rsplit("/", 1)[-1]: b for b in an.block_folders}
    assert by["00000011"].as_label == "ST_NORTH" and "(KANIT)" in by["00000011"].mapping     # HW export ile çapraz kontrol
    assert by["00000012"].as_label == "ST_SOUTH" and "(ÇIKARIM)" in by["00000012"].mapping   # çapraz kanıt yok
    assert "ID zinciri YLNKLIST" in by["00000011"].symbol_source


def test_negative_cases_go_to_unknown(tmp_path):
    proj = _project(tmp_path)
    (proj / "hrs" / "linkhrs.lnk").write_bytes(b"\x00" * 0x200)          # imza yok
    with open_source(tmp_path) as src:
        bm = resolve(src, ["MP/P1"])
    assert all(link.block_folder is None for link in bm.links)
    assert sum("imzası yok" in u for u in bm.unknown) == 1                  # 2. programın ofseti dosya dışında
    assert any("ofset geçersiz" in u for u in bm.unknown)
    (proj / "hrs" / "linkhrs.lnk").unlink()
    with open_source(tmp_path) as src:
        bm = resolve(src, ["MP/P1"])
    assert any("linkhrs.lnk | yok" in u for u in bm.unknown)


def test_missing_folder_and_masked_diagnostics(tmp_path):
    progs = [dict(PROGS[0], folder_id=0x99)]                                 # backup'ta olmayan klasör
    _project(tmp_path, progs)
    with open_source(tmp_path) as src:
        bm = resolve(src, ["MP/P1"])
    assert any("00000099 backup'ta yok" in u for u in bm.unknown)
    txt = diagnostics(bm)
    for secret in ("Prog_A", "ST_NORTH", "CPU 417-4H", "MP/P1"):
        assert secret not in txt
    assert "<proje 1>" in txt
