"""FAZ 1: kullanıcı çıktısında belirsizlik dili yok. Ana tablolar = doğrulanmış bilgi; doğrulanamayanlar sonda tek
'Teyit edilecek noktalar' bölümünde (HTML / MD / Word) veya 'Teyit_Edilecekler' sayfasında (rapor.xlsx)."""
import json
import re

import pytest

from pcs7_analyzer import confirm
from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.excel_report import SHEETS, build_workbook, write_excel
from pcs7_analyzer.qa import HATA, run_qa
from pcs7_analyzer.report import (Bullets, Heading, Note, Para, ReportMeta, Table, Topline, build_document,
                                  confirm_items, render_html, render_markdown)
from pcs7_analyzer.report_ir import build_ir, dumps


@pytest.fixture(scope="module")
def an(tmp_path_factory):
    root = tmp_path_factory.mktemp("confirm_demo")
    bk = build_demo_project(root)
    return analyze(bk, released_csv=root / "released_demo.csv")


def _texts(block):
    if isinstance(block, (Topline, Heading, Para, Note)):
        yield block.text
    elif isinstance(block, Bullets):
        yield from block.items
    elif isinstance(block, Table):
        yield block.caption
        yield from block.headers
        for r in block.rows:
            yield from (str(c) for c in r)


def _split(doc):
    """(ana bloklar, teyit bölümü blokları)"""
    idx = [i for i, b in enumerate(doc) if isinstance(b, Heading) and b.level == 1 and b.text == confirm.HEADING]
    assert len(idx) == 1, "teyit bölümü tam bir kez ve yazılmış olmalı"
    return doc[:idx[0]], doc[idx[0]:]


@pytest.mark.parametrize("full", [False, True])
def test_main_sections_have_no_forbidden_words(an, full):
    main, _ = _split(build_document(an, full=full))
    bad = [t for b in main for t in _texts(b) if not confirm.is_clean(t)]
    assert bad == []


@pytest.mark.parametrize("full", [False, True])
def test_confirm_section_is_last_and_not_a_table(an, full):
    doc = build_document(an, full=full)
    _, tail = _split(doc)
    assert [type(b) for b in tail] == [Heading, Bullets]               # numarasız madde listesi: Word Tablo numarası değişmez
    assert [b.caption for b in doc if isinstance(b, Table) and b.caption.startswith("Tablo ")] == [
        "Tablo 1: Genel değerlendirme", "Tablo 2: AS envanteri", "Tablo 3: OS yapısı", "Tablo 4: WinCC yapısı",
        "Tablo 5: Yazılım içeriği", "Tablo 6: Zorluklar ve etkileri"]
    last_h1 = [b for b in doc if isinstance(b, Heading) and b.level == 1][-1]
    assert last_h1.text == confirm.HEADING


def test_confirm_items_unique_and_action_sentences(an):
    items = confirm_items(an)
    assert items
    keys = [i.action.strip().lower() for i in items]
    assert len(keys) == len(set(keys))
    assert all(i.topic and i.action for i in items)


def test_unverified_finding_not_in_main_tables(an):
    unsure = [f for f in an.findings if not f.verified]
    assert unsure, "demo en az bir doğrulanmamış bulgu içermeli"
    doc = build_document(an, full=True)
    main, _ = _split(doc)
    risk = next(b for b in main if isinstance(b, Table) and b.caption.startswith("Tablo 6"))
    shown = {x for ids in risk.row_ids for x in ids}
    assert not shown & {f.fid for f in unsure}
    md = render_markdown(an, doc)
    ekc = md[md.index("## Ek C"):md.index("## Ek D")]
    assert not any(f"| {f.fid} |" in ekc for f in unsure)


def test_html_and_md_end_with_confirm_section(an):
    doc = build_document(an, full=True)
    md = render_markdown(an, doc, ReportMeta())
    heads = re.findall(r"^## (.+)$", md, re.M)
    assert heads[-1] == confirm.HEADING
    html = render_html(an, doc, ReportMeta())
    assert html.rindex("<h2>") == html.rindex(f"<h2>{confirm.HEADING}</h2>")
    assert "teyit edilmeli" not in html.split(f"<h2>{confirm.HEADING}</h2>")[0].lower()


