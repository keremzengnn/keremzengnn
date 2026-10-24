"""Offline doküman bilgi tabanı (Siemens manual arşivi -> SQLite FTS5).

Her analyzer bulgusuna 1-3 kısa sayfa referansı ("Kaynak": dosya adı, ürün versiyonu, sayfa) verir.
**Risk kararı vermez**; sadece referans gösterir. Bağımlılık yok (stdlib + sqlite3 FTS5). PDF metni tercihen harici
`pdftotext` (poppler) ile; yoksa yerleşik basit PDF okuyucu (FlateDecode + Tj/TJ, "metin kalitesi düşük").
Kaynak klasör veya .zip olabilir; kaynağa asla yazılmaz (zip'ten PDF'ler tek tek temp'e çıkarılır, sonra silinir).
Build artımlıdır: değişmeyen dosyalar (ad + boyut + mtime/CRC) tekrar okunmaz; yarıda kalan build devam eder.

    python -m pcs7_analyzer kb build --root <klasör|arşiv.zip> [--db <kb.sqlite>] [--all] [--rebuild]
    python -m pcs7_analyzer kb search "<metin>" [--db <kb.sqlite>] [--target V10.0SP2]

Varsayılan db: ayar klasörü (`settings.settings_path().parent / "kb.sqlite"`), `settings.find_kb` otomatik bulur.
Ayrıntılar: docs/spec/kb.md
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import hashlib
import json
import mmap
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

SCHEMA_VERSION = "2"
REPORT_NAME = "kb_rapor.txt"
PROGRESS_EVERY = 25          # her N dosyada bir ilerleme satırı
TEXT_MAX_BYTES = 64 << 20    # .md/.txt üst sınırı (daha büyüğü atlanır)
FALLBACK_MAX_BYTES = 400 << 20   # yerleşik PDF okuyucu üst sınırı


def default_db() -> Path:
    """Ayar klasöründeki kb.sqlite (settings.find_kb bunu otomatik bulur)."""
    from . import settings
    return settings.settings_path().parent / "kb.sqlite"

# Kökte SADECE bu isimlere uyan klasörler taranır (büyük/küçük harf duyarsız, fnmatch).
INCLUDE_TOP_PATTERNS: tuple[str, ...] = (
    "PCS7_*", "OT_Network", "OT_Cybersecurity", "Safety", "SCALANCE", "Sanallastirma",
)
# Path'in herhangi bir parçası bunlara uyarsa atlanır (büyük/küçük harf duyarsız, fnmatch).
EXCLUDE_PATTERNS: tuple[str, ...] = (
    "Projeler", "CN4100", "Kendi_Kilavuzlarim", "Kurs_*",
    "_tekrarlar", "_tablolar", "_diger", "_md_donusumler",
)
DOC_SUFFIXES = (".pdf", ".md", ".txt")

WINDOWS_PDFTOTEXT_GLOBS: tuple[str, ...] = (
    r"C:\Program Files\poppler*\Library\bin\pdftotext.exe",
    r"C:\Program Files\poppler*\bin\pdftotext.exe",
    r"C:\poppler*\Library\bin\pdftotext.exe",
    r"C:\poppler*\bin\pdftotext.exe",
)
PDFTOTEXT_TIMEOUT_S = 600

SNIPPET_MAX = 160
UNKNOWN_NO_PDFTOTEXT = "pdftotext yok: PDF indekslenmedi"
UNKNOWN_NO_TEXT = "metin yok, OCR yapılmadı"

# Dosya adı <-> başlık karşılaştırmasında anlamsız kelimeler (normalize: küçük harf, aksansız).
TITLE_STOPWORDS = {
    "simatic", "siemens", "pcs", "pcs7", "manual", "manuals", "handbuch", "system", "systems",
    "process", "control", "edition", "version", "service", "function", "functions",
    "readme", "documentation", "with", "from", "this", "that", "for", "and", "the",
}
# Arama sorgusundan atılan kelimeler (Türkçe bulgu metni + İngilizce dolgu).
QUERY_STOPWORDS = {
    # en
    "the", "and", "for", "with", "of", "to", "in", "on", "is", "are", "be", "a", "an", "or",
    "not", "by", "from", "this", "that", "it", "as", "at", "if", "no", "yes", "all", "any",
    # tr
    "ve", "ile", "için", "icin", "bir", "bu", "şu", "su", "var", "yok", "olan", "olarak", "değil",
    "degil", "gibi", "daha", "çok", "cok", "en", "da", "de", "mi", "ya", "veya", "sadece", "ayrıca",
    "kullanılıyor", "kullaniliyor", "kullanılmıyor", "bulundu", "bulunamadı", "tespit", "edildi",
    "gerekli", "gerekir", "yapılmalı", "kontrol", "edilmeli", "adet", "sayısı", "toplam", "mevcut",
    "block", "blocks", "blok", "klasör", "klasörü", "proje", "projede", "projesi", "dosya",
    "teyit", "edilmedi", "olabilir", "uyarı", "not", "kurulu",
}
# Bulgu metninden "anahtar" sayılan teknik terimler (en az biri eşleşmezse referans zayıf sayılır).
KEY_TERM_PATTERNS: tuple[str, ...] = (
    r"Logic Matrix", r"Process Historian", r"F-Library", r"Failsafe", r"Faceplates?",
    r"Basis Library", r"Advanced Process Library", r"Software update", r"Released Modules",
    r"6[A-Z]{2}\d\s?\d{3}-\d[A-Z0-9]{4}-\d[A-Z0-9]{3}",      # MLFB: 6ES7 410-5HX08-0AB0
    r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b",                       # OB_DIAG, IM_DRV, OR_M_16
    r"\b[A-Z]{2,}[a-z]*[A-Z]+\b",                           # TCiR
    r"\b[A-Z][A-Z0-9]{1,7}\b",                              # APL, SFC, CAS, OPC
)
GENERIC_KEY_TOKENS = {"PCS", "AS", "OS", "ES", "HW", "FW", "CPU", "V", "SP", "PC", "ID", "OK"}
GENERIC_CHECK_PARTS = {"LIB", "HW", "OS", "AS", "ES", "NO", "CHECK", "DIFF"}


@dataclass
class KbRef:
    file_name: str
    doc_title: str
    product_version: str | None
    page: int
    heading: str
    snippet: str
    score: float
    version_note: str = ""
    page_kind: str = "page"
    path: str = ""
    matched_tokens: int = 0      # sorgu token'larından sayfada bulunanlar
    matched_keys: int = 0        # refs_for_findings anahtar terimlerinden sayfada bulunanlar
    quality: str = ""            # 'low' = yerleşik PDF okuyucu (metin kalitesi düşük)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- yardımcılar
def _fold(s: str) -> str:
    """Küçük harf + aksan/diakritik kaldırma (karşılaştırma için)."""
    s = unicodedata.normalize("NFKD", s.replace("ı", "i").replace("İ", "I"))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", _fold(s))


def normalize_page_text(text: str) -> str:
    return " ".join(text.split()).lower()


def content_hash(text: str) -> str:
    return hashlib.sha1(normalize_page_text(text).encode("utf-8")).hexdigest()


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _match_any(name: str, patterns: Iterable[str]) -> bool:
    n = name.lower()
    return any(fnmatch.fnmatchcase(n, p.lower()) for p in patterns)


def is_included_top(name: str) -> bool:
    return _match_any(name, INCLUDE_TOP_PATTERNS)


def is_excluded(rel_parts: Iterable[str]) -> bool:
    return any(_match_any(p, EXCLUDE_PATTERNS) for p in rel_parts)


# --------------------------------------------------------------------------- kaynak (klasör / zip)
ROOT_TOP = "(kök)"
CONTAINER_SUFFIXES = (".zip",)
ZIP_SKIP_PARTS = ("__MACOSX",)


@dataclass
class Entry:
    """Kaynaktaki tek dosya (sadece metadata; içerik gerektiğinde okunur)."""
    rel: str                      # kaynağa göre relatif, '/' ayraçlı (iç zip: 'a/b.zip/c/d.pdf')
    parts: tuple[str, ...]        # dahil/hariç kararı için parçalar (sarmalayıcı klasör atılmış)
    size: int
    sig: str                      # 'boyut:mtime' (klasör) / 'boyut:crc' (zip)
    src: "_FolderSource | _ZipSource"
    key: object                   # klasör: Path, zip: ZipInfo
    encrypted: bool = False

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()


class _FolderSource:
    kind = "klasör"

    def __init__(self, root: Path):
        self.root = Path(root)

    def entries(self) -> list[Entry]:
        out: list[Entry] = []
        base = _long(self.root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not _match_any(d, EXCLUDE_PATTERNS))
            for fn in sorted(filenames):
                if Path(fn).suffix.lower() not in DOC_SUFFIXES + CONTAINER_SUFFIXES:
                    continue
                p = Path(dirpath) / fn
                try:
                    st = p.stat()
                except OSError:
                    continue
                parts = p.relative_to(base).parts
                out.append(Entry("/".join(parts), parts, st.st_size, f"{st.st_size}:{int(st.st_mtime)}",
                                 self, p))
        return out

    def read_bytes(self, e: Entry) -> bytes:
        return Path(e.key).read_bytes()

    def materialize(self, e: Entry, tmpdir: Path) -> tuple[Path, str]:
        """(okunacak dosya, sha1). Klasörde dosyanın kendisi (kopya yok)."""
        return Path(e.key), _file_sha1(Path(e.key))

    def close(self) -> None:
        pass


def _zip_name(info: zipfile.ZipInfo) -> str:
    """UTF-8 bayrağı yoksa zipfile cp437 ile çözer; Windows (TR) zip'leri için utf-8 / cp857 dene."""
    n = info.filename
    if not info.flag_bits & 0x800:
        try:
            raw = n.encode("cp437")
        except UnicodeEncodeError:
            return n
        for enc in ("utf-8", "cp857"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
    return n


class _ZipSource:
    kind = "zip"

    def __init__(self, path: Path, prefix: str = "", base_parts: tuple[str, ...] = ()):
        self.path = Path(path)
        self.prefix = prefix              # iç zip: dış zip'teki rel ('a/b.zip')
        self.base_parts = base_parts      # iç zip: dış zip'teki parçalar
        self.zf = zipfile.ZipFile(_long(self.path))

    def entries(self) -> list[Entry]:
        out: list[Entry] = []
        for info in self.zf.infolist():
            if info.is_dir():
                continue
            name = _zip_name(info).replace("\\", "/")
            parts = tuple(p for p in name.split("/") if p not in ("", "."))
            if not parts or ".." in parts or any(p in ZIP_SKIP_PARTS for p in parts):
                continue
            if Path(parts[-1]).suffix.lower() not in DOC_SUFFIXES + CONTAINER_SUFFIXES:
                continue
            rel = "/".join(parts)
            if self.prefix:
                rel = f"{self.prefix}/{rel}"
            out.append(Entry(rel, self.base_parts + parts, info.file_size,
                             f"{info.file_size}:{info.CRC:08x}", self, info,
                             encrypted=bool(info.flag_bits & 0x1)))
        return out

    def read_bytes(self, e: Entry) -> bytes:
        return self.zf.read(e.key)

    def materialize(self, e: Entry, tmpdir: Path) -> tuple[Path, str]:
        """Üyeyi temp'e akışla çıkar (bellekte tutmadan), sha1'i yolda hesapla."""
        dst = Path(tmpdir) / f"doc{abs(hash(e.rel)) % 10**8}{e.suffix}"
        h = hashlib.sha1()
        with self.zf.open(e.key) as src, open(dst, "wb") as out:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                h.update(chunk)
                out.write(chunk)
        return dst, h.hexdigest()

    def close(self) -> None:
        self.zf.close()


def _long(p: Path) -> Path:
    try:
        from .source import long_path
        return long_path(p)
    except Exception:  # noqa: BLE001 - source modülü olmadan da çalışsın
        return Path(p)


def open_source(root: Path) -> "_FolderSource | _ZipSource":
    root = Path(root)
    if root.is_dir():
        return _FolderSource(root)
    if root.is_file() and zipfile.is_zipfile(root):
        return _ZipSource(root)
    if root.is_file():
        raise ValueError(f"Kaynak klasör veya .zip değil: {root}")
    raise FileNotFoundError(f"Kaynak yok: {root}")


def strip_wrappers(entries: list[Entry]) -> int:
    """Tek bir sarmalayıcı klasörü (ör. zip içinde 'Siemens_Dokumanlar/') kaç seviye atlanacağı.
    Tüm dosyalar aynı klasörün altındaysa ve o klasör INCLUDE_TOP_PATTERNS'a uymuyorsa bir seviye iner."""
    n = 0
    while entries:
        if any(len(e.parts) <= n + 1 for e in entries):
            break
        firsts = {e.parts[n] for e in entries}
        if len(firsts) != 1 or is_included_top(next(iter(firsts))):
            break
        n += 1
    if n:
        for e in entries:
            e.parts = e.parts[n:]
    return n


def select_entries(entries: list[Entry], all_files: bool = False) -> tuple[list[Entry], str]:
    """(seçilenler, mod). Mod 'include': kökte INCLUDE_TOP_PATTERNS'a uyan klasör var ve --all verilmedi;
    'all': her şey (EXCLUDE_PATTERNS yine geçerli). Sarmalayıcı klasör önce atılır."""
    strip_wrappers(entries)
    tops = {e.parts[0] for e in entries if len(e.parts) > 1}
    mode = "all" if all_files or not any(is_included_top(t) for t in tops) else "include"
    out = []
    for e in entries:
        if is_excluded(e.parts):
            continue
        if mode == "include" and (len(e.parts) < 2 or not is_included_top(e.parts[0])):
            continue
        out.append(e)
    out.sort(key=lambda e: e.rel)
    return out, mode


def entry_top(e: Entry) -> str:
    return e.parts[0] if len(e.parts) > 1 else ROOT_TOP


def iter_documents(root: Path, all_files: bool = False) -> Iterable[Path]:
    """Klasör kaynağında seçilen .pdf/.md/.txt dosyaları (iç zip'ler hariç; geriye uyumluluk / test)."""
    src = _FolderSource(Path(root))
    sel, _ = select_entries(src.entries(), all_files)
    for e in sel:
        if e.suffix in DOC_SUFFIXES:
            yield Path(root) / Path(*e.rel.split("/"))


# --------------------------------------------------------------------------- pdftotext
def find_pdftotext(explicit: str | None = None, log: Callable[[str], None] | None = None) -> str | None:
    """Sıra: verilen yol/komut -> PATH (shutil.which) -> yaygın Windows kurulum yerleri."""
    if explicit:
        if Path(explicit).is_file():
            return str(Path(explicit))
        w = shutil.which(explicit)
        if w:
            return w
        if log:
            log(f"Uyarı: verilen pdftotext bulunamadı: {explicit}")
    w = shutil.which("pdftotext")
    if w:
        return w
    if os.name == "nt":
        for pattern in WINDOWS_PDFTOTEXT_GLOBS:
            hits = sorted(glob.glob(pattern))
            if hits:
                return hits[-1]
    return None


def pdf_pages(pdf: Path, exe: str) -> list[str]:
    """Tek pdftotext çağrısı (-layout, UTF-8, stdout); sayfalar form feed ile ayrılır."""
    r = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(pdf), "-"],
                       capture_output=True, timeout=PDFTOTEXT_TIMEOUT_S)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise RuntimeError(f"pdftotext hata kodu {r.returncode}: {err}")
    out = r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, bytes) else (r.stdout or "")
    pages = out.split("\f")
    if pages and not pages[-1].strip():      # pdftotext son sayfadan sonra da \f yazar
        pages.pop()
    return pages


