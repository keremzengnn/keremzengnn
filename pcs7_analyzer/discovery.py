"""
Keşif: kaynağın (klasör veya zip) dosya indeksinden, analiz yapmadan ne bulunduğunu listeler.

Bulunanlar: multiproject (*.s7f), proje (*.s7p), block klasörleri (ombstx/offline/<8hex>/SUBBLK.DBF),
HW Config (*.s7h, .cfg export), symbol table (YDBs/SYMLIST.DBF, *.asc/*.sdf export),
WinCC OS projeleri (*.mcp içeren klasör), iç içe arşivler (*.zip/*.7z).
Tüm path'ler tam tutulur: aynı isimli dosyalar yüzlerce kez tekrar eder.
"""
from __future__ import annotations

import re
import struct
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .source import Entry, Source, open_source

_HEX8 = re.compile(r"^[0-9A-Fa-f]{8}$")
_WINCC_BUILD = re.compile(rb"V0?\d\.\d\d\.\d\d\.\d\d")
_ARCHIVE_EXT = (".zip", ".7z", ".rar")
_SYMBOL_EXPORT_EXT = (".asc", ".sdf")


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return "-"


def dbf_record_count_from_head(head: bytes) -> int | None:
    return struct.unpack("<I", head[4:8])[0] if len(head) >= 8 else None


def is_hw_cfg_head(head: bytes) -> bool:
    """HW Config export'u mu? (WinCC'nin TemplateControl.cfg vb. dosyalarını eler)."""
    return b"#STEP7_VERSION" in head or b"\nSTATION " in head or head.startswith(b"STATION ")


@dataclass
class BlockFolderInfo:
    path: str
    project: str
    dbf: str
    dbt: str | None
    dbf_size: int
    dbf_mtime: str
    n_records: int | None
    dbt_size: int | None
    dbt_mtime: str | None
    has_baustein: bool

    @property
    def is_empty(self) -> bool:
        return self.n_records == 0

    @property
    def label(self) -> str:
        return f"{Path(self.project).name or '-'}/{self.path.rsplit('/', 1)[-1]}"


@dataclass
class OsProjectInfo:
    path: str
    project: str            # içinde bulunduğu .s7p projesi ('-' = proje dışında: OS PC'den kopya)
    mcp: str
    wincc_build: str
    n_files: int
    custom_pictures: int
    faceplates_and_templates: int
    vbs_modules: int
    vbs_actions: int
    c_actions: int
    newest_mtime: str

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class DiscoveryResult:
    root: str
    multiprojects: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    block_folders: list[BlockFolderInfo] = field(default_factory=list)
    s7h_files: list[str] = field(default_factory=list)
    cfg_exports: list[str] = field(default_factory=list)
    symbol_tables: list[str] = field(default_factory=list)
    symbol_exports: list[str] = field(default_factory=list)
    os_projects: list[OsProjectInfo] = field(default_factory=list)
    archives: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_files: int = 0
    total_bytes: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def owner_project(rel_dir: str, project_dirs: list[str]) -> str:
    """En yakın üst klasördeki .s7p projesi (yoksa '-')."""
    best = None
    for p in project_dirs:
        if (p == "" or rel_dir == p or rel_dir.startswith(p + "/")) and (best is None or len(p) > len(best)):
            best = p
    return best if best is not None else "-"


def _summarize_os(files: list[Entry], os_dir: str) -> Counter:
    c = Counter()
    newest = 0.0
    for e in files:
        parts = [p.lower() for p in e.rel[len(os_dir) + 1:].split("/")]
        low = parts[-1]
        c["n_files"] += 1
        newest = max(newest, e.mtime)
        if parts[0] == "gracs" and len(parts) == 2 and low.endswith(".pdl"):
            c["faceplates_and_templates" if low.startswith("@") else "custom_pictures"] += 1
        elif parts[0] == "scriptlib" and low.endswith(".bmo"):
            c["vbs_modules"] += 1
        elif parts[0] == "scriptact" and low.endswith(".bac"):
            c["vbs_actions"] += 1
        elif "pas" in parts[:-1] and low.endswith(".pas"):
            c["c_actions"] += 1
    c["newest"] = newest
    return c


