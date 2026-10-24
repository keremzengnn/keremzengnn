"""
Envanter modu: backup'taki her şeyi OKUR ve LİSTELER; değerlendirme / yorum yapmaz.

Çıktılar:
  envanter.xlsx     tüm tablolar (filtrelenebilir)
  envanter.html     özet + tabloların ilk satırları (Siemens renkleri); boş sayfa yazılmaz
  semboller.xlsx    symbol table'lar + sembol kontrolleri (sadece symbol varsa; envantere girmez)
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
from .parsers.symbols import symbol_stats
from .mlfb_info import describe
from .parsers.hwconfig import _MLFB
from .report import _css
from .source import Source, open_source
from .xlsx import Workbook

_CPU_RE = re.compile(r"^6ES7 ?(41\d|31[2-9])-")
_FW = re.compile(r"\bV\d{1,2}\.\d{1,2}(?:\.\d{1,3})?\b")
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
    block_data: list = field(default_factory=list)      # [(BlockFolderInfo, BlockFolder)] -> Mevcut durum
    blockmap_diag: str = ""                              # blockmap_tanisi.txt (isimler maskeli)
    folder_as: dict = field(default_factory=dict)        # {block klasörü rel: "AS02 (S7 program P, CPU 414-5H, S7-400H, rack/slot 0/3; ÇIKARIM)"}
    special_blocks: list = field(default_factory=list)   # 'Özel bloklar' satırları (Kategori = sütun 2)
    blockmap: object = None                              # blockmap.BlockMap (bir kez çözülür)
    projects_meta: list = field(default_factory=list)    # [(ad, proje klasörü, en yeni dosya tarihi)]
    hw_stations: list = field(default_factory=list)      # HW export: [dict(name, rel, f_capable, pdm, used_s7, items)]
    hw_scan: list = field(default_factory=list)          # ham tarama: [(proje klasörü, rel, yöntem, mlfb, fw, adet)]
    os_rows: list = field(default_factory=list)          # [(OsProjectInfo, rol, yer)]
    symbol_sheets: list = field(default_factory=list)    # semboller.xlsx (envantere girmez)

    def sheet(self, name: str) -> Sheet:
        return next(s for s in self.sheets if s.name == name)

    def has(self, name: str) -> bool:
        return any(s.name == name for s in self.sheets)


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
    sh = Sheet("Projeler", ["Tür", "Ad", "Multiproject", "En yeni tarih"])
    for m in d.multiprojects:
        sh.rows.append(["Multiproject", Path(m).stem, Path(m).stem, ""])
    stems = Counter(Path(p).stem.lower() for p in d.projects)
    for p in d.projects:
        pd = p.rsplit("/", 1)[0] if "/" in p else ""
        newest = _iso(max((e.mtime for e in src.entries if not pd or e.rel.startswith(pd + "/")), default=0))
        inv.projects_meta.append((Path(p).stem, pd, newest))
        name = Path(p).stem + (f" ({pd})" if stems[Path(p).stem.lower()] > 1 else "")   # aynı isimli kopya: konum
        sh.rows.append(["Proje", name, _mp_of(d, pd), newest])
    inv.sheets.append(sh)


# Hardware sayfası: tür sırası (station içinde CPU önce)
HW_KINDS = ("CPU", "CP", "IM", "PS", "modül", "GSD", "diğer")
_IM_RE = re.compile(r"^6ES7 ?(15\d|46\d|36\d)-")
_PS_RE = re.compile(r"^6ES7 ?(40[57]|307)-")
_OTHER_RE = re.compile(r"^6ES7 ?(400|390|960|972)-")      # rack, H-Sync, bus connector…
SRC_EXPORT, SRC_S7H, SRC_DBF = "HW export", ".s7h taraması (çıkarım)", "hOmSave7 DBF taraması (çıkarım)"


def hw_kind(mlfb: str, station_header: bool = False, gsd: bool = False) -> str:
    """MLFB -> Hardware sayfası türü (CPU/CP/IM/PS/modül/GSD/diğer)."""
    if gsd:
        return "GSD"
    if _CPU_RE.match(mlfb):
        return "CPU"
    if mlfb.startswith("6GK7"):
        return "CP"
    if station_header or _IM_RE.match(mlfb):
        return "IM"
    if _PS_RE.match(mlfb):
        return "PS"
    if _OTHER_RE.match(mlfb):
        return "diğer"
    return "modül"


def _model(mlfb: str, fallback: str = "") -> str:
    """Model / açıklama: Released Modules listesi; MLFB ailesinden ise ' (çıkarım)'; yoksa HW Config ismi."""
    from .mlfb_info import SRC_FAMILY
    desc, dsrc = describe(mlfb)
    if desc:
        return desc + (" (çıkarım)" if dsrc == SRC_FAMILY else "")
    return fallback


def _hw_exports(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    for rel in d.cfg_exports:
        try:
            cfg = parse_cfg(src.materialize(rel))
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{rel}: okunamadı ({e})")
            continue
        m = re.match(r'STATION\s+\S+\s*,\s*"([^"]*)"', cfg["station"])
        name = m.group(1) if m else Path(rel).stem
        items: Counter = Counter()
        for mo in cfg["modules"]:
            if mo.is_internal:
                continue                                   # HSP submodule / port
            kind = hw_kind(mo.order_no, mo.is_station_header, mo.is_gsd)
            items[(kind, mo.order_no, _model(mo.order_no, mo.name), mo.firmware)] += 1
        inv.hw_stations.append({"name": name, "rel": rel, "f_capable": cfg["f_capable"], "pdm": cfg["pdm_used"],
                                "used_s7": cfg["used_s7_versions"], "items": items})


def _hw_internal(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    """Export olmadan backup içinden HW: .s7h (MLFB + ardışık FW) ve hOmSave7 DBF'lerindeki MLFB'ler (ham tarama)."""
    pdirs = _proj_dirs(d)
    for rel in d.s7h_files:
        try:
            for (mlfb, fw), n in sorted(scan_s7h(src.materialize(rel)).items()):
                inv.hw_scan.append((owner_project(rel.rsplit("/", 1)[0], pdirs), rel, SRC_S7H, mlfb, fw, n))
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
                inv.hw_scan.append((owner_project(e.parent, pdirs), e.rel, SRC_DBF, mlfb, fw, n))
        except Exception as ex:  # noqa: BLE001
            inv.warnings.append(f"{e.rel}: DBF okunamadı ({ex})")


def _stale_dirs(inv: Inventory) -> tuple[set, list[str]]:
    """Aynı isimli proje birden fazla yerde: en yeni dosya tarihli kopya kullanılır; diğer klasörler + not."""
    copies: dict = defaultdict(list)
    for name, pd, newest in inv.projects_meta:
        copies[name.lower()].append((str(newest or ""), pd))
    stale: set = set()
    notes = []
    for name, cs in sorted(copies.items()):
        if len(cs) > 1:
            cs.sort(reverse=True)
            stale |= {c[1] for c in cs[1:]}
            notes.append(f"{cs[0][1] or name} (en yeni, {cs[0][0]}) kullanıldı; özet dışı: "
                         + ", ".join(f"{c[1]} ({c[0]})" for c in cs[1:]))
    return stale, notes


def _hardware(inv: Inventory) -> None:
    """Tek Hardware tablosu: export'u olan station'lar export'tan; export'u olmayan projeler backup taramasından."""
    stale, _ = _stale_dirs(inv)
    sh = Sheet("Hardware", ["Station / Proje", "Tür", "MLFB", "Model / açıklama", "FW", "Adet", "Kaynak", "Dosya"])
    order = {k: i for i, k in enumerate(HW_KINDS)}
    files = []
    for st in sorted(inv.hw_stations, key=lambda s: s["name"].lower()):
        files.append(st["rel"])
        for (kind, mlfb, model, fw), n in sorted(st["items"].items(), key=lambda x: (order.get(x[0][0], 99), x[0][1:])):
            sh.rows.append([st["name"], kind, mlfb, model, fw, n, SRC_EXPORT, Path(st["rel"]).name])
    for proj, items in _scan_by_project(inv, stale).items():
        for (kind, mlfb, fw), (n, rel, method) in sorted(items.items(), key=lambda x: (order.get(x[0][0], 99), x[0][1:])):
            files.append(rel)
            sh.rows.append([Path(proj).name or proj or "-", kind, mlfb, _model(mlfb), fw, n, method, Path(rel).name])
    sh.note = ("Export'u olan station: HW Config export (.cfg); olmayan proje: backup içi ham tarama (MLFB doğru, FW her zaman "
               "okunamaz, rack/slot yok, adet = kayıt sayısı -> çıkarım). Aynı isimli projenin eski kopyaları hariç. "
               "'(çıkarım)' = açıklama MLFB ailesinden. Dosyalar: " + ", ".join(sorted(set(files))[:20])
               + (" …" if len(set(files)) > 20 else ""))
    inv.sheets.append(sh)


def _scan_by_project(inv: Inventory, stale: set) -> dict:
    """{proje klasörü: {(tür, mlfb, fw): (adet, dosya, yöntem)}} — export'u olan / eski kopya projeler hariç;
    .s7h taraması varsa hOmSave7 DBF taraması kullanılmaz."""
    exported = {_norm_name(s["name"]) for s in inv.hw_stations}
    by: dict = defaultdict(lambda: defaultdict(dict))
    for proj, rel, method, mlfb, fw, n in inv.hw_scan:
        if proj in stale or _norm_name(Path(proj).name) in exported:
            continue
        cur = by[proj][method].get((hw_kind(mlfb), mlfb, fw))
        by[proj][method][(hw_kind(mlfb), mlfb, fw)] = ((cur[0] if cur else 0) + n, rel, method)
    return {p: (m.get(SRC_S7H) or m.get(SRC_DBF) or {}) for p, m in sorted(by.items())}


# --- Block klasörleri / Özel bloklar ---------------------------------------------------------------------------
# Standart library block'ları (APL, Basis, Industry Library, ELEMENTA, CFC'nin ürettiği FC/DB, SFC system, SIMATIC
# system, isimden tanınan IEC standart block'ları) tek tek listelenmez: sayıları 'Block klasörleri' -> "Library'ler".
_STD_LIBS = {"APL", "Basis Library", "PCS 7 Industry Library", "CFC ELEMENTA", "CFC generated", "SFC system",
             "SIMATIC system / Standard Library"}
SPECIAL_CATEGORIES = ("Custom", "Know-how protected custom", "Header'sız", "Modbus", "Siemens add-on", "Haberleşme",
                      "Logic Matrix", "PCS 7 Library V7.1", "F-System")
_CUSTOM_CATS = {"Custom", "Know-how protected custom", "Header'sız"}


def special_category(b, protected: bool = False, symbol: str = "") -> str | None:
    """Block (parsers.subblk.BlockHeader) 'Özel bloklar'da listelenecek mi? Kategori ya da None (standart library).
    Header'sız block'ta isim yoksa symbol table'daki ad (``symbol``) kullanılır."""
    from .analyze import is_f_block_name
    from .checks import STD_COMM
    from .parsers.subblk import STANDARD_BLOCK_NAMES, STANDARD_LIBRARY
    lib = b.library
    name = (b.name or symbol or "").strip().upper()
    unknown = lib in ("custom", "custom/unknown")
    if name in STD_COMM and (name.startswith("MB_") or name.startswith("MODBUS")):
        return "Modbus"
    if lib.startswith("Siemens add-on"):
        return "Siemens add-on"
    if lib == "Logic Matrix":
        return "Logic Matrix"
    if lib == "S7 F Systems Failsafe Blocks" or (unknown and is_f_block_name(name)):
        return "F-System"
    if lib == "PCS 7 Library V7.1 COMM":
        return "PCS 7 Library V7.1"
    if name in STD_COMM:
        return "Haberleşme"
    if lib in _STD_LIBS or lib == STANDARD_LIBRARY or name in STANDARD_BLOCK_NAMES:
        return None
    if unknown:
        if protected:
            return "Know-how protected custom"
        return "Custom" if lib == "custom" else "Header'sız"
    return None


