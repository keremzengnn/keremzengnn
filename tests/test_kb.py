"""kb.py: offline doküman bilgi tabanı (sentetik arşiv, gerçek manual yok)."""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from pcs7_analyzer import kb
from pcs7_analyzer.model import Finding, Severity

if not kb.fts5_available():
    pytest.skip("sqlite3 bu Python'da FTS5 desteklemiyor (kb testleri atlandı)", allow_module_level=True)

SW_UPDATE = """# SIMATIC Process Control System PCS 7 Software update with utilization of new functions

Service Manual A5E52547920-AD

## 9.5 Updating SFC system blocks

The SFC system blocks FB245, FB246 and FC240 must be copied manually.

## 9.5.17 Compiling the CFC Charts

After the update, perform a complete compile of the CFC charts. The S7 F Failsafe Blocks
F-Library version 1.3 must be checked before compiling.

## 9.9.4 Logic Matrix

Upgrade without new functionality is not supported for Logic Matrix.
"""

OLD_MANUAL = """# SIMATIC PCS 7 Software update V9.1

## 7.1 Compiling the CFC Charts

Complete compile of the CFC charts in the old version.
"""

MISMATCH = """# Industrial Ethernet Switches Configuration Manual

## 2.1 Redundancy

Ring redundancy with media redundancy protocol.
"""


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "Siemens_Dokumanlar"
    _write(root / "PCS7_Version_Upgrade" / "Software_Update_V10.0_SP2.md", SW_UPDATE)
    _write(root / "PCS7_Genel" / "kopya" / "Software_Update_V10.0_SP2.md", SW_UPDATE)   # tekrar
    _write(root / "PCS7_Genel" / "Software_Update_V9.1.md", OLD_MANUAL)
    _write(root / "SCALANCE" / "Profinet_Diagnostics_V8.0.md", MISMATCH)
    _write(root / "Projeler" / "x.md", "# Gizli proje\n\nLogic Matrix müşteri")
    _write(root / "PCS7_Genel" / "_md_donusumler" / "y.md", "# Dönüşüm\n\nLogic Matrix tekrar")
    _write(root / "PCS7_Genel" / "Kurs_ST_PCS7" / "z.md", "# Kurs\n\nLogic Matrix kurs")
    _write(root / "Baska_Klasor" / "w.md", "# Dahil değil\n\nLogic Matrix")
    (root / "Safety").mkdir()
    (root / "Safety" / "F_Manual.pdf").write_bytes(b"%PDF-1.4 fake")
    return root


