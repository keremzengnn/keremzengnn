"""FAZ 1A: teyit listesi (confirm.collect), yasak kalıplar, verified / unverified bulgu ayrımı."""
from pcs7_analyzer import confirm
from pcs7_analyzer.analyze import analyze
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.model import Confidence, Finding, Severity
from pcs7_analyzer.readiness import (findings_json, findings_rows, unverified_findings, verified_findings)


def _an(tmp_path):
    return analyze(build_demo_project(tmp_path / "demo"))


def test_forbidden_patterns():
    for bad in ("Eşleme çıkarım", "aday sürüm", "teyit edilmeli", "heuristic eşleme", "ham tarama", "tahmini süre",
                "Sürüm 8.1?", "Güven: low"):
        assert not confirm.is_clean(bad), bad
    assert confirm.is_clean(confirm.HEADING)
    assert confirm.is_clean("Teyit edilecek noktalar")
    assert confirm.is_clean("AS1: HW Config export'unu iste ve F-I/O modüllerini kontrol et.")
    assert confirm.is_clean("")


def test_finding_verified_property_and_dict():
    hi = Finding("X", "t", Severity.LOW, "d")
    lo = Finding("Y", "t", Severity.LOW, "d", confidence=Confidence.LOW, confirm_action="Şunu kontrol et")
    assert hi.verified and not lo.verified
    d = lo.to_dict()
    assert d["confidence"] == "low" and d["confirm_action"] == "Şunu kontrol et"      # dahili alanlar korunur


def test_low_findings_not_in_main_lists_but_in_confirm(tmp_path):
    an = _an(tmp_path)
    lows = unverified_findings(an)
    highs = verified_findings(an)
    assert lows and highs and len(lows) + len(highs) == len(an.findings)
    assert all(f.verified for f in highs) and not any(f.verified for f in lows)
    ids_main = {r[0] for r in findings_rows(an)}
    assert not ({f.fid for f in lows} & ids_main)
    assert {f.fid for f in lows} <= {r[0] for r in findings_rows(an, include_unverified=True)}
    # findings.json tüm bulguları dahili alanlarla yazar
    fj = [d for d in findings_json(an) if "fid" in d]
    assert len(fj) == len(an.findings) and all("confidence" in d for d in fj)
    items = confirm.collect(an)
    assert items
    topics = " ".join(i.topic for i in items)
    for f in lows:
        assert f.title in topics


def test_collect_deterministic_unique_and_clean(tmp_path):
    an = _an(tmp_path)
    a, b = confirm.collect(an), confirm.collect(an)
    assert a == b
    assert len({(i.topic, i.action) for i in a}) == len(a)
    for i in a:
        assert i.action and confirm.is_clean(i.topic) and confirm.is_clean(i.action), (i.topic, i.action)


def test_verified_texts_clean(tmp_path):
    an = _an(tmp_path)
    for f in verified_findings(an):
        assert confirm.is_clean(f.detail), (f.check_id, f.detail)
    for row in findings_rows(an):
        assert confirm.is_clean(" ".join(row)), row


def test_not_checked_and_unmatched_copy_items():
    from pcs7_analyzer.analyze import Analysis
    from pcs7_analyzer.discovery import DiscoveryResult
    an = Analysis(source="s", target="V10.0SP2", tool_version="x", created="", discovery=DiscoveryResult(root="x"))
    an.not_checked = [("WINCC_DIFF", "WinCC Configuration Studio export'u yok"), ("HW_RELEASED", "hata: boom")]
    an.unmatched_os_copies = ["OS_X"]
    items = confirm.collect(an)
    assert any("WinCC Configuration Studio export'u yok" in i.action for i in items)
    assert any("OS_X" in i.action for i in items)
    assert not any("boom" in i.action for i in items)           # dahili hata kullanıcıya gitmez
