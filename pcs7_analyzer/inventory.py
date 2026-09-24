"""
Envanter modu: backup'taki her şeyi OKUR ve LİSTELER; değerlendirme / yorum yapmaz.

Çıktılar:
  envanter.xlsx     tüm tablolar (filtrelenebilir)
  envanter.html     özet + tabloların ilk satırları (Siemens renkleri)
  yapi_tanisi.txt   sadece yapı bilgisi (DBF alan adları, kayıt sayıları, dosya türleri) -> müşteri verisi İÇERMEZ;
                    formatı henüz çözülmemiş dosyalar (ör. hOmSave7 HW DBF'leri) için geliştiriciyle paylaşılabilir.
"""
from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import __version__
from ._vendor import dbfread
from .discovery import DiscoveryResult, discover_source, owner_project
from .parsers import library_summary, parse_cfg, parse_subblk, read_symbol_asc_all, read_symlist_all, scan_s7h
from .parsers.hwconfig import _MLFB
from .parsers.wincc import picture_kind
from .report import _css
from .source import Source, open_source
from .xlsx import Workbook

_FW = re.compile(r"\bV\d{1,2}\.\d{1,2}(?:\.\d{1,3})?\b")
_KIND_LABEL = {"custom": "custom picture", "faceplate": "faceplate", "f_faceplate": "F faceplate",
               "typicals": "picture object template", "custom_typicals": "custom template"}
HTML_ROW_LIMIT = 300


@dataclass
class Sheet:
    name: str
    headers: list[str]
    rows: list[list] = field(default_factory=list)
    note: str = ""