def discover_source(src: Source) -> DiscoveryResult:
    res = DiscoveryResult(root=src.label, warnings=list(src.warnings))
    by_dir: dict[str, list[Entry]] = defaultdict(list)
    for e in src.entries:
        by_dir[e.parent].append(e)
        res.n_files += 1
        res.total_bytes += e.size
        low = e.name.lower()
        if low.endswith(".s7f"):
            res.multiprojects.append(e.rel)
        elif low.endswith(".s7p"):
            res.projects.append(e.rel)
        elif low.endswith(".s7h"):
            res.s7h_files.append(e.rel)
        elif low.endswith(".cfg") and "/wincproj/" not in f"/{e.rel.lower()}":
            if is_hw_cfg_head(src.read_head(e.rel, 4096)):
                res.cfg_exports.append(e.rel)
        elif low.endswith(_SYMBOL_EXPORT_EXT):
            res.symbol_exports.append(e.rel)
        elif low == "symlist.dbf":
            res.symbol_tables.append(e.rel)
        elif low.endswith(_ARCHIVE_EXT):
            res.archives.append(e.rel)
    project_dirs = [p.rsplit("/", 1)[0] if "/" in p else "" for p in res.projects]

    # Block klasörleri
    for d, files in sorted(by_dir.items()):
        parts = d.lower().split("/")
        if len(parts) < 3 or parts[-3:-1] != ["ombstx", "offline"] or not _HEX8.match(parts[-1]):
            continue
        names = {f.name.lower(): f for f in files}
        dbf = names.get("subblk.dbf")
        if not dbf:
            continue
        dbt = names.get("subblk.dbt")
        res.block_folders.append(BlockFolderInfo(
            path=d, project=owner_project(d, project_dirs), dbf=dbf.rel, dbt=dbt.rel if dbt else None,
            dbf_size=dbf.size, dbf_mtime=_iso(dbf.mtime),
            n_records=dbf_record_count_from_head(src.read_head(dbf.rel, 8)),
            dbt_size=dbt.size if dbt else None, dbt_mtime=_iso(dbt.mtime) if dbt else None,
            has_baustein="baustein.dbf" in names,
        ))
        if dbt is None:
            res.warnings.append(f"{d}: SUBBLK.DBT yok -> instance eşlemesi yapılamaz")
        elif abs(dbt.mtime - dbf.mtime) > 24 * 3600:
            res.warnings.append(f"{d}: SUBBLK.DBF ve .DBT tarihleri >1 gün farklı -> eşleşme teyit edilmeli")

    # OS projeleri: kök seviyesinde .mcp olan klasör
    os_dirs = sorted(d for d, files in by_dir.items() if any(f.name.lower().endswith(".mcp") for f in files))
    os_dirs = [d for d in os_dirs if not any(d != o and d.startswith(o + "/") for o in os_dirs)]
    for d in os_dirs:
        files = [e for e in src.entries if e.rel.startswith(d + "/")]
        mcp = next(f for f in sorted(by_dir[d], key=lambda x: x.name) if f.name.lower().endswith(".mcp"))
        m = _WINCC_BUILD.search(src.read_bytes(mcp.rel)) if mcp.size < 50_000_000 else None
        s = _summarize_os(files, d)
        res.os_projects.append(OsProjectInfo(
            path=d, project=owner_project(d, project_dirs), mcp=mcp.name,
            wincc_build=m.group().decode() if m else "", n_files=s["n_files"],
            custom_pictures=s["custom_pictures"], faceplates_and_templates=s["faceplates_and_templates"],
            vbs_modules=s["vbs_modules"], vbs_actions=s["vbs_actions"], c_actions=s["c_actions"],
            newest_mtime=_iso(s["newest"]),
        ))

    names = defaultdict(list)
    for p in res.projects:
        names[p.rsplit("/", 1)[-1].lower()].append(p)
    for n, paths in names.items():
        if len(paths) > 1:
            res.warnings.append(f"Aynı proje dosyası birden fazla yerde ({n}): {', '.join(paths)} -> farklı tarihli backup?")
    expanded = set(getattr(src, "expanded", []))
    if expanded:
        res.warnings.append(f"İç içe arşivler açılıp tarandı: {', '.join(sorted(expanded))}")
    unread = [a for a in res.archives if a not in expanded]
    if unread:
        res.warnings.append(f"{len(unread)} iç arşiv okunmadı ({', '.join(unread)}): klasöre açılmalı (path yapısı korunarak).")
    if not res.cfg_exports and res.s7h_files:
        res.warnings.append("HW Config .cfg export'u yok -> .s7h binary fallback kullanılacak (F-I/O ve detay eksik olabilir)")
    return res


def discover(path: Path, progress=None) -> DiscoveryResult:
    with open_source(path, progress) as src:
        return discover_source(src)


def render_markdown(r: DiscoveryResult) -> str:
    out = ["# Keşif raporu", "", f"- Kaynak: `{r.root}`",
           f"- {r.n_files} dosya, {r.total_bytes / 1e6:.1f} MB", ""]

    def lst(title: str, items: list[str]) -> None:
        out.append(f"## {title} ({len(items)})")
        out.extend(f"- `{i}`" for i in items) if items else out.append("- yok")
        out.append("")

    lst("Multiproject (*.s7f)", r.multiprojects)
    lst("Proje (*.s7p)", r.projects)
    out.append(f"## Block klasörleri ({len(r.block_folders)})")
    if r.block_folders:
        out += ["| Klasör | Proje | Kayıt | DBF MB | DBT MB | DBF tarih | DBT tarih |", "|---|---|---|---|---|---|---|"]
        for b in r.block_folders:
            dbt = f"{b.dbt_size / 1e6:.1f}" if b.dbt_size is not None else "yok"
            rec = "boş" if b.is_empty else str(b.n_records)
            out.append(f"| `{b.path}` | `{b.project}` | {rec} | {b.dbf_size / 1e6:.1f} | {dbt} | {b.dbf_mtime} | {b.dbt_mtime or '-'} |")
    else:
        out.append("- yok")
    out.append("")
    lst("HW Config .cfg export", r.cfg_exports)
    lst("HW Config .s7h", r.s7h_files)
    lst("Symbol table (SYMLIST.DBF)", r.symbol_tables)
    lst("Symbol export (.asc/.sdf)", r.symbol_exports)
    out.append(f"## WinCC OS projeleri ({len(r.os_projects)})")
    if r.os_projects:
        out += ["| Klasör | Proje | WinCC build | Dosya | Custom picture | @pdl | .bmo | .bac | .pas | En yeni |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for o in r.os_projects:
            out.append(f"| `{o.path}` | `{o.project}` | {o.wincc_build or '?'} | {o.n_files} | {o.custom_pictures} | "
                       f"{o.faceplates_and_templates} | {o.vbs_modules} | {o.vbs_actions} | {o.c_actions} | {o.newest_mtime} |")
    else:
        out.append("- yok")
    out.append("")
    lst("İç içe arşivler", r.archives)
    lst("Uyarılar", r.warnings)
    return "\n".join(out)
