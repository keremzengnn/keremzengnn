"""Release kontrolü: `tests/regression/expected_local.json` (gitignore'lu) beklenen sayılarını gerçek backup'la karşılaştırır.

Müşteri değerleri koda girmez; dosya yoksa Türkçe mesaj verilir."""
from __future__ import annotations

import json
import os
from pathlib import Path

EXPECTED = Path(__file__).resolve().parents[1] / "tests" / "regression" / "expected_local.json"


def find_expected(path: Path | None = None) -> Path | None:
    for p in (path, EXPECTED):
        if p and Path(p).is_file():
            return Path(p)
    return None


def run_checks(source: Path, exp: dict, log=None) -> list[tuple[str, bool, str]]:
    """[(ad, geçti, detay)]"""
    from .analyze import analyze
    from .parsers import parse_subblk
    out: list[tuple[str, bool, str]] = []
    source = Path(source)

    def add(name, got, want):
        out.append((name, got == want, f"beklenen {want}, bulunan {got}"))

    for case in exp.get("block_folders", []):
        cid = case.get("id", "?")
        try:
            if not source.is_dir():
                raise OSError("block klasörü kontrolü için klasör gerekir (zip değil)")
            bf = parse_subblk(source / case["path"] / "SUBBLK.DBF")
        except Exception as e:  # noqa: BLE001
            out.append((f"{cid}: okunamadı", False, f"{type(e).__name__}: {e}"))
            continue
        for k, v in case.get("counts", {}).items():
            add(f"{cid}: {k} sayısı", bf.counts.get(k, 0), v)
        for fb, n in case.get("instances", {}).items():
            add(f"{cid}: FB{fb} instance", bf.instances_per_fb.get(("FB", int(fb)), 0), n)
        for author in case.get("authors_present", []):
            has = any(b.author == author for b in bf.blocks)
            out.append((f"{cid}: author {author}", has, "var" if has else "yok"))
    if any(k in exp for k in ("wincc", "sfc_charts", "client_groups")):
        an = analyze(source, extra_exports=[Path(p) for p in exp.get("exports", [])], log=log)
        for os_name, v in exp.get("wincc", {}).items():
            if os_name.startswith("_"):
                continue
            w = an.wincc.get(os_name)
            if w is None:
                out.append((f"{os_name}: WinCC export", False, "export bulunamadı"))
                continue
            add(f"{os_name}: tag/structtag/alarm", (w.dm_tag, w.dm_structtag, w.alarms),
                (v["dm_tag"], v["dm_structtag"], v["alarms"]))
        for os_name, n in exp.get("sfc_charts", {}).items():
            got = next((o.sfc["charts"] for o in an.os_projects if o.info.name == os_name and o.in_es), None)
            add(f"{os_name}: SFC chart", got, n)
        if "client_groups" in exp:
            add("client grup sayısı", len(an.client_groups), exp["client_groups"])
    return out


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="pcs7_analyzer release-check",
                                 description="Gerçek backup'ta beklenen sayıları doğrula (expected_local.json)")
    ap.add_argument("source", type=Path, nargs="?", help="Backup klasörü / zip (varsayılan: PCS7_TEST_PROJECT)")
    ap.add_argument("--expected", type=Path, help="Beklenen değerler JSON (varsayılan: tests/regression/expected_local.json)")
    a = ap.parse_args(argv)
    exp_path = find_expected(a.expected)
    if exp_path is None:
        print("Beklenen değer dosyası yok: tests/regression/expected_local.json "
              "(şablon: expected_example.json). Release kontrolü yapılamadı.")
        return 2
    src = a.source or (Path(os.environ["PCS7_TEST_PROJECT"]) if os.environ.get("PCS7_TEST_PROJECT") else None)
    if src is None or not Path(src).exists():
        print("Backup bulunamadı: klasör/zip verin veya PCS7_TEST_PROJECT ayarlayın.")
        return 2
    exp = json.loads(exp_path.read_text(encoding="utf-8"))
    res = run_checks(Path(src), exp)
    for name, ok, detail in res:
        print(f"{'GEÇTİ' if ok else 'KALDI'}  {name} — {detail}")
    failed = sum(1 for _, ok, _ in res if not ok)
    print(f"Toplam {len(res)} kontrol, {failed} kaldı.")
    return 1 if failed else 0
