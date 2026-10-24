"""Yol haritası (roadmap.py): demo projesiyle faz sırası, Finding ID referansları, determinizm, render."""
import re

import pytest

from pcs7_analyzer.analyze import analyze, staged_path_from
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.readiness import CIKARIM, KANIT
from pcs7_analyzer.roadmap import (INTERNAL, PHASES, ROADMAP_COLUMNS, build_roadmap, render_markdown, roadmap_rows,
                                   write_roadmap)


@pytest.fixture(scope="module")
def an(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo_rm")
    bk = build_demo_project(root)
    return analyze(bk, released_csv=root / "released_demo.csv")


@pytest.fixture(scope="module")
def phases(an):
    return build_roadmap(an)


def _step(phases, pid, title_part):
    p = next(p for p in phases if p.id == pid)
    return next(s for s in p.steps if title_part in s.title)


def test_phase_order_and_no_empty(phases):
    order = [pid for pid, _ in PHASES]
    ids = [p.id for p in phases]
    assert ids == sorted(ids, key=order.index)
    assert ids == order                       # demo projesinde tüm fazlar dolu
    assert all(p.steps for p in phases)
    for p in phases:
        assert [s.id for s in p.steps] == [f"{p.id}-{i:02d}" for i in range(1, len(p.steps) + 1)]


def test_finding_ids_exist(an, phases):
    fids = {f.fid for f in an.findings}
    used = [x for p in phases for s in p.steps for x in s.why]
    assert used and set(used) <= fids
    for p in phases:
        for s in p.steps:
            assert s.sources, s.id
            assert s.owner in ("Siemens", "Müşteri", "Siemens + Müşteri"), s.id
            if not s.generic:
                assert s.why, s.id                # bulgu adımı bulguya bağlı
            if INTERNAL in s.sources:
                assert s.confidence == CIKARIM, s.id
            assert s.confidence in (KANIT, CIKARIM)


def test_staged_path_steps(an, phases):
    path = staged_path_from(an.pcs7_family)
    p2 = next(p for p in phases if p.id == "P2")
    mig = [s for s in p2.steps if s.title.startswith("Migration adımı")]
    assert [s.title.rsplit(": ", 1)[1] for s in mig] == path == ["V8.2.4", "V9.1", "V10.0 SP2"]
    assert "@PCS7TypicalsAPC.pdl" in mig[0].detail      # demo: OS_SRV1'de APC typicals
    assert " → ".join(path) in _step(phases, "P1", "Kademeli yol").title


def test_project_specific_steps(an, phases):
    tcir = _step(phases, "P3", "TCiR")
    assert tcir.scope == ["AS01", "AS02"] and "AS STOP" in tcir.detail
    assert _step(phases, "P3", "SFC system").scope == ["AS01"]
    f = _step(phases, "P3", "F-System")
    assert f.scope == ["AS02"]
    assert {x.fid for x in an.findings if x.check_id == "LIB_F_SYSTEM"} <= set(f.why)
    assert _step(phases, "P1", "temiz kurulum")          # V8.1 < V9.1
    # tetiklenmeyen adım çıkarılır (demo'da BOX RTX / IM_DRV / CAS yok)
    titles = [s.title for p in phases for s in p.steps]
    assert not any("BOX RTX" in t or "IM_DRV" in t or "CAS" in t for t in titles)


def test_deterministic(an, phases):
    assert roadmap_rows(an) == roadmap_rows(an, phases)
    assert render_markdown(an) == render_markdown(an, build_roadmap(an))


def test_rows_shape(an):
    rows = roadmap_rows(an)
    assert rows and all(len(r) == len(ROADMAP_COLUMNS) for r in rows)
    assert all(isinstance(c, str) for r in rows for c in r)


def test_write(an, tmp_path):
    p = write_roadmap(an, tmp_path)
    assert p.name == "yol_haritasi.html" and p.exists()
    html = p.read_text(encoding="utf-8")
    md = (tmp_path / "yol_haritasi.md").read_text(encoding="utf-8")
    for pid, title in PHASES:
        assert f'id="{pid}"' in html and title.split(" (")[0] in md
    assert "--deep-blue" in html                          # report.py Siemens token'ları
    assert html.count("<section") == len(build_roadmap(an)) + 1   # özet + boş olmayan fazlar
    for t in (html, md):
        assert not re.search(r"\b(TODO|TBD|FIXME)\b", t)
        assert "kütüphane" not in t.lower() and "derleme" not in t.lower()


def test_empty_phase_dropped(an, monkeypatch):
    import pcs7_analyzer.roadmap as rm
    monkeypatch.setitem(rm._BUILDERS, "P4", lambda a: [None])
    ids = [p.id for p in rm.build_roadmap(an)]
    assert "P4" not in ids and "P5" in ids


def test_phase_error_isolated(an, monkeypatch):
    import pcs7_analyzer.roadmap as rm

    def boom(a):
        raise ValueError("x")
    monkeypatch.setitem(rm._BUILDERS, "P3", boom)
    n = len(an.warnings)
    p3 = next(p for p in rm.build_roadmap(an) if p.id == "P3")
    assert "üretilemedi" in p3.steps[0].title and len(an.warnings) == n + 1
    del an.warnings[n:]
