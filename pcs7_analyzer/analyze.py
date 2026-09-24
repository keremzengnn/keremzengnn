"""
Analiz: keşif sonucunu parser'larla işleyip rapordan bağımsız `Analysis` modelini üretir.

Her sonuç kaynağını (dosya yolu) ve gerekiyorsa güven seviyesini taşır. Bir dosya okunamazsa
analiz durmaz: uyarı eklenir, ilgili bölüm "okunamadı" olarak raporlanır.
"""
from __future__ import annotations

import copy
import re
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import __version__
from .discovery import BlockFolderInfo, DiscoveryResult, OsProjectInfo, discover_source, owner_project
from .model import Confidence, Finding
from .parsers import (
    compare_os, hw_inventory, library_summary, parse_cfg, parse_subblk,
    parse_symbol_asc, parse_symlist_dbf, scan_s7h,
)
from .parsers.wincc import list_os_entries, picture_kind
from .released_modules import ReleasedModules
from .source import Source, open_source

DATA_DIR = Path(__file__).resolve().parent / "data"


def data_dirs() -> list[Path]:
    """Released Modules CSV arama sırası: exe/çalışma klasörü yanındaki data/, sonra paket içi."""
    import sys
    dirs = [Path.cwd() / "data"]
    if getattr(sys, "frozen", False):
        dirs.insert(0, Path(sys.executable).resolve().parent / "data")
    return dirs + [DATA_DIR]

# ---------------------------------------------------------------------------
# Versiyon eşlemeleri
# ---------------------------------------------------------------------------

# STEP 7 (USED_S7_VERSIONS ilk token'ı major.minor.sp) -> aday PCS 7 ailesi.
# PCS 7 V8.1 = STEP 7 V5.5 SP4 (PCS 7 Readme V8.1 SP1, Bölüm 5). V5.5 SP4 sonraki sürümlerde de kullanılmış
# olabileceğinden tek başına kesin kabul edilmez.
STEP7_TO_PCS7 = {"5.5.4": "V8.1"}

# WinCC build (mcp) major.minor -> (WinCC adı, PCS 7 ailesi, doğrulandı mı)
WINCC_TO_PCS7 = {
    "07.03": ("WinCC V7.3", "V8.1", True),     # PCS 7 Readme V8.1 SP1, Bölüm 5
    "07.02": ("WinCC V7.2", "V8.0", False), "07.04": ("WinCC V7.4", "V8.2", False),
    "07.05": ("WinCC V7.5", "V9.x", False), "08.00": ("WinCC V8.0", "V10.x", False),
}

# İç prosedür: kademeli yol
STAGED_PATH = ["V8.2.4", "V9.1", "V10.0 SP2"]


def staged_path_from(pcs7: str | None) -> list[str]:
    if not pcs7:
        return STAGED_PATH
    m = re.match(r"V(\d+)\.(\d+|x)", pcs7)
    if not m:
        return STAGED_PATH
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2).isdigit() else 0
    if major >= 10:
        return ["V10.0 SP2"]
    if major == 9:
        return ["V10.0 SP2"] if minor >= 1 else ["V9.1", "V10.0 SP2"]
    if major == 8 and minor >= 2:
        return ["V9.1", "V10.0 SP2"]
    return STAGED_PATH


def author_version(author: str) -> str:
    """'AdvLib81' -> 'V8.1', 'DRIVER81' -> 'V8.1', 'F_SAFE13' -> 'V1_3'."""
    m = re.search(r"(\d)(\d)$", author)
    if not m:
        return ""
    return f"V{m.group(1)}_{m.group(2)}" if author.startswith("F_SAFE") else f"V{m.group(1)}.{m.group(2)}"


# ---------------------------------------------------------------------------
# Sonuç modelleri
# ---------------------------------------------------------------------------

@dataclass
class VersionInfo:
    item: str
    value: str
    source: str
    confidence: str = Confidence.HIGH.value