class PdfSkip(Exception):
    """PDF'ten metin alınamadı (şifreli / taranmış / desteklenmeyen); mesaj = neden."""


REASON_ENCRYPTED = "şifreli PDF"
REASON_NO_TEXT = "metin yok (taranmış PDF?, OCR yapılmadı)"
REASON_UNDECODABLE = "metin çözülemedi (font encoding / desteklenmeyen filtre)"
REASON_BROKEN = "PDF yapısı okunamadı"
REASON_TOO_BIG = "çok büyük"
_REASONS = (REASON_ENCRYPTED, REASON_NO_TEXT, REASON_UNDECODABLE, REASON_BROKEN, REASON_TOO_BIG)
QUALITY_LOW = "low"
QUALITY_LOW_TEXT = "metin kalitesi düşük"


def _pdftotext_encrypted(msg: str) -> bool:
    m = msg.lower()
    return "encrypt" in m or "password" in m


# --------------------------------------------------------------------------- yerleşik PDF okuyucu
# Best effort, sadece stdlib: nesneler + object stream'ler, sayfa ağacı, FlateDecode content stream'ler,
# Tj / TJ / ' / " operatörleri, ToUnicode CMap (bfchar/bfrange). Form XObject, Type3, /Differences, OCR yok.
class _Ref:
    __slots__ = ("num",)

    def __init__(self, num: int):
        self.num = num

    def __repr__(self) -> str:
        return f"R{self.num}"


class _Name(str):
    pass


class _Op(str):
    pass


_WS = b" \t\r\n\f\x00"
_DELIM = b"()<>[]{}/%"
_PDF_TOKEN_RE = re.compile(
    rb"(?P<ws>[ \t\r\n\f\x00]+|%[^\r\n]*)"
    rb"|(?P<num>[+-]?(?:\d+\.?\d*|\.\d+))(?![^ \t\r\n\f\x00()<>\[\]{}/%])"
    rb"|(?P<name>/[^ \t\r\n\f\x00()<>\[\]{}/%]*)"
    rb"|(?P<dict><<)|(?P<dend>>>)"
    rb"|(?P<hex><[0-9A-Fa-f \t\r\n\f]*>)"
    rb"|(?P<lit>\()"
    rb"|(?P<arr>\[)|(?P<aend>\])|(?P<brace>[{}])"
    rb"|(?P<kw>[^ \t\r\n\f\x00()<>\[\]{}/%]+)"
    rb"|(?P<bad>.)", re.S)
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
_END = object()
_PUNCT = {"dict": "<<", "dend": ">>", "arr": "[", "aend": "]"}


def _lit_string(data, i: int) -> tuple[bytes, int]:
    out = bytearray()
    depth = 1
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0x5C:
            i += 1
            if i >= n:
                break
            c = data[i]
            if c in _ESC:
                out.append(_ESC[c])
            elif 0x30 <= c <= 0x37:
                j = i
                while j < n and j < i + 3 and 0x30 <= data[j] <= 0x37:
                    j += 1
                out.append(int(bytes(data[i:j]), 8) & 0xFF)
                i = j
                continue
            elif c == 13:
                if i + 1 < n and data[i + 1] == 10:
                    i += 1
            elif c != 10:
                out.append(c)
            i += 1
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        out.append(c)
        i += 1
    return bytes(out), i


class _Lexer:
    def __init__(self, data, pos: int = 0):
        self.data = data
        self.pos = pos
        self.n = len(data)

    def token(self):
        while self.pos < self.n:
            m = _PDF_TOKEN_RE.match(self.data, self.pos)
            if not m:
                return _END
            self.pos = m.end()
            k = m.lastgroup
            if k == "ws" or k == "bad" or k == "brace":
                continue
            v = m.group(k)
            if k == "num":
                return float(v) if b"." in v else int(v)
            if k == "name":
                return _Name(re.sub(rb"#([0-9A-Fa-f]{2})", lambda x: bytes([int(x.group(1), 16)]),
                                    v[1:]).decode("latin1"))
            if k == "hex":
                h = re.sub(rb"\s", b"", v[1:-1])
                if len(h) % 2:
                    h += b"0"
                return bytes.fromhex(h.decode("ascii"))
            if k == "lit":
                s, self.pos = _lit_string(self.data, self.pos)
                return s
            if k == "kw":
                return _Op(v.decode("latin1"))
            return _Op(_PUNCT[k])
        return _END

    def obj(self, tok=None, depth: int = 0):
        """Bir PDF nesnesi; sayı sonrası 'n g R' referansa çevrilir."""
        t = self.token() if tok is None else tok
        if depth > 60:
            return None
        if isinstance(t, _Op):
            if t == "<<":
                d: dict = {}
                while True:
                    k = self.token()
                    if k is _END or (isinstance(k, _Op) and k == ">>"):
                        return d
                    if isinstance(k, _Name):
                        d[str(k)] = self.obj(depth=depth + 1)
            if t == "[":
                a: list = []
                while True:
                    x = self.token()
                    if x is _END or (isinstance(x, _Op) and x == "]"):
                        return a
                    a.append(self.obj(x, depth + 1))
            if t == "true":
                return True
            if t == "false":
                return False
            if t == "null":
                return None
            return t
        if isinstance(t, int):
            save = self.pos
            t2 = self.token()
            if isinstance(t2, int):
                t3 = self.token()
                if isinstance(t3, _Op) and t3 == "R":
                    return _Ref(t)
            self.pos = save
        return t


_OBJ_HDR = re.compile(rb"(\d{1,10})\s+(\d{1,5})\s+obj\b")
_STREAM_KW = re.compile(rb"\s*stream\r?\n?")