@pytest.fixture
def fake_pdftotext(monkeypatch, tmp_path):
    exe = tmp_path / "bin" / "pdftotext.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        assert "-layout" in cmd
        out = ("SIMATIC Safety Integrated\nS7 F/FH Systems Configuring and Programming\n"
               "A5E00048979-AM\n\f\f"
               "5.3 Safety program\nF-Library version 1.3 with F_CH_AI driver blocks.\n\f")
        return subprocess.CompletedProcess(cmd, 0, stdout=out.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(kb.subprocess, "run", fake_run)
    return str(exe), calls


@pytest.fixture
def db(archive, fake_pdftotext, tmp_path):
    db_path = tmp_path / "out" / "kb.sqlite"
    stats = kb.build(archive, db_path, log=lambda m: None, pdftotext=fake_pdftotext[0])
    return db_path, stats


def _q(db_path, sql, *args):
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def test_walk_include_exclude(archive):
    rels = {p.relative_to(archive).as_posix() for p in kb.iter_documents(archive)}
    assert rels == {
        "PCS7_Version_Upgrade/Software_Update_V10.0_SP2.md",
        "PCS7_Genel/kopya/Software_Update_V10.0_SP2.md",
        "PCS7_Genel/Software_Update_V9.1.md",
        "SCALANCE/Profinet_Diagnostics_V8.0.md",
        "Safety/F_Manual.pdf",
    }


def test_build_schema_and_dedupe(db):
    db_path, stats = db
    files = {r[0] for r in _q(db_path, "SELECT path FROM docs")}
    assert not any("Projeler" in f or "_md_donusumler" in f or "Kurs_" in f for f in files)
    assert len(files) == 5 and stats["docs"] == 5
    # 9.5.17 chunk'ı: tek FTS satırı, iki referans
    rows = _q(db_path, "SELECT content_hash FROM pages WHERE heading = ?", "9.5.17 Compiling the CFC Charts")
    assert len(rows) == 1
    refs = _q(db_path, "SELECT doc_id, page FROM page_refs WHERE content_hash = ?", rows[0][0])
    assert len(refs) == 2
    assert stats["pages_duplicate"] == 4   # Software_Update kopyasının 4 chunk'ı
    meta = dict(_q(db_path, "SELECT key, value FROM meta"))
    assert meta["schema_version"] == kb.SCHEMA_VERSION and meta["root"] and meta["built_at"]
    kinds = {r[0] for r in _q(db_path, "SELECT DISTINCT page_kind FROM pages")}
    assert kinds == {"chunk", "page"}


def test_metadata(db):
    db_path, _ = db
    docs = {r[0]: r[1:] for r in _q(db_path, "SELECT path, doc_title, product_version, doc_no, title_mismatch"
                                              " FROM docs")}
    title, ver, no, mm = docs["PCS7_Version_Upgrade/Software_Update_V10.0_SP2.md"]
    assert "Software update" in title and ver == "V10.0 SP2" and no == "A5E52547920-AD" and mm == 0
    _, ver8, _, mm8 = docs["SCALANCE/Profinet_Diagnostics_V8.0.md"]
    assert ver8 == "V8.0" and mm8 == 1
    ptitle, pver, pno, _ = docs["Safety/F_Manual.pdf"]
    assert "Safety Integrated" in ptitle and pno == "A5E00048979-AM" and pver is None


def test_pdf_pages_and_empty_page_unknown(db, fake_pdftotext):
    db_path, stats = db
    assert len(fake_pdftotext[1]) == 1     # tek çağrı / doküman
    pdf_pages = _q(db_path, "SELECT p.page FROM pages p JOIN docs d ON d.id = p.doc_id"
                            " WHERE d.file_name = 'F_Manual.pdf' ORDER BY p.page")
    assert [r[0] for r in pdf_pages] == [1, 3]
    assert _q(db_path, "SELECT pages FROM docs WHERE file_name='F_Manual.pdf'")[0][0] == 3
    assert stats["pages_empty"] == 1
    assert any("F_Manual.pdf" in u and kb.UNKNOWN_NO_TEXT in u and "s. 2" in u for u in stats["unknown"])


def test_missing_pdftotext(archive, tmp_path, monkeypatch):
    monkeypatch.setattr(kb.shutil, "which", lambda name: None)
    monkeypatch.setattr(kb, "WINDOWS_PDFTOTEXT_GLOBS", ())
    assert kb.find_pdftotext(str(tmp_path / "yok.exe")) is None
    stats = kb.build(archive, tmp_path / "kb2.sqlite", log=lambda m: None, pdftotext=str(tmp_path / "yok.exe"))
    # pdftotext yok -> yerleşik okuyucu denenir; sahte PDF okunamaz -> atlanır (sayılır, build durmaz)
    assert stats["pdftotext"] is None and stats["pdf_skipped"] == 1
    assert stats["skip_reasons"] == {kb.REASON_BROKEN: 1}
    assert any("F_Manual.pdf" in u and kb.REASON_BROKEN in u for u in stats["unknown"])
    assert stats["docs"] == 4


def test_db_inside_root_refused(archive):
    with pytest.raises(ValueError):
        kb.build(archive, archive / "kb.sqlite", log=lambda m: None)
    assert not (archive / "kb.sqlite").exists()


def test_search_ranking_and_ref_text(db):
    db_path, _ = db
    refs = kb.search(db_path, "Compiling the CFC Charts complete compile", limit=3)
    assert refs and refs[0].heading in ("9.5.17 Compiling the CFC Charts", "7.1 Compiling the CFC Charts")
    headings = [r.heading for r in refs]
    assert "9.5.17 Compiling the CFC Charts" in headings
    assert all(len(r.snippet) <= kb.SNIPPET_MAX for r in refs)
    lm = kb.search(db_path, "Logic Matrix upgrade", limit=3)
    assert lm[0].heading == "9.9.4 Logic Matrix"
    r = next(x for x in refs if x.heading.startswith("9.5.17"))
    assert kb.ref_text(r).startswith("Software_Update_V10.0_SP2.md (V10.0 SP2), bölüm ")
    assert kb.ref_text(r).endswith("— 9.5.17 Compiling the CFC Charts")


def test_search_version_note(db):
    db_path, _ = db
    refs = kb.search(db_path, "Compiling CFC Charts", target_version="V10.0SP2", limit=5)
    notes = {r.product_version: r.version_note for r in refs}
    assert notes.get("V10.0 SP2") == ""
    assert notes.get("V9.1") == "farklı sürüm"
    assert "[farklı sürüm]" in kb.ref_text(next(r for r in refs if r.product_version == "V9.1"))


def test_search_safe_and_missing_db(db, tmp_path):
    db_path, _ = db
    assert kb.search(tmp_path / "yok.sqlite", "Logic Matrix") == []
    assert isinstance(kb.search(db_path, '"" * ( ) NEAR OR AND ^ Logic:Matrix'), list)   # çökme yok
    assert kb.search(db_path, "") == []
    assert kb.match_expr(['a"b', "c*"]) == '"a b" OR "c"'


def test_refs_for_findings(db, tmp_path):
    db_path, _ = db
    findings = [
        Finding("LIB_LOGIC_MATRIX", "Logic Matrix kullanılıyor", Severity.HIGH, "AS1: 12 LM_Matrix instance"),
        Finding("LIB_SFC", "SFC system block'ları", Severity.MEDIUM, "FB245, FB246 bulundu"),
        Finding("XYZ", "Tamamen alakasız bulgu", Severity.LOW, "Kuantum QQQZ parametresi"),
    ]
    out = kb.refs_for_findings(db_path, findings, target_version="V10.0 SP2")
    assert out["LIB_LOGIC_MATRIX"] and out["LIB_LOGIC_MATRIX"][0].heading == "9.9.4 Logic Matrix"
    assert 1 <= len(out["LIB_LOGIC_MATRIX"]) <= 3
    assert out["LIB_SFC"] and out["LIB_SFC"][0].heading == "9.5 Updating SFC system blocks"
    assert out["XYZ"] == []
    assert kb.refs_for_findings(tmp_path / "yok.sqlite", findings) == {
        "LIB_LOGIC_MATRIX": [], "LIB_SFC": [], "XYZ": []}


def test_helpers():
    assert kb.find_version("Software_Update_V10.0_SP2") == "V10.0 SP2"
    assert kb.find_version("PCS7 V9.1 SP2 Upd1 readme") == "V9.1 SP2 Upd1"
    assert kb.find_version("Nothing here", "") is None
    assert kb.version_major_minor("V10.0SP2") == (10, 0)
    assert kb.page_heading("text\n9.5.17 Compiling the CFC Charts\nmore") == "9.5.17 Compiling the CFC Charts"
    assert kb.page_heading("6ES7 410-5HX08-0AB0\n2023 x") == ""
    assert kb.title_mismatch("SIMATIC_PCS7_Manual_en-US.pdf", "Some Title") is False
    assert kb.is_excluded(["PCS7_X", "kurs_abc"]) and not kb.is_excluded(["PCS7_X", "docs"])
    assert "APL" in kb.key_terms("APL V8.1 block'ları; TCiR yok; OB_DIAG")
    assert "TCiR" in kb.key_terms("TCiR yok") and "OB_DIAG" in kb.key_terms("OB_DIAG silinmeli")


def test_cli(db, capsys):
    db_path, _ = db
    assert kb.main(["search", "Logic Matrix", "--db", str(db_path), "--target", "V10.0SP2"]) == 0
    assert "9.9.4 Logic Matrix" in capsys.readouterr().out
    assert kb.main(["search", "x", "--db", str(db_path) + ".yok"]) == 2
