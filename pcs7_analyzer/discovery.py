"""
Keşif: proje klasörünü SALT OKUNUR tarar, analiz yapmadan ne bulunduğunu listeler.

Bulunanlar: multiproject (*.s7f), proje (*.s7p), block klasörleri (ombstx/offline/<8hex>/SUBBLK.DBF),
HW Config (*.s7h, .cfg export), symbol table (YDBs/SYMLIST.DBF, *.asc/*.sdf export),
WinCC OS projeleri (*.mcp içeren klasör), arşivler (*.zip/*.7z; düzleşme riski).
Tüm path'ler tam (root'a göre relatif) tutulur: aynı isimli dosyalar yüzlerce kez tekrar eder.
"""
from __future__ import annotations

import os
import re
import struct
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

_HEX8 = re.compile(r"^[0-9A-Fa-f]{8}$")
_WINCC_BUILD = re.compile(rb"V0?\d\.\d\d\.\d\d\.\d\d")
_ARCHIVE_EXT = (".zip", ".7z", ".rar")
_SYMBOL_EXPORT_EXT = (".asc", ".sdf")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def dbf_record_count(path: Path) -> int | None:
    """DBF header'ından kayıt sayısı (offset 4, uint32 LE). Tüm dosyayı okumaz."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        return struct.unpack("<I", head[4:8])[0] if len(head) == 8 else None
    except OSError:
        return None


def is_hw_cfg(path: Path) -> bool:
    """HW Config export'u mu? (WinCC'nin TemplateControl.cfg vb. dosyalarını eler)."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return b"#STEP7_VERSION" in head or b"\nSTATION " in head or head.startswith(b"STATION ")


def wincc_build(mcp: Path) -> str:
    try:
        m = _WINCC_BUILD.search(mcp.read_bytes())
    except OSError:
        return ""
    return m.group().decode() if m else ""


@dataclass
class BlockFolderInfo:
    path: str
    project: str
    dbf_size: int
    dbf_mtime: str
    n_records: int | None
    dbt_size: int | None
    dbt_mtime: str | None
    has_baustein: bool

    @property
    def is_empty(self) -> bool:
        return self.n_records == 0


@dataclass
class OsProjectInfo:
    path: str
    project: str
    mcp: str
    wincc_build: str
    n_files: int
    custom_pictures: int
    faceplates_and_templates: int
    vbs_modules: int
    vbs_actions: int
    c_actions: int


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


def _owner_project(rel: Path, project_dirs: list[Path]) -> str:
    """En yakın üst klasördeki .s7p projesi (yoksa '-')."""
    best = None
    for p in project_dirs:
        if (p == Path(".") or p in rel.parents or p == rel) and (best is None or len(p.parts) > len(best.parts)):
            best = p
    return best.as_posix() if best is not None else "-"


def _summarize_os(os_dir: Path) -> dict:
    c = Counter()
    for dirpath, _, files in os.walk(os_dir):
        parts = [p.lower() for p in Path(dirpath).relative_to(os_dir).parts]
        for fn in files:
            c["n_files"] += 1
            low = fn.lower()
            if parts[:1] == ["gracs"] and low.endswith(".pdl"):
                c["faceplates_and_templates" if low.startswith("@") else "custom_pictures"] += 1
            elif parts[:1] == ["scriptlib"] and low.endswith(".bmo"):
                c["vbs_modules"] += 1
            elif parts[:1] == ["scriptact"] and low.endswith(".bac"):
                c["vbs_actions"] += 1
            elif "pas" in parts and low.endswith(".pas"):
                c["c_actions"] += 1
    return c