class MiniPdf:
    """Basit PDF okuyucu (mmap: büyük dosya belleğe alınmaz)."""

    def __init__(self, path: Path):
        self._f = open(path, "rb")
        try:
            self.mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:          # boş dosya
            self._f.close()
            raise PdfSkip(REASON_BROKEN)
        if self.mm.find(b"%PDF", 0, 1024) < 0:
            self.close()
            raise PdfSkip(REASON_BROKEN)
        self.offsets: dict[int, int] = {}
        pos = 0
        mm = self.mm
        while True:
            m = _OBJ_HDR.search(mm, pos)
            if not m:
                break
            self.offsets[int(m.group(1))] = m.end()      # sonraki (incremental update) kazanır
            e = mm.find(b"endobj", m.end())
            pos = e + 6 if e >= 0 else m.end()
        self._objstm: dict[int, tuple[int, int]] | None = None
        self._objstm_data: dict[int, tuple[bytes, int, list[int]]] = {}
        self._cache: dict[int, object] = {}
        self._fonts: dict[object, tuple[dict[int, str] | None, int, bool]] = {}

    def close(self) -> None:
        try:
            self.mm.close()
        finally:
            self._f.close()

    # nesneler
    def _parse_at(self, off: int):
        lx = _Lexer(self.mm, off)
        val = lx.obj()
        stream = None
        if isinstance(val, dict):
            m = _STREAM_KW.match(self.mm, lx.pos)
            if m:
                start = m.end()
                length = self.resolve(val.get("Length"))
                end = -1
                if isinstance(length, int) and 0 <= length and start + length <= len(self.mm):
                    tail = self.mm[start + length:start + length + 20]
                    if b"endstream" in tail:
                        end = start + length
                if end < 0:
                    end = self.mm.find(b"endstream", start)
                    if end < 0:
                        end = len(self.mm)
                stream = (start, end)
        return val, stream

    def _load_objstms(self) -> None:
        self._objstm = {}
        for num, off in self.offsets.items():
            head = self.mm[off:off + 400]
            if b"ObjStm" not in head:
                continue
            try:
                d, st = self._parse_at(off)
                if not isinstance(d, dict) or d.get("Type") != "ObjStm" or not st:
                    continue
                data = self._decode(d, st)
                if data is None:
                    continue
                nobj, first = int(d.get("N", 0)), int(d.get("First", 0))
                lx = _Lexer(data)
                nums = [lx.token() for _ in range(2 * nobj)]
                for i in range(0, len(nums) - 1, 2):
                    if isinstance(nums[i], int) and isinstance(nums[i + 1], int):
                        self._objstm.setdefault(nums[i], (num, first + nums[i + 1]))
                self._objstm_data[num] = (data, first, [])
            except Exception:  # noqa: BLE001 - bozuk object stream atlanır
                continue

    def get(self, num: int):
        """(değer, stream) — stream: (başlangıç, bitiş) mmap içinde veya None."""
        if num in self._cache:
            return self._cache[num]
        res: tuple = (None, None)
        if num in self.offsets:
            try:
                res = self._parse_at(self.offsets[num])
            except Exception:  # noqa: BLE001
                res = (None, None)
        else:
            if self._objstm is None:
                self._load_objstms()
            loc = self._objstm.get(num) if self._objstm else None
            if loc and loc[0] in self._objstm_data:
                data = self._objstm_data[loc[0]][0]
                try:
                    res = (_Lexer(data, loc[1]).obj(), None)
                except Exception:  # noqa: BLE001
                    res = (None, None)
        if len(self._cache) < 20000:
            self._cache[num] = res
        return res

    def resolve(self, v, depth: int = 0):
        while isinstance(v, _Ref) and depth < 20:
            v = self.get(v.num)[0]
            depth += 1
        return v

    def _decode(self, d: dict, st: tuple[int, int]) -> bytes | None:
        raw = self.mm[st[0]:st[1]]
        filters = self.resolve(d.get("Filter"))
        if filters is None:
            filters = []
        elif not isinstance(filters, list):
            filters = [filters]
        for f in filters:
            f = self.resolve(f)
            if f in ("FlateDecode", "Fl"):
                try:
                    raw = zlib.decompressobj().decompress(raw)
                except zlib.error:
                    return None
            else:
                return None         # DCT/LZW/ASCII85…: desteklenmiyor
        return raw

    def stream_of(self, ref) -> bytes | None:
        if isinstance(ref, _Ref):
            d, st = self.get(ref.num)
            if isinstance(d, dict) and st:
                return self._decode(d, st)
        return None

    # sayfalar
    def root(self) -> dict | None:
        mm = self.mm
        pos = len(mm)
        while pos > 0:
            i = mm.rfind(b"/Root", 0, pos)
            if i < 0:
                break
            v = _Lexer(mm, i + 5).obj()
            if isinstance(v, _Ref):
                r = self.resolve(v)
                if isinstance(r, dict):
                    return r
            pos = i
        return None

    def encrypted(self) -> bool:
        return self.mm.find(b"/Encrypt") >= 0

    def pages(self) -> list[tuple[object, dict]]:
        """[(Contents, Resources)] sayfa sırasıyla; sayfa ağacı yoksa /Type /Page nesneleri dosya sırasıyla."""
        out: list[tuple[object, dict]] = []
        root = self.root()
        seen: set[int] = set()

        def walk(node_ref, inherited, depth):
            if depth > 50:
                return
            if isinstance(node_ref, _Ref):
                if node_ref.num in seen:
                    return
                seen.add(node_ref.num)
            node = self.resolve(node_ref)
            if not isinstance(node, dict):
                return
            res = self.resolve(node.get("Resources")) or inherited
            kids = self.resolve(node.get("Kids"))
            if node.get("Type") == "Pages" or isinstance(kids, list):
                for k in kids or []:
                    walk(k, res, depth + 1)
            else:
                out.append((node.get("Contents"), res if isinstance(res, dict) else {}))

        if isinstance(root, dict):
            walk(root.get("Pages"), {}, 0)
        if not out:
            for num in sorted(self.offsets, key=self.offsets.get):
                d = self.get(num)[0]
                if isinstance(d, dict) and d.get("Type") == "Page":
                    out.append((d.get("Contents"), self.resolve(d.get("Resources")) or {}))
        return out

    def _font(self, ref) -> tuple[dict[int, str] | None, int, bool]:
        key = ref.num if isinstance(ref, _Ref) else id(ref)
        if key in self._fonts:
            return self._fonts[key]
        fd = self.resolve(ref)
        cmap, width, composite = None, 1, False
        if isinstance(fd, dict):
            composite = fd.get("Subtype") == "Type0"
            width = 2 if composite else 1
            data = self.stream_of(fd.get("ToUnicode"))
            if data:
                cmap, w = parse_cmap(data)
                width = w or width
        self._fonts[key] = (cmap, width, composite)
        return self._fonts[key]

    def page_text(self, contents, resources: dict) -> tuple[str, int]:
        """(metin, çözülemeyen string sayısı)."""
        if isinstance(contents, _Ref) and isinstance(self.get(contents.num)[0], list):
            contents = self.get(contents.num)[0]
        refs = contents if isinstance(contents, list) else [contents]
        data = b"\n".join(x for x in (self.stream_of(r) for r in refs) if x)
        fonts = self.resolve(resources.get("Font")) if isinstance(resources, dict) else None
        fonts = fonts if isinstance(fonts, dict) else {}
        return content_text(data, lambda name: self._font(fonts[name]) if name in fonts else (None, 1, False))


def parse_cmap(data: bytes) -> tuple[dict[int, str], int]:
    """ToUnicode CMap -> ({kod: metin}, kod byte genişliği)."""
    def u(h: bytes) -> str:
        b = bytes.fromhex(re.sub(rb"\s", b"", h).decode("ascii") or "")
        try:
            return b.decode("utf-16-be")
        except UnicodeDecodeError:
            return ""

    m: dict[int, str] = {}
    width = 0
    cs = re.search(rb"begincodespacerange\s*<([0-9A-Fa-f]+)>", data)
    if cs:
        width = len(cs.group(1)) // 2
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f\s]*)>", block):
            m[int(src, 16)] = u(dst)
            width = width or len(src) // 2
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, rest in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f\s]*>|\[[^\]]*\])",
                                       block):
            a, b = int(lo, 16), int(hi, 16)
            width = width or len(lo) // 2
            if b - a > 65535:
                continue
            if rest.startswith(b"["):
                for i, d in enumerate(re.findall(rb"<([0-9A-Fa-f\s]*)>", rest)):
                    if a + i <= b:
                        m[a + i] = u(d)
            else:
                base = u(rest[1:-1])
                if not base:
                    continue
                for i in range(b - a + 1):
                    m[a + i] = base[:-1] + chr(min(ord(base[-1]) + i, 0x10FFFF))
    return m, width


def _decode_str(s: bytes, font: tuple[dict[int, str] | None, int, bool]) -> tuple[str, bool]:
    cmap, width, composite = font
    if cmap:
        w = max(1, width)
        return "".join(cmap.get(int.from_bytes(s[i:i + w], "big"), "") for i in range(0, len(s), w)), True
    if composite:
        return "", False            # Identity-H, ToUnicode yok: çözülemez
    return s.decode("cp1252", "replace"), True


def content_text(data: bytes, font_for: Callable[[str], tuple]) -> tuple[str, int]:
    """Content stream'den metin: Tj/TJ/'/" + satır sonu tahmini (Td/TD/T*/Tm/ET)."""
    lx = _Lexer(data)
    out: list[str] = []
    ops: list = []
    font = (None, 1, False)
    bad = 0
    last_y: float | None = None

    def emit(s: bytes):
        nonlocal bad
        t, ok = _decode_str(s, font)
        if not ok:
            bad += 1
        out.append(t)

    while True:
        t = lx.token()
        if t is _END:
            break
        if isinstance(t, _Op):
            if t == "[":
                lx.pos -= 1
                ops.append(lx.obj())
                continue
            if t == "<<":
                lx.pos -= 2
                ops.append(lx.obj())
                continue
            if t == "Tf" and len(ops) >= 2 and isinstance(ops[-2], _Name):
                try:
                    font = font_for(str(ops[-2]))
                except Exception:  # noqa: BLE001
                    font = (None, 1, False)
            elif t == "Tj" and ops and isinstance(ops[-1], bytes):
                emit(ops[-1])
            elif t in ("'", '"') and ops and isinstance(ops[-1], bytes):
                out.append("\n")
                emit(ops[-1])
            elif t == "TJ" and ops and isinstance(ops[-1], list):
                for x in ops[-1]:
                    if isinstance(x, bytes):
                        emit(x)
                    elif isinstance(x, (int, float)) and x < -200:
                        out.append(" ")
            elif t in ("Td", "TD") and len(ops) >= 2 and isinstance(ops[-1], (int, float)):
                out.append("\n" if ops[-1] != 0 else " ")
            elif t == "Tm" and len(ops) >= 6 and isinstance(ops[-1], (int, float)):
                y = float(ops[-1])
                out.append("\n" if last_y is None or abs(y - last_y) > 0.5 else " ")
                last_y = y
            elif t == "T*":
                out.append("\n")
            elif t == "ET":
                out.append("\n")
            elif t == "ID":         # inline image: EI'ya kadar atla
                e = re.compile(rb"\sEI(?=[\s]|$)").search(data, lx.pos)
                lx.pos = e.end() if e else len(data)
            ops = []
        else:
            ops.append(t)
            if len(ops) > 64:
                ops = ops[-64:]
    text = "".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip(), bad


def _text_ok(text: str) -> bool:
    """Çözülmüş metin makul mü (harf/rakam/boşluk/noktalama oranı)?"""
    if not text:
        return False
    good = sum(1 for c in text if c.isalnum() or c.isspace() or c in ".,;:-_()/[]%&+*'\"!?=<>#°§")
    return good / len(text) >= 0.85


def fallback_pdf_pages(path: Path) -> list[str]:
    """Yerleşik okuyucuyla sayfa metinleri. Şifreli / metinsiz / çözülemeyen -> PdfSkip(neden)."""
    try:
        size = Path(path).stat().st_size
    except OSError as e:
        raise PdfSkip(f"{REASON_BROKEN} ({e})")
    if size > FALLBACK_MAX_BYTES:
        raise PdfSkip(f"{REASON_TOO_BIG} (yerleşik okuyucu sınırı {FALLBACK_MAX_BYTES >> 20} MB)")
    pdf = MiniPdf(path)
    try:
        if pdf.encrypted():
            raise PdfSkip(REASON_ENCRYPTED)
        pages = pdf.pages()
        if not pages:
            raise PdfSkip(REASON_BROKEN)
        texts: list[str] = []
        bad = 0
        for contents, res in pages:
            try:
                t, b = pdf.page_text(contents, res)
            except Exception:  # noqa: BLE001 - tek sayfa hatası
                t, b = "", 1
            bad += b
            texts.append(t if _text_ok(t) else "")
        if not any(t.strip() for t in texts):
            raise PdfSkip(REASON_UNDECODABLE if bad else REASON_NO_TEXT)
        return texts
    finally:
        pdf.close()


