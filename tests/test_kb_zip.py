"""kb.py: zip kaynağı, yerleşik PDF okuyucu, artımlı build, rapor, digest (sentetik PDF/zip; gerçek manual yok)."""
from __future__ import annotations

import csv
import hashlib
import io
import shutil
import sqlite3
import subprocess
import zipfile
from pathlib import Path

import pytest

from _pdfgen import make_pdf
from pcs7_analyzer import kb

if not kb.fts5_available():
    pytest.skip("sqlite3 bu Python'da FTS5 desteklemiyor", allow_module_level=True)

README_PAGES = [
    ["SIMATIC PCS 7 Readme V10.0 SP2", "A5E12345678-AA"],
    ["9.9.4 Logic Matrix", "Upgrade without new functionality is not supported for Logic Matrix."],
    ["5.3 Compiling", "Perform a complete compile of the CFC charts. Zebrafisch"],
]
UPDATE_MD = "# PCS 7 Software update V10.0 SP2\n\n## 4.3 Requirements\n\nThe project must be V7.1 SP4 or higher.\n"
NOTES_TXT = "SIMATIC PCS 7 notes\n\nTCiR requires CPU 410-5H.\n"


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def _inner_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _members() -> dict[str, bytes]:
    w = "Siemens_Dokumanlar/"         # sarmalayıcı klasör (zip'in kökü)
    return {
        w + "PCS7_Readme/PCS7_Readme_V10.0_SP2.pdf": make_pdf(README_PAGES),
        w + "PCS7_Readme/Scanned_V9.1.pdf": make_pdf([[], []]),
        w + "PCS7_Readme/Locked.pdf": make_pdf(README_PAGES, encrypt=True),
        w + "PCS7_Upgrade/Software_Update_V10.0_SP2.md": UPDATE_MD.encode("utf-8"),
        w + "PCS7_Upgrade/notes.txt": NOTES_TXT.encode("utf-8"),
        w + "PCS7_Upgrade/Projeler/gizli.md": b"# Gizli\n\nLogic Matrix musteri",
        w + "PCS7_Upgrade/paket.zip": _inner_zip({
            "APL/APL_Readme_V9.1.pdf": make_pdf([["SIMATIC PCS 7 Advanced Process Library V9.1",
                                                 "APL TCiR is only possible with CPU 410-5H."]], use_tj=True),
            "APL/apl_notes.md": b"# APL notes\n\nMixed operation only with APL V9.0.\n",
            "APL/derin.zip": _inner_zip({"x.md": b"# Derin\n\nikinci seviye"}),
        }),
        w + "Baska_Klasor/disari.md": b"# Disari\n\nLogic Matrix",
    }


@pytest.fixture
def no_pdftotext(monkeypatch):
    monkeypatch.setattr(kb.shutil, "which", lambda name: None)
    monkeypatch.setattr(kb, "WINDOWS_PDFTOTEXT_GLOBS", ())


@pytest.fixture
def tmp_root(monkeypatch, tmp_path):
    """tempfile'ın kullandığı klasör: build sonrası boş kalmalı."""
    t = tmp_path / "_tmp"
    t.mkdir()
    monkeypatch.setattr(kb.tempfile, "tempdir", str(t))
    return t


def _q(db, sql, *a):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql, a).fetchall()
    finally:
        con.close()