@dataclass
class Station:
    name: str
    source: str
    project: str = "-"
    kind: str = "cfg"                     # cfg / s7h
    cpus: list[tuple[str, str, str]] = field(default_factory=list)      # (order, fw, name)
    cps: list[tuple[str, str, str]] = field(default_factory=list)
    slaves: Counter = field(default_factory=Counter)                     # {"ET 200iSP (6ES7 152-...)": n}
    gsd: Counter = field(default_factory=Counter)
    h_sync: int = 0
    f_capable: bool | None = None
    pdm_used: bool | None = None
    f_modules: int = 0
    used_s7_versions: str = ""
    station_text: str = ""                                               # STATION satırı + modül isimleri
    inventory: Counter = field(default_factory=Counter)                  # {(order, fw): n}


@dataclass
class HwMatch:
    order: str
    fw: str
    count: int
    stations: list[str]
    status: str
    note: str = ""


@dataclass
class CustomBlock:
    kind: str
    number: int
    name: str
    family: str
    author: str
    lang: str
    version: str
    instances: int
    headerless: bool


@dataclass
class BlockFolderResult:
    info: BlockFolderInfo
    as_label: str
    mapping: str                    # nasıl eşlendi
    mapping_confidence: str
    counts: dict = field(default_factory=dict)
    libraries: dict = field(default_factory=dict)          # {lib: {author: n}}
    mixed_versions: dict = field(default_factory=dict)     # {lib: [versions]}
    custom_blocks: list[CustomBlock] = field(default_factory=list)
    top_instances: list[tuple[str, int]] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    unused_library_fbs: list[str] = field(default_factory=list)
    f_driver_instances: int = 0
    unresolved_instances: int = 0
    memo_available: bool = False
    fb_numbers: list[int] = field(default_factory=list)
    fb_instances: dict = field(default_factory=dict)       # {fb_nr: instance sayısı}
    block_names: list[str] = field(default_factory=list)   # header'daki FB/FC isimleri
    fb_by_name: dict = field(default_factory=dict)          # {isim: FB no}
    f_blocks_from_symbols: list[str] = field(default_factory=list)
    symbol_source: str = ""
    symbol_only: list[str] = field(default_factory=list)   # symbol'de var, block klasöründe yok
    block_only: list[str] = field(default_factory=list)    # block'ta var, symbol'de yok
    error: str = ""


@dataclass
class OsProject:
    info: OsProjectInfo
    role: str
    in_es: bool
    pictures: Counter = field(default_factory=Counter)
    custom_typicals: list[str] = field(default_factory=list)
    f_faceplates: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    opc: list[str] = field(default_factory=list)
    cas_packages: list[str] = field(default_factory=list)


@dataclass
class OsDiff:
    a: str
    b: str
    a_label: str
    b_label: str
    only_a: list[str]
    only_b: list[str]
    newer_a: list[str]
    newer_b: list[str]
    n_size_diff: int

    def relevant(self, lst: list[str]) -> list[str]:
        return [r for r in lst if picture_kind(r) != "other"
                or r.lower().startswith(("scriptlib/", "scriptact/", "<pc>/pas/")) or "/pas/" in r.lower()]


@dataclass
class ClientGroup:
    members: list[str]
    n_files: int
    only_in_group: list[str] = field(default_factory=list)      # referansa göre
    missing_in_group: list[str] = field(default_factory=list)
    is_reference: bool = False


@dataclass
class BackupCopy:
    name: str
    paths: list[str]
    newest: list[str]
    newest_path: str


@dataclass
class Analysis:
    source: str
    target: str
    tool_version: str
    created: str
    discovery: DiscoveryResult
    versions: list[VersionInfo] = field(default_factory=list)
    pcs7_family: str | None = None
    pcs7_family_confidence: str = Confidence.LOW.value
    stations: list[Station] = field(default_factory=list)
    hw_matches: list[HwMatch] = field(default_factory=list)
    released_list: str = ""
    block_folders: list[BlockFolderResult] = field(default_factory=list)
    os_projects: list[OsProject] = field(default_factory=list)
    os_diffs: list[OsDiff] = field(default_factory=list)
    client_groups: list[ClientGroup] = field(default_factory=list)
    backups: list[BackupCopy] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    not_checked: list[tuple[str, str]] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stale_dirs: list[str] = field(default_factory=list)   # analiz dışı bırakılan eski kopyalar

    def mp_of(self, rel_dir: str) -> str:
        """Bir proje klasörünün multiproject adı (s7f klasörü ata ise; tek MP varsa o)."""
        best = None
        for m in self.discovery.multiprojects:
            d = m.rsplit("/", 1)[0] if "/" in m else ""
            if (d == "" or rel_dir == d or rel_dir.startswith(d + "/")) and (best is None or len(d) > len(best[0])):
                best = (d, m)
        if best:
            return Path(best[1]).stem
        mps = [m for m in self.discovery.multiprojects]
        return Path(mps[0]).stem if len(mps) == 1 else "-"

    @property
    def project_name(self) -> str:
        mps = self.discovery.multiprojects
        if mps:
            return ", ".join(Path(m).stem for m in mps)
        if self.discovery.projects:
            return Path(self.discovery.projects[0]).stem
        return Path(self.source).stem


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