def pdf_text(path: Path, exe: str | None) -> tuple[list[str], str]:
    """(sayfalar, yöntem 'pdftotext' | 'fallback'). pdftotext tercih; hata verirse yerleşik okuyucu denenir.
    Metin alınamazsa PdfSkip(neden)."""
    if exe:
        try:
            pages = pdf_pages(path, exe)
            if any(p.strip() for p in pages):
                return pages, "pdftotext"
            raise PdfSkip(REASON_NO_TEXT)
        except RuntimeError as e:
            if _pdftotext_encrypted(str(e)):
                raise PdfSkip(REASON_ENCRYPTED) from e
            try:
                return fallback_pdf_pages(path), "fallback"
            except PdfSkip:
                raise PdfSkip(f"{REASON_BROKEN} ({e})") from e
    return fallback_pdf_pages(path), "fallback"


# --------------------------------------------------------------------------- md/txt
_MD_HEADING = re.compile(r"^#{1,6}\s+\S")


def text_chunks(text: str) -> tuple[list[str], str]:
    """Form feed varsa sayfa (page_kind='page'), yoksa Markdown başlıklarına göre chunk ('chunk')."""
    if "\f" in text:
        pages = text.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        return pages, "page"
    chunks: list[list[str]] = [[]]
    for line in text.splitlines():
        if _MD_HEADING.match(line) and any(l.strip() for l in chunks[-1]):
            chunks.append([])
        chunks[-1].append(line)
    return ["\n".join(c) for c in chunks if any(l.strip() for l in c)], "chunk"


def _decode_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1")


def _read_text(path: Path) -> str:
    return _decode_text(Path(path).read_bytes())


# --------------------------------------------------------------------------- metadata
_VERSION_RE = re.compile(
    r"(?<![A-Za-z0-9])V(\d{1,2}(?:[._]\d{1,2}){0,3})(?:[ _-]?(SP\d+))?(?:[ _-]?(Upd\d+))?(?![0-9])",
    re.IGNORECASE)
_DOCNO_RE = re.compile(r"A5E\d{8}(?:-[A-Z]{2})?")
_NUM_HEADING = re.compile(r"^\s*#*\s*(\d{1,2}(?:\.\d{1,3})*)\.?\s+([A-Za-zÄÖÜäöüß].*)$")


def find_version(*texts: str) -> str | None:
    """`V10.0_SP2` / `V10.0 SP2 Upd1` -> 'V10.0 SP2' ('V10.0 SP2 Upd1'); ilk bulunan metin kazanır."""
    for t in texts:
        if not t:
            continue
        m = _VERSION_RE.search(t)
        if m:
            v = "V" + m.group(1).replace("_", ".")
            if m.group(2):
                v += " SP" + m.group(2)[2:]
            if m.group(3):
                v += " Upd" + m.group(3)[3:]
            return v
    return None