def _sha(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- yerleşik PDF okuyucu
def test_fallback_reader_variants(tmp_path):
    lines = [["5.2 Restrictions", "Logic Matrix is not supported (Größe)."]]
    for kw in ({}, {"use_tj": True}, {"cid_font": True}, {"compress": False}):
        p = tmp_path / "x.pdf"
        p.write_bytes(make_pdf(lines, **kw))
        pages = kb.fallback_pdf_pages(p)
        assert pages == ["5.2 Restrictions\nLogic Matrix is not supported (Größe)."], kw


def test_fallback_reader_skips(tmp_path):
    enc = tmp_path / "enc.pdf"
    enc.write_bytes(make_pdf(README_PAGES, encrypt=True))
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(make_pdf([[], []]))
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    for p, reason in ((enc, kb.REASON_ENCRYPTED), (scan, kb.REASON_NO_TEXT), (junk, kb.REASON_BROKEN),
                      (empty, kb.REASON_BROKEN)):
        with pytest.raises(kb.PdfSkip) as e:
            kb.fallback_pdf_pages(p)
        assert str(e.value).startswith(reason), p.name


def test_fallback_reader_type0_without_tounicode(tmp_path):
    data = make_pdf([["Hidden text"]], cid_font=True)
    data = data.replace(b" /ToUnicode 3 0 R", b"")       # ToUnicode yok -> çözülemez
    p = tmp_path / "cid.pdf"
    p.write_bytes(data)
    with pytest.raises(kb.PdfSkip) as e:
        kb.fallback_pdf_pages(p)
    assert str(e.value) == kb.REASON_UNDECODABLE


def test_parse_cmap():
    m, w = kb.parse_cmap(b"1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
                         b"2 beginbfchar <0003> <0020> <0011> <00410042> endbfchar\n"
                         b"1 beginbfrange <0020> <0022> <0061> endbfrange\n"
                         b"1 beginbfrange <0030> <0031> [<0058> <0059>] endbfrange")
    assert w == 2 and m[3] == " " and m[0x11] == "AB" and m[0x21] == "b" and m[0x31] == "Y"


# --------------------------------------------------------------------------- zip build
def test_zip_build_fallback(tmp_path, no_pdftotext, tmp_root):
    src = _zip(tmp_path / "in" / "Siemens.zip", _members())
    before = _sha(src)
    db = tmp_path / "out" / "kb.sqlite"
    logs: list[str] = []
    st = kb.build(src, db, log=logs.append, progress_every=2)

    assert _sha(src) == before and sorted(p.name for p in src.parent.iterdir()) == ["Siemens.zip"]
    assert list(tmp_root.iterdir()) == []                 # temp'e çıkarılan PDF/zip'ler silindi
    assert st["mode"] == "include" and st["source_kind"] == "zip" and st["completed"]
    assert any("Mod: include" in m for m in logs) and any("/" in m and "dosya," in m for m in logs)

    paths = {r[0]: r[1:] for r in _q(db, "SELECT path, method, quality, top FROM docs")}
    w = "Siemens_Dokumanlar/"
    assert set(paths) == {
        w + "PCS7_Readme/PCS7_Readme_V10.0_SP2.pdf",
        w + "PCS7_Upgrade/Software_Update_V10.0_SP2.md",
        w + "PCS7_Upgrade/notes.txt",
        w + "PCS7_Upgrade/paket.zip/APL/APL_Readme_V9.1.pdf",
        w + "PCS7_Upgrade/paket.zip/APL/apl_notes.md",
    }
    assert paths[w + "PCS7_Readme/PCS7_Readme_V10.0_SP2.pdf"] == ("fallback", "low", "PCS7_Readme")
    assert paths[w + "PCS7_Upgrade/notes.txt"] == ("text", "", "PCS7_Upgrade")
    assert paths[w + "PCS7_Upgrade/paket.zip/APL/APL_Readme_V9.1.pdf"][2] == "PCS7_Upgrade"

    assert st["pdf_methods"] == {"pdftotext": 0, "fallback": 2}
    assert st["pdf_skipped"] == 2
    assert st["skip_reasons"][kb.REASON_ENCRYPTED] == 1 and st["skip_reasons"][kb.REASON_NO_TEXT] == 1
    assert any("derin.zip" in u and "2. seviye" in u for u in st["unknown"])

    refs = kb.search(db, "Logic Matrix upgrade", limit=3)
    assert refs and refs[0].heading == "9.9.4 Logic Matrix" and refs[0].page == 2
    assert refs[0].quality == "low" and kb.ref_text(refs[0]).endswith(f"[{kb.QUALITY_LOW_TEXT}]")
    apl = kb.search(db, "TCiR only possible", limit=3)
    assert any(r.file_name == "APL_Readme_V9.1.pdf" for r in apl)

    rep = (db.parent / kb.REPORT_NAME).read_text(encoding="utf-8")
    assert "Locked.pdf" in rep and kb.REASON_ENCRYPTED in rep and "Scanned_V9.1.pdf" in rep
    assert "PCS7_Readme" in rep and "PCS7_Upgrade" in rep and "Mod        : include" in rep
    assert "Zebrafisch" not in rep and "Logic Matrix is" not in rep          # içerik yok, sadece adlar
    assert st["summary"]["docs"] == 5 and st["db_size"] > 0


def test_zip_without_include_tops_indexes_all(tmp_path, no_pdftotext, tmp_root):
    src = _zip(tmp_path / "docs.zip", {
        "Readmes/a.md": b"# PCS 7 a\n\nLogic Matrix",
        "Manuals/Sub/b.pdf": make_pdf([["SIMATIC PCS 7 Manual", "Logic Matrix restriction"]]),
        "top.txt": b"Kokteki dosya PCS 7",
        "Kurs_X/c.md": b"# kurs",
    })
    logs: list[str] = []
    st = kb.build(src, tmp_path / "kb.sqlite", log=logs.append)
    assert st["mode"] == "all" and any("Mod: all" in m for m in logs)
    tops = dict(_q(tmp_path / "kb.sqlite", "SELECT path, top FROM docs"))
    assert tops == {"Readmes/a.md": "Readmes", "Manuals/Sub/b.pdf": "Manuals", "top.txt": kb.ROOT_TOP}


def test_folder_all_flag(tmp_path, no_pdftotext):
    root = tmp_path / "arsiv"
    for rel, txt in (("PCS7_A/a.md", "# a\n\nx"), ("Diger/b.md", "# b\n\ny"), ("Diger/Projeler/c.md", "# c")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt, encoding="utf-8")
    assert kb.build(root, tmp_path / "1.sqlite", log=lambda m: None)["mode"] == "include"
    assert {r[0] for r in _q(tmp_path / "1.sqlite", "SELECT path FROM docs")} == {"PCS7_A/a.md"}
    st = kb.build(root, tmp_path / "2.sqlite", log=lambda m: None, all_files=True)
    assert st["mode"] == "all"
    assert {r[0] for r in _q(tmp_path / "2.sqlite", "SELECT path FROM docs")} == {"PCS7_A/a.md", "Diger/b.md"}


def test_incremental_rebuild_and_prune(tmp_path, no_pdftotext, tmp_root):
    members = _members()
    src = _zip(tmp_path / "s.zip", members)
    db = tmp_path / "kb.sqlite"
    first = kb.build(src, db, log=lambda m: None)
    assert first["docs"] == 5

    again = kb.build(src, db, log=lambda m: None)
    assert again["docs"] == 0 and again["pruned"] == 0
    assert again["unchanged"] == 6          # 3 doküman + 2 atlanan PDF + iç zip (içi hiç açılmaz)
    assert again["summary"]["docs"] == 5

    w = "Siemens_Dokumanlar/"
    members[w + "PCS7_Upgrade/notes.txt"] = b"SIMATIC PCS 7 notes\n\nTCiR requires CPU 410-5H V8.2.\n"
    del members[w + "PCS7_Upgrade/Software_Update_V10.0_SP2.md"]
    src.unlink()
    _zip(src, members)
    third = kb.build(src, db, log=lambda m: None)
    assert third["docs"] == 1 and third["pruned"] == 1
    paths = {r[0] for r in _q(db, "SELECT path FROM docs")}
    assert w + "PCS7_Upgrade/Software_Update_V10.0_SP2.md" not in paths and len(paths) == 4
    assert kb.search(db, "V7.1 SP4 must") == [] or all(
        "Software_Update" not in r.file_name for r in kb.search(db, "V7.1 SP4 must"))
    assert _q(db, "SELECT COUNT(*) FROM page_refs WHERE doc_id NOT IN (SELECT id FROM docs)") == [(0,)]


def test_dedupe_survives_deleting_first_copy(tmp_path, no_pdftotext):
    root = tmp_path / "a"
    for rel in ("PCS7_A/one.md", "PCS7_B/two.md"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# Logic Matrix\n\nLogic Matrix is not supported.\n", encoding="utf-8")
    db = tmp_path / "kb.sqlite"
    kb.build(root, db, log=lambda m: None)
    (root / "PCS7_A/one.md").unlink()
    st = kb.build(root, db, log=lambda m: None)
    assert st["pruned"] == 1
    refs = kb.search(db, "Logic Matrix supported")
    assert refs and refs[0].file_name == "two.md"


def test_resume_after_interrupt(tmp_path, no_pdftotext, monkeypatch):
    root = tmp_path / "a"
    for i in range(5):
        p = root / "PCS7_A" / f"d{i}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# Doc {i}\n\ntext {i}\n", encoding="utf-8")
    db = tmp_path / "kb.sqlite"
    real = kb.text_chunks
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return real(text)

    monkeypatch.setattr(kb, "text_chunks", flaky)
    with pytest.raises(KeyboardInterrupt):
        kb.build(root, db, log=lambda m: None)
    monkeypatch.setattr(kb, "text_chunks", real)
    st = kb.build(root, db, log=lambda m: None)
    assert st["unchanged"] == 2 and st["docs"] == 3 and st["summary"]["docs"] == 5


def test_fallback_docs_retried_when_pdftotext_appears(tmp_path, no_pdftotext, monkeypatch):
    src = _zip(tmp_path / "s.zip", {"PCS7_A/r.pdf": make_pdf(README_PAGES)})
    db = tmp_path / "kb.sqlite"
    assert kb.build(src, db, log=lambda m: None)["pdf_methods"]["fallback"] == 1
    exe = tmp_path / "pdftotext.exe"
    exe.write_bytes(b"")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"SIMATIC PCS 7 Readme\n\fLogic Matrix\n\f", stderr=b"")

    monkeypatch.setattr(kb.subprocess, "run", fake_run)
    st = kb.build(src, db, log=lambda m: None, pdftotext=str(exe))
    assert st["pdf_methods"] == {"pdftotext": 1, "fallback": 0} and st["docs"] == 1
    assert _q(db, "SELECT method, quality FROM docs") == [("pdftotext", "")]
    assert kb.build(src, db, log=lambda m: None, pdftotext=str(exe))["unchanged"] == 1


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) kurulu değil")
def test_zip_with_real_pdftotext(tmp_path, tmp_root):
    src = _zip(tmp_path / "s.zip", {"PCS7_A/r.pdf": make_pdf(README_PAGES),
                                    "PCS7_A/enc.pdf": make_pdf(README_PAGES, encrypt=True)})
    st = kb.build(src, tmp_path / "kb.sqlite", log=lambda m: None)
    assert st["pdf_methods"]["pdftotext"] == 1 and st["skip_reasons"] == {kb.REASON_ENCRYPTED: 1}
    assert list(tmp_root.iterdir()) == []
    refs = kb.search(tmp_path / "kb.sqlite", "Logic Matrix")
    assert refs and refs[0].page == 2 and refs[0].quality == ""


