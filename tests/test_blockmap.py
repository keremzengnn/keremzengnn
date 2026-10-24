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


def test_logical_field_nul_does_not_drop_chain(tmp_path):
    """Gerçek projede görüldü: SYMLISTS.DBF _SAVED/_DELETED (L) alanında \\x00 -> zincir kaybolmamalı."""
    proj = _project(tmp_path)
    write_dbf(proj / "YDBs" / "SYMLISTS.DBF", [("_ID", "N", 10), ("_DBPATH", "C", 24), ("_SAVED", "L", 1),
                                              ("_DELETED", "L", 1)],
              [{"_ID": 4, "_DBPATH": "4", "_SAVED": b"\x00", "_DELETED": b"\x00"}])
    with open_source(tmp_path) as src:
        bm = resolve(src, ["MP/P1"])
    a = bm.for_folder("MP/P1/ombstx/offline/00000011")
    assert a.station_name == "ST_NORTH" and a.symbol_table == "MP/P1/YDBs/4/SYMLIST.DBF"
    assert not any("okunamadı" in u for u in bm.unknown)


def test_symbol_step_failure_keeps_station_links(tmp_path):
    proj = _project(tmp_path)
    (proj / "YDBs" / "YLNKLIST.DBF").write_bytes(b"\x03bozuk")
    with open_source(tmp_path) as src:
        bm = resolve(src, ["MP/P1"])
    assert bm.for_folder("MP/P1/ombstx/offline/00000011").station_name == "ST_NORTH"
    assert any("symbol table bağı okunamadı" in u for u in bm.unknown)


def test_s7h_hw_grouped_per_station(tmp_path):
    """HW export yokken .s7h dosyaları (<station ID hex>.s7h) station adıyla ayrı AS olur; F_TRIG F-System değildir."""
    from pcs7_analyzer.demo import _s7h
    proj = _project(tmp_path)
    st = proj / "hOmSave7" / "s7hstatx"
    (st / "21.s7h").write_bytes(_s7h([("6ES7 417-4HT14-0AB0", "V4.5"), ("6ES7 960-1AA04-0XA0", "")]))
    (st / "22.s7h").write_bytes(_s7h([("6ES7 410-5HX08-0AB0", "V8.1")]))
    (st / "99.s7h").write_bytes(_s7h([("6ES7 315-2EH14-0AB0", "V3.2")]))          # station listesinde yok
    an = analyze(tmp_path)
    by = {s.name: s for s in an.stations}
    assert set(by) == {"ST_NORTH", "ST_SOUTH", "P1"}
    assert by["ST_NORTH"].cpus[0][0] == "6ES7 417-4HT14-0AB0" and by["ST_NORTH"].station_text == "S7-400H"
    assert by["P1"].cpus[0][0] == "6ES7 315-2EH14-0AB0"
    from pcs7_analyzer.analyze import is_f_block_name
    assert not is_f_block_name("F_TRIG") and is_f_block_name("F_CH_DI")