def version_major_minor(v: str | None) -> tuple[int, int] | None:
    if not v:
        return None
    m = re.search(r"V?\s*(\d+)(?:[._](\d+))?", v, re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def find_doc_no(*texts: str) -> str | None:
    for t in texts:
        m = _DOCNO_RE.search(t or "")
        if m:
            return m.group(0)
    return None


def page_heading(text: str) -> str:
    """İlk numaralı başlık satırı (`9.5.17 Compiling ...`, Markdown `#` önekiyle de); yoksa ''."""
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 150:
            continue
        m = _NUM_HEADING.match(line)
        if m:
            return " ".join(f"{m.group(1)} {m.group(2)}".split())
    return ""


def _trivial_line(line: str) -> bool:
    w = _words(line)
    letters = sum(c.isalpha() for c in line)
    if letters < 4 or not w:
        return True
    if all(x in TITLE_STOPWORDS or x.isdigit() or len(x) < 3 for x in w):
        return True
    if _DOCNO_RE.fullmatch(line.strip()) or re.fullmatch(r"[\d./\s-]+", line.strip()):
        return True
    return False


def find_title(first_page: str) -> str:
    """Başlık heuristic'i (bkz. docs/spec/kb.md):
    1) Markdown: ilk `#` başlığı. 2) İlk 25 satırda 'SIMATIC' içeren satırdan sonraki ilk anlamlı satır
    (SIMATIC satırının kendisi anlamlıysa o). 3) Yoksa ilk anlamlı satır. Kısa ise (< 3 kelime) bir sonraki
    anlamlı satır eklenir. Anlamlı = >= 4 harf, sadece stopword/sayı/doküman no değil, <= 150 karakter."""
    lines = [" ".join(l.split()) for l in first_page.splitlines()]
    lines = [l for l in lines if l][:25]
    for l in lines:
        if _MD_HEADING.match(l):
            t = l.lstrip("#").strip()
            if not _trivial_line(t):
                return t[:200]
    cands = [l.lstrip("#").strip() for l in lines if len(l) <= 150]
    start = 0
    for i, l in enumerate(cands):
        if "simatic" in l.lower():
            start = i
            break
    good = [l for l in cands[start:] if not _trivial_line(l)] or [l for l in cands if not _trivial_line(l)]
    if not good:
        return ""
    title = good[0]
    if len(title.split()) < 3 and len(good) > 1:
        title = f"{title} {good[1]}"
    return title[:200]


def _meaningful_words(s: str) -> set[str]:
    out = set()
    for w in _words(s.replace("_", " ")):
        if len(w) >= 4 and w.isalpha() and w not in TITLE_STOPWORDS:
            out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def title_mismatch(file_name: str, title: str) -> bool:
    """Dosya adı ile başlık ortak anlamlı kelime (>= 4 harf, stopword değil) paylaşmıyorsa True.
    Taraflardan birinde anlamlı kelime yoksa karar verilemez -> False."""
    a = _meaningful_words(Path(file_name).stem)
    b = _meaningful_words(title)
    if not a or not b:
        return False
    return not (a & b)


# --------------------------------------------------------------------------- şema
SCHEMA_SQL = """
CREATE TABLE docs(
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    doc_title TEXT,
    product_version TEXT,
    doc_no TEXT,
    pages INTEGER,
    title_mismatch INTEGER NOT NULL DEFAULT 0,
    sha1 TEXT,
    top TEXT,
    method TEXT,
    quality TEXT
);
CREATE INDEX docs_path ON docs(path);
CREATE VIRTUAL TABLE pages USING fts5(
    text, heading, doc_id UNINDEXED, page UNINDEXED, page_kind UNINDEXED, content_hash UNINDEXED,
    quality UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE page_refs(
    content_hash TEXT NOT NULL,
    doc_id INTEGER NOT NULL,
    page INTEGER NOT NULL
);
CREATE INDEX page_refs_hash ON page_refs(content_hash);
CREATE INDEX page_refs_doc ON page_refs(doc_id);
CREATE TABLE files(
    path TEXT PRIMARY KEY,
    sig TEXT NOT NULL,
    status TEXT NOT NULL,
    method TEXT,
    reason TEXT,
    top TEXT
);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""
# files.status: indexed | skipped | error | container ; files.method: pdftotext | fallback | text | none


def fts5_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _ro_uri(db_path: Path) -> str:
    """Salt okunur SQLite URI; boşluk / # / % içeren Windows path'leri için yüzde kodlamalı."""
    return Path(db_path).resolve().as_uri() + "?mode=ro"


def _schema_version(db_path: Path) -> str | None:
    try:
        con = sqlite3.connect(db_path)
        try:
            r = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            con.execute("SELECT path, sig FROM files LIMIT 1")
            return r[0] if r else None
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _open_db(db_path: Path, rebuild: bool, log: Callable[[str], None]) -> tuple[sqlite3.Connection, bool]:
    """(bağlantı, yeni mi). Eski şema / --rebuild -> baştan."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fresh = rebuild or not db_path.exists()
    if not fresh and _schema_version(db_path) != SCHEMA_VERSION:
        log(f"Mevcut KB eski/uyumsuz şema -> baştan oluşturuluyor: {db_path}")
        fresh = True
    if fresh:
        for p in (db_path, db_path.with_name(db_path.name + "-journal"), db_path.with_name(db_path.name + ".tmp")):
            if p.exists():
                p.unlink()
    con = sqlite3.connect(db_path)
    if fresh:
        con.executescript(SCHEMA_SQL)
        con.execute("INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        con.commit()
    return con, fresh


def _delete_doc(con: sqlite3.Connection, doc_id: int, seen_hashes: set[str]) -> None:
    """Dokümanı sil; paylaşılan (tekrar) sayfa metni başka bir kopyaya devredilir."""
    con.execute("DELETE FROM page_refs WHERE doc_id=?", (doc_id,))
    for rowid, h in con.execute("SELECT rowid, content_hash FROM pages WHERE doc_id=?", (doc_id,)).fetchall():
        other = con.execute("SELECT doc_id, page FROM page_refs WHERE content_hash=? ORDER BY doc_id LIMIT 1",
                            (h,)).fetchone()
        if other:
            con.execute("UPDATE pages SET doc_id=?, page=? WHERE rowid=?", (other[0], other[1], rowid))
        else:
            con.execute("DELETE FROM pages WHERE rowid=?", (rowid,))
            seen_hashes.discard(h)
    con.execute("DELETE FROM docs WHERE id=?", (doc_id,))


def _upsert_file(con, rel: str, sig: str, status: str, method: str | None, reason: str | None,
                 top: str) -> None:
    con.execute("INSERT OR REPLACE INTO files(path, sig, status, method, reason, top) VALUES (?,?,?,?,?,?)",
                (rel, sig, status, method, reason, top))


def _needs_work(row, sig: str, exe: str | None) -> bool:
    """Ledger satırına göre dosya yeniden okunmalı mı?"""
    if row is None or row[0] != sig:
        return True
    status, method = row[1], row[2]
    if status == "error":
        return True
    if exe and method in ("fallback", "none"):     # artık pdftotext var: daha iyi metin
        return True
    return False


def _fmt_mb(n: int) -> str:
    return f"{n / (1 << 20):.1f} MB"


@dataclass
class _Run:
    stats: dict
    seen: set[str] = field(default_factory=set)
    seen_prefixes: list[str] = field(default_factory=list)
    seen_hashes: set[str] = field(default_factory=set)
    no_text_skips: list[str] = field(default_factory=list)


def build(root: Path, db_path: Path | None = None, log: Callable[[str], None] = print,
          pdftotext: str | None = None, all_files: bool = False, rebuild: bool = False,
          progress_every: int = PROGRESS_EVERY) -> dict:
    """Klasör veya .zip arşivini artımlı indeksler; istatistik döner ve db yanına kb_rapor.txt yazar.
    Değişmeyen dosyalar (ad + boyut + mtime/CRC) atlanır; her dosya ayrı transaction (yarıda kalırsa devam eder)."""
    root = Path(root)
    db_path = Path(db_path) if db_path else default_db()
    if root.is_dir() and _is_within(db_path, root):
        raise ValueError(f"Veritabanı kaynak klasörün içine yazılamaz: {db_path}")
    if root.is_file() and db_path.resolve() == root.resolve():
        raise ValueError(f"Veritabanı kaynak dosyanın yerine yazılamaz: {db_path}")
    if not fts5_available():
        raise RuntimeError("Bu Python'un sqlite3 modülünde FTS5 yok")
    src = open_source(root)          # FileNotFoundError / ValueError / zipfile.BadZipFile

    exe = find_pdftotext(pdftotext, log)
    stats: dict = {
        "root": str(root), "source_kind": src.kind, "db": str(db_path), "pdftotext": exe, "mode": "",
        "files_seen": 0, "files_selected": 0, "docs": 0, "unchanged": 0, "pruned": 0,
        "pdf_methods": {"pdftotext": 0, "fallback": 0}, "pdf_skipped": 0, "skip_reasons": {},
        "pages_total": 0, "pages_indexed": 0, "pages_duplicate": 0, "pages_empty": 0, "errors": 0,
        "containers": 0, "unknown": [], "completed": False,
    }
    if exe is None:
        log("Uyarı: pdftotext bulunamadı -> PDF'ler yerleşik basit okuyucuyla denenecek "
            "(metin kalitesi düşük; poppler kurulursa bir sonraki build bu PDF'leri yeniden okur)")
    else:
        log(f"pdftotext: {exe}")

    t0 = time.monotonic()
    tmpdir = Path(tempfile.mkdtemp(prefix="pcs7kb_"))
    con = None
    try:
        all_entries = src.entries()
        stats["files_seen"] = len(all_entries)
        entries, mode = select_entries(all_entries, all_files)
        stats["mode"] = mode
        stats["files_selected"] = len(entries)
        if mode == "include":
            tops = sorted({entry_top(e) for e in entries})
            log(f"Mod: include (kökte INCLUDE_TOP_PATTERNS'a uyan klasörler taranıyor: {', '.join(tops)})")
        else:
            why = "--all verildi" if all_files else "kökte INCLUDE_TOP_PATTERNS'a uyan klasör yok"
            log(f"Mod: all ({why}; EXCLUDE_PATTERNS yine uygulanıyor)")
        total_bytes = sum(e.size for e in entries)
        log(f"Kaynak ({src.kind}): {len(entries)} dosya seçildi / {len(all_entries)}, {_fmt_mb(total_bytes)}")

        con, fresh = _open_db(db_path, rebuild, log)
        if not fresh:
            n = con.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            log(f"Mevcut KB'ye artımlı ekleme ({n} doküman var; değişmeyen dosyalar atlanacak)")
        run = _Run(stats)
        run.seen_hashes = {r[0] for r in con.execute("SELECT content_hash FROM pages")}
        done_bytes = 0
        for i, e in enumerate(entries, start=1):
            _process_entry(con, e, exe, tmpdir, run, log, level=0)
            done_bytes += e.size
            if progress_every and (i % progress_every == 0 or i == len(entries)):
                log(f"  {i}/{len(entries)} dosya, {_fmt_mb(done_bytes)}/{_fmt_mb(total_bytes)}, "
                    f"{stats['docs']} yeni doküman, {stats['unchanged']} değişmemiş, "
                    f"{stats['pages_indexed']} sayfa, {time.monotonic() - t0:.0f} s")
        # kaynakta artık olmayanları temizle (sadece tam tur sonunda)
        stale = []
        for (path,) in con.execute("SELECT path FROM files").fetchall():
            if path in run.seen or any(path.startswith(p) for p in run.seen_prefixes):
                continue
            stale.append(path)
        for path in stale:
            for (doc_id,) in con.execute("SELECT id FROM docs WHERE path=?", (path,)).fetchall():
                _delete_doc(con, doc_id, run.seen_hashes)
                stats["pruned"] += 1
            con.execute("DELETE FROM files WHERE path=?", (path,))
        if run.no_text_skips:
            stats["unknown"].append(f"{UNKNOWN_NO_TEXT} ({len(run.no_text_skips)} PDF)")
        stats["completed"] = True
        stats["seconds"] = round(time.monotonic() - t0, 1)
        meta = {"schema_version": SCHEMA_VERSION, "built_at": datetime.now().isoformat(timespec="seconds"),
                "root": str(root), "pdftotext": exe or "", "mode": mode,
                "stats": json.dumps({k: v for k, v in stats.items() if k != "unknown"}, ensure_ascii=False)}
        con.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", meta.items())
        con.commit()
    except KeyboardInterrupt:
        log("Build yarıda kesildi; tekrar çalıştırınca kaldığı yerden devam eder.")
        raise
    finally:
        if con is not None:
            con.close()
        src.close()
        shutil.rmtree(tmpdir, ignore_errors=True)

    stats["summary"] = kb_summary(db_path)
    stats["db_size"] = db_path.stat().st_size
    report = db_path.with_name(REPORT_NAME)
    try:
        report.write_text(format_report(stats), encoding="utf-8")
        stats["report"] = str(report)
    except OSError as ex:
        log(f"Uyarı: {report} yazılamadı: {ex}")
    pm = stats["pdf_methods"]
    log(f"KB hazır: bu turda {stats['docs']} doküman indekslendi ({stats['unchanged']} değişmemiş atlandı, "
        f"{stats['pruned']} silindi), {stats['pages_indexed']} sayfa (+{stats['pages_duplicate']} tekrar); "
        f"PDF: pdftotext {pm['pdftotext']}, yerleşik okuyucu {pm['fallback']} (metin kalitesi düşük), "
        f"atlanan {stats['pdf_skipped']}; {stats['errors']} hata -> {db_path} ({_fmt_mb(stats['db_size'])})")
    for reason, n in sorted(stats["skip_reasons"].items()):
        log(f"  atlandı: {n} × {reason}")
    if "report" in stats:
        log(f"Rapor: {stats['report']}")
    try:
        from . import settings
        found = settings.find_kb()
        if found is None or Path(found).resolve() != db_path.resolve():
            log(f"Not: analiz otomatik olarak bu KB'yi kullanmayacak (bulunan: {found or 'yok'}); "
                f"ayarlarda 'kb_db' = {db_path} yapın veya --db vermeden build edin.")
    except Exception:  # noqa: BLE001
        pass
    return stats


def _skip(run: _Run, reason: str) -> None:
    r = run.stats["skip_reasons"]
    r[reason] = r.get(reason, 0) + 1


def _process_entry(con, e: Entry, exe, tmpdir: Path, run: _Run, log, level: int) -> None:
    stats = run.stats
    top = entry_top(e)
    run.seen.add(e.rel)
    row = con.execute("SELECT sig, status, method FROM files WHERE path=?", (e.rel,)).fetchone()

    if e.suffix in CONTAINER_SUFFIXES:
        if level >= 1:
            stats["unknown"].append(f"{e.rel}: iç içe zip (2. seviye) atlandı")
            _skip(run, "iç içe zip (2. seviye)")
            return
        run.seen_prefixes.append(e.rel + "/")
        if row and row[0] == e.sig and row[1] == "container" and not (exe and row[2] == "fallback"):
            stats["unchanged"] += 1
            return
        stats["containers"] += 1
        inner = None
        try:
            if e.encrypted:
                raise PdfSkip("zip şifreli")
            path, _ = e.src.materialize(e, tmpdir)
            inner = _ZipSource(path, prefix=e.rel, base_parts=e.parts)
            members = [m for m in inner.entries() if not is_excluded(m.parts)]
            log(f"  iç zip: {e.rel} ({len(members)} dosya)")
            used_fallback = False
            for m in sorted(members, key=lambda m: m.rel):
                _process_entry(con, m, exe, tmpdir, run, log, level + 1)
                r = con.execute("SELECT method FROM files WHERE path=?", (m.rel,)).fetchone()
                used_fallback |= bool(r and r[0] == "fallback")
            _upsert_file(con, e.rel, e.sig, "container", "fallback" if used_fallback else None, None, top)
            con.commit()
        except (PdfSkip, zipfile.BadZipFile, OSError, RuntimeError, ValueError) as ex:
            con.rollback()
            stats["errors"] += 1
            stats["unknown"].append(f"{e.rel}: iç zip okunamadı ({type(ex).__name__}: {ex})")
            _upsert_file(con, e.rel, e.sig, "error", None, f"iç zip okunamadı: {ex}", top)
            con.commit()
        finally:
            if inner is not None:
                inner.close()
                if inner.path.parent == tmpdir:        # sadece temp kopya silinir, kaynak asla
                    try:
                        inner.path.unlink()
                    except OSError:
                        pass
        return

    if not _needs_work(row, e.sig, exe):
        stats["unchanged"] += 1
        return
    for (doc_id,) in con.execute("SELECT id FROM docs WHERE path=?", (e.rel,)).fetchall():
        _delete_doc(con, doc_id, run.seen_hashes)

    tmp_file: Path | None = None
    try:
        if e.encrypted:
            raise PdfSkip("zip şifreli")
        if e.suffix == ".pdf":
            path, sha = e.src.materialize(e, tmpdir)
            if path.parent == tmpdir:
                tmp_file = path
            page_texts, method = pdf_text(path, exe)
            kind = "page"
            stats["pdf_methods"][method] += 1
        else:
            if e.size > TEXT_MAX_BYTES:
                raise PdfSkip(f"{REASON_TOO_BIG} (> {TEXT_MAX_BYTES >> 20} MB metin)")
            raw = e.src.read_bytes(e)
            sha = hashlib.sha1(raw).hexdigest()
            page_texts, kind = text_chunks(_decode_text(raw))
            method = "text"
    except PdfSkip as ex:
        reason = str(ex)
        if e.suffix == ".pdf":
            stats["pdf_skipped"] += 1
        _skip(run, next((r for r in _REASONS if reason.startswith(r)), reason))
        if reason.startswith(REASON_NO_TEXT) or reason.startswith(REASON_UNDECODABLE):
            run.no_text_skips.append(e.rel)
        stats["unknown"].append(f"{e.rel}: {reason}")
        _upsert_file(con, e.rel, e.sig, "skipped", "none" if not exe and e.suffix == ".pdf" else None,
                     reason, top)
        con.commit()
        return
    except Exception as ex:  # noqa: BLE001 - tek dosya hatası build'i durdurmaz
        con.rollback()
        stats["errors"] += 1
        stats["unknown"].append(f"{e.rel}: okunamadı ({type(ex).__name__}: {ex})")
        log(f"Uyarı: {e.rel} okunamadı: {ex}")
        _upsert_file(con, e.rel, e.sig, "error", None, f"{type(ex).__name__}: {ex}", top)
        con.commit()
        return
    finally:
        if tmp_file is not None:
            try:
                tmp_file.unlink()
            except OSError:
                pass

    quality = QUALITY_LOW if method == "fallback" else ""
    first = next((t for t in page_texts if t.strip()), "")
    title = find_title(first)
    cur = con.execute(
        "INSERT INTO docs(path, file_name, doc_title, product_version, doc_no, pages, title_mismatch, sha1,"
        " top, method, quality) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (e.rel, e.name, title, find_version(Path(e.name).stem, first), find_doc_no(e.name, first),
         len(page_texts), int(title_mismatch(e.name, title)), sha, top, method, quality))
    doc_id = cur.lastrowid
    stats["docs"] += 1
    empty: list[int] = []
    for no, text in enumerate(page_texts, start=1):
        stats["pages_total"] += 1
        if not text.strip():
            empty.append(no)
            continue
        h = content_hash(text)
        con.execute("INSERT INTO page_refs(content_hash, doc_id, page) VALUES (?,?,?)", (h, doc_id, no))
        if h in run.seen_hashes:
            stats["pages_duplicate"] += 1
            continue
        run.seen_hashes.add(h)
        con.execute("INSERT INTO pages(text, heading, doc_id, page, page_kind, content_hash, quality)"
                    " VALUES (?,?,?,?,?,?,?)", (text, page_heading(text), doc_id, no, kind, h, quality))
        stats["pages_indexed"] += 1
    if empty and kind == "page":
        stats["pages_empty"] += len(empty)
        shown = ", ".join(map(str, empty[:20])) + (" …" if len(empty) > 20 else "")
        stats["unknown"].append(f"{e.rel}: {UNKNOWN_NO_TEXT} (s. {shown})")
    _upsert_file(con, e.rel, e.sig, "indexed", method, None, top)
    con.commit()


# --------------------------------------------------------------------------- özet / rapor
def kb_summary(db_path: Path) -> dict:
    """Tüm KB'nin (önceki turlar dahil) özeti: üst klasör başına doküman/sayfa, yöntemler, atlananlar."""
    con = sqlite3.connect(_ro_uri(db_path), uri=True)
    try:
        per_top = [
            {"top": t or ROOT_TOP, "docs": d, "pages": p or 0, "low_quality": lq or 0}
            for t, d, p, lq in con.execute(
                "SELECT top, COUNT(*), SUM(pages), SUM(quality='low') FROM docs GROUP BY top ORDER BY top")]
        methods = dict(con.execute("SELECT COALESCE(method,''), COUNT(*) FROM docs GROUP BY method"))
        skipped = con.execute("SELECT path, status, reason FROM files WHERE status IN ('skipped','error')"
                              " ORDER BY path").fetchall()
        low = [r[0] for r in con.execute("SELECT path FROM docs WHERE quality='low' ORDER BY path")]
        return {
            "docs": sum(x["docs"] for x in per_top), "pages": sum(x["pages"] for x in per_top),
            "fts_pages": con.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
            "per_top": per_top, "methods": methods,
            "skipped": [{"path": p, "status": s, "reason": r or ""} for p, s, r in skipped],
            "low_quality": low,
        }
    finally:
        con.close()


def format_report(stats: dict) -> str:
    """kb_rapor.txt: sadece dosya adları ve sayılar (doküman içeriği yok)."""
    s = stats["summary"]
    pm = stats["pdf_methods"]
    lines = [
        "PCS 7 Analyzer - doküman bilgi tabanı (KB) raporu",
        f"Tarih      : {datetime.now().isoformat(timespec='seconds')}",
        f"Kaynak     : {stats['root']} ({stats['source_kind']})",
        f"Mod        : {stats['mode']}" + ("  (kökte INCLUDE_TOP_PATTERNS klasörü yok veya --all: her şey tarandı)"
                                          if stats["mode"] == "all" else "  (sadece INCLUDE_TOP_PATTERNS klasörleri)"),
        f"Veritabanı : {stats['db']} ({_fmt_mb(stats.get('db_size', 0))})",
        f"pdftotext  : {stats['pdftotext'] or 'YOK (yerleşik basit okuyucu kullanıldı)'}",
        "",
        "Bu tur:",
        f"  dosya (kaynakta / seçilen) : {stats['files_seen']} / {stats['files_selected']}",
        f"  yeni/değişen indekslendi   : {stats['docs']}",
        f"  değişmemiş (atlandı)       : {stats['unchanged']}",
        f"  kaynakta artık yok (silindi): {stats['pruned']}",
        f"  PDF pdftotext / yerleşik   : {pm['pdftotext']} / {pm['fallback']}",
        f"  PDF atlandı                : {stats['pdf_skipped']}",
        f"  hata                       : {stats['errors']}",
    ]
    for reason, n in sorted(stats["skip_reasons"].items()):
        lines.append(f"    - {n} × {reason}")
    lines += ["", f"KB toplam: {s['docs']} doküman, {s['pages']} sayfa ({s['fts_pages']} tekil sayfa metni)",
              "Yöntem: " + ", ".join(f"{k or '-'} {v}" for k, v in sorted(s["methods"].items())), "",
              f"{'Üst klasör':<40} {'doküman':>8} {'sayfa':>8} {'düşük kalite':>13}"]
    for x in s["per_top"]:
        lines.append(f"{x['top'][:40]:<40} {x['docs']:>8} {x['pages']:>8} {x['low_quality']:>13}")
    if s["skipped"]:
        lines += ["", f"Atlanan / okunamayan dosyalar ({len(s['skipped'])}):"]
        lines += [f"  {x['path']}  -- {x['reason']}" for x in s["skipped"]]
    if s["low_quality"]:
        lines += ["", f"Metin kalitesi düşük (yerleşik okuyucu; poppler pdftotext kurup tekrar build edin) "
                      f"({len(s['low_quality'])}):"]
        lines += [f"  {p}" for p in s["low_quality"]]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- search
_TOKEN_RE = re.compile(r"\w+(?:[.\-/]\w+)*")


def query_tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    """Serbest metinden FTS token'ları (sıralı, tekrarsız). `9.5.17`, `6ES7-410` tek parça kalır."""
    out: list[str] = []
    seen: set[str] = set()
    for t in _TOKEN_RE.findall(text or ""):
        f = _fold(t)
        if len(f) < 2 or (drop_stopwords and f in QUERY_STOPWORDS) or f in seen:
            continue
        seen.add(f)
        out.append(t)
    return out


def match_expr(tokens: Iterable[str], op: str = "OR") -> str:
    """Her token çift tırnaklı phrase (FTS özel karakterleri etkisiz); `op` ile birleştirilir."""
    parts = []
    for t in tokens:
        t = re.sub(r'["*^():{}\[\]]', " ", t).strip()
        if t:
            parts.append('"' + t + '"')
    return f" {op} ".join(parts)


def _token_hit(token: str, page_words: set[str]) -> bool:
    w = _words(token)
    return bool(w) and all(x in page_words for x in w)


def _version_note(doc_version: str | None, target: str | None) -> str:
    if not target or not doc_version:
        return ""
    a, b = version_major_minor(doc_version), version_major_minor(target)
    return "farklı sürüm" if a and b and a != b else ""


def _snippet(text: str) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= SNIPPET_MAX else s[:SNIPPET_MAX - 1].rstrip() + "…"


def search(db_path: Path, query: str, target_version: str | None = None, limit: int = 3,
           _tokens: list[str] | None = None, _keys: list[str] | None = None) -> list[KbRef]:
    """FTS5 bm25 araması. db yoksa / sorgu boşsa / sqlite hatasında []. score = -bm25 (büyük = iyi)."""
    db_path = Path(db_path)
    if not db_path.is_file():
        return []
    tokens = _tokens if _tokens is not None else query_tokens(query)
    expr = match_expr(tokens)
    if not expr:
        return []
    try:
        con = sqlite3.connect(_ro_uri(db_path), uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(
            "SELECT p.text, p.heading, p.doc_id, p.page, p.page_kind, p.content_hash, bm25(pages) AS r,"
            " snippet(pages, 0, '', '', '…', 16), p.quality"
            " FROM pages p WHERE pages MATCH ? ORDER BY r LIMIT ?", (expr, max(limit * 5, 15))).fetchall()
        docs = {r[0]: r[1:] for r in con.execute(
            "SELECT id, path, file_name, doc_title, product_version FROM docs")}
        out: list[KbRef] = []
        seen: set[tuple[str, int]] = set()
        for text, heading, doc_id, page, kind, h, rank, snip, quality in rows:
            refs = con.execute("SELECT doc_id, page FROM page_refs WHERE content_hash=? ORDER BY doc_id",
                               (h,)).fetchall() or [(doc_id, page)]
            # Tekrarlanan sayfa: hedef sürümle uyuşan kopyayı tercih et, yoksa ilk kopya.
            best = refs[0]
            for d, pg in refs:
                if docs.get(d) and not _version_note(docs[d][3], target_version) and docs[d][3]:
                    best = (d, pg)
                    break
            d = docs.get(best[0])
            if d is None:
                continue
            path, file_name, title, version = d
            key = (file_name, int(best[1]))
            if key in seen:
                continue
            seen.add(key)
            page_words = set(_words(text))
            out.append(KbRef(
                file_name=file_name, doc_title=title or "", product_version=version, page=int(best[1]),
                heading=heading or "", snippet=_snippet(snip or text), score=round(-float(rank), 6),
                version_note=_version_note(version, target_version), page_kind=kind, path=path,
                matched_tokens=sum(_token_hit(t, page_words) for t in tokens),
                matched_keys=sum(_token_hit(k, page_words) for k in (_keys or [])),
                quality=quality or ""))
            if len(out) >= limit:
                break
        return out
    except sqlite3.Error:
        return []
    finally:
        con.close()


def ref_text(ref: KbRef) -> str:
    """'Software_Update.pdf (V10.0 SP2), s. 91 — 9.5.17 Compiling the CFC Charts' (+ farklı sürüm notu)."""
    s = ref.file_name
    if ref.product_version:
        s += f" ({ref.product_version})"
    s += f", {'s.' if ref.page_kind == 'page' else 'bölüm'} {ref.page}"
    if ref.heading:
        s += f" — {ref.heading}"
    if ref.version_note:
        s += f" [{ref.version_note}]"
    if ref.quality == QUALITY_LOW:
        s += f" [{QUALITY_LOW_TEXT}]"
    return s


# --------------------------------------------------------------------------- findings
def key_terms(text: str, max_terms: int = 6) -> list[str]:
    """Bulgu metninden teknik terimler (APL, Logic Matrix, SFC, TCiR, OB_DIAG, MLFB …)."""
    found: list[str] = []
    seen: set[str] = set()
    for pat in KEY_TERM_PATTERNS:
        for m in re.finditer(pat, text or ""):
            t = " ".join(m.group(0).split())
            if (t.upper() in GENERIC_KEY_TOKENS or re.fullmatch(r"V\d+|(?:AS|OS|ES)\d+", t)
                    or _fold(t) in seen):
                continue
            if any(_fold(t) in s for s in seen):        # 'SFC' zaten 'SFC system' içinde
                continue
            seen.add(_fold(t))
            found.append(t)
            if len(found) >= max_terms:
                return found
    return found


def finding_query(finding) -> tuple[list[str], list[str]]:
    """(tüm token'lar, anahtar terimler). Başlık + detaydaki teknik terimler + check_id parçaları."""
    title = getattr(finding, "title", "") or ""
    detail = getattr(finding, "detail", "") or ""
    keys = key_terms(f"{title}\n{detail}")
    check_parts = [p for p in (getattr(finding, "check_id", "") or "").split("_")
                   if len(p) >= 3 and p.upper() not in GENERIC_CHECK_PARTS and not re.fullmatch(r"V\d+", p)]
    tokens: list[str] = []
    seen: set[str] = set()
    for t in [*keys, *query_tokens(title), *check_parts]:
        f = _fold(t)
        if f not in seen and f not in QUERY_STOPWORDS:
            seen.add(f)
            tokens.append(t)
    return tokens[:16], keys


def refs_for_findings(db_path: Path, findings: Iterable, target_version: str | None = None,
                      limit: int = 3, min_score: float | None = None) -> dict[str, list[KbRef]]:
    """check_id -> 0..limit referans. Zayıf eşleşme -> [] (çağıran 'kaynak bulunamadı' yazar).
    Zayıf: sonuç yok, (verildiyse) score <= min_score, anahtar terim varken hiçbiri sayfada yok, anahtar terim yokken
    < 2 token eşleşmesi (tek token'lı sorguda 1)."""
    out: dict[str, list[KbRef]] = {}
    if not Path(db_path).is_file():
        return {getattr(f, "check_id", ""): [] for f in findings}
    for f in findings:
        cid = getattr(f, "check_id", "")
        if cid in out:
            continue
        tokens, keys = finding_query(f)
        refs = search(db_path, "", target_version, limit=limit, _tokens=tokens, _keys=keys) if tokens else []
        good = []
        for r in refs:
            if min_score is not None and r.score <= min_score:
                continue
            if keys and r.matched_keys == 0:
                continue
            elif r.matched_tokens < min(2, len(tokens)):
                continue
            good.append(r)
        out[cid] = good
    return out


# --------------------------------------------------------------------------- digest (kural adayı pasajlar)
DIGEST_NAME = "kb_ozet.md"               # parçalar: kb_ozet_01.md, kb_ozet_02.md …
DIGEST_INDEX_NAME = "kb_ozet_index.csv"
DIGEST_PART_MB = 4.0
DIGEST_PASSAGE_MAX = 600
DIGEST_PASSAGE_MIN = 25

# Kural cümlesi kalıpları (EN/DE/TR).
DIGEST_RULE_PATTERNS: tuple[str, ...] = (
    r"not supported", r"no longer supported", r"not (?:be )?possible", r"must be", r"must not", r"\bmust\b",
    r"is required", r"are required", r"\brequires?\b", r"only with", r"only (?:be )?(?:possible|permitted|used)",
    r"compatib", r"upgrad", r"\bupdat", r"migrat", r"discontinued", r"replaced by", r"restriction",
    r"\bnote:", r"\bnotice\b", r"\bcaution\b", r"\bimportant\b", r"cannot be", r"not permitted",
    r"nicht unterstützt", r"nicht mehr", r"\bmuss\b", r"\bmüssen\b", r"erforderlich", r"nur mit",
    r"desteklenmez", r"desteklenmiyor", r"gerekir", r"zorunlu",
)
# PCS 7 terimleri (kural cümlesinde terim veya versiyon da olmalı).
DIGEST_TERM_PATTERNS: tuple[str, ...] = (
    r"\bAPL\b", r"Advanced Process Library", r"Basis Library", r"Industry Library", r"WinCC",
    r"SIMATIC Manager", r"\bCFC\b", r"\bSFC\b", r"Logic Matrix", r"F-Systems?", r"Failsafe", r"F-Library",
    r"\bTCiR\b", r"H-Systems?", r"\bH system", r"OS server", r"OS client", r"Process Historian", r"\bPH\b",
    r"\bCAS\b", r"SQL Server", r"\bWindows\b", r"firmware", r"PCS\s?7", r"STEP\s?7", r"\bCPU\s?41\d",
    r"faceplate", r"\bOPC\b", r"Maintenance Station", r"\bPDM\b", r"\bdriver blocks?\b", r"library",
)
# Başlığı bunlara uyan bölüm TAMAMEN alınır (bir sonraki aynı/üst seviye başlığa kadar).
DIGEST_SECTION_HEADING = re.compile(
    r"restriction|notes?\b|important|compatib|what'?s new|\bnew features|changes|upgrad|migrat|"
    r"installation notes?|known (?:issues|problems)|discontinued|"
    r"hinweis|einschränkung|kompatibilit|neuerung|änderung|wichtig|"
    r"kısıtlama|uyumluluk|önemli|yenilik|değişiklik", re.IGNORECASE)
# Tek başına satır olan uyarı kutusu başlıkları: sonraki paragraf alınır.
DIGEST_NOTICE_LINE = re.compile(
    r"^\s*(?:note|notes|notice|important|caution|warning|restriction|restrictions|hinweis|wichtig|"
    r"achtung|vorsicht|not|önemli|uyarı)\s*:?\s*$", re.IGNORECASE)
# Tablo benzeri satırlar: MLFB, versiyon, firmware, SP/Upd.
DIGEST_TABLE_LINE = re.compile(
    r"\b6[A-Z]{2}\d\s?\d{3}-[0-9A-Z]{4,5}-[0-9A-Z]{4}\b|(?<![A-Za-z0-9])V\s?\d+\.\d+|firmware|\bSP\s?\d|\bUpd\s?\d",
    re.IGNORECASE)
DIGEST_RELEVANCE = re.compile(r"PCS\s?7|WinCC|\bS7\b|S7-[34]00|SIMATIC|STEP\s?7", re.IGNORECASE)
_DIGEST_RULES = [re.compile(p, re.IGNORECASE) for p in DIGEST_RULE_PATTERNS]
_DIGEST_TERMS = [re.compile(p, re.IGNORECASE) for p in DIGEST_TERM_PATTERNS]
_DIGEST_VER = re.compile(r"(?<![A-Za-z0-9])V\s?(\d{1,2})(?:\.(\d{1,2}))?", re.IGNORECASE)
_SENT_SPLIT = re.compile(r"(?<=[.!?:;])\s+(?=[A-ZÄÖÜÇĞİŞ0-9•\-])")


def passage_score(p: str) -> float:
    """0 = kural cümlesi değil. (3 × farklı kural kalıbı + 2 × farklı terim + versiyon bonusu) / uzunluk faktörü.
    Kural kalıbı şart; ayrıca en az bir terim veya versiyon geçmeli. V10.x / V9.1 +3, diğer versiyon +1."""
    rules = sum(1 for r in _DIGEST_RULES if r.search(p))
    if not rules:
        return 0.0
    terms = sum(1 for t in _DIGEST_TERMS if t.search(p))
    vbonus = 0
    for m in _DIGEST_VER.finditer(p):
        major, minor = int(m.group(1)), m.group(2)
        vbonus = max(vbonus, 3 if major == 10 or (major == 9 and minor == "1") else 1)
    if not terms and not vbonus:
        return 0.0
    return round((3 * rules + 2 * terms + vbonus) / (1 + len(p) / 300), 6)


def _split_long(p: str, limit: int = DIGEST_PASSAGE_MAX) -> list[str]:
    """≤ limit karakterlik parçalar (cümle sınırında; çok uzun cümle sert kesilir). Metin kaybolmaz."""
    if len(p) <= limit:
        return [p]
    out: list[str] = []
    cur = ""
    for sent in _SENT_SPLIT.split(p):
        while len(sent) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(sent[:limit])
            sent = sent[limit:]
        if cur and len(cur) + 1 + len(sent) > limit:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


def _heading_level(line: str) -> tuple[int, str] | None:
    """Numaralı (`9.5.17 Başlık` -> 3) veya Markdown (`## Başlık` -> 2) başlık; değilse None."""
    s = line.strip()
    if not s or len(s) > 150:
        return None
    m = re.match(r"^(#{1,6})\s+(\S.*)$", s)
    if m:
        return len(m.group(1)), m.group(2).strip()
    m = _NUM_HEADING.match(s)
    if m and not re.search(r"\.{4,}|\s\d+\s*$", s):          # içindekiler satırı ('5.2 Notes ..... 34') değil
        return m.group(1).count(".") + 1, f"{m.group(1)} {m.group(2).strip()}"
    return None


@dataclass
class _Sel:
    page: int
    kind: str          # 'section' | 'rule' | 'table' | 'all'
    text: str
    label: str = ""    # bölüm başlığı


class _DocSelector:
    """Bir dokümanın sayfalarını sırayla gezer; bölüm durumu sayfalar arası taşınır."""

    def __init__(self):
        self.section: tuple[int, str] | None = None     # (seviye, başlık)
        self.notice: str | None = None                  # 'Note' / 'Hinweis' kutusu açık
        self.notice_has_content = False

    def page(self, page: int, text: str) -> list[_Sel]:
        out: list[_Sel] = []
        para: list[tuple[str, str | None]] = []          # (satır, bölüm etiketi | None)

        def flush():
            if not para:
                return
            lines = [l for l, _ in para]
            labels = [lab for _, lab in para if lab]
            joined = " ".join(" ".join(lines).split())
            para.clear()
            if len(joined) < DIGEST_PASSAGE_MIN and not labels:
                return
            if labels:
                out.extend(_Sel(page, "section", p, labels[0]) for p in _split_long(joined))
                return
            if passage_score(joined) > 0:
                out.extend(_Sel(page, "rule", p) for p in _split_long(joined))
                return
            tab = [" ".join(l.split()) for l in lines if DIGEST_TABLE_LINE.search(l)]
            if tab:
                out.extend(_Sel(page, "table", p) for p in _split_long(" | ".join(tab)))

        for raw in (text or "").splitlines():
            if not raw.strip():
                flush()
                if self.notice and self.notice_has_content:
                    self.notice = None
                continue
            h = _heading_level(raw)
            if h:
                flush()
                level, title = h
                if self.section and level <= self.section[0]:
                    self.section = None
                if self.section is None and DIGEST_SECTION_HEADING.search(title):
                    self.section = (level, title)
                self.notice = None
            elif DIGEST_NOTICE_LINE.match(raw):
                flush()
                self.notice = raw.strip().rstrip(":").strip()
                self.notice_has_content = False
                para.append((raw, "!" + self.notice))
                continue
            elif self.notice:
                self.notice_has_content = True
            lab = self.section[1] if self.section else ("!" + self.notice if self.notice else None)
            para.append((raw, lab))
        flush()
        self.notice = None          # uyarı kutusu sayfa sonunda biter
        return out


class _PartWriter:
    """kb_ozet_01.md, _02 … her biri ≤ part_bytes; doküman parçaya sığmazsa '(devam)' ile sürer."""

    def __init__(self, base: Path, part_bytes: int, preamble: list[str]):
        self.base = base
        self.part_bytes = max(part_bytes, 16 << 10)
        self.preamble = preamble
        self.no = 0
        self.f = None
        self.size = 0
        self.paths: list[Path] = []
        self.doc_header: str | None = None
        self.header_written = False

    def _path(self, no: int) -> Path:
        return self.base.with_name(f"{self.base.stem}_{no:02d}{self.base.suffix or '.md'}")

    def _open(self):
        if self.f:
            self.f.close()
        self.no += 1
        p = self._path(self.no)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(p, "w", encoding="utf-8", newline="\n")
        self.paths.append(p)
        self.size = 0
        self._raw(f"# KB özet — bölüm {self.no}\n\n" + "\n".join(self.preamble) + "\n\n")

    def _raw(self, s: str):
        self.f.write(s)
        self.size += len(s.encode("utf-8"))

    def start_doc(self, header: str):
        self.doc_header = header
        self.header_written = False

    def write(self, s: str):
        b = len(s.encode("utf-8"))
        if self.f is None or (self.size + b > self.part_bytes and self.size > 2048):
            cont = self.header_written
            self._open()
            if self.doc_header:
                self._raw(self.doc_header.replace("\n", " (devam)\n", 1) if cont else self.doc_header)
                self.header_written = True
        elif not self.header_written and self.doc_header:
            self._raw(self.doc_header)
            self.header_written = True
        self._raw(s)

    def close(self) -> list[Path]:
        if self.f:
            self.f.close()
        stale = self.no + 1
        while self._path(stale).exists():          # önceki çalışmadan kalan fazla parçalar (bizim çıktımız)
            self._path(stale).unlink()
            stale += 1
        return self.paths


def digest(db_path: Path, out_path: Path | None = None, part_mb: float = DIGEST_PART_MB,
           tum: bool = False, log: Callable[[str], None] = print) -> dict:
    """KB'den upgrade ile ilgili içeriği yüksek recall ile seçip parçalı Markdown'a yazar (toplam sınır yok):
    - başlığı kısıt/not/uyumluluk/yenilik/değişiklik/upgrade/migration… olan bölümlerin TAMAMI,
    - 'Note/Important/Hinweis' uyarı kutusunu izleyen paragraf,
    - kural cümlesi içeren paragraflar (not supported / must / requires … + PCS 7 terimi veya versiyon),
    - MLFB / V<x.y> / firmware / SP / Upd geçen tablo satırları.
    `tum=True`: PCS 7 / WinCC / S7 ile ilgili dokümanların bütün metni. İlgisiz doküman sadece index'te.
    Deterministik (dosya yolu + sayfa sırası, zaman damgası yok). Index CSV her dokümanı listeler."""
    import csv

    db_path = Path(db_path)
    base = Path(out_path) if out_path else Path(DIGEST_NAME)
    con = sqlite3.connect(_ro_uri(db_path), uri=True)
    try:
        docs = {r[0]: r[1:] for r in con.execute(
            "SELECT id, path, file_name, doc_title, product_version, pages, quality FROM docs")}
        # Tekrar sayfalar (build'de tek FTS satırı) page_refs ile HER dokümana bağlanır; pasajlar dosya yolu
        # sırasında ilk dokümana yazılır, sonrakilerde 'duplicate_passages' olarak sayılır.
        by_doc: dict[int, list[tuple[int, int, str]]] = {}
        row_of: dict[str, tuple[int, str]] = {}
        for rowid, h, kind in con.execute("SELECT rowid, content_hash, page_kind FROM pages"):
            row_of[h] = (rowid, kind)
        for h, doc_id, page in con.execute("SELECT content_hash, doc_id, page FROM page_refs"):
            if doc_id in docs and h in row_of:
                by_doc.setdefault(doc_id, []).append((int(page), row_of[h][0], row_of[h][1]))
        del row_of
        meta = dict(con.execute("SELECT key, value FROM meta"))
        preamble = [
            f"Kaynak KB: {db_path.name} (build {meta.get('built_at', '?')}), {len(docs)} doküman. "
            + ("Mod: --tum (ilgili dokümanların tüm metni)." if tum else
               "Seçim: kısıt/not/uyumluluk/yenilik/upgrade bölümleri (tamamı), uyarı kutuları, kural cümleleri, "
               "MLFB/versiyon/firmware satırları."),
            "Etiketler: [s. N] PDF sayfası, [bölüm N] Markdown chunk; 'bölüm: …' = başlığı eşleşen bölüm, "
            "'tablo' = MLFB/versiyon satırları. Otomatik seçim: teyit edilmeli. Tekrar eden pasajlar bir kez yazılır.",
        ]
        writer = _PartWriter(base, int(part_mb * (1 << 20)), preamble)
        seen: set[str] = set()
        index_rows = []
        dup = 0
        for doc_id in sorted(docs, key=lambda d: (docs[d][0], d)):
            path, file_name, title, version, pages_total, quality = docs[doc_id]
            rows = sorted(by_doc.get(doc_id, []))
            relevant = bool(DIGEST_RELEVANCE.search(f"{file_name} {title or ''}"))     # klasör adı sayılmaz
            texts: list[tuple[int, str, str]] = []
            for page, rowid, kind in rows:
                t = con.execute("SELECT text FROM pages WHERE rowid=?", (rowid,)).fetchone()
                t = (t[0] if t else "") or ""
                relevant = relevant or bool(DIGEST_RELEVANCE.search(t))
                texts.append((page, kind, t))
            counts = {"section": 0, "rule": 0, "table": 0, "all": 0}
            doc_dup = 0
            pages_kept: set[int] = set()
            parts_used: set[int] = set()
            if relevant and texts:
                info = [x for x in (version,) if x]
                if quality == QUALITY_LOW:
                    info.append(QUALITY_LOW_TEXT)
                hdr = f"## {file_name}" + (f" ({', '.join(info)})" if info else "") + "\n"
                hdr += (f"_{title}_ — `{path}`" if title else f"`{path}`") + "\n\n"
                writer.start_doc(hdr)
                sel = _DocSelector()
                for page, kind, t in texts:
                    tag = "s." if kind == "page" else "bölüm"
                    if tum:
                        body = "\n".join(l.rstrip() for l in t.splitlines() if l.strip())
                        if body.strip():
                            key = content_hash(body)
                            if key in seen:
                                dup += 1
                                doc_dup += 1
                                continue
                            seen.add(key)
                            writer.write(f"### [{tag} {page}]\n\n{body}\n\n")
                            counts["all"] += 1
                            pages_kept.add(page)
                            parts_used.add(writer.no)
                        continue
                    for s in sel.page(page, t):
                        key = hashlib.sha1(normalize_page_text(_fold(s.text)).encode("utf-8")).hexdigest()
                        if key in seen:
                            dup += 1
                            doc_dup += 1
                            continue
                        seen.add(key)
                        lab = ""
                        if s.kind == "section":
                            lab = f", {'uyarı' if s.label.startswith('!') else 'bölüm'}: {s.label.lstrip('!')}"
                        elif s.kind == "table":
                            lab = ", tablo"
                        writer.write(f"- [{tag} {page}{lab}] {s.text}\n")
                        counts[s.kind] += 1
                        pages_kept.add(page)
                        parts_used.add(writer.no)
                if writer.header_written:
                    writer.write("\n")
            index_rows.append([file_name, path, version or "", "evet" if relevant else "hayır",
                               pages_total or 0, len(pages_kept), sum(counts.values()), counts["section"],
                               counts["rule"], counts["table"], counts["all"], doc_dup,
                               " ".join(f"{n:02d}" for n in sorted(parts_used))])
    finally:
        con.close()
    if writer.f is None:          # hiç pasaj yok: yine de tek parça yaz (boş değil, açıklamalı)
        writer._open()
        writer._raw("_Seçilen pasaj yok._\n")
    paths = writer.close()

    index_path = base.with_name(DIGEST_INDEX_NAME)
    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc", "path", "version", "relevant", "pages_total", "pages_kept", "passages",
                    "section_passages", "rule_passages", "table_passages", "full_pages",
                    "duplicate_passages", "parts"])
        w.writerows(index_rows)
    kept_docs = sum(1 for r in index_rows if r[6])
    stats = {"parts": [str(p) for p in paths], "index": str(index_path), "docs": len(docs),
             "docs_kept": kept_docs, "passages": sum(r[6] for r in index_rows), "duplicates": dup,
             "irrelevant_docs": sum(1 for r in index_rows if r[3] == "hayır"),
             "bytes": sum(p.stat().st_size for p in paths)}
    log(f"Özet: {len(paths)} parça ({_fmt_mb(stats['bytes'])}), {kept_docs}/{len(docs)} doküman, "
        f"{stats['passages']} pasaj (tekrar {dup}, ilgisiz {stats['irrelevant_docs']}) -> "
        f"{paths[0].parent}; index: {index_path}")
    return stats