def _link_label(lk) -> str:
    """blockmap.ProgramLink -> 'AS02 (S7 program AS02_Prog, CPU 414-5H, S7-400H, rack/slot 0/3; ÇIKARIM)'."""
    det = [f"S7 program {lk.program_name}" if lk.station_name and lk.program_name else "", lk.cpu_name,
           lk.station_type, f"rack/slot {lk.rack}/{lk.slot}" if lk.rack is not None else ""]
    det = ", ".join(x for x in det if x)
    return f"{lk.label} ({det + '; ' if det else ''}{lk.confidence})"


def _resolve_blockmap(src: Source, d: DiscoveryResult, inv: Inventory):
    """S7 program -> block klasörü -> CPU -> station zinciri; bir kez çözülür (inv.blockmap), inv.folder_as doldurulur."""
    if inv.blockmap is not None:
        return inv.blockmap
    from .blockmap import BlockMap, diagnostics as bm_diag, resolve
    try:
        bm = resolve(src, _proj_dirs(d))
    except Exception as e:  # noqa: BLE001 - zincir yoksa block listesi yine çıkar
        inv.warnings.append(f"S7 program ↔ AS zinciri çözülemedi: {type(e).__name__}: {e}")
        bm = BlockMap()
    inv.blockmap = bm
    try:
        inv.blockmap_diag = bm_diag(bm)
    except Exception as e:  # noqa: BLE001
        inv.warnings.append(f"blockmap tanısı üretilemedi: {e}")
    inv.warnings += [f"S7 program ↔ AS: {u}" for u in bm.unknown]
    for lk in bm.links:
        if lk.block_folder:
            inv.folder_as[lk.block_folder] = _link_label(lk)
    return bm