def test_old_schema_rebuilt_and_db_guard(tmp_path, no_pdftotext):
    src = _zip(tmp_path / "s.zip", {"PCS7_A/a.md": b"# a\n\nLogic Matrix"})
    db = tmp_path / "kb.sqlite"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
                      "INSERT INTO meta VALUES ('schema_version', '1');")
    con.close()
    logs: list[str] = []
    assert kb.build(src, db, log=logs.append)["docs"] == 1
    assert any("baştan" in m for m in logs)
    with pytest.raises(ValueError):
        kb.build(src, src, log=lambda m: None)
    with pytest.raises(ValueError):
        kb.build(_not_zip(tmp_path), db, log=lambda m: None)


def _not_zip(tmp_path: Path) -> Path:
    p = tmp_path / "x.txt"
    p.write_text("x")
    return p


def test_default_db_in_settings_dir(tmp_path, no_pdftotext, monkeypatch, capsys):
    from pcs7_analyzer import settings
    monkeypatch.setenv("APPDATA", str(tmp_path / "app data #1"))
    monkeypatch.chdir(tmp_path)
    src = _zip(tmp_path / "s.zip", {"PCS7_A/a.md": b"# Logic Matrix\n\nLogic Matrix is not supported."})
    assert kb.main(["build", "--root", str(src)]) == 0
    expected = tmp_path / "app data #1" / "pcs7_analyzer" / "kb.sqlite"
    assert expected.is_file() and (expected.parent / kb.REPORT_NAME).is_file()
    assert settings.find_kb() == expected
    assert kb.main(["search", "Logic Matrix"]) == 0
    assert "a.md" in capsys.readouterr().out