# --------------------------------------------------------------------------- CLI
def _resolve_db(explicit: Path | None) -> Path:
    if explicit:
        return Path(explicit)
    try:
        from . import settings
        found = settings.find_kb()
        if found:
            return Path(found)
    except Exception:  # noqa: BLE001
        pass
    return default_db()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pcs7_analyzer kb",
                                 description="Offline Siemens doküman bilgi tabanı (SQLite FTS5)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="arşivi (klasör veya .zip) artımlı indeksle")
    b.add_argument("--root", required=True, type=Path, help="doküman arşivi: klasör veya .zip (salt okunur)")
    b.add_argument("--db", type=Path, default=None,
                   help="veritabanı (varsayılan: ayar klasörü/kb.sqlite, analiz otomatik bulur)")
    b.add_argument("--pdftotext", default=None, help="pdftotext.exe yolu")
    b.add_argument("--all", action="store_true", dest="all_files",
                   help="INCLUDE_TOP_PATTERNS'ı yok say, her klasörü tara (EXCLUDE_PATTERNS geçerli)")
    b.add_argument("--rebuild", action="store_true", help="mevcut KB'yi silip baştan oluştur")
    b.add_argument("--progress-every", type=int, default=PROGRESS_EVERY, help="her N dosyada ilerleme")
    s = sub.add_parser("search", help="ara")
    s.add_argument("query")
    s.add_argument("--db", type=Path, default=None)
    s.add_argument("--target", default=None, help="hedef sürüm, ör. V10.0SP2")
    s.add_argument("--limit", type=int, default=3)
    s.add_argument("--json", action="store_true", help="JSON çıktı")
    d = sub.add_parser("digest", help="upgrade ile ilgili kural adayı pasajları tek dosyaya yaz")
    d.add_argument("--db", type=Path, default=None)
    d.add_argument("-o", "--out", type=Path, default=Path(DIGEST_NAME),
                   help=f"çıktı adı (varsayılan {DIGEST_NAME} -> kb_ozet_01.md, _02 … + {DIGEST_INDEX_NAME})")
    d.add_argument("--part-mb", type=float, default=DIGEST_PART_MB,
                   help=f"parça başına üst sınır (MB, varsayılan {DIGEST_PART_MB:g}); toplam sınır yok")
    d.add_argument("--tum", action="store_true", help="PCS 7/WinCC/S7 dokümanlarının TÜM metni (parçalı)")
    a = ap.parse_args(argv)

    if a.cmd == "build":
        try:
            stats = build(a.root, a.db, pdftotext=a.pdftotext, all_files=a.all_files, rebuild=a.rebuild,
                          progress_every=a.progress_every)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as e:
            print(f"Hata: {e}", file=sys.stderr)
            return 2
        for u in stats["unknown"][:30]:
            print(f"  ? {u}")
        if len(stats["unknown"]) > 30:
            print(f"  … +{len(stats['unknown']) - 30} kayıt (tamamı: {REPORT_NAME})")
        return 0

    db = _resolve_db(a.db)
    if not db.is_file():
        print(f"Veritabanı yok: {db} (önce 'build')", file=sys.stderr)
        return 2
    if a.cmd == "digest":
        try:
            digest(db, a.out, a.part_mb, tum=a.tum)
        except (OSError, sqlite3.Error) as e:
            print(f"Hata: {e}", file=sys.stderr)
            return 2
        return 0
    refs = search(db, a.query, a.target, limit=a.limit)
    if a.json:
        print(json.dumps([r.to_dict() for r in refs], ensure_ascii=False, indent=2))
    elif not refs:
        print("kaynak bulunamadı")
    else:
        for r in refs:
            print(f"- {ref_text(r)}  (score {r.score})\n    {r.snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