def _folder_symbols(src: Source, d: DiscoveryResult, bm, info) -> dict:
    """Block klasörünün SYMLIST.DBF'i -> {(tür, no): sembol}: ID zincirinin (YLNKLIST) bağladığı tablo; yoksa projede
    tek symbol table varsa o (heuristic). Bulunamazsa {}."""
    lk = bm.for_folder(info.path) if bm is not None else None
    rel = lk.symbol_table if lk else None
    if not rel and info.project != "-":
        own = [s for s in d.symbol_tables if s.lower().startswith(info.project.lower() + "/")]
        rel = own[0] if len(own) == 1 else None
    if not rel:
        return {}
    try:
        rows, _ = read_symlist_all(src.materialize(rel))
    except Exception:  # noqa: BLE001 - sadece header'sız block adı için; Semboller bölümü hatayı ayrıca raporlar
        return {}
    out = {}
    for r in rows:
        m = re.match(r"(FB|FC|SFB)\s*(\d+)$", r["operand"])
        if m:
            out[(m.group(1), int(m.group(2)))] = r["symbol"]
    return out


def _library_cell(bf) -> str:
    """'APL V8.0: 1, V8.1: 2 (karışık versiyon); Basis Library V8.1: 1; CFC ELEMENTA: 12' (custom hariç)."""
    from .analyze import author_version
    parts = []
    for lib, cnt in sorted(library_summary(bf).items()):
        if lib in ("custom", "custom/unknown"):
            continue
        vers: Counter = Counter()
        for a, n in cnt.items():
            vers[author_version(a)] += n
        if len(vers) == 1:
            v, n = next(iter(vers.items()))
            parts.append(f"{lib}{' ' + v if v and v not in lib else ''}: {n}")
        else:
            inner = ", ".join(f"{v or 'sürümsüz'}: {n}" for v, n in sorted(vers.items()))
            parts.append(f"{lib} {inner}" + (" (karışık versiyon)" if sum(1 for v in vers if v) > 1 else ""))
    return "; ".join(parts)


def _short_list(xs: list[str], k: int = 6) -> str:
    return ", ".join(xs[:k]) + (f" … (+{len(xs) - k})" if len(xs) > k else "")


def _special_rows(bf, proj: str, label: str, syms: dict) -> tuple[list[list], int]:
    """Bir block klasörünün 'Özel bloklar' satırları + özel block sayısı. F-System author başına tek satır (özet)."""
    from .checks import STD_COMM_SFB
    order = {c: i for i, c in enumerate(SPECIAL_CATEGORIES)}
    rows, f_groups = [], defaultdict(list)
    for b in bf.blocks:
        sym = syms.get((b.kind, b.number), "") if not b.name else ""
        cat = special_category(b, (b.kind, b.number) in bf.protected, sym)
        if cat is None:
            continue
        n = bf.instances_per_fb.get(("FB", b.number), 0) if b.kind == "FB" and bf.memo_available else ""
        if cat == "F-System":
            f_groups[b.author or "(header yok, symbol adından)"].append((b, n))
            continue
        name = b.name or (f"{sym} (symbol)" if sym else "")
        rows.append([proj, label, cat, b.kind, b.number, name, b.author, b.language, n])
    for author, items in sorted(f_groups.items()):
        kinds = "/".join(sorted({b.kind for b, _ in items}))
        nrs = [f"{b.kind}{b.number}" for b, _ in sorted(items, key=lambda x: (x[0].kind, x[0].number))]
        inst = sum(n for _, n in items if n != "")
        rows.append([proj, label, "F-System", kinds, _short_list(nrs, 4), f"{len(items)} block (özet)", author, "",
                     inst if bf.memo_available else ""])
    for (kind, nr), n in sorted(bf.instances_per_fb.items()):
        if kind == "SFB" and nr in STD_COMM_SFB and n:
            rows.append([proj, label, "Haberleşme", "SFB", nr, STD_COMM_SFB[nr], "SIMATIC (system)", "", n])
    rows.sort(key=lambda r: (order.get(r[2], 99), r[3], r[4] if isinstance(r[4], int) else -1))
    return rows, len(rows) - len(f_groups) + sum(len(x) for x in f_groups.values())