_CPU = re.compile(r"^6ES7 ?41\d-")
_HSYNC = re.compile(r"^6ES7 ?960-1AA")
_F_ORDER = re.compile(r"^6ES7 ?(13[68]-|326-|336-)")   # F-DI/F-DO/F-AI (ET 200S/iSP F, SM326/336)


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", s.lower())


def _name_match(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    return bool(na and nb) and (na == nb or re.fullmatch(rf"(.*\D)?{re.escape(na)}(\D.*)?", nb) is not None
                                or re.fullmatch(rf"(.*\D)?{re.escape(nb)}(\D.*)?", na) is not None)


def os_role(name: str) -> str:
    n = name.upper()
    if re.search(r"STBY|STANDBY", n):
        return "standby"
    if re.search(r"SRV|SERVER", n):
        return "server"
    if re.search(r"REF", n):
        return "reference"
    if re.search(r"OSC|CLIENT|CLT|^OS\s*\(?\d|^OS\d", n):
        return "client"
    if re.search(r"\bES\b|ENG", n):
        return "es"
    return "?"


# ---------------------------------------------------------------------------
# Bölümler
# ---------------------------------------------------------------------------

def _analyze_stations(src: Source, d: DiscoveryResult, an: Analysis, log) -> None:
    project_dirs = [p.rsplit("/", 1)[0] if "/" in p else "" for p in d.projects]
    projects_with_cfg = set()
    for rel in d.cfg_exports:
        try:
            cfg = parse_cfg(src.materialize(rel))
        except Exception as e:  # noqa: BLE001
            an.warnings.append(f"{rel}: okunamadı ({e})")
            continue
        m = re.match(r'STATION\s+\S+\s*,\s*"([^"]*)"', cfg["station"])
        st = Station(name=m.group(1) if m else Path(rel).stem, source=rel, kind="cfg",
                     f_capable=cfg["f_capable"], pdm_used=cfg["pdm_used"],
                     used_s7_versions=cfg["used_s7_versions"])
        for pd in project_dirs:
            pname = pd.rsplit("/", 1)[-1]
            if _name_match(pname, st.name) or _name_match(pname, Path(rel).stem):
                st.project = pd
                projects_with_cfg.add(pd)
                break
        st.station_text = cfg["station"] + " " + " ".join(m.name for m in cfg["modules"])
        for mod in cfg["modules"]:
            if mod.is_internal:
                continue
            if _CPU.match(mod.order_no):
                st.cpus.append((mod.order_no, mod.firmware, mod.name))
            elif mod.order_no.startswith("6GK7"):
                st.cps.append((mod.order_no, mod.firmware, mod.name))
            elif _HSYNC.match(mod.order_no):
                st.h_sync += 1
            if mod.is_station_header:
                (st.gsd if mod.is_gsd else st.slaves)[f"{mod.name} ({mod.order_no})"] += 1
            if _F_ORDER.match(mod.order_no):
                st.f_modules += 1
        for (order, fw, _), n in hw_inventory(cfg).items():
            if not (order.upper().endswith((".GSD", ".GSE", ".GSG")) or ":" in order):
                st.inventory[(order, fw)] += n
        an.stations.append(st)
        log(f"HW: {st.name} ({rel})")

    # .cfg yoksa .s7h fallback (proje bazında)
    by_project: dict[str, list[str]] = defaultdict(list)
    for rel in d.s7h_files:
        by_project[owner_project(rel.rsplit("/", 1)[0], project_dirs)].append(rel)
    for pd, rels in sorted(by_project.items()):
        if pd in projects_with_cfg:
            continue
        st = Station(name=pd.rsplit("/", 1)[-1] or "-", source=", ".join(rels), project=pd, kind="s7h")
        for rel in rels:
            try:
                for (order, fw), n in scan_s7h(src.materialize(rel)).items():
                    st.inventory[(order, fw)] += n
            except Exception as e:  # noqa: BLE001
                an.warnings.append(f"{rel}: okunamadı ({e})")
        if not st.inventory:
            continue
        for (order, fw), n in st.inventory.items():
            if _CPU.match(order):
                st.cpus += [(order, fw, "")] * n
            elif order.startswith("6GK7"):
                st.cps += [(order, fw, "")] * n
            elif _HSYNC.match(order):
                st.h_sync += n
            if _F_ORDER.match(order):
                st.f_modules += n
        an.stations.append(st)
        log(f"HW (.s7h fallback): {st.name}")


def _analyze_released(an: Analysis, released_csv: Path | None) -> None:
    csv_path = released_csv
    if csv_path is None:
        cands = [p for d in data_dirs() if d.is_dir() for p in sorted(d.glob(f"released_modules_{an.target}*.csv"))]
        csv_path = cands[0] if cands else None
    agg: dict[tuple[str, str], list] = {}
    for st in an.stations:
        for (order, fw), n in st.inventory.items():
            a = agg.setdefault((order, fw), [0, set()])
            a[0] += n
            a[1].add(st.name)
    if csv_path is None or not Path(csv_path).exists():
        an.released_list = ""
        for (order, fw), (n, sts) in sorted(agg.items()):
            an.hw_matches.append(HwMatch(order, fw, n, sorted(sts), "kontrol edilmedi (liste yok)"))
        return
    an.released_list = str(csv_path)
    rm = ReleasedModules.load(Path(csv_path))
    for (order, fw), (n, sts) in sorted(agg.items()):
        r = rm.match(order, fw)
        note = "; ".join(e.status for e in r.entries if e.status)
        an.hw_matches.append(HwMatch(order, fw, n, sorted(sts), r.status.value, note))


def _symbol_tables(src: Source, d: DiscoveryResult, an: Analysis) -> list[tuple[str, dict]]:
    out = []
    for rel in d.symbol_tables + d.symbol_exports:
        try:
            p = src.materialize(rel)
            rows = parse_symlist_dbf(p) if rel.lower().endswith(".dbf") else parse_symbol_asc(p)
        except Exception as e:  # noqa: BLE001
            an.warnings.append(f"Symbol table okunamadı: {rel} ({e})")
            continue
        syms = {(t, n): name for t, n, name, _ in rows if t in ("FB", "FC", "SFB", "SFC", "DB")}
        if syms:
            out.append((rel, syms))
    return out


def _analyze_block_folder(src: Source, info: BlockFolderInfo, log) -> BlockFolderResult:
    res = BlockFolderResult(info=info, as_label=info.label, mapping="-", mapping_confidence=Confidence.LOW.value)
    if info.is_empty:
        return res
    if info.dbt:
        src.materialize(info.dbt)

    def prog(n, total):
        log(f"  {info.path}: {n}/{total} kayıt")

    bf = parse_subblk(src.materialize(info.dbf), progress=prog)
    res.counts = bf.counts
    res.fb_numbers = sorted(b.number for b in bf.blocks if b.kind == "FB")
    res.block_names = sorted({b.name for b in bf.blocks if b.name})
    res.fb_by_name = {b.name: b.number for b in bf.blocks if b.kind == "FB" and b.name}
    res.memo_available = bf.memo_available
    res.unresolved_instances = bf.unresolved_instances
    summary = library_summary(bf)
    res.libraries = {lib: dict(c) for lib, c in sorted(summary.items())}
    for lib, c in summary.items():
        if lib in ("custom", "custom/unknown", "CFC generated"):
            continue
        versions = sorted({author_version(a) or a for a in c})
        if len(versions) > 1:
            res.mixed_versions[lib] = [f"{v} ({sum(n for a, n in c.items() if (author_version(a) or a) == v)})"
                                       for v in versions]
    inst = Counter(bf.instances_per_fb)
    res.fb_instances = {nr: n for (kind, nr), n in inst.items() if kind == "FB"}
    fb_names = {b.number: b for b in bf.blocks if b.kind == "FB"}
    for b in bf.blocks:
        if b.kind != "FB":
            continue
        n = inst.get(("FB", b.number), 0)
        if b.library in ("custom", "custom/unknown"):
            res.custom_blocks.append(CustomBlock(b.kind, b.number, b.name, b.family, b.author, b.lang,
                                                 b.version, n, headerless=not b.author and not b.name))
        elif n == 0 and b.library not in ("SFC system", "SIMATIC system / Standard Library"):
            res.unused_library_fbs.append(f"FB{b.number} {b.name} ({b.author})")
        if b.name.upper().startswith("F_CH_") or b.library == "S7 F Systems Failsafe Blocks":
            res.f_driver_instances += n
    res.top_instances = [
        (f"{kind}{nr} {fb_names[nr].name if kind == 'FB' and nr in fb_names else ''}".strip(), n)
        for (kind, nr), n in inst.most_common(12)
    ]
    libs = set(summary)
    feat = []
    for lib, tag in [("APL", "APL"), ("Basis Library", "Basis"), ("Logic Matrix", "Logic Matrix"),
                     ("SFC system", "SFC"), ("PCS 7 Library V7.1 COMM", "PCS 7 Lib V7.1"),
                     ("S7 F Systems Failsafe Blocks", "F-System"), ("CFC ELEMENTA", "ELEMENTA")]:
        if lib in libs:
            feat.append(tag)
    names_up = {b.name.upper() for b in bf.blocks}
    if names_up & {"MB_CPCLI", "MB_REDCL", "MB_CPSRV", "MB_RED_CLNT", "MB_RED_SRV"} or \
            any(a.startswith("SIEMENS") for c in summary.values() for a in c):
        feat.append("Modbus TCP / Siemens add-on")
    if any(n.startswith("F_") for n in names_up) and "F-System" not in feat:
        feat.append("F-System")
    res.features = feat
    return res


def _map_block_folders(an: Analysis, symtabs: list[tuple[str, dict]]) -> None:
    # 1) symbol table <-> block klasörü: FB seti benzerliği (Jaccard). Doğrudan eşleme henüz bulunamadı.
    used = set()
    for bfr in an.block_folders:
        if not bfr.counts:
            continue
        fbs = set(bfr.fb_numbers)
        best, score = None, 0.0
        for rel, syms in symtabs:
            sfb = {n for (t, n) in syms if t == "FB"}
            if not sfb or not fbs:
                continue
            j = len(fbs & sfb) / len(fbs | sfb)
            if j > score:
                best, score = (rel, syms), j
        if best and score >= 0.5:
            rel, syms = best
            used.add(rel)
            bfr.symbol_source = f"{rel} (FB seti benzerliği {score:.0%}, heuristic)"
            sfb = {n: nm for (t, n), nm in syms.items() if t == "FB"}
            bfr.symbol_only = [f"FB{n} {sfb[n]}" for n in sorted(set(sfb) - fbs)]
            bfr.block_only = [f"FB{n}" for n in sorted(fbs - set(sfb))]
            # F-block'ların header'ı boş (korumalı): symbol isminden tanı
            f_nrs = [n for n in fbs if sfb.get(n, "").upper().startswith("F_")]
            if f_nrs:
                bfr.f_blocks_from_symbols = [f"FB{n} {sfb[n]}" for n in sorted(f_nrs)]
                bfr.custom_blocks = [c for c in bfr.custom_blocks if c.number not in f_nrs]
                bfr.f_driver_instances += sum(bfr.fb_instances.get(n, 0) for n in f_nrs
                                              if sfb[n].upper().startswith("F_CH_"))
                if "F-System" not in bfr.features:
                    bfr.features.append("F-System")
            for c in bfr.custom_blocks:
                if c.headerless and (c.kind, c.number) in syms:
                    c.name = f"{syms[(c.kind, c.number)]} (symbol)"
            stem = Path(rel).stem
            if rel.lower().endswith((".asc", ".sdf")) and re.search(r"AS\s*\d+", stem, re.I):
                bfr.as_label = re.search(r"AS\s*\d+", stem, re.I).group().replace(" ", "").upper()
                bfr.mapping = "symbol export dosya adı + FB seti"
        # 2) proje adı
        if bfr.mapping == "-":
            siblings = [b for b in an.block_folders if b.info.project == bfr.info.project and b.counts]
            pname = Path(bfr.info.project).name
            if pname and pname != "-" and len(siblings) == 1:
                bfr.as_label = pname
                bfr.mapping = "proje adı (projede tek dolu block klasörü)"
            elif pname and pname != "-":
                bfr.as_label = f"{pname}/{bfr.info.path.rsplit('/', 1)[-1]}"
                bfr.mapping = "projede birden fazla block klasörü: AS teyit edilmeli"


def _analyze_os(src: Source, d: DiscoveryResult, an: Analysis) -> None:
    listings = {}
    display: dict[str, str] = {}      # normalize (küçük harf) -> orijinal dosya adı

    def disp(rels):
        return [display.get(r, r) for r in rels]

    for info in d.os_projects:
        lst = list_os_entries(src.entries, info.path)
        listings[info.path] = lst
        for e in src.entries:
            if e.rel.startswith(info.path + "/"):
                display.setdefault(e.rel[len(info.path) + 1:].lower(), e.rel[len(info.path) + 1:])
        op = OsProject(info=info, role=os_role(info.name), in_es=info.project != "-")
        for rel in lst:
            k = picture_kind(rel)
            if k != "other":
                op.pictures[k] += 1
            if k == "custom_typicals":
                op.custom_typicals.append(display.get(rel, rel).rsplit("/", 1)[-1])
            elif k == "f_faceplate":
                op.f_faceplates.append(display.get(rel, rel).rsplit("/", 1)[-1])
            if rel.endswith(".pck") and "cas" in rel.rsplit("/", 1)[-1]:
                op.cas_packages.append(display.get(rel, rel))
            if rel.startswith(("scriptlib/", "scriptact/")) and rel.endswith((".bmo", ".bac", ".act")):
                op.scripts.append(display.get(rel, rel))
        opc = sorted({"/".join(r.split("/")[:2]) for r in lst if r.startswith("opc/")} |
                     {r.split("/")[0] for r in lst if r.split("/")[0] in ("opc", "opcua", "opc_ua")})
        op.opc = [o for o in opc if "/" in o] or opc
        an.os_projects.append(op)

    # ES <-> OS PC kopyası (aynı isimli proje, biri .s7p içinde, diğeri dışında)
    by_name = defaultdict(list)
    for op in an.os_projects:
        by_name[op.info.name.lower()].append(op)
    for name, ops in by_name.items():
        es = [o for o in ops if o.in_es]
        copies = [o for o in ops if not o.in_es]
        if not es:
            continue
        for c in copies:
            a, b = listings[es[0].info.path], listings[c.info.path]
            r = compare_os(a, b)
            an.os_diffs.append(OsDiff(es[0].info.path, c.info.path, "ES", _copy_label(c.info.path),
                                      disp(r["only_a"]), disp(r["only_b"]), disp(r["newer_in_a"]),
                                      disp(r["newer_in_b"]), len(r["size_diff"])))

    # Client gruplama: içerik imzası (path + boyut)
    clients = [o for o in an.os_projects if o.role == "client"]
    groups: dict[frozenset, list[OsProject]] = defaultdict(list)
    for o in clients:
        sig = frozenset((r, s) for r, (s, _) in listings[o.info.path].items() if not r.startswith("<pc>/"))
        groups[sig].append(o)
    if groups:
        ref_sig = max(groups, key=lambda s: (len(groups[s]), len(s)))
        ref_paths = {r for r, _ in ref_sig}
        for sig, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            paths = {r for r, _ in sig}
            an.client_groups.append(ClientGroup(
                members=[m.info.path for m in members], n_files=len(sig),
                only_in_group=disp(sorted(paths - ref_paths)), missing_in_group=disp(sorted(ref_paths - paths)),
                is_reference=sig == ref_sig,
            ))


def _copy_label(path: str) -> str:
    parts = path.split("/")
    i = next((k for k, p in enumerate(parts) if p.lower() == "wincproj"), None)
    return "/".join(parts[:i]) if i else path


def _analyze_backups(src: Source, d: DiscoveryResult, an: Analysis) -> None:
    names = defaultdict(list)
    for p in d.projects:
        names[p.rsplit("/", 1)[-1].lower()].append(p.rsplit("/", 1)[0] if "/" in p else "")
    for name, dirs in names.items():
        if len(dirs) < 2:
            continue
        newest = {}
        for dd in dirs:
            ts = [e.mtime for e in src.entries if e.rel.startswith(dd + "/")] if dd else [e.mtime for e in src.entries]
            newest[dd] = max(ts) if ts else 0.0
        top = max(newest, key=newest.get)
        an.backups.append(BackupCopy(name, dirs, [datetime.fromtimestamp(newest[x]).isoformat(timespec="seconds")
                                                 for x in dirs], top))


def _without_stale_copies(d: DiscoveryResult, an: Analysis) -> DiscoveryResult:
    """Aynı projenin eski kopyalarını (en güncel olmayan) analiz dışı bırakır; keşifte kalırlar."""
    stale = [p for b in an.backups for p in b.paths if p != b.newest_path]
    if not stale:
        return d
    an.stale_dirs = stale

    def keep(rel: str) -> bool:
        return not any(rel == s or rel.startswith(s + "/") for s in stale)

    out = copy.copy(d)
    out.block_folders = [b for b in d.block_folders if keep(b.path)]
    out.os_projects = [o for o in d.os_projects if keep(o.path)]
    out.s7h_files = [x for x in d.s7h_files if keep(x)]
    out.cfg_exports = [x for x in d.cfg_exports if keep(x)]
    out.symbol_tables = [x for x in d.symbol_tables if keep(x)]
    out.symbol_exports = [x for x in d.symbol_exports if keep(x)]
    out.projects = [x for x in d.projects if keep(x)]
    return out


def _versions(an: Analysis) -> None:
    """Versiyon kaynakları: WinCC build (en güvenilir), APL author çoğunluğu, STEP 7 USED_S7_VERSIONS."""
    cands: list[tuple[str, str, bool]] = []      # (aile, kaynak türü, doğrulanmış)
    for st in an.stations:
        tok = re.match(r"(\d+)\.(\d+)\.(\d+)", st.used_s7_versions or "")
        if not tok:
            continue
        key = ".".join(tok.groups())
        sp = f" SP{tok.group(3)}" if tok.group(3) != "0" else ""
        fam = STEP7_TO_PCS7.get(key)
        an.versions.append(VersionInfo(f"STEP 7 ({st.name})", f"V{tok.group(1)}.{tok.group(2)}{sp}"
                                       + (f" -> PCS 7 {fam} ailesi ile uyumlu" if fam else ""),
                                       st.source, Confidence.LOW.value))
        if fam:
            cands.append((fam, "STEP 7", False))
    seen = set()
    for op in an.os_projects:
        b = op.info.wincc_build
        if not b or b in seen:
            continue
        seen.add(b)
        mm = re.match(r"V0?(\d+)\.(\d\d)", b)
        key = f"{int(mm.group(1)):02d}.{mm.group(2)}" if mm else ""
        wn, fam, ok = WINCC_TO_PCS7.get(key, (f"WinCC {b}", None, False))
        an.versions.append(VersionInfo("WinCC", f"{wn} (build {b})" + (f" -> PCS 7 {fam}" if fam else ""),
                                       f"{op.info.path}/{op.info.mcp}", Confidence.HIGH.value if ok else Confidence.LOW.value))
        if fam:
            cands.append((fam, "WinCC", ok))
    libs = Counter()
    apl_fams = Counter()
    for bfr in an.block_folders:
        for lib in ("APL", "Basis Library", "S7 F Systems Failsafe Blocks"):
            for a, n in bfr.libraries.get(lib, {}).items():
                libs[(lib, author_version(a) or a, bfr.as_label)] += n
                if lib == "APL" and author_version(a):
                    apl_fams[author_version(a)] += n
    per_lib = defaultdict(lambda: defaultdict(list))
    for (lib, v, asl), n in libs.items():
        per_lib[lib][v].append(asl)
    for lib, vs in per_lib.items():
        val = "; ".join(f"{v} ({', '.join(sorted(set(a)))})" for v, a in sorted(vs.items()))
        an.versions.append(VersionInfo(lib, val, "block header author (SUBBLK.DBF)"))
    if apl_fams:
        cands.append((apl_fams.most_common(1)[0][0], "APL", False))

    # Öncelik: doğrulanmış WinCC > APL çoğunluğu > diğer WinCC > STEP 7
    order = sorted(cands, key=lambda c: (0 if c[1] == "WinCC" and c[2] else 1 if c[1] == "APL" else 2 if c[1] == "WinCC" else 3))
    an.pcs7_family = order[0][0] if order else None
    fams = {c[0] for c in cands}
    if len(fams) > 1:
        an.open_items.append("Versiyon kaynakları çelişiyor: " + ", ".join(f"{k}: {f}" for f, k, _ in cands)
                             + f" -> '{an.pcs7_family}' kabul edildi, teyit edilmeli")
    an.pcs7_family_confidence = (Confidence.HIGH.value if order and (order[0][1] == "WinCC" and order[0][2]
                                                                   or len(fams) == 1 and len(cands) > 1)
                                 else Confidence.LOW.value)


# ---------------------------------------------------------------------------
# Ana giriş
# ---------------------------------------------------------------------------

def analyze_source(src: Source, target: str = "V10.0SP2", released_csv: Path | None = None, log=None) -> Analysis:
    log = log or (lambda msg: None)
    log("Keşif...")
    d = discover_source(src)
    an = Analysis(source=src.label, target=target, tool_version=__version__,
                  created=datetime.now().isoformat(timespec="minutes"), discovery=d)
    an.warnings += d.warnings
    _analyze_backups(src, d, an)
    d = _without_stale_copies(d, an)

    log("HW Config...")
    _analyze_stations(src, d, an, log)
    _analyze_released(an, released_csv)

    log("Block klasörleri...")
    for i, info in enumerate(d.block_folders, 1):
        log(f"[{i}/{len(d.block_folders)}] {info.path} ({info.n_records} kayıt)")
        try:
            bfr = _analyze_block_folder(src, info, log)
        except Exception as e:  # noqa: BLE001
            bfr = BlockFolderResult(info=info, as_label=info.label, mapping="-",
                                    mapping_confidence=Confidence.LOW.value, error=f"{e}")
            an.warnings.append(f"{info.path}: okunamadı ({e})")
            log(traceback.format_exc())
        an.block_folders.append(bfr)

    log("Symbol table'lar...")
    symtabs = _symbol_tables(src, d, an)
    _map_block_folders(an, symtabs)

    log("OS projeleri...")
    _analyze_os(src, d, an)
    _versions(an)

    log("Kontroller...")
    from .checks import run_checks
    run_checks(an)
    _open_items(an)
    return an


def _open_items(an: Analysis) -> None:
    items = an.open_items
    heur = [f"{b.as_label} ← {b.info.path} ({b.mapping})" for b in an.block_folders if b.counts]
    if heur:
        items.append("Block klasörü ↔ AS eşlemesi heuristic (teyit edilmeli): " + "; ".join(heur))
    unk = [o.info.name for o in an.os_projects if o.role == "?"]
    if unk:
        items.append("Rolü tespit edilemeyen OS projeleri: " + ", ".join(sorted(set(unk))))
    nomap = [s.name for s in an.stations if s.project == "-"]
    if nomap:
        items.append("Projeye eşlenemeyen HW Config export'ları: " + ", ".join(nomap))
    if not an.stations:
        items.append("HW Config export'u (.cfg) alınmalı: HW Config → Station → Export (F Configuration Pack kurulu PC'den)")
    if any(b.counts and not b.memo_available for b in an.block_folders):
        items.append("Bazı block klasörlerinde SUBBLK.DBT yok: instance sayıları eksik")


def analyze(path: Path, target: str = "V10.0SP2", released_csv: Path | None = None, log=None) -> Analysis:
    with open_source(path, log) as src:
        return analyze_source(src, target, released_csv, log)
