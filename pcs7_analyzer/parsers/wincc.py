"""WinCC proje klasörü (wincproj/<OS>/...) listeleme ve karşılaştırma."""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
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


_TS_FORMATS = ("%m/%d/%Y %I:%M:%S %p", "%d.%m.%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
               "%m/%d/%Y %H:%M:%S", "%d.%m.%Y %H:%M")


def parse_timestamp(ts: str) -> float | None:
    """PowerShell LastWriteTime (en-US, tr-TR, de-DE, ISO). Tanınmazsa None (çağıran uyarı üretir)."""
    ts = ts.strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts, fmt).timestamp()
        except ValueError:
            continue
    return None


def list_os_project_from_csv(csv_path: Path, project: str, warnings: list | None = None) -> dict[str, tuple[int, float]]:
    """PowerShell 'Get-ChildItem -Recurse | Export-Csv' çıktısı (FullName,Length,LastWriteTime).
    Tarihi okunamayan satırlar mtime=0 alır ve `warnings` listesine sayısı yazılır (sessizce yutulmaz)."""
    raw = Path(csv_path).read_bytes().decode("utf-8-sig", "ignore")
    out = {}
    bad = []
    for r in csv.DictReader(io.StringIO(raw)):
        p = r["FullName"].split("wincproj\\", 1)[-1].split("\\")
        if p[0] != project:
            continue
        rel = "/".join(p[1:]).lower()
        if rel.endswith(OS_IGNORE_EXT):
            continue
        mtime = parse_timestamp(r["LastWriteTime"])
        if mtime is None:
            bad.append(r["LastWriteTime"])
            mtime = 0.0
        out[rel] = (int(r["Length"] or 0), mtime)
    if bad and warnings is not None:
        warnings.append(f"{csv_path}: {len(bad)} satırda tarih okunamadı (ör. '{bad[0]}'); bu dosyalar için "
                        "'hangisi daha yeni' karşılaştırması yapılamaz")
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


# ---------------------------------------------------------------------------
# SFC görselleştirme (SfcRtBase) ve arşivler
# ---------------------------------------------------------------------------

# Boş SfcRtBase şablonu (hiç derlenmemiş): objects.dat 10.240 B + objects.idx 141.312 B
SFC_EMPTY_SIZES = {"objects.dat": 10240, "objects.idx": 141312}
_CHART_LINE = re.compile(r"^V\d+\.(?P<name>[^.]+)\.(?P<ts>\d{9,11})\.(?P<name2>[^.]*)\.\d+\.\d+\.(?P<comment>.*)\.\d+\s*$")


def parse_chartlst(text: str) -> list[tuple[str, int, str]]:
    """ChartLst: 'V701.<Chart>.<unix_ts>.<Chart>.0.0.<Yorum>.0' -> [(chart, ts, yorum)]."""
    out = []
    for line in text.splitlines():
        m = _CHART_LINE.match(line.strip())
        if m:
            out.append((m.group("name"), int(m.group("ts")), m.group("comment")))
    return out


def chart_group(name: str) -> str:
    """'TK01_OP1_FILL_CYCLE' -> 'TK01'; kısa önekler (GO, FO, MN) iki token: 'MN_SEL'."""
    toks = [t for t in name.split("_") if t]
    if not toks:
        return name
    if len(toks) > 1 and re.fullmatch(r"[A-Za-z]{1,3}", toks[0]):
        return f"{toks[0]}_{toks[1]}"
    return toks[0]


def sfc_visualization(entries, os_dir: str, read_bytes=None) -> dict:
    """
    SfcRtBase kanıtı. {'present', 'filled', 'charts', 'groups', 'first', 'last', 'files': {ad: (boyut, mtime)}}.
    read_bytes(rel) -> bytes: ChartLst'i okumak için (verilmezse sadece boyutlar).
    """
    prefix = os_dir + "/"
    files = {}
    chartlst_rel = None
    for e in entries:
        if not e.rel.startswith(prefix):
            continue
        sub = e.rel[len(prefix):]
        parts = sub.split("/")
        if len(parts) >= 2 and parts[0].lower() == "sfcrtbase":
            files[parts[-1]] = (e.size, e.mtime)
            if parts[-1].lower() == "chartlst":
                chartlst_rel = e.rel
    res = {"present": bool(files), "filled": False, "charts": 0, "groups": Counter(), "first": 0, "last": 0,
           "files": files}
    if not files:
        return res
    charts = []
    if chartlst_rel and read_bytes:
        try:
            charts = parse_chartlst(read_bytes(chartlst_rel).decode("latin1", "replace"))
        except OSError:
            charts = []
    big = any(files.get(k, files.get(k.upper(), (0, 0)))[0] > v for k, v in SFC_EMPTY_SIZES.items())
    res["filled"] = bool(charts) or big
    res["charts"] = len(charts)
    res["groups"] = Counter(chart_group(c[0]) for c in charts)
    if charts:
        res["first"] = min(c[1] for c in charts)
        res["last"] = max(c[1] for c in charts)
    return res


def archive_files(entries, os_dir: str, os_name: str) -> dict:
    """
    Arşiv izleri: ArchiveManager/ içeriği, kökteki <proje>ALG_*/TLG_* segmentleri, <proje>Alg/Tlg.mdf,
    ana veritabanı <proje>.mdf/.ldf. {'segments': [(dosya, boyut, mtime)], 'alg_tlg': [...], 'archive_manager': [...],
    'main_mdf': (boyut, mtime) | None, 'main_ldf': ...}
    """
    prefix = os_dir + "/"
    n = os_name.lower()
    out = {"segments": [], "alg_tlg": [], "archive_manager": [], "main_mdf": None, "main_ldf": None}
    for e in entries:
        if not e.rel.startswith(prefix):
            continue
        sub = e.rel[len(prefix):]
        low = sub.lower()
        if low.startswith("archivemanager/"):
            out["archive_manager"].append((sub, e.size, e.mtime))
            continue
        if "/" in sub:
            continue
        if low in (f"{n}.mdf",):
            out["main_mdf"] = (e.size, e.mtime)
        elif low in (f"{n}.ldf", f"{n}_log.ldf"):
            out["main_ldf"] = (e.size, e.mtime)
        elif low in (f"{n}alg.mdf", f"{n}tlg.mdf", f"{n}alg.ldf", f"{n}tlg.ldf"):
            out["alg_tlg"].append((sub, e.size, e.mtime))
        elif re.match(rf"{re.escape(n)}_?(alg|tlg)_.*\.(mdf|ldf)$", low):
            out["segments"].append((sub, e.size, e.mtime))
    return out