def _blocks(src: Source, d: DiscoveryResult, inv: Inventory, log) -> dict[str, set[int]]:
    """Kompakt block envanteri: dolu klasör başına bir satır + sadece özel block'lar tek tek (standart library'ler sayı)."""
    folders = Sheet("Block klasörleri", ["Proje", "AS / S7 program", "Klasör", "FB", "FC", "DB", "OB", "Library'ler",
                                         "Özel block", "Custom"])
    special = Sheet("Özel bloklar", ["Proje", "Klasör / AS", "Kategori", "Tür", "No", "İsim", "Author", "Dil",
                                     "Instance sayısı"],
                    note="Sadece özel block'lar: custom (integratör), header'sız, know-how protected, Modbus / Siemens "
                         "add-on, haberleşme (PUT/GET/BSEND/TSEND/TCON…), Logic Matrix, PCS 7 Library V7.1, F-System "
                         "(author başına özet). Standart library'ler (APL, Basis, Industry Library, ELEMENTA, ES_MAP, "
                         "ES_SFC, SIMATIC/IEC) listelenmez: sayıları 'Block klasörleri' -> Library'ler. Header'sız "
                         "block adı '(symbol)' = ID zincirinin bağladığı (yoksa projedeki tek) symbol table'dan "
                         "(ÇIKARIM).")
    bm = _resolve_blockmap(src, d, inv)
    names = Counter(Path(i.project).name for i in d.block_folders)
    fb_sets: dict[str, set[int]] = {}
    n_empty = 0
    for i, info in enumerate(d.block_folders, 1):
        if info.is_empty:
            n_empty += 1
            continue
        pname = Path(info.project).name
        proj = pname if names[pname] < 2 or info.project == "-" else info.project   # aynı isimli kopyalar ayrışsın
        as_lab = inv.folder_as.get(info.path, "-")
        lk = bm.for_folder(info.path)
        label = lk.label if lk else info.label          # kısa etiket (station / S7 program adı)
        log(f"[{i}/{len(d.block_folders)}] {info.path} ({info.n_records} kayıt)")
        try:
            if info.dbt:
                src.materialize(info.dbt)
            bf = parse_subblk(src.materialize(info.dbf), progress=lambda n, t: log(f"  {n}/{t}"))
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{info.path}: okunamadı ({e})")
            folders.rows.append([proj, as_lab, info.path, "", "", "", "", f"HATA: {e}", "", ""])
            continue
        c = bf.counts
        fb_sets[info.path] = {b.number for b in bf.blocks if b.kind == "FB"}
        rows, n_special = _special_rows(bf, proj, label, _folder_symbols(src, d, bm, info))
        n_custom = sum(1 for r in rows if r[2] in _CUSTOM_CATS)
        folders.rows.append([proj, as_lab, info.path, c.get("FB", 0), c.get("FC", 0), c.get("DB", 0), c.get("OB", 0),
                             _library_cell(bf), n_special, n_custom])
        special.rows += rows
        if not bf.memo_available:
            inv.warnings.append(f"{info.path}: SUBBLK.DBT yok -> instance sayıları boş")
        if bf.unresolved_instances:
            inv.warnings.append(f"{info.path}: {bf.unresolved_instances} instance referansı çözülemedi")
        if bf.bad_records:
            inv.warnings.append(f"{info.path}: {bf.bad_records} SUBBLK kaydı okunamadı (atlandı)")
        inv.block_data.append((info, bf))
    folders.note = ((f"{n_empty} boş block klasörü listelenmedi. " if n_empty else "")
                    + "AS / S7 program: STEP 7 ID zinciri (S7RESOFF, linkhrs.lnk, HRELATI1), gerçek projede teyit "
                      "edilmedi (ÇIKARIM); '-' = zincir bulunamadı. Library'ler: block header author -> library + "
                      "versiyon (block sayısı). Özel block / Custom: 'Özel bloklar' sayfasındaki block sayısı.")
    inv.special_blocks = special.rows
    inv.sheets += [folders, special]
    return fb_sets


