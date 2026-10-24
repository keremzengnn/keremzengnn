"""
Paketle: backup'tan sadece analiz / envanter için gereken dosyaları küçük bir zip'e toplar.

5+ GB backup'ın büyük kısmı (WinCC .mdf/.ldf, arşiv segmentleri, picture'lar, CFC/SFC kaynakları) analizde sadece
ADI, BOYUTU ve TARİHİ ile kullanılır. Paket:
  - içeriği okunan dosyaları aynen içerir (SUBBLK.DBF/.DBT, HW .s7h/.cfg, DBF'ler, symbol table, .mcp, ChartLst,
    Configuration Studio export'ları, VBS/C script'leri),
  - diğer TÜM dosyaları sadece manifest satırı olarak tutar (_pcs7_manifest.csv: path, boyut, tarih).
Paket `open_source` ile açılınca orijinal backup gibi görünür (aynı dosya listesi, boyut, tarih) -> analiz aynı sonucu verir.

Paket müşteri verisi İÇERİR (block / symbol adları, HW, script'ler). Paylaşmadan önce veri kullanım kuralları teyit edilmeli.

  python -m pcs7_analyzer <backup klasörü|zip> --collect [-o çıktı_klasörü]
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime
from pathlib import Path

from .source import NESTED_SEP, Source, open_source

MANIFEST = "_pcs7_manifest.csv"
MANIFEST_VERSION = "1"

_ALWAYS_EXT = (".s7f", ".s7p", ".s7h", ".mcp", ".asc", ".sdf")
_SCRIPT_EXT = (".bmo", ".bac", ".pas", ".act")
_MAX_DBF = 50_000_000          # hOmSave7 / global DBF'leri küçüktür; büyük olanlar sadece SUBBLK / SYMLIST
_MAX_TEXT = 50_000_000


def needed(rel: str, size: int) -> bool:
    """Bu dosyanın İÇERİĞİ analiz / envanter tarafından okunuyor mu?"""
    low = rel.lower().replace(NESTED_SEP, "/")
    name = low.rsplit("/", 1)[-1]
    in_wincc = "/wincproj/" in f"/{low}"
    if name.endswith(_ALWAYS_EXT):
        return True
    if name in ("subblk.dbf", "subblk.dbt", "baustein.dbf", "symlist.dbf", "linkhrs.lnk"):
        return True
    if "/xutils/" in f"/{low}" and name.endswith((".dbf", ".dbt")):
        # XUTILS cross-reference: CT (call tree), BS (block listesi), CTL/BSL/XRL link tabloları, CT112001 okunur;
        # XR (operand cross-ref, 100k+ kayıt) okunmaz -> pakete girmez
        if re.match(r"^xr\d+\.(dbf|dbt)$", name):
            return False
        return bool(re.match(r"^(ct|bs)\d+\.dbf$|^(ct|bs|xr)l\d+\.dbf$", name)) or size <= _MAX_DBF
    if name.endswith(".dbf"):
        return size <= _MAX_DBF
    if name.endswith(".dbt") and "/homsave7/" in f"/{low}":
        return size <= _MAX_DBF
    if name.endswith(".cfg") and not in_wincc:
        return size <= _MAX_TEXT                      # HW Config export (discovery başlığa bakar)
    if name.endswith(".txt") and not in_wincc:
        return size <= _MAX_TEXT                      # Configuration Studio export olabilir
    if name == "chartlst" and "/sfcrtbase/" in f"/{low}":
        return True
    from .parsers.diag import is_diag_file
    kind = is_diag_file(rel.replace(NESTED_SEP, "/"))
    if kind in ("sql_errorlog", "wincc_log") or (kind == "eventlog_csv" and not in_wincc):
        return size <= _MAX_TEXT                      # DIAGNOSTICS: SQL ERRORLOG, WinCC diagnose, event log CSV
    if in_wincc and name.endswith(_SCRIPT_EXT):
        return size <= 5_000_000                      # VBS / C script'ler (OPC, 3rd party referansları için)
    return False


def collect(source: Path, out_zip: Path, log=print) -> dict:
    """Paketi yazar; özet sözlüğü döndürür. Kaynak sadece okunur."""
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    stats = {"files": 0, "included": 0, "bytes_total": 0, "bytes_included": 0, "errors": []}
    with open_source(source, log) as src:
        stats["files"] = len(src.entries)
        rows = []
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for i, e in enumerate(src.entries, 1):
                stats["bytes_total"] += e.size
                inc = needed(e.rel, e.size)
                if inc:
                    try:
                        _add(zf, src, e)
                        stats["included"] += 1
                        stats["bytes_included"] += e.size
                    except Exception as ex:  # noqa: BLE001 - okunamayan dosya paketi durdurmaz
                        inc = False
                        stats["errors"].append(f"{e.rel}: {type(ex).__name__}: {ex}")
                        log(f"UYARI: pakete eklenemedi: {e.rel} ({ex})")
                rows.append((e.rel, e.size, f"{e.mtime:.3f}", "1" if inc else "0"))
                if i % 5000 == 0:
                    log(f"  {i}/{len(src.entries)} dosya")
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(["#pcs7_manifest", MANIFEST_VERSION, src.label, datetime.now().isoformat(timespec="minutes")])
            w.writerow(["rel", "size", "mtime", "included"])
            w.writerows(rows)
            zf.writestr(MANIFEST, buf.getvalue().encode("utf-8"))
    log(f"Paket: {out_zip} — {stats['included']}/{stats['files']} dosya içerikli, "
        f"{stats['bytes_included'] / 1e6:.0f} MB / {stats['bytes_total'] / 1e6:.0f} MB "
        f"(zip: {out_zip.stat().st_size / 1e6:.0f} MB)")
    return stats


def _add(zf: zipfile.ZipFile, src: Source, e) -> None:
    zi = zipfile.ZipInfo(e.rel, date_time=_zip_time(e.mtime))
    zi.compress_type = zipfile.ZIP_DEFLATED
    with open(src.materialize(e.rel), "rb") as f, zf.open(zi, "w", force_zip64=e.size > 2_000_000_000) as dst:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            dst.write(b)


def _zip_time(ts: float) -> tuple:
    try:
        t = datetime.fromtimestamp(ts).timetuple()[:6]
    except (OverflowError, OSError, ValueError):
        t = (1980, 1, 1, 0, 0, 0)
    return t if t[0] >= 1980 else (1980, 1, 1, 0, 0, 0)


def read_manifest(data: bytes) -> tuple[str, list[tuple[str, int, float, bool]]]:
    """(orijinal kaynak etiketi, [(rel, size, mtime, included)])."""
    rd = csv.reader(io.StringIO(data.decode("utf-8")))
    head = next(rd)
    if not head or head[0] != "#pcs7_manifest":
        raise ValueError("geçersiz manifest")
    next(rd)
    out = []
    for r in rd:
        if len(r) >= 4:
            out.append((r[0], int(r[1]), float(r[2]), r[3] == "1"))
    return (head[2] if len(head) > 2 else ""), out


__all__ = ["MANIFEST", "collect", "needed", "read_manifest"]
