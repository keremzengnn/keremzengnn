"""Destek paketi: çıktı klasöründeki TANI dosyalarını (izinli liste) maskeleyip tek zip'e koyar.

Rapor dosyaları (docx/xlsx/html/md, findings.json, report_ir.json) ve ham backup içeriği ASLA girmez.
SADECE mutlak yollar maskelenir (`inventory.mask_path`: son 3 seviye, bilinen STEP 7 klasörleri açık,
diğerleri <klasör>). Log içindeki müşteri / proje / station adı gibi serbest metin maskelenmez:
müşteri adı garantisi YOKTUR, göndermeden önce içeriği kontrol edin.
Traceback'teki `pcs7_analyzer` kaynak dosya yolları (ve satır numaraları) hata ayıklama için açık kalır."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from . import __version__

ALLOWED = ("log.txt", "unknown.log", "yapi_tanisi.txt", "blockmap_tanisi.txt", "qa_report.md",
           "envanter_ozet.json")
FORBIDDEN_SUFFIXES = (".docx", ".xlsx", ".html", ".dbf", ".dbt", ".s7p", ".mcp", ".zip", ".mdf", ".s7h")

_WIN = re.compile(r"[A-Za-z]:[\\/][^\r\n\"'<>|*?:]*|\\\\[^\r\n\"'<>|*?:]+")
_POSIX = re.compile(r"(?<![\w.<-])/(?:[\w.@ -]+/)+[\w.@-]*")


_SRC = re.compile(r"(?:^|/)(pcs7_analyzer/(?:[\w.-]+/)*[\w.-]+\.py)$")


def _mask_match(m: re.Match) -> str:
    from .inventory import mask_path
    s = m.group(0).replace("\\", "/")
    src = _SRC.search(s)
    if src:                                              # traceback: kaynak yolu açık (kurulum öneki atılır)
        return src.group(1)
    head, sep, last = s.rpartition("/")
    tail = ""
    ext = re.match(r"(\S*?\.\w{1,5})(\s.*)$", last)      # "SUBBLK.DBF hata" -> dosya + açıklama metni
    if ext:
        last, tail = ext.group(1), ext.group(2)
    return mask_path(head + sep + last.rstrip()) + tail


def mask_text(text: str) -> str:
    """Metindeki mutlak yolları maskeler."""
    return _POSIX.sub(_mask_match, _WIN.sub(_mask_match, text))


def collect(out_dir: Path) -> list[Path]:
    """Pakete girecek dosyalar (sadece izinli liste, mevcut olanlar)."""
    out_dir = Path(out_dir)
    return [out_dir / n for n in ALLOWED if (out_dir / n).is_file()]


def build(out_dir: Path, dest_zip: Path) -> tuple[Path, list[tuple[str, int]]]:
    """Zip yazar; (zip_yolu, [(dosya adı, maskeli boyut)]) döndürür."""
    out_dir, dest_zip = Path(out_dir), Path(dest_zip)
    files = collect(out_dir)
    if not files:
        raise FileNotFoundError(f"Tanı dosyası bulunamadı (log.txt, unknown.log …): {out_dir}")
    listed: list[tuple[str, int]] = []
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            data = mask_text(f.read_text(encoding="utf-8", errors="replace")).encode("utf-8")
            z.writestr(f.name, data)
            listed.append((f.name, len(data)))
        z.writestr("_destek_paketi.txt", f"pcs7_analyzer {__version__} destek paketi\n"
                   "Sadece mutlak yollar maskelenmiştir (pcs7_analyzer kaynak yolları hariç).\n"
                   "Müşteri / proje / station adı gibi metinler maskelenmez; müşteri adı garantisi yoktur.\n"
                   "Göndermeden önce içeriği kontrol edin.\n"
                   "Rapor dosyaları (docx/xlsx/html/md, findings.json, report_ir.json) ve backup dosyaları dahil değildir.\n"
                   .encode("utf-8"))
    return dest_zip, listed


def describe(out_dir: Path) -> str:
    """Kullanıcıya gösterilecek dahil edilecek dosya listesi (boyutlarıyla)."""
    rows = [f"  {f.name}  ({f.stat().st_size / 1024:.1f} KB)" for f in collect(out_dir)]
    if not rows:
        return "  (tanı dosyası yok)"
    return "\n".join(rows)
