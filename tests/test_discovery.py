import json
import os

import pytest

from dbfwriter import SUBBLK_FIELDS, block, write_dbf
from pcs7_analyzer.discovery import discover, render_markdown


def _mk(root, rel, data=b"x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def project_tree(tmp_path):
    root = tmp_path / "backup"
    _mk(root, "MP/MP.s7f")
    _mk(root, "MP/As2/As2.s7p")
    write_dbf(_mk(root, "MP/As2/ombstx/offline/0000000a/SUBBLK.DBF"), SUBBLK_FIELDS,
              [block("00004", 1, "F", "X", author="AdvLib81")], memo="db4")
    _mk(root, "MP/As2/ombstx/offline/0000000a/BAUSTEIN.DBF")
    write_dbf(_mk(root, "MP/As2/ombstx/offline/0000000B/SUBBLK.DBF"), SUBBLK_FIELDS, [], memo=None)  # boş, DBT yok
    _mk(root, "MP/As2/ombstx/offline/notahex1/SUBBLK.DBF")              # 8 hex değil -> alınmaz
    _mk(root, "MP/As2/hOmSave7/s7hstatx/S00001.s7h")
    _mk(root, "MP/As2/YDBs/1/SYMLIST.DBF")
    _mk(root, "exports/AS2.cfg", b"FILEVERSION \"3.2\"\r\n#STEP7_VERSION V5.5 SP4\r\nSTATION S7400H , \"AS2\"\r\n")
    _mk(root, "exports/AS2_sym.ASC")
    _mk(root, "MP/Os/Os.s7p")
    os_root = "MP/Os/wincproj/OS_SRV1"
    _mk(root, f"{os_root}/OS_SRV1.mcp", b"\x00\x00V07.03.20.04\x00")
    _mk(root, f"{os_root}/TemplateControl.cfg", b"not hw config")
    for n in ["Tank_1.PDL", "Tank_2.pdl", "@PG_MotL.PDL", "@PCS7TypicalsAPL.PDL"]:
        _mk(root, f"{os_root}/GraCS/{n}")
    _mk(root, f"{os_root}/ScriptLib/Module1.bmo")
    _mk(root, f"{os_root}/ScriptAct/Global1.bac")
    _mk(root, f"{os_root}/SRV1PC/PAS/x.pas")
    _mk(root, "old/As2/As2.s7p")          # ikinci backup
    _mk(root, "backup2.zip")
    return root


def test_discover(project_tree):
    r = discover(project_tree)
    assert r.multiprojects == ["MP/MP.s7f"]
    assert sorted(r.projects) == ["MP/As2/As2.s7p", "MP/Os/Os.s7p", "old/As2/As2.s7p"]
    assert r.s7h_files == ["MP/As2/hOmSave7/s7hstatx/S00001.s7h"]
    assert r.cfg_exports == ["exports/AS2.cfg"]          # TemplateControl.cfg elenir
    assert r.symbol_tables == ["MP/As2/YDBs/1/SYMLIST.DBF"]
    assert r.symbol_exports == ["exports/AS2_sym.ASC"]
    assert r.archives == ["backup2.zip"]

    bfs = {b.path: b for b in r.block_folders}
    assert set(bfs) == {"MP/As2/ombstx/offline/0000000a", "MP/As2/ombstx/offline/0000000B"}
    full = bfs["MP/As2/ombstx/offline/0000000a"]
    assert full.n_records == 1 and full.has_baustein and full.dbt_size and full.project == "MP/As2"
    empty = bfs["MP/As2/ombstx/offline/0000000B"]
    assert empty.is_empty and empty.dbt_size is None

    (o,) = r.os_projects
    assert (o.path, o.project, o.mcp, o.wincc_build) == ("MP/Os/wincproj/OS_SRV1", "MP/Os", "OS_SRV1.mcp", "V07.03.20.04")
    assert (o.custom_pictures, o.faceplates_and_templates, o.vbs_modules, o.vbs_actions, o.c_actions) == (2, 2, 1, 1, 1)

    w = "\n".join(r.warnings)
    assert "0000000B: SUBBLK.DBT yok" in w
    assert "as2.s7p" in w and "backup" in w
    assert "arşiv" in w


def test_discover_zip_equals_folder(project_tree, tmp_path):
    import zipfile
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in sorted(project_tree.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(project_tree).as_posix())
    a, b = discover(project_tree), discover(z)
    for attr in ("multiprojects", "projects", "s7h_files", "cfg_exports", "symbol_tables", "symbol_exports", "archives"):
        assert sorted(getattr(a, attr)) == sorted(getattr(b, attr)), attr
    assert [(x.path, x.n_records, x.dbt_size) for x in a.block_folders] == [(x.path, x.n_records, x.dbt_size) for x in b.block_folders]
    assert [(o.path, o.custom_pictures, o.wincc_build) for o in a.os_projects] == [(o.path, o.custom_pictures, o.wincc_build) for o in b.os_projects]


def test_discover_is_read_only(project_tree):
    def snapshot():
        return sorted((p, os.stat(os.path.join(d, p)).st_mtime_ns)
                      for d, _, fs in os.walk(project_tree) for p in fs)
    before = snapshot()
    discover(project_tree)
    assert snapshot() == before


def test_render_and_json(project_tree):
    r = discover(project_tree)
    md = render_markdown(r)
    assert "## Block klasörleri (2)" in md and "| boş |" in md
    assert "V07.03.20.04" in md
    json.dumps(r.to_dict())


def test_dbt_date_mismatch_warning(tmp_path):
    d = tmp_path / "P/ombstx/offline/00000001"
    d.mkdir(parents=True)
    write_dbf(d / "SUBBLK.DBF", SUBBLK_FIELDS, [block("00010", 1, ssb=b"\x0a\x01\x00")], memo="db4")
    os.utime(d / "SUBBLK.DBT", (0, 0))
    assert any("tarihleri" in w for w in discover(tmp_path).warnings)