@dataclass
class Inventory:
    source: str
    created: str
    discovery: DiscoveryResult
    sheets: list[Sheet] = field(default_factory=list)
    summary: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: str = ""

    def sheet(self, name: str) -> Sheet:
        return next(s for s in self.sheets if s.name == name)


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).isoformat(sep=" ", timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def _proj_dirs(d: DiscoveryResult) -> list[str]:
    return [p.rsplit("/", 1)[0] if "/" in p else "" for p in d.projects]


def _mp_of(d: DiscoveryResult, rel_dir: str) -> str:
    best = None
    for m in d.multiprojects:
        md = m.rsplit("/", 1)[0] if "/" in m else ""
        if (md == "" or rel_dir == md or rel_dir.startswith(md + "/")) and (best is None or len(md) > len(best[0])):
            best = (md, m)
    if best:
        return Path(best[1]).stem
    return Path(d.multiprojects[0]).stem if len(d.multiprojects) == 1 else ""


# ---------------------------------------------------------------------------
# Bölümler
# ---------------------------------------------------------------------------

def _projects(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    sh = Sheet("Projeler", ["Tür", "Ad", "Dosya", "Multiproject", "Dosya sayısı", "En yeni dosya tarihi"])
    for m in d.multiprojects:
        sh.rows.append(["Multiproject", Path(m).stem, m, Path(m).stem, "", ""])
    for p in d.projects:
        pd = p.rsplit("/", 1)[0] if "/" in p else ""
        files = [e for e in src.entries if e.rel.startswith(pd + "/")] if pd else src.entries
        sh.rows.append(["Proje", Path(p).stem, p, _mp_of(d, pd), len(files), _iso(max((e.mtime for e in files), default=0))])
    inv.sheets.append(sh)


def _hw_exports(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    mods = Sheet("HW modüller (export)", ["Station", "Export dosyası", "Konum", "MLFB / GSD", "FW", "İsim", "Tür"],
                 note="HW Config -> Station -> Export (.cfg) dosyalarından")
    stations = Sheet("HW station (export)", ["Station", "Export dosyası", "F-capable", "PDM kullanımı",
                                             "USED_S7_VERSIONS", "Export eden STEP 7", "Subnet'ler"])
    for rel in d.cfg_exports:
        try:
            cfg = parse_cfg(src.materialize(rel))
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{rel}: okunamadı ({e})")
            continue
        m = re.match(r'STATION\s+\S+\s*,\s*"([^"]*)"', cfg["station"])
        name = m.group(1) if m else Path(rel).stem
        stations.rows.append([name, rel, cfg["f_capable"], cfg["pdm_used"], cfg["used_s7_versions"],
                              cfg["export_step7_version"], "; ".join(re.sub(r"^SUBNET\s+", "", s) for s in cfg["subnets"])])
        for mo in cfg["modules"]:
            kind = ("dahili (HSP/port)" if mo.is_internal else "GSD cihaz" if mo.is_gsd and mo.is_station_header
                    else "GSD modül" if mo.is_gsd else "slave (IM)" if mo.is_station_header else
                    "CPU" if re.match(r"6ES7 ?41\d-", mo.order_no) else "CP" if mo.order_no.startswith("6GK7") else "modül")
            mods.rows.append([name, rel, mo.location, mo.order_no, mo.firmware, mo.name, kind])
    inv.sheets += [stations, mods]


def _hw_internal(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    """Export olmadan backup içinden HW: .s7h (MLFB + ardışık FW) ve hOmSave7 DBF'lerindeki MLFB'ler (ham tarama)."""
    sh = Sheet("HW (backup içi)", ["Proje", "Kaynak", "Yöntem", "MLFB", "FW", "Adet"],
               note="Export'suz ham tarama: MLFB ve FW doğru, rack/slot/adres yok; adetler kayıt sayısıdır (teyit edilmeli)")
    pdirs = _proj_dirs(d)
    for rel in d.s7h_files:
        try:
            for (mlfb, fw), n in sorted(scan_s7h(src.materialize(rel)).items()):
                sh.rows.append([owner_project(rel.rsplit("/", 1)[0], pdirs), rel, ".s7h tarama", mlfb, fw, n])
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{rel}: okunamadı ({e})")
    for e in src.entries:
        low = e.rel.lower()
        if "/homsave7/" not in "/" + low or not low.endswith(".dbf"):
            continue
        try:
            table = dbfread.DBF(str(src.materialize(e.rel)), encoding="latin1", char_decode_errors="ignore",
                                ignore_missing_memofile=True)
            found: Counter = Counter()
            for rec in table:
                vals = [v for v in rec.values() if isinstance(v, str) and v.strip()]
                text = " ".join(vals)
                for m in _MLFB.finditer(text.encode("latin1", "ignore")):
                    fw = _FW.search(text)
                    found[(m.group().decode(), fw.group() if fw else "")] += 1
            for (mlfb, fw), n in sorted(found.items()):
                sh.rows.append([owner_project(e.parent, pdirs), e.rel, "hOmSave7 DBF tarama", mlfb, fw, n])
        except Exception as ex:  # noqa: BLE001
            inv.warnings.append(f"{e.rel}: DBF okunamadı ({ex})")
    inv.sheets.append(sh)


def _blocks(src: Source, d: DiscoveryResult, inv: Inventory, log) -> dict[str, set[int]]:
    folders = Sheet("Block klasörleri", ["Proje", "Multiproject", "Klasör", "Kayıt", "FB", "FC", "DB", "OB",
                                         "DBT (instance bilgisi)", "Symbol table (FB seti eşleşmesi)"])
    blocks = Sheet("Bloklar", ["Proje", "Klasör", "Tür", "No", "İsim", "Family", "Author", "Library", "Versiyon",
                               "Dil (BLKLANG)", "Instance DB sayısı"],
                   note="FB'ler ve isimli FC'ler (CFC'nin ürettiği isimsiz FC'ler hariç); instance = SSBPART'tan")
    inst = Sheet("Instance sayıları", ["Proje", "Klasör", "Tür", "No", "İsim", "Instance DB sayısı"])
    libs = Sheet("Library özeti", ["Proje", "Klasör", "Library", "Author", "Block sayısı"])
    dbfam = Sheet("DB family", ["Proje", "Klasör", "DB family", "DB sayısı"])
    fb_sets: dict[str, set[int]] = {}
    for i, info in enumerate(d.block_folders, 1):
        pname = Path(info.project).name
        folder = info.path.rsplit("/", 1)[-1]
        row = [pname, _mp_of(d, info.project), info.path, info.n_records]
        if info.is_empty:
            folders.rows.append(row + [0, 0, 0, 0, "boş klasör", ""])
            continue
        log(f"[{i}/{len(d.block_folders)}] {info.path} ({info.n_records} kayıt)")
        try:
            if info.dbt:
                src.materialize(info.dbt)
            bf = parse_subblk(src.materialize(info.dbf), progress=lambda n, t: log(f"  {n}/{t}"))
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{info.path}: okunamadı ({e})")
            folders.rows.append(row + ["", "", "", "", f"HATA: {e}", ""])
            continue
        c = bf.counts
        folders.rows.append(row + [c.get("FB", 0), c.get("FC", 0), c.get("DB", 0), c.get("OB", 0),
                                   "var" if bf.memo_available else "yok (instance sayılamaz)", ""])
        fb_sets[info.path] = {b.number for b in bf.blocks if b.kind == "FB"}
        names = {b.number: b.name for b in bf.blocks if b.kind == "FB"}
        for b in bf.blocks:
            n = bf.instances_per_fb.get(("FB", b.number), 0) if b.kind == "FB" else ""
            blocks.rows.append([pname, folder, b.kind, b.number, b.name, b.family, b.author, b.library, b.version,
                                b.lang, n if bf.memo_available else ""])
        for (kind, nr), n in bf.instances_per_fb.most_common():
            inst.rows.append([pname, folder, kind, nr, names.get(nr, "") if kind == "FB" else "", n])
        for lib, cnt in sorted(library_summary(bf).items()):
            for author, n in sorted(cnt.items()):
                libs.rows.append([pname, folder, lib, author, n])
        for fam, n in bf.db_families.most_common():
            dbfam.rows.append([pname, folder, fam or "(boş)", n])
        if bf.unresolved_instances:
            inv.warnings.append(f"{info.path}: {bf.unresolved_instances} instance referansı çözülemedi")
    inv.sheets += [folders, blocks, inst, libs, dbfam]
    return fb_sets


def _symbols(src: Source, d: DiscoveryResult, inv: Inventory, fb_sets: dict[str, set[int]]) -> None:
    sh = Sheet("Semboller", ["Kaynak", "Proje", "Eşlenen block klasörü", "Sembol", "Operand", "Veri tipi", "Yorum"],
               note="YDBs/SYMLIST.DBF (backup içi) ve .asc export'ları; block klasörü eşlemesi FB seti benzerliği (heuristic)")
    pdirs = _proj_dirs(d)
    folders = inv.sheet("Block klasörleri")
    for rel in d.symbol_tables + d.symbol_exports:
        try:
            p = src.materialize(rel)
            if rel.lower().endswith(".dbf"):
                rows, _ = read_symlist_all(p)
            else:
                rows = read_symbol_asc_all(p)
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"Symbol table okunamadı: {rel} ({e})")
            continue
        sfb = set()
        for r in rows:
            m = re.match(r"(FB|SFB)\s*(\d+)$", r["operand"])
            if m and m.group(1) == "FB":
                sfb.add(int(m.group(2)))
        best, score = "", 0.0
        sym_proj = owner_project(rel.rsplit("/", 1)[0], pdirs)
        same = {pth: f for pth, f in fb_sets.items() if sym_proj != "-" and pth.startswith(sym_proj + "/")}
        for path, fbs in (same or fb_sets).items():
            if sfb and fbs:
                j = len(sfb & fbs) / len(sfb | fbs)
                if j > score:
                    best, score = path, j
        match = f"{best} (%{score * 100:.0f})" if score >= 0.5 else ""
        if match:
            for fr in folders.rows:
                if fr[2] == best:
                    fr[9] = (fr[9] + "; " if fr[9] else "") + f"{rel} (%{score * 100:.0f})"
        proj = Path(owner_project(rel.rsplit("/", 1)[0], pdirs)).name
        for r in rows:
            sh.rows.append([rel, proj, match, r["symbol"], r["operand"], r["datatype"], r["comment"]])
    inv.sheets.append(sh)


def _os(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    projs = Sheet("OS projeleri", ["OS projesi", "Klasör", "Yer", "Multiproject", "WinCC build", "Dosya", "Custom picture",
                                   "Faceplate/template (@)", "VBS modül (.bmo)", "VBS action (.bac)", "C action (.pas)",
                                   "En yeni dosya"])
    files = Sheet("OS dosyaları", ["OS projesi", "Yer", "Dosya", "Kategori", "Boyut (byte)", "Değişiklik tarihi"],
                  note="Picture, script, action ve OPC dosyaları (WinCC runtime/veritabanı dosyaları hariç)")
    for o in d.os_projects:
        in_es = o.project != "-"
        projs.rows.append([o.name, o.path, "ES (proje içinde)" if in_es else "proje dışı kopya (OS PC?)",
                           _mp_of(d, o.project) if in_es else "", o.wincc_build, o.n_files, o.custom_pictures,
                           o.faceplates_and_templates, o.vbs_modules, o.vbs_actions, o.c_actions, o.newest_mtime])
        from .parsers.wincc import OS_IGNORE_EXT, normalize_os_rel
        for e in sorted((x for x in src.entries if x.rel.startswith(o.path + "/")), key=lambda x: x.rel.lower()):
            rel_orig = e.rel[len(o.path) + 1:]
            rel = normalize_os_rel(rel_orig)
            if rel.endswith(OS_IGNORE_EXT):
                continue
            k = picture_kind(rel)
            if k != "other":
                cat = _KIND_LABEL.get(k, k)
            elif rel.endswith(".bmo"):
                cat = "VBS modül"
            elif rel.endswith(".bac"):
                cat = "VBS global action"
            elif rel.endswith(".act"):
                cat = "action"
            elif rel.endswith(".pas"):
                cat = "C action"
            elif rel.startswith("opc/"):
                cat = "OPC"
            else:
                continue
            files.rows.append([o.name, "ES" if in_es else "kopya", rel_orig, cat, e.size, _iso(e.mtime)])
    inv.sheets += [projs, files]


def _file_types(src: Source, inv: Inventory) -> None:
    c: Counter = Counter()
    s: Counter = Counter()
    for e in src.entries:
        ext = Path(e.name).suffix.lower() or "(uzantısız)"
        c[ext] += 1
        s[ext] += e.size
    inv.sheets.append(Sheet("Dosya türleri", ["Uzantı", "Adet", "Toplam boyut (MB)"],
                            [[k, n, round(s[k] / 1e6, 2)] for k, n in c.most_common()]))


# Yapı tanısında açık yazılan (müşteriye özgü olmayan) STEP 7 / WinCC klasör adları
KNOWN_DIRS = {"ombstx", "offline", "online", "homsave7", "s7hstatx", "ydbs", "global", "xutils", "s7asrcom", "s7cfc",
              "s7wb53ax", "s7netze", "s7nfrdbx", "s7nfrdb", "s7nfrsbx", "s7nfrsb", "s7ncfgx", "s7ncfg", "dbmhdbx", "hrs",
              "s7hk41ax", "s7hkdmax", "s7hkimdx", "s7pfaxdb", "subblk", "wincproj", "gracs", "scriptlib", "scriptact",
              "pas", "opc", "library", "text", "prt", "cfcdata", "chartsfc", "apilog", "s7fcpnx", "s7obbsx", "amobjs",
              "ssdb", "tmp", "sfcdata", "s7topdb", "s7techx", "s7pdiagx", "s7mdb"}


def mask_path(rel: str) -> str:
    """Son 3 seviye; bilinen klasör adları açık, hex -> <hex>, sayı -> <n>, diğerleri (proje/müşteri adı olabilir) -> <klasör>."""
    parts = rel.split("/")[-3:]
    out = []
    for i, p in enumerate(parts):
        if i == len(parts) - 1:
            out.append(p.upper() if p.lower().endswith(".dbf") and len(p) <= 16 else "<dosya>")
        elif re.fullmatch(r"[0-9A-Fa-f]{8}", p):
            out.append("<hex>")
        elif p.isdigit():
            out.append("<n>")
        elif p.lower() in KNOWN_DIRS:
            out.append(p)
        else:
            out.append("<klasör>")
    return "/".join(out)


def diagnostics(src: Source) -> str:
    """Müşteri verisi içermeyen yapı raporu: DBF şemaları (alan adı/tip/uzunluk) + kayıt sayıları, dosya türleri."""
    lines = [f"PCS 7 backup yapı tanısı — pcs7_analyzer {__version__} — {datetime.now():%Y-%m-%d %H:%M}",
             "Bu dosya sadece yapı bilgisi içerir (dosya türleri, DBF alan adları, kayıt sayıları); kayıt içeriği YOKTUR.", ""]
    schemas: dict[tuple, list] = defaultdict(list)
    for e in src.entries:
        if not e.name.lower().endswith(".dbf"):
            continue
        pattern = mask_path(e.rel)
        try:
            head = src.read_head(e.rel, 8192)
            if len(head) < 32:
                continue
            nrec = int.from_bytes(head[4:8], "little")
            hlen = int.from_bytes(head[8:10], "little")
            fields = []
            for i in range(32, min(hlen, len(head)) - 1, 32):
                if head[i] == 0x0D:
                    break
                fname = head[i:i + 11].split(b"\x00", 1)[0].decode("latin1", "replace")
                fields.append(f"{fname}:{chr(head[i + 11])}{head[i + 16]}")
            key_name = e.name.upper() if len(e.name) <= 16 else "<dosya>.DBF"
            schemas[(key_name, tuple(fields))].append((pattern, nrec, e.size))
        except Exception:  # noqa: BLE001
            continue
    lines.append(f"## DBF şemaları ({len(schemas)} farklı şema)")
    for (name, fields), occ in sorted(schemas.items()):
        recs = [o[1] for o in occ]
        pats = sorted({o[0] for o in occ})
        lines.append(f"- {name}  ×{len(occ)} dosya, kayıt: min {min(recs)} / max {max(recs)} / toplam {sum(recs)}")
        lines.append(f"    konum: {', '.join(pats[:4])}{' …' if len(pats) > 4 else ''}")
        lines.append(f"    alanlar: {', '.join(fields)}")
    ext = Counter(Path(e.name).suffix.lower() for e in src.entries)
    lines += ["", "## Dosya türleri", ", ".join(f"{k or '(yok)'}: {n}" for k, n in ext.most_common())]
    s7h = [e for e in src.entries if e.name.lower().endswith(".s7h")]
    if s7h:
        lines += ["", f"## .s7h dosyaları: {len(s7h)} adet, boyut min {min(e.size for e in s7h)} / max {max(e.size for e in s7h)} byte"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Ana giriş ve çıktılar
# ---------------------------------------------------------------------------

def build_inventory_source(src: Source, log=None) -> Inventory:
    log = log or (lambda m: None)
    log("Keşif...")
    d = discover_source(src)
    inv = Inventory(source=src.label, created=datetime.now().isoformat(sep=" ", timespec="minutes"), discovery=d)
    inv.warnings += d.warnings
    log("Projeler...")
    _projects(src, d, inv)
    log("HW Config export'ları...")
    _hw_exports(src, d, inv)
    log("HW (backup içi tarama)...")
    _hw_internal(src, d, inv)
    log("Block klasörleri...")
    fb_sets = _blocks(src, d, inv, log)
    log("Symbol table'lar...")
    _symbols(src, d, inv, fb_sets)
    log("OS projeleri...")
    _os(src, d, inv)
    _file_types(src, inv)
    log("Yapı tanısı...")
    inv.diagnostics = diagnostics(src)

    authors = Counter()
    for r in inv.sheet("Library özeti").rows:
        if r[2] in ("APL", "Basis Library", "S7 F Systems Failsafe Blocks", "Logic Matrix", "PCS 7 Library V7.1 COMM"):
            authors[f"{r[2]}: {r[3]}"] += r[4]
    step7 = sorted({r[4] for r in inv.sheet("HW station (export)").rows if r[4]})
    wincc = sorted({o.wincc_build for o in d.os_projects if o.wincc_build})
    inv.summary = [
        ("Kaynak", inv.source), ("Tarih", inv.created),
        ("Dosya / boyut", f"{d.n_files} dosya, {d.total_bytes / 1e9:.2f} GB"),
        ("Multiproject", ", ".join(Path(m).stem for m in d.multiprojects) or "-"),
        ("Proje", str(len(d.projects))),
        ("Block klasörü", f"{len(d.block_folders)} ({sum(1 for b in d.block_folders if b.is_empty)} boş)"),
        ("HW Config export (.cfg)", str(len(d.cfg_exports))), (".s7h (backup içi HW)", str(len(d.s7h_files))),
        ("Symbol table (SYMLIST.DBF / export)", f"{len(d.symbol_tables)} / {len(d.symbol_exports)}"),
        ("OS projesi", str(len(d.os_projects))),
        ("USED_S7_VERSIONS (export)", ", ".join(step7) or "-"),
        ("WinCC build (.mcp)", ", ".join(wincc) or "-"),
        ("Library author'ları", "; ".join(f"{k} ({n})" for k, n in sorted(authors.items())) or "-"),
        ("Uyarı", str(len(inv.warnings))),
    ]
    inv.sheets.insert(0, Sheet("Özet", ["Konu", "Değer"], [list(x) for x in inv.summary]))
    inv.sheets.append(Sheet("Uyarılar", ["Uyarı"], [[w] for w in inv.warnings]))
    return inv


def build_inventory(path: Path, log=None) -> Inventory:
    with open_source(path, log) as src:
        return build_inventory_source(src, log)


def write_xlsx(inv: Inventory, path: Path) -> Path:
    wb = Workbook()
    for s in inv.sheets:
        wb.add(s.name, s.headers, s.rows)
    return wb.save(path)


def render_html(inv: Inventory) -> str:
    e = html.escape
    toc, body = [], []
    for i, s in enumerate(inv.sheets):
        toc.append(f'<a href="#t{i}">{e(s.name)} ({len(s.rows)})</a>')
        rows = [["Evet" if v is True else "Hayır" if v is False else v for v in r] for r in s.rows[:HTML_ROW_LIMIT]]
        more = (f'<div class="caption">İlk {HTML_ROW_LIMIT} / {len(s.rows)} satır gösteriliyor — tam liste envanter.xlsx içinde.</div>'
                if len(s.rows) > HTML_ROW_LIMIT else "")
        table = ("<div class='tw'><table><thead><tr>" + "".join(f"<th>{e(h)}</th>" for h in s.headers) + "</tr></thead><tbody>"
                 + "".join("<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in r) + "</tr>" for r in rows)
                 + "</tbody></table></div>") if s.rows else "<p>Kayıt yok.</p>"
        body.append(f'<section id="t{i}"><h2>{e(s.name)}</h2>' + (f'<div class="note">{e(s.note)}</div>' if s.note else "")
                    + table + more + "</section>")
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>PCS 7 Envanter</title>
<style>{_css()} nav a {{ display:inline-block; margin: 2px 14px 2px 0; }}</style></head><body>
<header><div class="topline">SIMATIC PCS 7 · Proje envanteri</div><h1>Backup envanteri</h1>
<div class="sub">{e(inv.created)} · Kaynak: {e(inv.source)} · Değerlendirme içermez, sadece backup'ta bulunanlar listelenir.</div></header>
<nav>{''.join(toc)}</nav><main>{''.join(body)}</main>
<footer>pcs7_analyzer {e(__version__)} · Envanter modu</footer></body></html>"""


def write_outputs(inv: Inventory, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_xlsx(inv, out_dir / "envanter.xlsx")
    p = out_dir / "envanter.html"
    p.write_text(render_html(inv), encoding="utf-8")
    (out_dir / "yapi_tanisi.txt").write_text(inv.diagnostics, encoding="utf-8")
    return p


__all__ = ["Inventory", "build_inventory", "build_inventory_source", "write_outputs", "write_xlsx", "diagnostics"]
