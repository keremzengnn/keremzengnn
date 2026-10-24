"""Revizyon farkı (revision.py): yeni / kapanan / değişen; anahtar = check_id + scope + title."""
import json

import pytest

from pcs7_analyzer.revision import diff, load_findings, previous_revision, render


def F(check_id, title="", scope="", fid="", **kw):
    d = {"check_id": check_id, "title": title, "scope": scope, "fid": fid, "status": "RİSK",
         "severity": "Orta", "guven": "KANIT", "detail": "d"}
    d.update(kw)
    return d


OLD = [F("LIB_SFC", "SFC block'ları", "AS01", "F-001"),
       F("HW_RELEASED", "Released listede yok", "AS02", "F-002"),
       F("LIB_APL_V8", "APL V8", "AS01", "F-003", severity="Düşük"),
       F("OS_DIFF", "Fark", "OS1", "F-004")]
NEW = [F("LIB_SFC", "SFC block'ları", "AS01", "F-010"),                     # aynı (sadece fid farklı)
       F("LIB_APL_V8", "APL V8", "AS01", "F-001", severity="Yüksek", status="BLOCKER"),
       F("OS_DIFF", "Fark", "OS1", "F-004", detail="yeni detay"),
       F("HW_RELEASED", "Released listede yok", "AS03", "F-005"),             # scope farklı -> yeni
       F("CAS_PH", "CAS", "", "F-006")]


@pytest.fixture
def d():
    return diff(OLD, NEW)


def test_new(d):
    assert [(f["check_id"], f["scope"]) for f in d["new"]] == [("CAS_PH", ""), ("HW_RELEASED", "AS03")]


def test_closed(d):
    assert [(f["check_id"], f["scope"], f["fid"]) for f in d["closed"]] == [("HW_RELEASED", "AS02", "F-002")]


def test_changed(d):
    ch = {tuple(c["key"]): c for c in d["changed"]}
    assert set(ch) == {("LIB_APL_V8", "AS01", "APL V8"), ("OS_DIFF", "OS1", "Fark")}
    apl = ch[("LIB_APL_V8", "AS01", "APL V8")]
    assert apl["fid"] == "F-001"                    # yeni rapordaki ID
    assert apl["changes"] == {"status": ("RİSK", "BLOCKER"), "severity": ("Düşük", "Yüksek")}
    assert ch[("OS_DIFF", "OS1", "Fark")]["changes"] == {"detail": ("d", "yeni detay")}


def test_fid_not_part_of_key():
    """Finding ID numaralandırması değişse de aynı bulgu 'değişmedi' sayılır."""
    a = [F("X", "t", "s", "F-001"), F("Y", "u", "", "F-002")]
    b = [F("Y", "u", "", "F-001"), F("X", "t", "s", "F-002")]
    assert diff(a, b) == {"new": [], "closed": [], "changed": []}


def test_title_part_of_key():
    r = diff([F("X", "eski başlık")], [F("X", "yeni başlık")])
    assert len(r["new"]) == 1 and len(r["closed"]) == 1 and not r["changed"]


def test_missing_fields_tolerated():
    """VERİ YOK satırları (findings.json'da title/scope/fid yok)."""
    r = diff([{"check_id": "Z", "status": "VERİ YOK", "detail": "a"}], [{"check_id": "Z", "status": "RİSK", "detail": "a"}])
    assert r["changed"][0]["changes"] == {"status": ("VERİ YOK", "RİSK")}
    assert r["changed"][0]["fid"] == ""


def test_render(d, tmp_path):
    md = render(d, tmp_path / "onceki_rapor", 3)
    assert md.startswith("# Revizyon r3")
    assert "Önceki: onceki_rapor" in md
    assert "- Yeni bulgu: 2" in md and "- Kapanan bulgu: 1" in md and "- Değişen bulgu: 2" in md
    assert "## Yeni bulgular" in md and "## Kapanan bulgular" in md and "## Değişen bulgular" in md
    assert "status: RİSK → BLOCKER" in md and "detay değişti" in md
    assert "Released listede yok (AS02)" in md


def test_render_no_changes(tmp_path):
    md = render(diff(OLD, OLD), tmp_path, 1)
    assert "- Yeni bulgu: 0" in md and "## " not in md


def test_load_and_previous_revision(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_findings(tmp_path)
    assert previous_revision(tmp_path) == 0
    (tmp_path / "findings.json").write_text(json.dumps(OLD, ensure_ascii=False), encoding="utf-8")
    assert load_findings(tmp_path) == OLD
    (tmp_path / "report_ir.json").write_text(json.dumps({"revision": 2}), encoding="utf-8")
    assert previous_revision(tmp_path) == 2
    (tmp_path / "report_ir.json").write_text("{bozuk", encoding="utf-8")
    assert previous_revision(tmp_path) == 0


def test_cli_compare_to(tmp_path):
    """İki demo çalıştırması: compare_to ile revizyon.md + IR'de revision artar; aynı girdi -> fark yok."""
    from pcs7_analyzer.cli import run
    from pcs7_analyzer.demo import build_demo_project
    bk = build_demo_project(tmp_path / "d")
    a, b = tmp_path / "a", tmp_path / "b"
    run(bk, a, log=lambda m: None)
    run(bk, b, log=lambda m: None, compare_to=a)
    md = (b / "revizyon.md").read_text(encoding="utf-8")
    assert "- Yeni bulgu: 0" in md and "- Kapanan bulgu: 0" in md and "- Değişen bulgu: 0" in md
    ir = json.loads((b / "report_ir.json").read_text(encoding="utf-8"))
    assert ir.get("revision") == previous_revision(a) + 1