# --------------------------------------------------------------------------- digest
DIGEST_DOC = """# SIMATIC PCS 7 Readme V10.0 SP2

## 1 Introduction

This document describes the product family overview and is long enough to be a paragraph.

## 5 Notes on installation

The installation takes about two hours on a typical engineering station without network access.

### 5.1 Details

Second level text inside notes section also kept completely here.

## 6 Restrictions

Faceplates of APL V8.1 are not supported in V10.0 SP2 mixed operation mode, plan migration.

## 7 Hardware

Note

The plain paragraph after the note box is kept verbatim even without any keywords at all.

Unrelated paragraph that has no keywords and should therefore not appear in the digest output.

CPU 410-5H   6ES7 410-5HX08-0AB0   firmware V8.2.3
Some random filler line without anything

## 8 Something else

The Logic Matrix must be compiled again after the upgrade to V10.0 with CFC.
"""
IRRELEVANT = "# Kochbuch\n\n## 2 Notes\n\nThe soup must be stirred, upgrade not supported in V10.0.\n"


def _digest_kb(tmp_path, extra: dict[str, str] | None = None) -> Path:
    root = tmp_path / "docs"
    files = {"PCS7_A/readme_V10.0_SP2.md": DIGEST_DOC, "PCS7_A/zz_copy.md": DIGEST_DOC,
             "PCS7_B/kochbuch.md": IRRELEVANT, **(extra or {})}
    for rel, txt in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt, encoding="utf-8")
    db = tmp_path / "kb.sqlite"
    kb.build(root, db, log=lambda m: None)
    return db