def discover(root: Path, progress: bool = False) -> DiscoveryResult:
    root = Path(root).resolve()
    res = DiscoveryResult(root=str(root))
    project_dirs: list[Path] = []
    block_dirs: list[tuple[Path, Path]] = []   # (rel_dir, abs_dir)
    os_dirs: list[tuple[Path, Path]] = []
    n_dirs = 0

    def _onerror(err: OSError) -> None:
        res.warnings.append(f"Okunamadı: {err.filename} ({err.strerror})")

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror):
        dirnames.sort()
        n_dirs += 1
        if progress and n_dirs % 500 == 0:
            print(f"  ... {n_dirs} klasör, {res.n_files} dosya", file=sys.stderr)
        d = Path(dirpath)
        rel_d = d.relative_to(root)
        lower = {f.lower(): f for f in filenames}
        for fn in filenames:
            p = d / fn
            try:
                res.total_bytes += p.stat().st_size
            except OSError:
                pass
            res.n_files += 1
            low = fn.lower()
            rel = (rel_d / fn).as_posix()
            if low.endswith(".s7f"):
                res.multiprojects.append(rel)
            elif low.endswith(".s7p"):
                res.projects.append(rel)
                project_dirs.append(rel_d)
            elif low.endswith(".s7h"):
                res.s7h_files.append(rel)
            elif low.endswith(".cfg") and is_hw_cfg(p):
                res.cfg_exports.append(rel)
            elif low.endswith(_SYMBOL_EXPORT_EXT):
                res.symbol_exports.append(rel)
            elif low == "symlist.dbf":
                res.symbol_tables.append(rel)
            elif low.endswith(_ARCHIVE_EXT):
                res.archives.append(rel)
        parts_low = [x.lower() for x in rel_d.parts]
        if (len(parts_low) >= 3 and parts_low[-3:-1] == ["ombstx", "offline"]
                and _HEX8.match(rel_d.name) and "subblk.dbf" in lower):
            block_dirs.append((rel_d, d))
        if any(f.endswith(".mcp") for f in lower):
            os_dirs.append((rel_d, d))
            dirnames[:] = []   # OS projesinin içini ayrıca özetleyeceğiz

    for rel_d, d in block_dirs:
        dbf = d / next(f for f in os.listdir(d) if f.lower() == "subblk.dbf")
        dbt = next((d / f for f in os.listdir(d) if f.lower() == "subblk.dbt"), None)
        st = dbf.stat()
        dst = dbt.stat() if dbt else None
        res.block_folders.append(BlockFolderInfo(
            path=rel_d.as_posix(), project=_owner_project(rel_d, project_dirs),
            dbf_size=st.st_size, dbf_mtime=_iso(st.st_mtime), n_records=dbf_record_count(dbf),
            dbt_size=dst.st_size if dst else None, dbt_mtime=_iso(dst.st_mtime) if dst else None,
            has_baustein=any(f.lower() == "baustein.dbf" for f in os.listdir(d)),
        ))
        if dbt is None:
            res.warnings.append(f"{rel_d.as_posix()}: SUBBLK.DBT yok -> instance eşlemesi yapılamaz")
        elif dst and abs(dst.st_mtime - st.st_mtime) > 24 * 3600:
            res.warnings.append(f"{rel_d.as_posix()}: SUBBLK.DBF ve .DBT tarihleri >1 gün farklı -> eşleşme teyit edilmeli")

    for rel_d, d in os_dirs:
        mcp = next(f for f in sorted(os.listdir(d)) if f.lower().endswith(".mcp"))
        s = _summarize_os(d)
        res.n_files += s["n_files"]
        res.os_projects.append(OsProjectInfo(
            path=rel_d.as_posix(), project=_owner_project(rel_d, project_dirs), mcp=mcp,
            wincc_build=wincc_build(d / mcp), n_files=s["n_files"],
            custom_pictures=s["custom_pictures"], faceplates_and_templates=s["faceplates_and_templates"],
            vbs_modules=s["vbs_modules"], vbs_actions=s["vbs_actions"], c_actions=s["c_actions"],
        ))

    names = defaultdict(list)
    for p in res.projects:
        names[Path(p).name.lower()].append(p)
    for n, paths in names.items():
        if len(paths) > 1:
            res.warnings.append(f"Aynı proje dosyası birden fazla yerde ({n}): {', '.join(paths)} -> farklı tarihli backup?")
    if res.archives:
        res.warnings.append(f"{len(res.archives)} arşiv dosyası var: açılmadı. Açarken path yapısı korunmalı (düzleşme riski).")
    if not res.cfg_exports and res.s7h_files:
        res.warnings.append("HW Config .cfg export'u yok -> .s7h binary fallback kullanılacak (F-I/O ve detay eksik olabilir)")
    return res


def render_markdown(r: DiscoveryResult) -> str:
    out = [f"# Keşif raporu", "", f"- Klasör: `{r.root}`",
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
        out += ["| Klasör | .mcp | WinCC build | Dosya | Custom picture | @pdl | .bmo | .bac | .pas |",
                "|---|---|---|---|---|---|---|---|---|"]
        for o in r.os_projects:
            out.append(f"| `{o.path}` | {o.mcp} | {o.wincc_build or '?'} | {o.n_files} | {o.custom_pictures} | "
                       f"{o.faceplates_and_templates} | {o.vbs_modules} | {o.vbs_actions} | {o.c_actions} |")
    else:
        out.append("- yok")
    out.append("")

    lst("Arşivler", r.archives)
    lst("Uyarılar", r.warnings)
    return "\n".join(out)
