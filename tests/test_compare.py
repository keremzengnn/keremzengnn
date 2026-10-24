"""İki backup karşılaştırması (compare.py): demo projesi A, kopyası + değişiklikler B. Sadece sentetik veri."""
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from dbfwriter import SUBBLK_FIELDS, block, write_dbf
from pcs7_analyzer import demo
from pcs7_analyzer.compare import (
    CIKARIM, KANIT, NEWER_B, ONLY_A, ONLY_B, DIFF, DiffRow, compare, compare_sources, write_outputs,
)
from pcs7_analyzer.source import open_source

FB = "00004"
T_NEW = demo.T0 + 20 * demo.DAY
AS01 = "DEMO_MP/AS01"
AS01_DBF = f"{AS01}/ombstx/offline/00000001/SUBBLK.DBF"
SRV = "DEMO_MP/OS/wincproj/OS_SRV1"


def _as01_records(tmp: Path, monkeypatch) -> list[dict]:
    """demo._as01'in SUBBLK kayıtlarını yakalar (yazmadan)."""
    got = {}
    monkeypatch.setattr(demo, "write_dbf", lambda path, fields, recs, **kw: got.setdefault(Path(path).parent.name, recs))
    demo._as01(tmp, "X", demo.T0)
    monkeypatch.undo()
    return [dict(r) for r in got["00000001"]]


def _rec(recs, nr):
    return next(r for r in recs if r["SUBBLKTYP"] == FB and r["BLKNUMBER"] == f"{nr:05d}")


@pytest.fixture(scope="module")
def sides(tmp_path_factory):
    root = tmp_path_factory.mktemp("cmp")
    a = demo.build_demo_project(root / "a")
    b = root / "b" / "DEMO_BACKUP"
    shutil.copytree(a, b)
    return a, b


def _mutate(b: Path, monkeypatch, tmp: Path) -> None:
    # 1) block: FB1990 VERSION 1.1 -> 1.2, FB1800 AdvLib81 -> AdvLib82, yeni FB2600
    recs = _as01_records(tmp, monkeypatch)
    _rec(recs, 1990)["VERSION"] = 0x12
    _rec(recs, 1800).update(USERNAME="AdvLib82", BLOCKFNAME="AdvLib82")
    recs.append(block(FB, 2600, "TEST", "NEW_FB", 0x10, "UK", lang="00001"))
    dbf = b / AS01_DBF
    write_dbf(dbf, SUBBLK_FIELDS, recs, memo="db4")
    for p in (dbf, dbf.with_suffix(".DBT")):
        os.utime(p, (T_NEW, T_NEW))
    # 2) HW geçmişi: yeni .s7h kaydı
    s7h = b / AS01 / "hOmSave7/s7hstatx/S00002.s7h"
    s7h.write_bytes(demo._s7h([("6ES7 414-5HM06-0AB0", "V6.0")]))
    os.utime(s7h, (T_NEW, T_NEW))
    # 3) OS: picture ekle / sil / touch, script içeriği değişti
    g = b / SRV / "GraCS"
    (g / "Tank_9.pdl").write_bytes(b"yeni picture")
    os.utime(g / "Tank_9.pdl", (T_NEW, T_NEW))
    (g / "Tank_1.pdl").unlink()
    os.utime(g / "Overview.pdl", (T_NEW, T_NEW))
    mod = b / SRV / "ScriptLib/Module1.bmo"
    mod.write_bytes(b"vbs degisti")
    os.utime(mod, (T_NEW, T_NEW))
    # 4) HW: AS02 CP firmware V3.0 -> V3.1
    cfg = b / "exports/AS02.cfg"
    cfg.write_bytes(cfg.read_bytes().replace(b'"6GK7 443-1EX30-0XE0" "V3.0"', b'"6GK7 443-1EX30-0XE0" "V3.1"'))


@pytest.fixture(scope="module")
def mutated(tmp_path_factory):
    root = tmp_path_factory.mktemp("cmpm")
    a = demo.build_demo_project(root / "a")
    b = root / "b" / "DEMO_BACKUP"
    shutil.copytree(a, b)
    mp = pytest.MonkeyPatch()
    try:
        _mutate(b, mp, root / "scratch")
    finally:
        mp.undo()
    return a, b, compare(a, b)


def _key(r: DiffRow):
    return (r.category, r.scope, r.item, r.change, r.a, r.b, r.confidence)


def _rows(res, *cats):
    return {_key(r) for r in res.rows if r.category in cats}


