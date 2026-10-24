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

# Program PCS 7 V10.0 SP2'ye upgrade için özelleşmiştir (hangi versiyondan gelinirse gelinsin hedef budur).
TARGET = "V10.0SP2"
TARGET_LABEL = "PCS 7 V10.0 SP2"
DEFAULT_TARGET = TARGET


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pcs7_analyzer",
                                description="PCS 7 proje backup'ı (klasör veya .zip) offline upgrade ön değerlendirmesi")
    p.add_argument("source", type=Path, nargs="?", help="Proje / multiproject backup klasörü veya .zip (salt okunur)")
    p.add_argument("-o", "--out-dir", type=Path, help="Rapor klasörü (varsayılan: ./pcs7_rapor/<isim>_<tarih>)")
    p.add_argument("--released", type=Path, help="Released Modules CSV (varsayılan: gömülü V10.0 SP2 listesi)")
    p.add_argument("--template", type=Path, help="Word template (.dotx) (varsayılan: gömülü template)")
    p.add_argument("--author", help="Header'da ad (ayarlara kaydedilir)")
    p.add_argument("--department", help="Header'da departman (ayarlara kaydedilir)")
    p.add_argument("--customer", help="Kapak üst satırı (varsayılan: multiproject adları)")
    p.add_argument("--inventory", action="store_true",
                   help="Envanter modu: backup'taki her şeyi listele (Excel + HTML), değerlendirme yapma")
    p.add_argument("--exports", type=Path, action="append", default=[],
                   help="WinCC Configuration Studio export klasörü/dosyası (backup dışındaysa); birden fazla verilebilir")
    p.add_argument("--manual", type=Path, help="Manuel girişler JSON (PO, archive tag, PC station listesi…); "
                                              "şablon: data/manuel_giris_ornek.json")
    p.add_argument("--collect", action="store_true",
                   help="Paketle: sadece analiz için gereken dosyaları küçük bir zip'e topla (paylaşım için); "
                        "paket bu programla orijinal backup gibi analiz edilir")
    p.add_argument("--no-inventory", action="store_true",
                   help="Analizle birlikte envanter (envanter.xlsx) üretme (büyük backup'ta süreyi kısaltır)")
    p.add_argument("--profile", choices=["teklif", "musteri", "muhendis"], default="teklif",
                   help="report_ir.json okuyucu profili (teklif / musteri = Word raporu, muhendis = tam rapor)")
    p.add_argument("--compare-to", type=Path, metavar="ÖNCEKİ_KLASÖR",
                   help="Önceki rapor klasörü: yeni / kapanan / değişen bulgular -> revizyon.md")
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


def default_out_dir(source: Path, root: Path | None = None) -> Path:
    """Varsayılan: Belgeler/PCS7_Raporlar/<isim>_<tarih> (Belgeler yoksa çalışma klasörü)."""
    name = re.sub(r"[^\w.-]+", "_", source.stem or "proje")
    if root is None:
        docs = Path.home() / "Documents"
        root = (docs if docs.is_dir() else Path.cwd()) / "PCS7_Raporlar"
    base = Path(root) / f"{name}_{datetime.now():%Y%m%d_%H%M}"
    p, i = base, 2
    while p.exists():                      # aynı dakikada ikinci çalıştırma önceki raporun üstüne yazmasın
        p, i = base.with_name(f"{base.name}_{i}"), i + 1
    return p


def _tee_log(log, path: Path):
    """Log mesajlarını ekrana ve çıktı klasöründeki log.txt'ye yazar (sorun bildirirken paylaşılabilir)."""
    try:
        path.write_text(f"pcs7_analyzer {__version__} — {datetime.now():%Y-%m-%d %H:%M}\n", encoding="utf-8")
    except OSError:
        return log

    def tee(msg):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{msg}\n")
        except OSError:
            pass
        log(msg)
    return tee


def _index(out_dir: Path, source: Path, mode: str, log) -> Path | None:
    """index.html (giriş sayfası) yazar; hata raporları engellemez."""
    try:
        from .index_page import write_index
        return write_index(out_dir, source, mode)
    except Exception as e:  # noqa: BLE001
        import traceback as _tb
        log(f"UYARI: index.html üretilemedi ({type(e).__name__}: {e})")
        log(_tb.format_exc())
        return None


def index_path(result: Path) -> Path:
    """run()'ın döndürdüğü dosyanın klasöründeki index.html (yoksa dosyanın kendisi)."""
    p = Path(result).parent / "index.html"
    return p if p.is_file() else Path(result)


