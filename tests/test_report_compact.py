"""Çalışma raporu (HTML/MD, build_document(full=True)) kompakt: uzun listeler kısaltılır + Excel'e işaret,
ekler HTML'de kapalı; Word müşteri raporu (full=False) yapısı ve bulgular kaybolmaz."""
import copy
import re

import pytest

from pcs7_analyzer.analyze import CustomBlock, HwMatch, analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.report import (FULL_LIST_MAX, Heading, Table, build_document, render_html, render_markdown)


@pytest.fixture(scope="module")
def an(tmp_path_factory):
    root = tmp_path_factory.mktemp("compact_demo")
    bk = build_demo_project(root)
    return analyze(bk, released_csv=root / "released_demo.csv")


@pytest.fixture(scope="module")
def big(an):
    """Gerçek proje ölçeği: çok modül, custom block, uyarı ve okunamayan dosya."""
    a = copy.deepcopy(an)
    a.hw_matches += [HwMatch(f"6ES7 131-7RF{i:02d}-0AB0", "", 3, ["AS01"], "listede") for i in range(80)]
    a.hw_matches += [HwMatch(f"6ES7 999-{i:04d}", "", 1, ["AS02"], "bulunamadı, teyit edilmeli") for i in range(25)]
    b = next(x for x in a.block_folders if x.counts and x.custom_blocks)
    b.custom_blocks += [CustomBlock("FB", 3000 + i, f"CUST_{i}", "FAM", "BM", "4", "1.0", 1, False) for i in range(60)]
    a.warnings += [f"Okunamadı: dosya_{i}.dbf (latin1)" for i in range(40)]
    for i in range(30):
        a.unknown.add("hwconfig", f"X/hOmSave7/s7hstatx/f{i}.s7h", "format tanınmadı")
    return a


def _captions(doc):
    return [b.caption for b in doc if isinstance(b, Table) and b.caption.startswith("Tablo ")]


def test_word_structure_unchanged(an):
    short = build_document(an, full=False)
    assert _captions(short) == ["Tablo 1: Genel değerlendirme", "Tablo 2: AS envanteri", "Tablo 3: OS yapısı",
                                "Tablo 4: WinCC yapısı", "Tablo 5: Yazılım içeriği", "Tablo 6: Zorluklar ve etkileri"]
    assert not any(isinstance(b, Heading) and b.fold for b in short)
    assert _captions(build_document(an, full=True)) == _captions(short)    # numaralama bozulmaz


def test_no_finding_lost(big):
    doc = build_document(big, full=True)
    risk = next(b for b in doc if isinstance(b, Table) and b.caption.startswith("Tablo 6"))
    assert sorted(x for ids in risk.row_ids for x in ids) == sorted(f.fid for f in big.findings)
    assert all(r[3] for r in risk.rows)                                     # aksiyon sütunu dolu
    md = render_markdown(big, doc)
    ekc = md[md.index("## Ek C"):md.index("## Ek D")]
    assert all(f"| {f.fid} |" in ekc for f in big.findings)                 # tam metin Ek C'de


def test_long_lists_capped(big):
    md = render_markdown(big, build_document(big, full=True))
    assert "CUST_5 |" in md and "CUST_59" not in md and "Excel 'Custom_Blocklar'" in md
    hw = md[md.index("### Hardware uyumluluk"):]
    hw = hw[:hw.index("\n### ")]
    assert "6ES7 131-7RF05" not in hw                                       # 'listede' satırları sayı olarak
    assert "**86 listede**" in hw and "Excel 'HW_Moduller'" in hw
    assert hw.count("bulunamadı, teyit edilmeli") <= 16
    assert "dosya_39" not in md and "Excel 'Acik_Konular_Kaynak'" in md
    ekd = md[md.index("## Ek D"):]
    assert "| hwconfig | format tanınmadı | 30 |" in ekd                     # aynı modül + neden tek satır
    for t in (b for b in build_document(big, full=True) if isinstance(b, Table) and not b.caption.startswith("Tablo")):
        if t.headers[0] != "ID":                                            # Ek C: tüm bulgular kalır
            assert len(t.rows) <= max(FULL_LIST_MAX, 15) + 1, t.headers


def test_compact_vs_full_size(an, big):
    """Ölçek büyüdükçe çalışma raporu neredeyse sabit kalır (listeler Excel'de)."""
    n_small = len(render_markdown(an, build_document(an, full=True)).splitlines())
    n_big = len(render_markdown(big, build_document(big, full=True)).splitlines())
    assert n_big - n_small < 40


def test_html_first_screen_and_folds(an):
    html = render_html(an, build_document(an, full=True))
    first = html[:html.index('class="fold"><details>')]
    for h in ("Sonuç:", "Tablo 2: AS envanteri", "Tablo 3: OS yapısı", "Tablo 6: Zorluklar ve etkileri",
              "Aksiyon (sorumlu)"):
        assert h in first
    for h in ("Ek A: Detaylar", "Ek B: Keşif", "Ek C: Bulgular", "Ek D: Analiz edilemeyenler",
              "Backup içeriği ve yeterlilik", "Teklif için girdiler"):
        m = re.search(r'<section id="s\d+" class="fold"><details><summary><h2>' + re.escape(h), html)
        assert m, h
    assert html.count("<details>") == html.count("</details>")
    assert html.count("<section") == html.count("</section>")


def test_warning_not_repeated_from_unknown(an):
    a = copy.deepcopy(an)
    a.unknown.add("blockmap", "P/hrs/S7RESOFF.DBF", "yok: liste okunamadı")
    a.warnings.append("Block↔AS zinciri: blockmap | P/hrs/S7RESOFF.DBF | yok: liste okunamadı")
    md = render_markdown(a, build_document(a, full=True))
    ekb = md[md.index("## Ek B"):md.index("## Ek C")]
    assert "S7RESOFF.DBF" not in ekb and "Ek D'de" in ekb
    assert "P/hrs/S7RESOFF.DBF" in md[md.index("## Ek D"):]


def test_manual_and_open_items_not_duplicated(an):
    md = render_markdown(an, build_document(an, full=True))
    assert md.count("AS bazında izin verilen duruş süreleri") == 1
    sec = md[md.index("## Manuel girişler"):md.index("## Teklif öncesi")]
    assert "Eksik (müşteriden istenecek)" in sec and "| OS PO | eksik |" not in sec