def test_identical_inputs_zero_rows(sides):
    a, _ = sides
    res = compare(a, a)
    assert res.rows == []
    assert res.evidence == []
    assert res.recommendation.endswith("Karar kullanıcıya aittir.")
    assert ("Fark satırı (toplam)", "0") in res.summary


def test_block_and_library_rows(mutated):
    _, _, res = mutated
    assert _rows(res, "Block", "Library") == {
        ("Block", "AS01", "FB1800 Pcs7DiIn", DIFF, "Pcs7DiIn, AdvLib81, 1.0", "Pcs7DiIn, AdvLib82, 1.0", KANIT),
        ("Block", "AS01", "FB1990 SINAMICS_G120", DIFF, "SINAMICS_G120, BM, 1.1", "SINAMICS_G120, BM, 1.2", KANIT),
        ("Block", "AS01", "FB2600 NEW_FB", ONLY_B, "", "NEW_FB, UK, 1.0", KANIT),
        ("Block", "AS01", "FB sayısı", DIFF, "12", "13", KANIT),
        ("Library", "AS01", "APL", DIFF, "AdvLib80: 1, AdvLib81: 2, AdvLib82: 1",
         "AdvLib80: 1, AdvLib81: 1, AdvLib82: 2", KANIT),
    }
    r = next(r for r in res.rows if r.item == "FB2600 NEW_FB")
    assert r.source_b == AS01_DBF and r.source_a == ""
    assert ("Block sayıları: AS01", "A: FB 12, FC 3, DB 23, OB 3 | B: FB 13, FC 3, DB 23, OB 3") in res.summary


def test_hw_rows(mutated):
    _, _, res = mutated
    assert _rows(res, "HW") == {
        ("HW", "AS02", "6GK7 443-1EX30-0XE0 V3.0", ONLY_A, "1 adet", "", KANIT),
        ("HW", "AS02", "6GK7 443-1EX30-0XE0 V3.1", ONLY_B, "", "1 adet", KANIT),
    }
    assert all(r.source_a == "exports/AS02.cfg" for r in res.rows if r.category == "HW")


def test_hw_history_rows(mutated):
    _, _, res = mutated
    rows = {(r.scope, r.item, r.change, r.confidence) for r in res.rows if r.category == "HW geçmişi"}
    assert rows == {("AS01", "s7h kayıt sayısı", DIFF, CIKARIM), ("AS01", "son s7h kaydı", NEWER_B, CIKARIM)}
    last = next(r for r in res.rows if r.item == "son s7h kaydı")
    assert last.source_b == f"{AS01}/hOmSave7/s7hstatx/S00002.s7h"
    assert last.b.startswith("2023-06-21")


def test_os_rows(mutated):
    _, _, res = mutated
    assert {(r.scope, r.item, r.change, r.confidence) for r in res.rows if r.category == "OS dosyası"} == {
        ("OS_SRV1", "GraCS/Tank_9.pdl", ONLY_B, KANIT),
        ("OS_SRV1", "GraCS/Tank_1.pdl", ONLY_A, KANIT),
        ("OS_SRV1", "GraCS/Overview.pdl", NEWER_B, CIKARIM),       # sadece tarih değişti (touch)
        ("OS_SRV1", "ScriptLib/Module1.bmo", NEWER_B, KANIT),      # boyut + tarih
    }
    r = next(r for r in res.rows if r.item == "GraCS/Tank_9.pdl")
    assert r.source_b == f"{SRV}/GraCS/Tank_9.pdl"      # ES içindeki OS_SRV1 (PC kopyası değil)


def test_nothing_else_differs(mutated):
    _, _, res = mutated
    assert {r.category for r in res.rows} == {"Block", "Library", "HW", "HW geçmişi", "OS dosyası"}
    assert len(res.rows) == 13


def test_evidence_and_recommendation(mutated):
    _, _, res = mutated
    ev = "\n".join(res.evidence)
    assert "SUBBLK.DBF (block klasörü) B tarafında daha yeni (A / B): AS01 (2023-06-01 12:00:00 / 2023-06-21" in ev
    assert "AS01: B tarafı 2023-06-01 12:00:00 tarihinden sonra 1 HW kaydı almış; A'yı baz almak" in ev
    assert "doğrudan download riski" in ev
    assert "B'de 2 dosya" in ev
    assert "B tarafının daha güncel" in res.recommendation
    assert res.recommendation.endswith("Karar kullanıcıya aittir.")