class UsageError(ValueError):
    """Kullanıcı girdisi hatası (komut satırında kullanım mesajı olarak gösterilir)."""


def run(source: Path, out_dir: Path | None = None, target: str = TARGET, released: Path | None = None,
        discover_only: bool = False, log=print, template: Path | None = None, author: str | None = None,
        department: str | None = None, customer: str | None = None, inventory: bool = False,
        manual=None, exports: list[Path] | None = None, with_inventory: bool = True, collect: bool = False,
        profile: str = "teklif", compare_to: Path | None = None) -> Path:
    """Analizi (veya envanteri) çalıştırır, çıktıları yazar ve ana HTML dosyasının yolunu döndürür.
    with_inventory: analizle birlikte envanter (envanter.xlsx, Mevcut durum sayfası) de üretilir; kaynak bir kez açılır."""
    from . import settings
    from .analyze import analyze_source
    from .source import open_source
    from .discovery import discover, render_markdown as render_discovery
    from .report import ReportMeta, build_document, render_html, render_json, render_markdown

    source = Path(source)
    out_dir = Path(out_dir) if out_dir else default_out_dir(source)
    if source.is_dir() and _inside(out_dir, source):
        raise UsageError(f"Çıktı kaynak klasörün içine yazılamaz (salt okuma kuralı): {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    log = _tee_log(log, out_dir / "log.txt")

    if collect:
        from .collect import collect as do_collect
        name = re.sub(r"[^\w.-]+", "_", source.stem or "backup")
        z = out_dir / f"{name}_paket.zip"
        do_collect(source, z, log)
        log("Paket müşteri verisi içerir (block / symbol adları, HW, script'ler): paylaşmadan önce veri kullanım "
            "kurallarını teyit edin.")
        _index(out_dir, source, "collect", log)
        return z

    if inventory:
        from .inventory import build_inventory, write_outputs
        from .index_page import write_inventory_summary
        inv = build_inventory(source, log)
        p = write_outputs(inv, out_dir)
        write_inventory_summary(inv, out_dir)
        log(f"Envanter: {out_dir / 'envanter.xlsx'}")
        log(f"Yapı tanısı (müşteri verisi içermez): {out_dir / 'yapi_tanisi.txt'}")
        _index(out_dir, source, "inventory", log)
        return p

    if discover_only:
        r = discover(source, progress=log)
        p = out_dir / "kesif.md"
        p.write_text(render_discovery(r), encoding="utf-8")
        log(f"Keşif raporu: {p}")
        _index(out_dir, source, "discover", log)
        return p

    st = settings.load()
    meta = ReportMeta(author=author if author is not None else st.get("author", ""),
                      department=department if department is not None else st.get("department", ""),
                      customer=customer or "")
    from .analyze import ManualInputs
    with open_source(source, log) as src:
        an = analyze_source(src, target, released, log, manual if manual is not None else ManualInputs(), exports)
        from .report_ir import input_hash
        src_hash = input_hash(src.entries)
        if with_inventory:
            log("Envanter (mevcut durum)...")
            try:
                from .index_page import write_inventory_summary
                from .inventory import build_inventory_source, write_outputs
                inv = build_inventory_source(src, log)
                write_outputs(inv, out_dir)
                write_inventory_summary(inv, out_dir)
                log(f"Envanter: {out_dir / 'envanter.xlsx'}")
            except Exception as e:  # noqa: BLE001 - envanter hatası analiz raporunu engellemez
                import traceback as _tb
                log(f"UYARI: envanter üretilemedi ({type(e).__name__}: {e})")
                log(_tb.format_exc())
    kb_db = settings.find_kb()
    if kb_db:
        try:
            from .kb import refs_for_findings
            an.kb_refs = refs_for_findings(kb_db, an.findings, an.target.replace("SP", " SP"))
            log(f"Doküman referansları: {kb_db} ({sum(1 for v in an.kb_refs.values() if v)} bulgu)")
        except Exception as e:  # noqa: BLE001
            an.unknown.add("kb", str(kb_db), f"doküman referansı alınamadı ({type(e).__name__}: {e})")
    # Her çıktı ayrı üretilir: biri hata verirse diğerleri yine yazılır.
    import traceback
    failed = []

    def out(name, fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            log(f"UYARI: {name} üretilemedi ({type(e).__name__}: {e})")
            log(traceback.format_exc())

    html_p = out_dir / "rapor.html"
    out("rapor.json", lambda: (out_dir / "rapor.json").write_text(render_json(an), encoding="utf-8"))
    out("rapor.html", lambda: html_p.write_text(render_html(an, build_document(an), meta), encoding="utf-8"))
    out("rapor.md", lambda: (out_dir / "rapor.md").write_text(render_markdown(an, build_document(an), meta),
                                                              encoding="utf-8"))

    def excel():
        from .excel_report import write_excel
        write_excel(an, out_dir / "rapor.xlsx", meta)
        log(f"Excel rapor: {out_dir / 'rapor.xlsx'}")
    out("rapor.xlsx", excel)
    tpl = settings.find_template(str(template) if template else None)
    if tpl:
        from .word import TemplateError, render_docx

        def word():
            try:
                p = render_docx(an, build_document(an, full=False), meta, tpl, out_dir / "rapor.docx")
                log(f"Word rapor: {p}")
            except TemplateError as e:
                log(f"Word rapor üretilemedi: {e}")
        out("rapor.docx", word)
    else:
        log("Word template (.dotx) seçilmedi: rapor.docx üretilmedi (HTML/MD/JSON üretildi).")
    def bm_diag():
        if an.blockmap is not None:
            from .blockmap import diagnostics as bm_diagnostics
            (out_dir / "blockmap_tanisi.txt").write_text(bm_diagnostics(an.blockmap), encoding="utf-8")
    out("blockmap_tanisi.txt", bm_diag)

    def extras():
        import json as _json
        from .readiness import findings_json
        (out_dir / "findings.json").write_text(_json.dumps(findings_json(an), ensure_ascii=False, indent=1, default=str),
                                               encoding="utf-8")
        (out_dir / "unknown.log").write_text(an.unknown.to_log(), encoding="utf-8")
    out("findings.json / unknown.log", extras)

    def ir_and_rev():
        from .report_ir import PROFILES, build_ir, dumps
        ir = build_ir(an, build_document(an, full=PROFILES.get(profile, False)), profile, src_hash,
                      {"source": Path(source).name, "author": meta.author, "department": meta.department})
        if compare_to:
            out("revizyon.md", lambda: _revision(ir, compare_to, out_dir, log))
        (out_dir / "report_ir.json").write_text(dumps(ir), encoding="utf-8")
    out("report_ir.json", ir_and_rev)

    def roadmap():
        try:
            from .roadmap import write_roadmap
        except ModuleNotFoundError as e:
            if e.name and e.name.endswith("roadmap"):
                return                   # yol haritası modülü bu sürümde yok
            raise
        p = write_roadmap(an, out_dir, meta)
        log(f"Yol haritası: {p or out_dir / 'yol_haritasi.html'}")
    out("yol_haritasi.html", roadmap)

    def qa():
        from .qa import write_report
        p, n_err = write_report(out_dir)
        log(f"QA: {'GEÇMEDİ, ' + str(n_err) + ' hata' if n_err else 'geçti'} ({p.name})")
    out("qa_report.md", qa)
    if len(an.unknown):
        log(f"Analiz edilemeyen: {len(an.unknown)} (unknown.log)")
    if an.warnings:
        log(f"{len(an.warnings)} uyarı var (raporun 'Keşif ve uyarılar' ekinde).")
    if "rapor.html" in failed:
        alt = next((out_dir / n for n in ("rapor.xlsx", "rapor.md", "rapor.json") if (out_dir / n).exists()), None)
        if alt is None:
            raise RuntimeError("Hiçbir rapor dosyası üretilemedi (log'a bakın)")
        html_p = alt
    from .parsers.subblk import clear_cache
    clear_cache()
    log(f"Rapor: {html_p}")
    _index(out_dir, source, "analysis", log)
    return html_p


def _revision(ir: dict, compare_to: Path, out_dir: Path, log) -> None:
    import json
    from .revision import diff, load_findings, previous_revision, render
    d = diff(load_findings(compare_to), json.loads((out_dir / "findings.json").read_text(encoding="utf-8")))
    rev = previous_revision(compare_to) + 1
    ir["revision"] = rev
    ir["revision_diff"] = {k: len(v) for k, v in d.items()}
    (out_dir / "revizyon.md").write_text(render(d, compare_to, rev), encoding="utf-8")
    log(f"Revizyon r{rev}: {len(d['new'])} yeni, {len(d['closed'])} kapanan, {len(d['changed'])} değişen (revizyon.md)")


SUBCOMMANDS = ("compare", "kb", "diag", "qa", "learn", "extract-style")


def _sub_main(argv: list[str]) -> int:
    """Alt komutlar: compare A B / kb build|search / diag <arşiv>. Ana kullanım (analiz) değişmedi."""
    cmd, rest = argv[0], argv[1:]
    if cmd == "kb":
        from .kb import main as kb_main
        return kb_main(rest)
    if cmd == "learn":
        from .learn import main as learn_main
        return learn_main(rest)
    if cmd == "extract-style":
        from .docx_style import main as style_main
        return style_main(rest)
    if cmd == "qa":
        qp = argparse.ArgumentParser(prog="pcs7_analyzer qa", description="Rapor klasöründe QA (qa_report.md)")
        qp.add_argument("folder", type=Path)
        qa_args = qp.parse_args(rest)
        if not qa_args.folder.is_dir():
            qp.error(f"klasör bulunamadı: {qa_args.folder}")
        from .qa import write_report
        p, n_err = write_report(qa_args.folder)
        print(p)
        return 1 if n_err else 0
    ap = argparse.ArgumentParser(prog=f"pcs7_analyzer {cmd}")
    if cmd == "compare":
        ap.add_argument("a", type=Path, help="Backup A (klasör / zip)")
        ap.add_argument("b", type=Path, help="Backup B (klasör / zip)")
    else:
        ap.add_argument("source", type=Path, help="DIAGNOSTICS arşivi / klasörü")
    ap.add_argument("-o", "--out-dir", type=Path)
    a = ap.parse_args(rest)

    def log(msg):
        print(msg, file=sys.stderr)
    if cmd == "compare":
        from .compare import compare, write_outputs
        for p in (a.a, a.b):
            if not p.exists():
                ap.error(f"bulunamadı: {p}")
        out = a.out_dir or default_out_dir(Path(f"{a.a.stem}_vs_{a.b.stem}"))
        res = compare(a.a, a.b, log)
        p = write_outputs(res, out)
        _index(out, Path(f"{a.a} ↔ {a.b}"), "compare", log)
    else:
        if not a.source.exists():
            ap.error(f"bulunamadı: {a.source}")
        from .parsers.diag import scan_diagnostics
        from .source import open_source
        out = a.out_dir or default_out_dir(a.source)
        out.mkdir(parents=True, exist_ok=True)
        with open_source(a.source, log) as src:
            res = scan_diagnostics(src.entries, src.read_bytes)
        p = _write_diag(res, out)
    print(p)
    return 0


def _write_diag(res, out: Path) -> Path:
    import json
    from dataclasses import asdict
    lines = ["# Diagnostics", "", "## Bulgular", "", "| Bulgu | Önem | Güven | Detay | Kaynak |", "|---|---|---|---|---|"]
    lines += [f"| {f.title} | {f.severity} | {f.confidence} | {f.detail} | {f.source} |" for f in res.findings]
    lines += ["", "## Zaman çizelgesi", "", "| Zaman | Kategori | Olay | Dosya |", "|---|---|---|---|"]
    lines += [f"| {e.ts or '-'} | {e.category} | {e.text.replace('|', '/')} | {e.source} |" for e in res.events[:2000]]
    if res.warnings:
        lines += ["", "## Uyarılar", ""] + [f"- {w}" for w in res.warnings]
    p = out / "diag.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    def clean(o):
        if isinstance(o, dict):
            return {(k if isinstance(k, (str, int, float, bool)) or k is None else " / ".join(map(str, k))
                     if isinstance(k, tuple) else str(k)): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple, set)):
            return [clean(v) for v in o]
        return o
    (out / "diag.json").write_text(json.dumps(clean(asdict(res)), ensure_ascii=False, indent=1, default=str),
                                   encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> int:
    import os
    if sys.stdout is None:        # windowed exe: konsol yok
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in SUBCOMMANDS:
        return _sub_main(argv)
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
        from .analyze import ManualInputs
        try:
            manual = ManualInputs.load(args.manual) if args.manual else None
        except (OSError, ValueError) as e:
            raise UsageError(f"--manual okunamadı: {args.manual} ({e})") from e
        out = run(src, args.out_dir, TARGET, args.released, args.discover, log, args.template,
                  args.author, args.department, args.customer, args.inventory, manual, args.exports,
                  with_inventory=not args.no_inventory, collect=args.collect, profile=args.profile,
                  compare_to=args.compare_to)
    except UsageError as e:
        parser.error(str(e))
    idx = index_path(out)
    if args.open:
        webbrowser.open(idx.resolve().as_uri())
    print(out)
    if idx.name == "index.html":
        from .index_page import summary_lines
        for line in summary_lines(idx.parent):
            print(f"  {line}")
        print(f"Özet sayfası: {idx}")
    return 0
