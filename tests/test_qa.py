"""Rapor QA kapısı (qa.py): her QA kontrolü için en az bir 'bozuk' fixture + temiz demo çalıştırması 0 HATA."""
import json
import zipfile
from pathlib import Path

import pytest

from pcs7_analyzer import qa
from pcs7_analyzer.qa import HATA, QA_CHECKS, UYARI, run_qa, write_report
from pcs7_analyzer.xlsx import Workbook

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ---------------- fixture yardımcıları ----------------
def _run(text, highlight=False, direct=()):
    rpr = ""
    if highlight or direct:
        inner = '<w:highlight w:val="yellow"/>' if highlight else ""
        inner += "".join({"rFonts": '<w:rFonts w:ascii="Arial"/>', "color": '<w:color w:val="FF0000"/>',
                          "sz": '<w:sz w:val="20"/>'}[d] for d in direct)
        rpr = f"<w:rPr>{inner}</w:rPr>"
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _p(*runs):
    return "<w:p>" + "".join(r if r.startswith("<w:r>") else _run(r) for r in runs) + "</w:p>"


def _tbl(rows, repeat_header=True, cant_split=True):
    out = []
    for i, r in enumerate(rows):
        tr_pr = ""
        if i == 0 and repeat_header:
            tr_pr = "<w:trPr><w:tblHeader/></w:trPr>"
        elif i > 0 and cant_split:
            tr_pr = "<w:trPr><w:cantSplit/></w:trPr>"
        out.append(f"<w:tr>{tr_pr}" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in r) + "</w:tr>")
    return "<w:tbl>" + "".join(out) + "</w:tbl>"


def write_docx(path: Path, body: str) -> Path:
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W_NS}">'
           f"<w:body>{body}</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)
    return path


def write_xlsx(path: Path, sheets: dict) -> Path:
    wb = Workbook()
    for name, rows in sheets.items():
        wb.add_sheet(name, rows, header_rows={0})
    return wb.save(path)


