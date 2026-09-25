import os

from pcs7_analyzer.parsers import compare_os, is_custom_picture, list_os_project, list_os_project_from_csv


def _mk(root, rel, data=b"x", mtime=None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if mtime:
        os.utime(p, (mtime, mtime))


def test_list_os_project_ignores_runtime_files(tmp_path):
    _mk(tmp_path, "GraCS/Tank_1.PDL")
    _mk(tmp_path, "OS.mcp")
    _mk(tmp_path, "OS.MDF")
    _mk(tmp_path, "ScriptLib/Module1.bmo")
    out = list_os_project(tmp_path)
    assert set(out) == {"gracs/tank_1.pdl", "scriptlib/module1.bmo"}


def test_compare_os_newer_and_only():
    es = {"gracs/a.pdl": (10, 100.0), "gracs/b.pdl": (10, 200.0), "gracs/es_only.pdl": (1, 1.0), "gracs/same.pdl": (5, 1.0)}
    srv = {"gracs/a.pdl": (11, 300.0), "gracs/b.pdl": (12, 100.0), "scriptact/global_new.bac": (1, 1.0), "gracs/same.pdl": (5, 9.0)}
    d = compare_os(es, srv)
    assert d["only_a"] == ["gracs/es_only.pdl"]
    assert d["only_b"] == ["scriptact/global_new.bac"]
    assert d["size_diff"] == ["gracs/a.pdl", "gracs/b.pdl"]   # aynı boyut -> fark sayılmaz (mtime farklı olsa da)
    assert d["newer_in_a"] == ["gracs/b.pdl"]
    assert d["newer_in_b"] == ["gracs/a.pdl"]


def test_list_os_project_from_csv(tmp_path):
    p = tmp_path / "srv.csv"
    rows = [
        '"FullName","Length","LastWriteTime"',
        r'"D:\Proj\OS\wincproj\OS_SRV1\GraCS\Tank_1.PDL","123","3/5/2024 1:02:03 PM"',
        r'"D:\Proj\OS\wincproj\OS_SRV1\OS_SRV1.mcp","9","3/5/2024 1:02:03 PM"',
        r'"D:\Proj\OS\wincproj\OS_SRV1\GraCS","","3/5/2024 1:02:03 PM"',
        r'"D:\Proj\OS\wincproj\OTHER\GraCS\X.PDL","1","3/5/2024 1:02:03 PM"',
        r'"D:\Proj\OS\wincproj\OS_SRV1\ScriptAct\a.bac","5","05.03.2024 13:02:03"',
        r'"D:\Proj\OS\wincproj\OS_SRV1\ScriptAct\b.bac","6","dün öğlen"',
    ]
    p.write_bytes(("\r\n".join(rows)).encode("utf-8-sig"))
    warns = []
    out = list_os_project_from_csv(p, "OS_SRV1", warns)
    assert out["gracs/tank_1.pdl"][0] == 123 and out["gracs/tank_1.pdl"][1] > 0
    assert "os_srv1.mcp" not in out and "gracs/x.pdl" not in out
    assert out["scriptact/a.bac"][1] > 0            # tr-TR tarih formatı da okunur
    assert out["scriptact/b.bac"] == (6, 0.0)       # okunamayan tarih: 0 + uyarı (sessiz değil)
    assert warns and "1 satırda tarih okunamadı" in warns[0]
    assert out["gracs"] == (0, out["gracs/tank_1.pdl"][1])


def test_is_custom_picture():
    assert is_custom_picture("gracs/tank_1.pdl")
    assert not is_custom_picture("gracs/@pg_motl.pdl")
    assert not is_custom_picture("gracs/@pcs7typicalsapl.pdl")
    assert not is_custom_picture("scriptlib/tank.pdl")
    assert not is_custom_picture("gracs/tank.bmp")