def test_empty_confirm_section_not_written(an, monkeypatch):
    import pcs7_analyzer.excel_report as xr
    import pcs7_analyzer.report as rp
    monkeypatch.setattr(rp, "confirm_items", lambda a: [])
    monkeypatch.setattr(xr, "confirm_items", lambda a: [])
    assert not any(isinstance(b, Heading) and b.text == confirm.HEADING for b in build_document(an, full=True))
    assert confirm.SHEET_ANALYSIS not in [s["name"] for s in build_workbook(an).sheets]


def test_excel_confirm_sheet_last_and_main_sheets_clean(an, tmp_path):
    wb = build_workbook(an)
    names = [s["name"] for s in wb.sheets]
    assert names[-1] == confirm.SHEET_ANALYSIS and names[:len(SHEETS)] == SHEETS
    for s in wb.sheets[:-1]:
        for row in s["rows"]:
            for c in row:
                v = str(getattr(c, "v", c) or "")
                assert confirm.is_clean(v), (s["name"], v)
                assert v not in ("KANIT", "ÇIKARIM")
    rows = wb.sheets[-1]["rows"]
    assert [getattr(c, "v", c) for c in rows[0]] == ["Konu", "Aksiyon", "Nerede"] and len(rows) > 1
    bulgu = next(s for s in wb.sheets if s["name"] == "Bulgular")["rows"]
    head = [getattr(c, "v", c) for c in bulgu[0]]
    assert "Güven" not in head
    ids = {str(getattr(r[0], "v", r[0])) for r in bulgu[1:]}
    assert not ids & {f.fid for f in an.findings if not f.verified}
    write_excel(an, tmp_path / "x.xlsx")


def test_ir_counts_only_verified_and_confirm_count(an):
    ir = json.loads(dumps(build_ir(an, build_document(an, full=False), "teklif")))
    sure = sorted(f.fid for f in an.findings if f.verified)
    assert ir["finding_ids"] == sure
    assert ir["stats"]["confirm_count"] == len(confirm_items(an))
    assert not {o["finding_id"] for o in ir["omitted"] if o["reason"] != "teyit listesinde"} & {f.fid for f in an.findings if not f.verified}


# ---------------- qa.forbidden_words ----------------
def _issues(folder):
    issues, _ = run_qa(folder)
    return [i for i in issues if i.check == "FORBIDDEN_WORDS"]


def test_qa_forbidden_words_fires_on_broken_fixture(tmp_path):
    (tmp_path / "rapor.md").write_text("## Zorluklar\n\nBu eşleme heuristic, teyit edilmeli.\n", encoding="utf-8")
    (tmp_path / "rapor.html").write_text("<html><body><h2>Zorluklar</h2><p>Rol tahmini yapıldı (ÇIKARIM)</p></body></html>",
                                         encoding="utf-8")
    got = _issues(tmp_path)
    assert got and all(i.level == HATA for i in got)
    assert {i.where for i in got} >= {"rapor.md", "rapor.html"}


def test_qa_forbidden_words_passes_clean_and_exempts_confirm_section(tmp_path):
    (tmp_path / "rapor.md").write_text(
        f"## Zorluklar\n\nTüm modüller listede.\n\n## {confirm.HEADING}\n\n- AS01 eşlemesi teyit edilmeli, heuristic.\n",
        encoding="utf-8")
    (tmp_path / "rapor.html").write_text(
        f"<html><body><nav><a href='#s2'>{confirm.HEADING}</a></nav><h2>Zorluklar</h2><p>Temiz.</p>"
        f"<h2>{confirm.HEADING}</h2><ul><li>çıkarım: kontrol et</li></ul></body></html>", encoding="utf-8")
    assert _issues(tmp_path) == []


def test_qa_forbidden_words_scans_xlsx_except_confirm_sheet(tmp_path):
    from tests.test_qa import write_xlsx
    write_xlsx(tmp_path / "rapor.xlsx", {"Ozet": [["A"], ["Rol ham tarama ile bulundu"]],
                                          confirm.SHEET_ANALYSIS: [["Konu", "Aksiyon"], ["x", "çıkarım, teyit edilmeli"]]})
    got = _issues(tmp_path)
    assert len(got) == 1 and got[0].where == "rapor.xlsx/Ozet"


def test_qa_clean_on_real_demo_outputs(an, tmp_path):
    doc = build_document(an, full=True)
    (tmp_path / "rapor.md").write_text(render_markdown(an, doc), encoding="utf-8")
    (tmp_path / "rapor.html").write_text(render_html(an, doc), encoding="utf-8")
    write_excel(an, tmp_path / "rapor.xlsx")
    assert _issues(tmp_path) == []