def _read_parts(st) -> str:
    return "".join(Path(p).read_text(encoding="utf-8") for p in st["parts"])


def test_digest_selection(tmp_path):
    db = _digest_kb(tmp_path)
    st = kb.digest(db, tmp_path / "out" / "kb_ozet.md", log=lambda m: None)
    assert [Path(p).name for p in st["parts"]] == ["kb_ozet_01.md"]
    text = _read_parts(st)
    assert "## readme_V10.0_SP2.md (V10.0 SP2)" in text
    assert "about two hours" in text and "Second level text" in text          # bölümün tamamı
    assert "bölüm: 5 Notes on installation" in text
    assert "APL V8.1 are not supported" in text and "bölüm: 6 Restrictions" in text
    assert "kept verbatim even without any keywords" in text and "uyarı: Note" in text
    assert "6ES7 410-5HX08-0AB0" in text and ", tablo]" in text
    assert "Some random filler" not in text and "Unrelated paragraph" not in text
    assert "product family overview" not in text
    assert "Logic Matrix must be compiled" in text
    assert "Kochbuch" not in text and "soup" not in text                        # ilgisiz doküman
    assert text.count("about two hours") == 1 and st["duplicates"] > 0           # tekrar bir kez

    rows = list(csv.DictReader(open(st["index"], encoding="utf-8-sig")))
    by = {r["doc"]: r for r in rows}
    assert set(by) == {"readme_V10.0_SP2.md", "zz_copy.md", "kochbuch.md"}         # hepsi listelenir
    assert by["kochbuch.md"]["relevant"] == "hayır" and by["kochbuch.md"]["passages"] == "0"
    assert by["zz_copy.md"]["passages"] == "0" and by["zz_copy.md"]["relevant"] == "evet"
    assert int(by["zz_copy.md"]["duplicate_passages"]) >= 10
    assert int(by["readme_V10.0_SP2.md"]["pages_kept"]) >= 4
    assert by["readme_V10.0_SP2.md"]["pages_total"] == "7" and by["readme_V10.0_SP2.md"]["parts"] == "01"


def test_digest_parts_deterministic_and_tum(tmp_path):
    big = "# PCS 7 Big V10.0\n\n" + "".join(
        f"## {i} Topic {i}\n\nThe block FB{i} must be updated for V10.0 in PCS 7 project number {i}.\n\n"
        for i in range(1, 800))
    db = _digest_kb(tmp_path, {"PCS7_C/big.md": big})
    out = tmp_path / "o" / "kb_ozet.md"
    st = kb.digest(db, out, part_mb=0.02, log=lambda m: None)
    assert len(st["parts"]) >= 3
    for p in st["parts"]:
        assert Path(p).stat().st_size <= 0.02 * (1 << 20) + 1000
    text = _read_parts(st)
    for i in (1, 400, 799):
        assert f"FB{i} must be updated" in text                                 # toplamda kayıp yok
    assert "## big.md (V10.0) (devam)" in text
    first = [Path(p).read_bytes() for p in st["parts"]]
    st2 = kb.digest(db, out, part_mb=0.02, log=lambda m: None)
    assert [Path(p).read_bytes() for p in st2["parts"]] == first                # deterministik

    st3 = kb.digest(db, out, part_mb=4, tum=True, log=lambda m: None)
    assert len(st3["parts"]) == 1 and not (out.parent / "kb_ozet_02.md").exists()   # eski parçalar temizlendi
    full = _read_parts(st3)
    assert "product family overview" in full and "Some random filler" in full and "soup" not in full


def test_digest_cli(tmp_path, monkeypatch):
    db = _digest_kb(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert kb.main(["digest", "--db", str(db)]) == 0
    assert (tmp_path / "kb_ozet_01.md").is_file() and (tmp_path / "kb_ozet_index.csv").is_file()
    assert kb.main(["digest", "--db", str(tmp_path / "yok.sqlite")]) == 2


def test_passage_score():
    assert kb.passage_score("Logic Matrix is not supported in V10.0 SP2.") > kb.passage_score(
        "Logic Matrix is not supported in V8.0.") > 0
    assert kb.passage_score("The soup is hot.") == 0
    assert kb.passage_score("You must stir.") == 0          # kural var ama terim/versiyon yok