def _programs(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    """S7 program -> block klasörü -> CPU -> station (blockmap ID zinciri). Ayrı sayfa yok: sonuç 'Block klasörleri'
    sayfasının "AS / S7 program" sütununda (`inv.folder_as`); burada sadece zincir (ve blockmap_tanisi) garanti edilir."""
    _resolve_blockmap(src, d, inv)


def _symbols(src: Source, d: DiscoveryResult, inv: Inventory, fb_sets: dict[str, set[int]]) -> None:
    sh = Sheet("Semboller", ["Kaynak", "Proje", "Eşlenen block klasörü", "Sembol", "Operand", "Veri tipi", "Yorum"],
               note="YDBs/SYMLIST.DBF (backup içi) ve .asc export'ları; block klasörü eşlemesi FB seti benzerliği (heuristic)")
    pdirs = _proj_dirs(d)
    chk = Sheet("Sembol kontrolleri", ["Kaynak", "Proje", "Kontrol", "Değer", "Detay", "Güven"],
                note="Çift operand / çift sembol adı / alan bazında adres aralığı. Bit-word çakışması (M10.0 - MW10) "
                     "kontrol edilmez.")
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
        proj = Path(owner_project(rel.rsplit("/", 1)[0], pdirs)).name
        for r in rows:
            sh.rows.append([rel, proj, match, r["symbol"], r["operand"], r["datatype"], r["comment"]])
        st = symbol_stats(rows)
        chk.rows.append([rel, proj, "toplam sembol", st["total"], "", ""])
        for area, (n, lo, hi) in st["areas"].items():
            chk.rows.append([rel, proj, "adres aralığı", f"{area}: {n}", f"{lo} … {hi}", ""])
        for op, syms in st["dup_operand"].items():
            chk.rows.append([rel, proj, "aynı operanda birden fazla sembol", op, ", ".join(syms[:5]), "KANIT"])
        for sym, n in st["dup_symbol"].items():
            chk.rows.append([rel, proj, "aynı sembol adı birden fazla satırda", sym, f"{n} satır", "KANIT"])
        if st["unparsed"]:
            chk.rows.append([rel, proj, "tanınmayan operand", st["unparsed"], "", "-"])
    inv.symbol_sheets = [s for s in (sh, chk) if s.rows]     # semboller.xlsx (envanter sayfası değil)


def _os(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    """Her OS projesi tek satır (dosya listesi yok). Rol isimden; isimden client görünen ama arşivi olan = server."""
    from .analyze import os_role
    from .parsers.wincc import archive_files
    sh = Sheet("OS projeleri", ["OS", "Rol", "Yer", "Multiproject", "WinCC build", "Custom picture",
                                "Faceplate / template (@)", "VBS modül (.bmo)", "VBS action (.bac)", "C action (.pas)",
                                "Son değişiklik"],
               note="Rol OS proje adından (çıkarım); 'OS PC kopyası' = .s7p dışında bulunan OS projesi. Klasör: "
                    + ", ".join(sorted({o.path.rsplit("/wincproj/", 1)[0] for o in d.os_projects})[:10]))
    for o in d.os_projects:
        in_es = o.project != "-"
        role = "library" if o.is_library else os_role(o.name)
        if role in ("?", "client"):
            arch = archive_files(src.entries, o.path, o.name)
            if arch.get("alg_tlg") or arch.get("segments"):
                role = "server (arşiv var)"
            elif role == "?":
                role = "client?"
        yer = "ES" if in_es else "OS PC kopyası"
        inv.os_rows.append((o, role, yer))
        sh.rows.append([o.name, role, yer, _mp_of(d, o.project) if in_es else "", o.wincc_build or "-",
                        o.custom_pictures, o.faceplates_and_templates, o.vbs_modules, o.vbs_actions, o.c_actions,
                        str(o.newest_mtime or "").replace("T", " ")])
    inv.sheets.append(sh)


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
             "Bu dosya sadece yapı bilgisi içerir (dosya türleri, DBF alan adları, kayıt sayıları, kod dağılımları, "
             "block author kodları); sembol / block / proje adı YOKTUR.", ""]
    schemas: dict[tuple, list] = defaultdict(list)
    bad: list[str] = []
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
        except Exception as ex:  # noqa: BLE001 - tanı dosyasında sayılır
            bad.append(f"{pattern}: {type(ex).__name__}")
    lines.append(f"## DBF şemaları ({len(schemas)} farklı şema)")
    if bad:
        lines.append(f"Okunamayan DBF başlığı: {len(bad)} (" + ", ".join(sorted(set(bad))[:10]) + ")")
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
    lines += _format_probe(src)
    return "\n".join(lines) + "\n"


# Kod alanları (müşteri verisi değil: tip / dil / işlem kodları). FC 64 KB (runtime group) ve block tipi analizleri için.
_PROBE_FIELDS = {"CT": ("BLTYPEDAD", "BLTYPESON", "OPTYPE", "LANGDAD"), "BS": ("BLOCKTYPE", "LANGUAGE"),
                 "BAUSTEIN": ("TYP",), "SUBBLK": ("SUBBLKTYP", "PASSWORD", "BLKLANG", "USERNAME"), "XR": ("OPTYPE", "OPACCESS",
                 "BLOCKTYPE")}
_VER_TOKEN = re.compile(rb"V?\d{1,2}\.\d{2}\.\d{2}\.\d{2}")


def _format_probe(src: Source, max_records: int = 200_000) -> list[str]:
    """Format çözümü için sayısal tanı: kod alanlarının değer dağılımı, .mcp versiyon dizileri (isim / içerik yok)."""
    out = ["", "## Kod alanı dağılımları (ilk dosya / tür, değerler kod; isim yok)"]
    done = set()
    for e in src.entries:
        name = e.name.upper()
        kind = ("CT" if name.startswith("CT0") else "BS" if name.startswith("BS0") else "XR" if name.startswith("XR0")
                else "BAUSTEIN" if name == "BAUSTEIN.DBF" else "SUBBLK" if name == "SUBBLK.DBF" else None)
        if not kind or not name.endswith(".DBF") or kind in done or e.size < 200:
            continue
        try:
            t = dbfread.DBF(str(src.materialize(e.rel)), encoding="latin1", char_decode_errors="replace",
                            ignore_missing_memofile=True)
            fields = [f for f in _PROBE_FIELDS[kind] if f in t.field_names]
            hist = {f: Counter() for f in fields}
            n = 0
            for rec in t:
                for f in fields:
                    if f == "USERNAME" and str(rec.get("SUBBLKTYP")).strip() not in ("00008", "00012", "00014"):
                        continue                    # author: sadece OB/FC/FB ana kayıtları (library tanıma için)
                    hist[f][str(rec.get(f)).strip()[:8] or "(boş)"] += 1
                n += 1
                if n >= max_records:
                    break
            done.add(kind)
            out.append(f"- {kind} ({n} kayıt, {mask_path(e.rel)}):")
            for f, c in hist.items():
                out.append(f"    {f}: " + ", ".join(f"{k}×{v}" for k, v in c.most_common(40)))
        except Exception as ex:  # noqa: BLE001 - tanı bölümü; hata metni yazılır
            out.append(f"- {kind}: okunamadı ({type(ex).__name__})")
    out += _memo_format_probe(src)
    toks = Counter()
    for e in src.entries:
        if e.name.lower().endswith(".mcp") and e.size < 50_000_000:
            try:
                raw = src.read_bytes(e.rel)
                for t in set(_VER_TOKEN.findall(raw) + _VER_TOKEN.findall(raw.replace(b"\x00", b""))):
                    toks[t.decode("latin1")] += 1
            except Exception as ex:  # noqa: BLE001
                out.append(f"- .mcp okunamadı ({type(ex).__name__})")
    out += ["", "## .mcp içindeki versiyon dizileri", ", ".join(f"{k}×{v}" for k, v in toks.most_common(20)) or "-"]
    return out


def _memo_format_probe(src: Source) -> list[str]:
    """İlk dolu SUBBLK.DBT'nin header'ı (512 byte, akış yok): memo formatı + block boyutu (parsers.subblk.RawMemoFile
    kuralları: ofset 16 = 0x03 -> dBASE III / block 512; aksi dBASE IV, block boyutu ofset 20-21)."""
    for e in src.entries:
        if e.name.upper() != "SUBBLK.DBT" or e.size <= 512:
            continue
        try:
            head = src.read_head(e.rel, 512)
        except Exception as ex:  # noqa: BLE001 - tanı bölümü
            return [f"- SUBBLK.DBT memo formatı: okunamadı ({type(ex).__name__})"]
        if len(head) < 22:
            continue
        if head[16] == 0x03:
            fmt, bs = "dBASE III", 512
        else:
            bs = int.from_bytes(head[20:22], "little")
            fmt, bs = "dBASE IV", bs if 64 <= bs <= 32768 and bs % 64 == 0 else 512
        n = sum(1 for x in src.entries if x.name.upper() == "SUBBLK.DBT" and x.size > 512)
        return [f"- SUBBLK.DBT memo formatı: {fmt}, blok {bs} (header sürüm byte 0x{head[16]:02X}; ilk dosya, "
                f"{mask_path(e.rel)}; dolu DBT: {n})"]
    return ["- SUBBLK.DBT memo formatı: dolu SUBBLK.DBT yok"]


# ---------------------------------------------------------------------------
# Ana giriş ve çıktılar
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mevcut durum: diğer sayfalardan tek bakışta özet (yazılım, library, hardware, OS). Yorum yok, kaynak var.
# ---------------------------------------------------------------------------

def _norm_name(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", x.lower())


_LIB_SKIP = {"custom", "custom/unknown", "CFC generated"}


def step7_label(used: str) -> str:
    """USED_S7_VERSIONS '5.5.4.9_10.1.0.1' -> 'STEP 7 V5.5 SP4'."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", used or "")
    if not m:
        return ""
    return f"STEP 7 V{m.group(1)}.{m.group(2)}" + (f" SP{m.group(3)}" if m.group(3) != "0" else "")


def _hw_line(items: Counter, extra: list[str]) -> str:
    """'CPU 410-5H V8.1 ×2, CP 443-1 V3.0 ×2; 14 IM, 53 modül, 2 GSD' — items: {(tür, mlfb, model, fw): n}."""
    main: Counter = Counter()
    rest: Counter = Counter()
    for (kind, mlfb, model, fw), n in items.items():
        if kind in ("CPU", "CP"):
            short = re.sub(r"\s*\(çıkarım\)$", "", model or "") or mlfb
            main[(0 if kind == "CPU" else 1, f"{short} {fw}".strip())] += n
        elif kind in ("IM", "modül", "GSD"):
            rest[kind] += n
    head = ", ".join(f"{t} ×{n}" if n > 1 else t for (_, t), n in sorted(main.items())) or "CPU bulunamadı"
    tail = ", ".join(f"{rest[k]} {k}" for k in ("IM", "modül", "GSD") if rest[k])
    return head + (f"; {tail}" if tail else "") + "".join(f"; {x}" for x in extra)


def _current_state(inv: Inventory, d: DiscoveryResult) -> Sheet:
    """Tek bakışta mevcut durum (≤ ~30 satır): genel, yazılım, library, hardware (station başına 1 satır), OS, not."""
    from .analyze import STEP7_TO_PCS7, WINCC_TO_PCS7, author_version
    sh = Sheet("Mevcut durum", ["Bölüm", "Konu", "Değer", "Kaynak"],
               note="Backup'ta bulunanların özeti. Versiyonlar proje dosyalarından (analizi yapan PC'nin yazılımı değil). "
                    "'aday' / 'çıkarım' = tek kaynaktan, teyit edilmeli. Detay: diğer sayfalar.")
    rows = sh.rows
    stale, dup_notes = _stale_dirs(inv)

    def plabel(proj_dir: str) -> str:
        return Path(proj_dir).name or proj_dir or "-"

    # 0) Genel
    n_empty = sum(1 for b in d.block_folders if b.is_empty)
    rows.append(["Genel", "Kaynak", f"{inv.source} — {d.n_files} dosya, {d.total_bytes / 1e9:.2f} GB", f"envanter {inv.created}"])
    rows.append(["Genel", "Proje yapısı",
                 f"Multiproject: {', '.join(Path(m).stem for m in d.multiprojects) or '-'}; {len(d.projects)} proje, "
                 f"{len(d.block_folders)} block klasörü ({n_empty} boş), {len(d.os_projects)} OS projesi, "
                 f"{len(d.cfg_exports)} HW Config export", "*.s7f / *.s7p"])

    # 1) Yazılım: PCS 7 / STEP 7 / WinCC — her biri tek satır
    s7: dict = defaultdict(list)
    for st in inv.hw_stations:
        lab = step7_label(st["used_s7"])
        if lab:
            fam = STEP7_TO_PCS7.get(".".join(re.match(r"(\d+)\.(\d+)\.(\d+)", st["used_s7"]).groups()))
            s7[lab + (f" (PCS 7 {fam} ailesi, aday)" if fam else "")].append(st["name"])
    builds: dict = defaultdict(list)
    for o in d.os_projects:
        if o.wincc_build:
            builds[o.wincc_build].append(o)
    fams, wincc_vals, wincc_src = [], [], ""
    for b, os_list in sorted(builds.items()):
        mm = re.match(r"V0?(\d+)\.(\d\d)", b)
        key = f"{int(mm.group(1)):02d}.{mm.group(2)}" if mm else ""
        wn, fam, ok = WINCC_TO_PCS7.get(key, (f"WinCC {b}", None, False))
        wincc_src = wincc_src or f"{os_list[0].path}/{os_list[0].mcp}"
        if b.endswith(".00.00"):     # format dizisi olabilir (bkz. analyze._versions): aile için kullanılmaz
            wincc_vals.append(f"build tespit edilemedi ('{b}' format dizisi olabilir, {wn} kesin değil; "
                              f"{len(os_list)} OS projesi)")
            continue
        if fam:
            fams.append((fam, ok))
        wincc_vals.append(f"{wn} (build {b})" + (f" -> PCS 7 {fam}" + ("" if ok else ", aday") if fam else "")
                          + f" — {len(os_list)} OS projesi")
    if fams:
        best = sorted(fams, key=lambda x: not x[1])[0]
        val = best[0] + ("" if best[1] else " (aday, teyit edilmeli)")
        if len({f for f, _ in fams}) > 1:
            val += " — farklı WinCC build'leri var: " + ", ".join(sorted({f for f, _ in fams}))
        rows.append(["Yazılım", "PCS 7", val, "WinCC build (.mcp)"])
    else:
        rows.append(["Yazılım", "PCS 7", "tespit edilemedi (WinCC build yok)", "-"])
    rows.append(["Yazılım", "STEP 7", "; ".join(f"{k} — {', '.join(sorted(v))}" for k, v in sorted(s7.items()))
                 or "tespit edilemedi (HW Config export yok)", "HW Config export (USED_S7_VERSIONS)" if s7 else "-"])
    if wincc_vals:
        rows.append(["Yazılım", "WinCC", "; ".join(wincc_vals), wincc_src])

    # 2) Library'ler (block header author'larından), eski kopyalar hariç
    libs: dict = defaultdict(lambda: defaultdict(lambda: [0, set()]))
    custom: dict = defaultdict(Counter)
    for info, bf in inv.block_data:
        if info.project in stale:
            continue
        lab = plabel(info.project)
        for lib, cnt in library_summary(bf).items():
            if lib in _LIB_SKIP:
                continue
            for author, n in cnt.items():
                v = author_version(author) or author or "-"
                libs[lib][v][0] += n
                libs[lib][v][1].add(lab)
        custom["custom"][lab] += sum(1 for b in bf.blocks if b.kind == "FB" and b.library == "custom")
        custom["headerless"][lab] += sum(1 for b in bf.blocks if b.kind == "FB" and b.library == "custom/unknown")
    for lib in sorted(libs):
        val = "; ".join(f"{v}: {n} block ({', '.join(sorted(ps))})" for v, (n, ps) in sorted(libs[lib].items()))
        if len({v for v in libs[lib] if re.match(r"V\d", v)}) > 1:     # sadece gerçek sürümler (ELEMENTA/ELEM_400 değil)
            val += " — karışık versiyon"
        rows.append(["Library", lib, val, "block header author (SUBBLK.DBF)"])

    def per(c: Counter) -> str:
        return ", ".join(f"{k} {n}" for k, n in sorted(c.items()) if n)
    nc, nh = sum(custom["custom"].values()), sum(custom["headerless"].values())
    if nc or nh:
        rows.append(["Library", "Custom FB", f"{nc} FB integratör author'lu ({per(custom['custom']) or '-'}); {nh} FB "
                     f"header'sız — korumalı F-block veya custom ({per(custom['headerless']) or '-'}) -> 'Özel bloklar'",
                     "block header author (SUBBLK.DBF)"])
    special = getattr(inv, "special_blocks", None) or []
    if special:
        cats = Counter(str(r[2]) if len(r) > 2 else "-" for r in special)
        rows.append(["Library", "Özel block", f"{len(special)} block ({', '.join(f'{k} {n}' for k, n in cats.most_common())})"
                     " -> 'Özel bloklar' sayfası", "SUBBLK.DBF"])

    # 3) Hardware: station başına tek satır (export); export'u olmayan proje -> backup taraması (çıkarım)
    for st in sorted(inv.hw_stations, key=lambda s: s["name"].lower()):
        extra = (["F-capable"] if st["f_capable"] else []) + (["PDM kullanımı var"] if st["pdm"] else [])
        rows.append(["Hardware", st["name"], _hw_line(st["items"], extra), f"HW export ({Path(st['rel']).name})"])
    scan = _scan_by_project(inv, stale)
    for proj, items in scan.items():
        c: Counter = Counter()
        method = ""
        for (kind, mlfb, fw), (n, _rel, m) in items.items():
            c[(kind, mlfb, _model(mlfb), fw)] += n
            method = m
        rows.append(["Hardware", plabel(proj), _hw_line(c, []) + " (backup taraması, çıkarım)", method])
    if not inv.hw_stations and not scan:
        rows.append(["Hardware", "-", "HW bilgisi bulunamadı: HW Config → Station → Export (.cfg) alınmalı", ""])

    # 4) OS: proje başına tek satır
    for o, role, yer in inv.os_rows:
        if o.project in stale:
            continue
        mm = re.match(r"V0?(\d+)\.(\d\d)", o.wincc_build or "")
        wcc = f"WinCC {int(mm.group(1))}.{int(mm.group(2))}" if mm else "WinCC -"
        rows.append(["OS", o.name, f"{role}, {yer}; {wcc}; custom picture {o.custom_pictures}, VBS {o.vbs_modules} modül + "
                     f"{o.vbs_actions} action, C action {o.c_actions}", o.path])

    # 5) Symbol table (ayrı dosya)
    if inv.symbol_sheets:
        syms = next((s for s in inv.symbol_sheets if s.name == "Semboller"), None)
        chk = next((s for s in inv.symbol_sheets if s.name == "Sembol kontrolleri"), None)
        n_tab = len({r[0] for r in syms.rows}) if syms else 0
        n_find = sum(1 for r in (chk.rows if chk else []) if r[5] == "KANIT" or r[2] == "tanınmayan operand")
        rows.append(["Symbol table", f"{n_tab} tablo", f"{len(syms.rows) if syms else 0} sembol, {n_find} kontrol bulgusu "
                     "-> semboller.xlsx", "YDBs/SYMLIST.DBF, .asc"])
    for n in dup_notes:
        rows.append(["Not", "Aynı proje birden fazla yerde", n + " — 'en yeni' dosya tarihine göre, teyit edilmeli", "*.s7p"])
    if inv.warnings:
        rows.append(["Not", "Uyarı", f"{len(inv.warnings)} uyarı -> 'Uyarılar' sayfası", ""])
    return sh


def build_inventory_source(src: Source, log=None) -> Inventory:
    log = log or (lambda m: None)
    log("Keşif...")
    d = discover_source(src)
    inv = Inventory(source=src.label, created=datetime.now().isoformat(sep=" ", timespec="minutes"), discovery=d)
    inv.warnings += d.warnings
    def stage(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 - bir bölümün hatası envanteri durdurmaz
            inv.warnings.append(f"{name} bölümü tamamlanamadı: {type(e).__name__}: {e}")
            log(f"UYARI: {name} bölümü tamamlanamadı ({e})")
            return None

    log("Projeler...")
    stage("Projeler", _projects, src, d, inv)
    log("HW Config export'ları...")
    stage("HW Config export", _hw_exports, src, d, inv)
    log("HW (backup içi tarama)...")
    stage("HW (backup içi)", _hw_internal, src, d, inv)
    log("Block klasörleri...")
    fb_sets = stage("Block klasörleri", _blocks, src, d, inv, log) or {}
    log("S7 program ↔ AS zinciri...")
    stage("S7 program ↔ AS", _programs, src, d, inv)
    log("Symbol table'lar...")
    stage("Symbol table", _symbols, src, d, inv, fb_sets)
    log("OS projeleri...")
    stage("OS projeleri", _os, src, d, inv)
    stage("Hardware", _hardware, inv)
    log("Yapı tanısı...")
    inv.diagnostics = stage("Yapı tanısı", diagnostics, src) or ""

    authors = Counter()
    for _info, bf in inv.block_data:
        for lib, cnt in library_summary(bf).items():
            if lib in ("APL", "Basis Library", "S7 F Systems Failsafe Blocks", "Logic Matrix", "PCS 7 Library V7.1 COMM"):
                for author, n in cnt.items():
                    authors[f"{lib}: {author}"] += n
    step7 = sorted({st["used_s7"] for st in inv.hw_stations if st["used_s7"]})
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
    cur = stage("Mevcut durum", _current_state, inv, d)
    if cur is not None:
        inv.sheets.insert(0, cur)
    inv.sheets.append(Sheet("Uyarılar", ["Uyarı"], [[w] for w in inv.warnings]))     # boşsa _order_sheets atar
    _order_sheets(inv)
    return inv


# Envanter sayfa sırası; listede olmayan (yeni) sayfalar 'Özel bloklar'dan sonra gelir. Boş sayfa yazılmaz.
SHEET_ORDER = ("Mevcut durum", "Hardware", "Block klasörleri", "Özel bloklar", None, "OS projeleri", "Projeler", "Uyarılar")


def _order_sheets(inv: Inventory) -> None:
    rest = SHEET_ORDER.index(None)
    rank = {n: i for i, n in enumerate(SHEET_ORDER) if n}
    inv.sheets = sorted((s for s in inv.sheets if s.rows), key=lambda s: rank.get(s.name, rest))


def build_inventory(path: Path, log=None) -> Inventory:
    with open_source(path, log) as src:
        return build_inventory_source(src, log)


def write_xlsx(inv: Inventory, path: Path, sheets: list[Sheet] | None = None) -> Path:
    """Boş sayfa yazılmaz. sheets: varsayılan envanter sayfaları (semboller.xlsx için inv.symbol_sheets)."""
    wb = Workbook()
    for s in (inv.sheets if sheets is None else sheets):
        if s.rows:
            wb.add(s.name, s.headers, s.rows)
    return wb.save(path)


def render_html(inv: Inventory) -> str:
    e = html.escape
    toc, body = [], []
    for i, s in enumerate(x for x in inv.sheets if x.rows):
        toc.append(f'<a href="#t{i}">{e(s.name)} ({len(s.rows)})</a>')
        rows = [["Evet" if v is True else "Hayır" if v is False else v for v in r] for r in s.rows[:HTML_ROW_LIMIT]]
        more = (f'<div class="caption">İlk {HTML_ROW_LIMIT} / {len(s.rows)} satır gösteriliyor — tam liste envanter.xlsx içinde.</div>'
                if len(s.rows) > HTML_ROW_LIMIT else "")
        table = ("<div class='tw'><table><thead><tr>" + "".join(f"<th>{e(h)}</th>" for h in s.headers) + "</tr></thead><tbody>"
                 + "".join("<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in r) + "</tr>" for r in rows)
                 + "</tbody></table></div>")
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
    if any(s.rows for s in inv.symbol_sheets):          # symbol table envantere girmez, ayrı dosya
        write_xlsx(inv, out_dir / "semboller.xlsx", inv.symbol_sheets)
    p = out_dir / "envanter.html"
    p.write_text(render_html(inv), encoding="utf-8")
    (out_dir / "yapi_tanisi.txt").write_text(inv.diagnostics, encoding="utf-8")
    if inv.blockmap_diag:
        (out_dir / "blockmap_tanisi.txt").write_text(inv.blockmap_diag, encoding="utf-8")
    return p


__all__ = ["Inventory", "build_inventory", "build_inventory_source", "write_outputs", "write_xlsx", "diagnostics"]