def write_json(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def checks(folder) -> dict:
    issues, _ = run_qa(folder)
    out = {}
    for i in issues:
        out.setdefault(i.check, []).append(i)
    return out


def _ir(**kw):
    ir = {"schema_version": "1", "profile": "teklif", "sections": [], "finding_ids": [],
          "stats": {"by_status": {}, "not_checked": 0}, "omitted": []}
    ir.update(kw)
    return ir


# ---------------- kontrol başına bozuk fixture ----------------
def test_placeholder_md(tmp_path):
    (tmp_path / "rapor.md").write_text("# Rapor\n\nCPU firmware: TODO\n", encoding="utf-8")
    c = checks(tmp_path)
    assert c["PLACEHOLDER"][0].level == HATA
    assert c["PLACEHOLDER"][0].where == "rapor.md:3"


def test_placeholder_docx_na(tmp_path):
    write_docx(tmp_path / "rapor.docx", _p("Firmware: N/A"))
    assert "PLACEHOLDER" in checks(tmp_path)


def test_placeholder_not_for_path_like(tmp_path):
    (tmp_path / "rapor.md").write_text("Bağlantı I/N/A tipi; TODOS değil\n", encoding="utf-8")
    assert "PLACEHOLDER" not in checks(tmp_path)


def test_no_action(tmp_path):
    write_json(tmp_path / "findings.json", [
        {"fid": "F-001", "check_id": "LIB_SFC", "status": "BLOCKER", "action": ""},
        {"fid": "F-002", "check_id": "X", "status": "RİSK", "action": "Recompile"},
        {"fid": "F-003", "check_id": "Y", "status": "BİLGİ"}])
    c = checks(tmp_path)
    assert [i.message.split(":")[0] for i in c["NO_ACTION"]] == ["F-001"]
    assert c["NO_ACTION"][0].level == HATA


def test_glossary_forbidden(tmp_path):
    (tmp_path / "rapor.md").write_text("Tüm AS'ler için derleme yapılmalı.\n", encoding="utf-8")
    c = checks(tmp_path)
    assert c["GLOSSARY"][0].level == HATA
    assert "compile" in c["GLOSSARY"][0].message


def test_glossary_english_ok(tmp_path):
    (tmp_path / "rapor.md").write_text("Complete compile ve firewall kontrolü.\n", encoding="utf-8")
    assert "GLOSSARY" not in checks(tmp_path)


def test_counts_mismatch_ir_findings(tmp_path):
    write_json(tmp_path / "findings.json", [{"fid": "F-001", "status": "RİSK", "action": "a"},
                                            {"fid": "F-002", "status": "BİLGİ"}])
    write_json(tmp_path / "report_ir.json", _ir(stats={"by_status": {"RİSK": 2}, "not_checked": 0}))
    c = checks(tmp_path)
    assert c["COUNTS"][0].level == HATA


def test_counts_mismatch_excel(tmp_path):
    write_json(tmp_path / "findings.json", [{"fid": "F-001", "status": "RİSK", "action": "a"},
                                            {"check_id": "Z", "status": "VERİ YOK"}])
    write_json(tmp_path / "report_ir.json", _ir(stats={"by_status": {"RİSK": 1}, "not_checked": 1}))
    write_xlsx(tmp_path / "rapor.xlsx", {"Bulgular": [["ID", "Bulgu", "Durum"], ["F-001", "x", "BLOCKER"],
                                                      ["", "z", "VERİ YOK"]]})
    c = checks(tmp_path)
    assert [i.where for i in c["COUNTS"]] == ["rapor.xlsx/Bulgular"]


def test_counts_consistent(tmp_path):
    write_json(tmp_path / "findings.json", [{"fid": "F-001", "status": "RİSK", "action": "a"},
                                            {"check_id": "Z", "status": "VERİ YOK"}])
    write_json(tmp_path / "report_ir.json", _ir(stats={"by_status": {"RİSK": 1}, "not_checked": 1}))
    write_xlsx(tmp_path / "rapor.xlsx", {"Bulgular": [["ID", "Bulgu", "Durum"], ["F-001", "x", "RİSK"],
                                                      ["", "z", "VERİ YOK"]]})
    assert "COUNTS" not in checks(tmp_path)


def test_highlight_missing(tmp_path):
    write_docx(tmp_path / "rapor.docx", _p(_run("Station eşlemesi heuristic, teyit edilmeli.")))
    c = checks(tmp_path)
    assert c["HIGHLIGHT"][0].level == HATA


def test_highlight_ok(tmp_path):
    write_docx(tmp_path / "rapor.docx", _p(_run("Station eşlemesi heuristic, teyit edilmeli.", highlight=True)))
    assert "HIGHLIGHT" not in checks(tmp_path)


def test_direct_format(tmp_path):
    write_docx(tmp_path / "rapor.docx", _p(_run("Kırmızı metin", direct=("color", "sz"))))
    c = checks(tmp_path)
    assert c["DIRECT_FORMAT"][0].level == HATA
    assert "color" in c["DIRECT_FORMAT"][0].message and "sz" in c["DIRECT_FORMAT"][0].message


def test_excel_error(tmp_path):
    write_xlsx(tmp_path / "rapor.xlsx", {"Ozet": [["A", "B"], ["x", "#REF!"]]})
    c = checks(tmp_path)
    assert c["EXCEL_ERROR"][0].level == HATA
    assert c["EXCEL_ERROR"][0].where == "rapor.xlsx/Ozet satır 2"


def test_empty_section(tmp_path):
    write_json(tmp_path / "report_ir.json", _ir(sections=[
        {"id": "s01", "title": "ÖZET", "blocks": [{"type": "sentence", "text": "x"}]},
        {"id": "s02", "title": "Zorluklar", "blocks": []}]))
    c = checks(tmp_path)
    assert len(c["EMPTY_SECTION"]) == 1 and "Zorluklar" in c["EMPTY_SECTION"][0].message


def test_omitted_blocker(tmp_path):
    write_json(tmp_path / "findings.json", [{"fid": "F-001", "status": "BLOCKER", "action": "a"},
                                            {"fid": "F-002", "status": "BİLGİ"}])
    write_json(tmp_path / "report_ir.json", _ir(omitted=[{"finding_id": "F-001"}, {"finding_id": "F-002"}]))
    c = checks(tmp_path)
    assert [i.message for i in c["OMITTED_BLOCKER"]] == ["BLOCKER rapora girmedi: F-001"]


def test_mask_musteri_profile(tmp_path):
    (tmp_path / "rapor.md").write_text("OS server 192.168.0.10\npassword: gizli123\n", encoding="utf-8")
    write_json(tmp_path / "report_ir.json", _ir(profile="musteri"))
    c = checks(tmp_path)
    assert {i.message for i in c["MASK"]} == {"maskelenmemiş IP adresi", "maskelenmemiş şifre"}


def test_mask_only_for_musteri(tmp_path):
    (tmp_path / "rapor.md").write_text("OS server 192.168.0.10\n", encoding="utf-8")
    write_json(tmp_path / "report_ir.json", _ir(profile="teklif"))
    assert "MASK" not in checks(tmp_path)


def test_cell_words(tmp_path):
    long = " ".join(["kelime"] * 30)
    write_docx(tmp_path / "rapor.docx", _tbl([["Konu", "Açıklama"], ["A", long]]))
    c = checks(tmp_path)
    assert c["CELL_WORDS"][0].level == UYARI and "en uzun 30" in c["CELL_WORDS"][0].message


def test_table_layout(tmp_path):
    write_docx(tmp_path / "rapor.docx", _tbl([["Konu", "Etki"], ["A", "Orta"]], repeat_header=False, cant_split=False))
    c = checks(tmp_path)
    assert c["TABLE_HEADER"][0].level == UYARI
    assert c["TABLE_SPLIT"][0].level == UYARI


def test_table_layout_ok(tmp_path):
    write_docx(tmp_path / "rapor.docx", _tbl([["Konu", "Etki"], ["A", "Orta"], ["B", "Düşük"]]))
    c = checks(tmp_path)
    assert "TABLE_HEADER" not in c and "TABLE_SPLIT" not in c


def test_repeats_body_only(tmp_path):
    s = "Bu cümle raporda iki kez geçiyor ve tekrar sayılmalı."
    cell = "Tablo hücresinde aynı uzun değer tekrar edebilir normaldir."
    write_docx(tmp_path / "rapor.docx", _p(s) + _p(s) + _tbl([["A"], [cell], [cell]]))
    c = checks(tmp_path)
    assert len(c["REPEAT"]) == 1 and c["REPEAT"][0].level == UYARI
    assert "iki kez" in c["REPEAT"][0].message


def test_unreadable_docx(tmp_path):
    with zipfile.ZipFile(tmp_path / "rapor.docx", "w") as z:
        z.writestr("word/document.xml", "<bozuk")
    assert checks(tmp_path)["UNREADABLE"][0].level == HATA


def test_every_qa_check_has_a_firing_fixture():
    """Yeni QA kontrolü eklenirse bu dosyaya bozuk fixture eklenmeli."""
    covered = {"qa_unreadable", "qa_placeholders", "qa_actions", "qa_glossary", "qa_counts", "qa_highlight", "qa_direct_format",
               "qa_excel_errors", "qa_empty_sections", "qa_omitted_blocker", "qa_mask", "qa_cell_words",
               "qa_table_layout", "qa_repeats"}
    assert {c.__name__ for c in QA_CHECKS} == covered


def test_broken_check_does_not_stop_others(tmp_path, monkeypatch):
    def boom(q):
        raise RuntimeError("x")
        yield  # noqa
    monkeypatch.setattr(qa, "QA_CHECKS", [boom] + list(QA_CHECKS))
    (tmp_path / "rapor.md").write_text("TODO\n", encoding="utf-8")
    c = checks(tmp_path)
    assert c["boom"][0].level == UYARI
    assert "PLACEHOLDER" in c


def test_empty_folder_lists_missing(tmp_path):
    p, n = write_report(tmp_path)
    assert n == 0
    txt = p.read_text(encoding="utf-8")
    assert "GEÇTİ" in txt and "report_ir.json" in txt and "rapor.docx" in txt


def test_write_report_counts_errors(tmp_path):
    (tmp_path / "rapor.md").write_text("TBD\nlorem ipsum\n", encoding="utf-8")
    p, n = write_report(tmp_path)
    assert n == 2 and "GEÇMEDİ" in p.read_text(encoding="utf-8")


# ---------------- uçtan uca: demo ----------------
@pytest.fixture(scope="module")
def demo_out(tmp_path_factory):
    from pcs7_analyzer.cli import run
    from pcs7_analyzer.demo import build_demo_project
    root = tmp_path_factory.mktemp("qa_demo")
    out = root / "out"
    run(build_demo_project(root / "d"), out, log=lambda m: None)
    return out


def test_demo_run_writes_qa_and_ir(demo_out):
    assert (demo_out / "qa_report.md").exists()
    assert (demo_out / "report_ir.json").exists()


def test_demo_run_zero_hata(demo_out):
    issues, q = run_qa(demo_out)
    errs = [i for i in issues if i.level == HATA]
    assert not errs, "\n".join(f"{i.check}: {i.message} [{i.where}]" for i in errs)
    assert not any(i.check.startswith("qa_") for i in issues), issues   # hiçbir kontrol çökmedi
    for name in ("report_ir.json", "findings.json", "rapor.md", "rapor.xlsx"):
        assert name not in q.missing


def test_qa_subcommand_exit_code(demo_out, tmp_path):
    from pcs7_analyzer.cli import main
    assert main(["qa", str(demo_out)]) == 0
    (tmp_path / "rapor.md").write_text("TODO\n", encoding="utf-8")
    assert main(["qa", str(tmp_path)]) == 1
