"""
DENEYSEL — WinCC OS projesi veritabanı (.mdf) şema tarayıcı (ek prompt bölüm 2-B).

Amaç: tag / connection / alarm / arşiv konfigürasyonunu Configuration Studio export'u olmadan okuyabilmek.
WinCC şeması dokümante değil; bu araç önce ŞEMAYI keşfeder (tablo adı, kolonlar, satır sayısı — İÇERİK YOK).
Çıktı paylaşılarak tablolar eşlenir, sonra okuma eklenir.

Güvenlik:
- Orijinal .mdf/.ldf'e asla attach edilmez: SQL Server'ın default data klasörüne KOPYALANIR (servis hesabı erişebilsin).
  Eski (ör. WinCC V7.3 / SQL 2008 R2) veritabanı yeni SQL sürümüne attach edilince geri dönüşsüz yükseltilir — bu yüzden kopya.
- Kopya geçici adla attach edilir, sorgu sonrası detach edilip silinir.
- Gerekenler: WinCC/SQL Server kurulu PC (ör. V10 ES), `sqlcmd`, SQL instance'ında sysadmin (Windows admin).

  python -m pcs7_analyzer.wincc_db <OS_PROJE>.mdf [--instance .\\WINCC] [-o sema.txt]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

DEFAULT_INSTANCE = r".\WINCC"
SQLCMD_GLOBS = [r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\*\Tools\Binn\SQLCMD.EXE",
                r"C:\Program Files\Microsoft SQL Server\*\Tools\Binn\SQLCMD.EXE"]


class ProbeError(RuntimeError):
    pass


def find_sqlcmd() -> str | None:
    p = shutil.which("sqlcmd")
    if p:
        return p
    import glob
    for g in SQLCMD_GLOBS:
        hits = sorted(glob.glob(g))
        if hits:
            return hits[-1]
    return None


def _run(sqlcmd: str, instance: str, query: str, runner=subprocess.run) -> str:
    r = runner([sqlcmd, "-S", instance, "-E", "-b", "-W", "-s", "\t", "-h", "-1", "-Q", query],
               capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise ProbeError((r.stderr or r.stdout or "").strip() or f"sqlcmd hata kodu {r.returncode}")
    return r.stdout


def find_ldf(mdf: Path) -> Path | None:
    for cand in (mdf.with_suffix(".ldf"), mdf.with_suffix(".LDF"), mdf.with_name(mdf.stem + "_log.ldf")):
        if cand.exists():
            return cand
    return None


def probe(mdf: Path, instance: str = DEFAULT_INSTANCE, runner=subprocess.run, sqlcmd: str | None = None,
          copy=shutil.copy2, log=print) -> str:
    """Şema raporunu (metin) döndürür. Orijinal dosyalar sadece okunur (kopyalanır)."""
    mdf = Path(mdf)
    if not mdf.exists():
        raise ProbeError(f".mdf bulunamadı: {mdf}")
    sqlcmd = sqlcmd or find_sqlcmd()
    if not sqlcmd:
        raise ProbeError("sqlcmd bulunamadı (SQL Server command line tools). WinCC/SQL Server kurulu bir PC'de çalıştırın.")
    ldf = find_ldf(mdf)
    data_dir = _run(sqlcmd, instance, "SET NOCOUNT ON; SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(400))",
                    runner).strip().splitlines()[-1].strip()
    if not data_dir:
        raise ProbeError("SQL Server default data klasörü alınamadı")
    tag = uuid.uuid4().hex[:8]
    db = f"pcs7an_probe_{tag}"
    dst_mdf = Path(data_dir) / f"{db}.mdf"
    dst_ldf = Path(data_dir) / f"{db}_log.ldf"
    if dst_mdf.resolve() == mdf.resolve():
        raise ProbeError("kopya hedefi orijinal dosya ile aynı (beklenmeyen)")
    log(f"Kopyalanıyor: {mdf} -> {dst_mdf}")
    copy(mdf, dst_mdf)
    files = f"(FILENAME = N'{dst_mdf}')"
    if ldf:
        copy(ldf, dst_ldf)
        files += f", (FILENAME = N'{dst_ldf}')"
        attach = f"CREATE DATABASE [{db}] ON {files} FOR ATTACH"
    else:
        attach = f"CREATE DATABASE [{db}] ON {files} FOR ATTACH_REBUILD_LOG"
    attached = False
    try:
        log(f"Attach (kopya): {db}")
        _run(sqlcmd, instance, attach, runner)
        attached = True
        tables = _run(sqlcmd, instance, f"SET NOCOUNT ON; USE [{db}]; SELECT s.name + '.' + t.name, SUM(p.rows) "
                      "FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id "
                      "JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1) "
                      "GROUP BY s.name, t.name ORDER BY 1", runner)
        cols = _run(sqlcmd, instance, f"SET NOCOUNT ON; USE [{db}]; SELECT TABLE_SCHEMA + '.' + TABLE_NAME, COLUMN_NAME, "
                    "DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION", runner)
        views = _run(sqlcmd, instance, f"SET NOCOUNT ON; USE [{db}]; SELECT s.name + '.' + v.name FROM sys.views v "
                     "JOIN sys.schemas s ON s.schema_id = v.schema_id ORDER BY 1", runner)
    finally:
        if attached:
            try:
                _run(sqlcmd, instance, f"ALTER DATABASE [{db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                     f"EXEC master.dbo.sp_detach_db @dbname = N'{db}'", runner)
            except ProbeError as e:
                log(f"UYARI: detach başarısız ({e}); SQL Server Management Studio'dan {db} elle detach edilmeli")
        for p in (dst_mdf, dst_ldf):
            try:
                if Path(p).exists():
                    Path(p).unlink()
            except OSError as e:
                log(f"UYARI: geçici kopya silinemedi: {p} ({e})")

    by_table: dict[str, list[str]] = {}
    for line in cols.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            by_table.setdefault(parts[0].strip(), []).append(f"{parts[1].strip()}:{parts[2].strip()}")
    out = [f"WinCC DB şema taraması — {datetime.now():%Y-%m-%d %H:%M} — kaynak dosya: {mdf.name}",
           "Sadece şema: tablo adları, kolonlar, satır sayıları. Kayıt içeriği YOK.", "", "## Tablolar (satır sayısı)"]
    for line in tables.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip():
            name = parts[0].strip()
            out.append(f"- {name}  [{parts[1].strip()} satır]")
            if name in by_table:
                out.append(f"    {', '.join(by_table[name])}")
    vl = [v.strip() for v in views.splitlines() if v.strip()]
    if vl:
        out += ["", "## View'lar", ", ".join(vl)]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mdf", type=Path, help="WinCC OS projesinin <proje>.mdf dosyası (backup içinden)")
    ap.add_argument("--instance", default=DEFAULT_INSTANCE, help=f"SQL instance (varsayılan {DEFAULT_INSTANCE})")
    ap.add_argument("-o", "--out", type=Path, help="Şema raporu dosyası (varsayılan: <mdf adı>_sema.txt, çalışma klasörü)")
    a = ap.parse_args(argv)
    try:
        text = probe(a.mdf, a.instance, log=lambda m: print(m, file=sys.stderr))
    except ProbeError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2
    out = a.out or Path.cwd() / f"{a.mdf.stem}_sema.txt"
    out.write_text(text, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