def test_write_outputs(mutated, tmp_path):
    _, _, res = mutated
    md = write_outputs(res, tmp_path)
    txt = md.read_text(encoding="utf-8")
    assert md.name == "fark.md" and "### Block (4)" in txt and "FB2600 NEW_FB" in txt and "Karar kullanıcıya aittir." in txt
    data = json.loads((tmp_path / "fark.json").read_text(encoding="utf-8"))
    assert len(data["rows"]) == len(res.rows) and data["rows"][0]["category"]
    with zipfile.ZipFile(tmp_path / "fark.xlsx") as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        assert "Kategori" in sheet and "NEW_FB" in sheet
        assert 'name="Ozet"' in z.read("xl/workbook.xml").decode()


def test_zip_input(mutated, tmp_path):
    a, b, res = mutated
    z = tmp_path / "B.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in sorted(b.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(b).as_posix())
    rz = compare(a, z)
    assert {_key(r) for r in rz.rows} == {_key(r) for r in res.rows}
    with open_source(b) as sb, open_source(z) as sz:      # klasör == zip (2 s zaman çözünürlüğü)
        assert compare_sources(sb, sz).rows == []


def test_side_without_os(sides, tmp_path):
    a, _ = sides
    b = tmp_path / "DEMO_BACKUP"
    shutil.copytree(a, b, ignore=shutil.ignore_patterns("wincproj"))
    res = compare(a, b)
    assert ("OS projeleri", "A: 8 | B: OS projesi yok") in res.summary
    os_rows = [r for r in res.rows if r.item.startswith("OS projesi ")]
    assert len(os_rows) == 8 and all(r.change == ONLY_A and r.category == "Proje" for r in os_rows)
    assert not [w for w in res.warnings if "tamamlanamadı" in w]
    rb = compare(b, a)                                     # ters yön de çökmemeli
    assert ("OS projeleri", "A: OS projesi yok | B: 8") in rb.summary


def test_corrupted_subblk_other_parts_still_compared(sides, tmp_path):
    a, _ = sides
    b = tmp_path / "DEMO_BACKUP"
    shutil.copytree(a, b)
    (b / AS01_DBF).write_bytes(b"\x03bozuk dosya" + b"\xff" * 40)
    cfg = b / "exports/AS02.cfg"
    cfg.write_bytes(cfg.read_bytes().replace(b'"V3.0"', b'"V3.1"'))
    res = compare(a, b)
    assert any("Block karşılaştırması yapılamadı: AS01" in w and "B:" in w for w in res.warnings)
    assert not [r for r in res.rows if r.category == "Block" and r.scope == "AS01"]
    assert ("HW", "AS02", "6GK7 443-1EX30-0XE0 V3.1", ONLY_B, "", "1 adet", KANIT) in {_key(r) for r in res.rows}
    assert res.recommendation.endswith("Karar kullanıcıya aittir.")


def test_source_not_modified(sides):
    a, _ = sides
    before = {p: (p.stat().st_size, p.stat().st_mtime) for p in a.rglob("*") if p.is_file()}
    compare(a, a)
    assert {p: (p.stat().st_size, p.stat().st_mtime) for p in a.rglob("*") if p.is_file()} == before


def test_wincc_export_rows(sides, tmp_path):
    a, _ = sides
    b = tmp_path / "DEMO_BACKUP"
    shutil.copytree(a, b)
    rows = [[str(1000 + i), f"TIC{i:03d}/Alarm#Value", "AS process control message", "Alarm High", "", f"TIC{i:03d}",
             "Area1", f"Tank {i} level high"] for i in range(10)]
    rows[2][7] = "Tank 2 level HIGH HIGH"
    rows.append(["5000", "NEW/Alarm#Value", "AS process control message", "", "", "", "Area1", "yeni alarm"])
    (b / "exports/wincc/OS_SRV1_Alarms.txt").write_bytes(demo._alarm_export(rows))
    res = compare(a, b)
    got = {(r.category, r.scope, r.item, r.change, r.a, r.b) for r in res.rows if r.category.startswith("Alarm")}
    assert got == {
        ("Alarm metni", "OS_SRV1", "1002", DIFF, "Tank 2 level high", "Tank 2 level HIGH HIGH"),
        ("Alarm", "OS_SRV1", "5000 NEW/Alarm#Value", ONLY_B, "", "yeni alarm"),
        ("Alarm", "OS_SRV1", "3001 TANKSRV_A/Conn", ONLY_A, "TANK_MASTER_SERVER connection lost", ""),
    }
