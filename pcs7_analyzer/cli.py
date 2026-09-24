"""
Komut satırı:  python -m pcs7_analyzer <proje_klasoru> [--discover] [--out rapor.md] [--json rapor.json] [--target V10.0SP2]

Şu an sadece keşif (--discover) implement edildi; analiz onaydan sonra eklenecek.
Proje klasörüne asla yazılmaz: çıktı yolu proje klasörünün içindeyse reddedilir.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .checks import CHECKS
from .discovery import discover, render_markdown

DEFAULT_TARGET = "V10.0SP2"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pcs7_analyzer", description="PCS 7 proje backup'ı offline upgrade ön değerlendirmesi")
    p.add_argument("project_dir", type=Path, nargs="?", help="Proje / multiproject backup klasörü (salt okunur)")
    p.add_argument("--discover", action="store_true", help="Sadece keşif: klasör yapısını raporla, analiz yapma")
    p.add_argument("--out", type=Path, help="Markdown rapor yolu (varsayılan: stdout)")
    p.add_argument("--json", type=Path, dest="json_out", help="JSON çıktı yolu")
    p.add_argument("--target", default=DEFAULT_TARGET, help=f"Hedef PCS 7 versiyonu (varsayılan {DEFAULT_TARGET})")
    p.add_argument("--list-checks", action="store_true", help="Tanımlı kontrolleri listele")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _inside(path: Path, root: Path) -> bool:
    path, root = path.resolve(), root.resolve()
    return path == root or root in path.parents


def _list_checks() -> str:
    rows = ["| ID | Başlık | Severity | Referans | Durum |", "|---|---|---|---|---|"]
    for c in CHECKS:
        rows.append(f"| {c.id} | {c.title} | {c.severity.value} | {c.manual_ref} | {'var' if c.implemented else 'planlandı'} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_checks:
        print(_list_checks())
        return 0
    if args.project_dir is None:
        parser.error("project_dir gerekli")
    root: Path = args.project_dir
    if not root.is_dir():
        parser.error(f"klasör bulunamadı: {root}")
    for out in (args.out, args.json_out):
        if out is not None and _inside(out, root):
            parser.error(f"çıktı proje klasörünün içine yazılamaz (salt okuma kuralı): {out}")

    if not args.discover:
        print("Analiz henüz implement edilmedi; şimdilik --discover kullanın.", file=sys.stderr)
        return 2

    result = discover(root, progress=True)
    md = render_markdown(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md + "\n")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0
