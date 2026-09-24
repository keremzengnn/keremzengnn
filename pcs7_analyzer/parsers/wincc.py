"""WinCC proje klasörü (wincproj/<OS>/...) listeleme ve karşılaştırma."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

OS_IGNORE_EXT = (".ldf", ".mdf", ".log", ".sav", ".lck", ".dum", ".err", ".rpl",
                 ".tmp", ".lock", ".mcp", ".dcf", ".sto", ".pin", ".liccount")


def list_os_project(root: Path) -> dict[str, tuple[int, float]]:
    """{relatif_path_lower: (size, mtime)}; computer-name alt klasörleri (…\\PAS) hariç."""
    root = Path(root)
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix().lower()
            if rel.endswith(OS_IGNORE_EXT):
                continue
            st = p.stat()
            out[rel] = (st.st_size, st.st_mtime)
    return out


def list_os_project_from_csv(csv_path: Path, project: str) -> dict[str, tuple[int, float]]:
    """PowerShell 'Get-ChildItem -Recurse | Export-Csv' çıktısı (FullName,Length,LastWriteTime)."""
    raw = Path(csv_path).read_bytes().decode("utf-8-sig", "ignore")
    out = {}
    for r in csv.DictReader(io.StringIO(raw)):
        p = r["FullName"].split("wincproj\\", 1)[-1].split("\\")
        if p[0] != project:
            continue
        rel = "/".join(p[1:]).lower()
        if rel.endswith(OS_IGNORE_EXT):
            continue
        ts = r["LastWriteTime"].strip()
        try:  # en-US PowerShell formatı; farklı locale'de format genişletilmeli
            mtime = datetime.strptime(ts, "%m/%d/%Y %I:%M:%S %p").timestamp()
        except ValueError:
            mtime = 0.0
        out[rel] = (int(r["Length"] or 0), mtime)
    return out


def compare_os(a: dict, b: dict) -> dict:
    """ES vs SRV veya client vs client. mtime karşılaştırması 'hangisi daha yeni' için."""
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    diff = sorted(k for k in set(a) & set(b) if a[k][0] != b[k][0])
    return {
        "only_a": only_a,
        "only_b": only_b,
        "size_diff": diff,
        "newer_in_a": [k for k in diff if a[k][1] > b[k][1]],
        "newer_in_b": [k for k in diff if b[k][1] > a[k][1]],
    }


def is_custom_picture(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return rel.startswith("gracs/") and name.endswith(".pdl") and not name.startswith("@")


def normalize_os_rel(rel: str) -> str:
    """'<PCadı>/PAS/x.pas' -> '<pc>/pas/x.pas': bilgisayar adı klasörü karşılaştırmada ihmal edilir."""
    parts = rel.lower().split("/")
    if len(parts) >= 3 and parts[1] == "pas":
        parts[0] = "<pc>"
    return "/".join(parts)


def list_os_entries(entries, os_dir: str) -> dict[str, tuple[int, float]]:
    """Kaynak indeksinden (source.Entry listesi) OS projesi listesi; list_os_project ile aynı kurallar."""
    prefix = os_dir + "/"
    out = {}
    for e in entries:
        if not e.rel.startswith(prefix):
            continue
        rel = normalize_os_rel(e.rel[len(prefix):])
        if rel.endswith(OS_IGNORE_EXT):
            continue
        out[rel] = (e.size, e.mtime)
    return out


F_FACEPLATE_PREFIXES = ("@pg_swc_mos", "@pcs7typicals_s7f")
STANDARD_TYPICALS = ("@pcs7typicals.pdl", "@@pcs7typicals.pdl", "@template.pdl", "@templateaplver10.pdl",
                     "@pcs7typicalsaplver10.pdl", "@pcs7typicalsapl.pdl", "@templateapl.pdl",
                     "@pcs7typicalsapc.pdl", "@pcs7typicalsaplv8.pdl", "@templateaplv8.pdl")


def picture_kind(rel: str) -> str:
    """gracs/*.pdl sınıfı: custom / faceplate / f_faceplate / typicals / custom_typicals / other."""
    name = rel.rsplit("/", 1)[-1].lower()
    if not (rel.lower().startswith("gracs/") and rel.count("/") == 1 and name.endswith(".pdl")):
        return "other"
    if not name.startswith("@"):
        return "custom"
    if name.startswith(F_FACEPLATE_PREFIXES):
        return "f_faceplate"
    if "typicals" in name or name.startswith("@template"):
        return "typicals" if name in STANDARD_TYPICALS else "custom_typicals"
    return "faceplate"
