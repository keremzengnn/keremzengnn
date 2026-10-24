"""Report IR (report_ir.py): şema, Finding ID bağları, omitted, determinizm (demo projesiyle)."""
import json
from types import SimpleNamespace

import pytest

from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.readiness import finding_status
from pcs7_analyzer.report import build_document
from pcs7_analyzer.report_ir import PROFILES, SCHEMA_VERSION, build_ir, dumps, input_hash


@pytest.fixture(scope="module")
def an(tmp_path_factory):
    root = tmp_path_factory.mktemp("ir_demo")
    bk = build_demo_project(root)
    return analyze(bk, released_csv=root / "released_demo.csv")


@pytest.fixture(scope="module")
def ir(an):
    return build_ir(an, build_document(an, full=False), "teklif", "abc123", {"customer": "Demo"})


def test_schema_keys(ir):
    assert {"schema_version", "profile", "project_meta", "generated_at", "input_hash", "sections",
            "finding_ids", "stats", "omitted"} <= set(ir)
    assert ir["schema_version"] == SCHEMA_VERSION
    assert ir["profile"] == "teklif" and ir["input_hash"] == "abc123"
    assert ir["project_meta"] == {"customer": "Demo"}
    assert {"findings", "by_status", "not_checked", "stations", "os_projects", "block_folders", "unknown"} <= set(ir["stats"])
    for s in ir["sections"]:
        assert {"id", "title", "part", "blocks"} <= set(s)
        for b in s["blocks"]:
            assert "type" in b
    assert [s["id"] for s in ir["sections"]] == [f"s{i:02d}" for i in range(1, len(ir["sections"]) + 1)]
    json.loads(dumps(ir))     # serileştirilebilir


def test_parts_and_sections(ir):
    parts = {s["part"] for s in ir["sections"]}
    assert {"ÖZET", "RİSKLER"} <= parts
    assert any(s["title"] == "Zorluklar" for s in ir["sections"])


def test_every_finding_in_finding_ids(an, ir):
    fids = [f.fid for f in an.findings]
    assert all(fids) and len(set(fids)) == len(fids)
    assert ir["finding_ids"] == sorted(fids)
    assert ir["stats"]["findings"] == len(an.findings)
    assert sum(ir["stats"]["by_status"].values()) == len(an.findings)


def _table(ir, title):
    sec = next(s for s in ir["sections"] if s["title"] == title)
    return next(b for b in sec["blocks"] if b["type"] == "table")


def test_risk_table_rows_carry_finding_ids(an, ir):
    t = _table(ir, "Zorluklar")
    assert t["columns"][:2] == ["Konu", "Etki"]
    assert t["rows"]
    for r in t["rows"]:
        assert r["finding_ids"], r["cells"][0]["text"]
        assert set(r["finding_ids"]) <= set(ir["finding_ids"])
        assert all({"text", "assumption", "finding_ids"} <= set(c) for c in r["cells"])


def test_omitted_has_no_blocker_and_covers_rest(an, ir):
    blockers = {f.fid for f in an.findings if finding_status(f) == "BLOCKER"}
    omitted = {o["finding_id"] for o in ir["omitted"]}
    assert not blockers & omitted
    shown = set()
    for s in ir["sections"]:
        for b in s["blocks"]:
            shown.update(b.get("finding_ids", []))
            for r in b.get("rows", []):
                shown.update(r["finding_ids"])
            for it in b.get("items", []):
                shown.update(it["finding_ids"])
    assert shown | omitted == set(ir["finding_ids"])
    assert not shown & omitted
    for o in ir["omitted"]:
        assert {"finding_id", "check_id", "severity", "reason"} <= set(o)


def test_deterministic(an):
    def one():
        d = build_ir(an, build_document(an, full=False), "teklif", "h")
        d.pop("generated_at")
        return dumps(d)
    assert one() == one()


def test_profiles(an):
    assert PROFILES == {"teklif": False, "musteri": False, "muhendis": True}
    full = build_ir(an, build_document(an, full=True), "muhendis")
    short = build_ir(an, build_document(an, full=False), "teklif")
    assert full["profile"] == "muhendis"
    assert len(full["sections"]) > len(short["sections"])
    assert len(full["omitted"]) <= len(short["omitted"])


def test_assumption_flag_on_sentences(an):
    from pcs7_analyzer.report import Bullets, Heading, Note, Para, Table, Topline
    doc = [Topline("ÖZET"), Heading(1, "Özet"), Para("Eşleme heuristic, teyit edilmeli (F-001)."),
           Note("Not metni"), Bullets(["Madde F-002", "Kesin bilgi"]),
           Table(["A", "B"], [["x", "F-003 çıkarım"]], "Tablo", row_ids=[["F-004"]])]
    d = build_ir(an, doc)
    blocks = d["sections"][0]["blocks"]
    assert blocks[0] == {"type": "sentence", "text": "Eşleme heuristic, teyit edilmeli (F-001).",
                         "finding_ids": ["F-001"], "assumption": True}
    assert blocks[1]["type"] == "note" and not blocks[1]["assumption"]
    assert [i["finding_ids"] for i in blocks[2]["items"]] == [["F-002"], []]
    row = blocks[3]["rows"][0]
    assert row["finding_ids"] == ["F-003", "F-004"] and row["cells"][1]["assumption"]
    assert d["sections"][0]["part"] == "ÖZET" and d["sections"][0]["title"] == "Özet"


def test_input_hash_stable_and_order_independent():
    e = [SimpleNamespace(rel="a/b.dbf", size=10), SimpleNamespace(rel="c.s7p", size=3)]
    h = input_hash(e)
    assert h == input_hash(list(reversed(e))) and len(h) == 16
    assert h != input_hash([SimpleNamespace(rel="a/b.dbf", size=11), e[1]])
