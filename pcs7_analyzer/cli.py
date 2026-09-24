"""
Komut satırı.

  python -m pcs7_analyzer                         -> pencere (GUI)
  python -m pcs7_analyzer <klasör|backup.zip>     -> tam analiz, rapor ./pcs7_rapor/ altına
  python -m pcs7_analyzer <..> --discover         -> sadece keşif
  python -m pcs7_analyzer --demo <klasör>         -> sahte demo projesi üret
  python -m pcs7_analyzer --list-checks

Kaynağa asla yazılmaz: çıktı klasörü kaynak klasörün içindeyse reddedilir.
"""
from __future__ import annotations

import argparse
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__
from .checks import CHECKS

DEFAULT_TARGET = "V10.0SP2"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pcs7_analyzer",
                                description="PCS 7 proje backup'ı (klasör veya .zip) offline upgrade ön değerlendirmesi")
    p.add_argument("source", type=Path, nargs="?", help="Proje / multiproject backup klasörü veya .zip (salt okunur)")
    p.add_argument("-o", "--out-dir", type=Path, help="Rapor klasörü (varsayılan: ./pcs7_rapor/<isim>_<tarih>)")
    p.add_argument("--target", default=DEFAULT_TARGET, help=f"Hedef PCS 7 versiyonu (varsayılan {DEFAULT_TARGET})")
    p.add_argument("--released", type=Path, help="Released Modules CSV (varsayılan: paket içindeki data/)")
    p.add_argument("--template", type=Path, help="Word template (.dotx); verilmezse ayarlardaki / data/ içindeki")
    p.add_argument("--author", help="Header'da ad (ayarlara kaydedilir)")
    p.add_argument("--department", help="Header'da departman (ayarlara kaydedilir)")
    p.add_argument("--customer", help="Kapak üst satırı (varsayılan: multiproject adları)")
    p.add_argument("--discover", action="store_true", help="Sadece keşif: yapı raporu, analiz yok")
    p.add_argument("--open", action="store_true", help="Bitince HTML raporu tarayıcıda aç")
    p.add_argument("--demo", type=Path, metavar="KLASÖR", help="Bu klasöre sahte demo backup'ı üret ve analiz et")
    p.add_argument("--list-checks", action="store_true", help="Tanımlı kontrolleri listele")
    p.add_argument("--gui", action="store_true", help="Pencereyi aç")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _inside(path: Path, root: Path) -> bool:
    path, root = path.resolve(), root.resolve()
    return path == root or root in path.parents


def _list_checks() -> str:
    rows = ["| ID | Konu | Severity | Referans | Durum |", "|---|---|---|---|---|"]
    for c in CHECKS:
        rows.append(f"| {c.id} | {c.title} | {c.severity.value} | {c.manual_ref} | {'var' if c.implemented else 'planlandı'} |")
    return "\n".join(rows)


def default_out_dir(source: Path) -> Path:
    name = re.sub(r"[^\w.-]+", "_", source.stem or "proje")
    return Path.cwd() / "pcs7_rapor" / f"{name}_{datetime.now():%Y%m%d_%H%M}"


def run(source: Path, out_dir: Path | None = None, target: str = DEFAULT_TARGET, released: Path | None = None,
        discover_only: bool = False, log=print, template: Path | None = None, author: str | None = None,
        department: str | None = None, customer: str | None = None) -> Path:
    """Analizi çalıştırır, raporları yazar ve ana rapor dosyasının yolunu döndürür."""
    from . import settings
    from .analyze import analyze
    from .discovery import discover, render_markdown as render_discovery
    from .report import ReportMeta, build_document, render_html, render_json, render_markdown

    source = Path(source)
    out_dir = Path(out_dir) if out_dir else default_out_dir(source)
    if source.is_dir() and _inside(out_dir, source):
        raise ValueError(f"Çıktı kaynak klasörün içine yazılamaz (salt okuma kuralı): {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    if discover_only:
        r = discover(source, progress=log)
        p = out_dir / "kesif.md"
        p.write_text(render_discovery(r), encoding="utf-8")
        log(f"Keşif raporu: {p}")
        return p

    st = settings.load()
    meta = ReportMeta(author=author if author is not None else st.get("author", ""),
                      department=department if department is not None else st.get("department", ""),
                      customer=customer or "")
    an = analyze(source, target=target, released_csv=released, log=log)
    doc = build_document(an)
    html_p = out_dir / "rapor.html"
    html_p.write_text(render_html(an, doc, meta), encoding="utf-8")
    (out_dir / "rapor.md").write_text(render_markdown(an, doc, meta), encoding="utf-8")
    (out_dir / "rapor.json").write_text(render_json(an), encoding="utf-8")
    tpl = settings.find_template(str(template) if template else None)
    if tpl:
        from .word import TemplateError, render_docx
        try:
            p = render_docx(an, build_document(an, full=False), meta, tpl, out_dir / "rapor.docx")
            log(f"Word rapor: {p}")
        except TemplateError as e:
            log(f"Word rapor üretilemedi: {e}")
    else:
        log("Word template (.dotx) seçilmedi: rapor.docx üretilmedi (HTML/MD/JSON üretildi).")
    log(f"Rapor: {html_p}")
    return html_p


def main(argv: list[str] | None = None) -> int:
    import os
    if sys.stdout is None:        # windowed exe: konsol yok
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_checks:
        print(_list_checks())
        return 0
    if args.gui or (args.source is None and args.demo is None):
        from .gui import main as gui_main
        return gui_main()
    if args.demo is not None:
        from .demo import build_demo_project
        args.demo.mkdir(parents=True, exist_ok=True)
        src = build_demo_project(args.demo)
        print(f"Demo backup: {src}")
        args.source = src
        args.released = args.released or (args.demo / "released_demo.csv")
        args.out_dir = args.out_dir or (args.demo / "rapor")

    src: Path = args.source
    if not src.exists():
        parser.error(f"bulunamadı: {src}")
    if args.out_dir is not None and src.is_dir() and _inside(args.out_dir, src):
        parser.error(f"çıktı kaynak klasörün içine yazılamaz (salt okuma kuralı): {args.out_dir}")

    def log(msg):
        print(msg, file=sys.stderr)

    from . import settings
    settings.save({k: v for k, v in (("author", args.author), ("department", args.department),
                                       ("template", str(args.template) if args.template else None)) if v})
    try:
        out = run(src, args.out_dir, args.target, args.released, args.discover, log, args.template,
                  args.author, args.department, args.customer)
    except ValueError as e:
        parser.error(str(e))
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    print(out)
    return 0
