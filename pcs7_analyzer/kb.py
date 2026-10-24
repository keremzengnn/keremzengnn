"""Offline doküman bilgi tabanı (Siemens manual arşivi -> SQLite FTS5).

Her analyzer bulgusuna 1-3 kısa sayfa referansı ("Kaynak": dosya adı, ürün versiyonu, sayfa) verir.
**Risk kararı vermez**; sadece referans gösterir. Bağımlılık yok (stdlib + sqlite3 FTS5); PDF metni harici
`pdftotext` (poppler) ile alınır, yoksa PDF'ler atlanır. Kaynak klasöre asla yazılmaz.

    python -m pcs7_analyzer.kb build --root <Siemens_Dokumanlar> [--db kb/kb.sqlite] [--pdftotext <exe>]
    python -m pcs7_analyzer.kb search "<metin>" [--db kb/kb.sqlite] [--target V10.0SP2]

Ayrıntılar: docs/spec/kb.md
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

SCHEMA_VERSION = "1"
DEFAULT_DB = Path("kb") / "kb.sqlite"

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


def iter_documents(root: Path) -> Iterable[Path]:
    """Dahil edilen üst klasörlerdeki .pdf/.md/.txt dosyaları (exclude kurallarıyla, sıralı)."""
    root = Path(root)
    for top in sorted(p for p in root.iterdir() if p.is_dir()):
        if not is_included_top(top.name) or is_excluded([top.name]):
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if not _match_any(d, EXCLUDE_PATTERNS))
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if p.suffix.lower() not in DOC_SUFFIXES:
                    continue
                if is_excluded(p.relative_to(root).parts):
                    continue
                yield p


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


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1")


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
    sha1 TEXT
);
CREATE VIRTUAL TABLE pages USING fts5(
    text, heading, doc_id UNINDEXED, page UNINDEXED, page_kind UNINDEXED, content_hash UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE page_refs(
    content_hash TEXT NOT NULL,
    doc_id INTEGER NOT NULL,
    page INTEGER NOT NULL
);
CREATE INDEX page_refs_hash ON page_refs(content_hash);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


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


# --------------------------------------------------------------------------- build
def build(root: Path, db_path: Path, log: Callable[[str], None] = print,
          pdftotext: str | None = None) -> dict:
    """Arşivi baştan indeksler (db geçici dosyaya yazılır, sonunda yerine konur). İstatistik döner."""
    root = Path(root)
    db_path = Path(db_path)
    if not root.is_dir():
        raise FileNotFoundError(f"Kök klasör yok: {root}")
    if _is_within(db_path, root):
        raise ValueError(f"Veritabanı kaynak klasörün içine yazılamaz: {db_path}")
    if not fts5_available():
        raise RuntimeError("Bu Python'un sqlite3 modülünde FTS5 yok")

    exe = find_pdftotext(pdftotext, log)
    stats: dict = {
        "root": str(root), "db": str(db_path), "pdftotext": exe,
        "files_seen": 0, "docs": 0, "pdf_skipped": 0, "pages_total": 0, "pages_indexed": 0,
        "pages_duplicate": 0, "pages_empty": 0, "errors": 0, "unknown": [],
    }
    if exe is None:
        log("Uyarı: pdftotext bulunamadı -> PDF'ler indekslenmeyecek (sadece .md/.txt)")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA_SQL)
        seen_hashes: set[str] = set()
        no_pdf_files: list[str] = []
        for path in iter_documents(root):
            stats["files_seen"] += 1
            rel = str(path.relative_to(root))
            suffix = path.suffix.lower()
            try:
                if suffix == ".pdf":
                    if exe is None:
                        stats["pdf_skipped"] += 1
                        no_pdf_files.append(rel)
                        continue
                    page_texts, kind = pdf_pages(path, exe), "page"
                else:
                    page_texts, kind = text_chunks(_read_text(path))
            except Exception as e:  # noqa: BLE001 - tek dosya hatası build'i durdurmaz
                stats["errors"] += 1
                stats["unknown"].append(f"{rel}: okunamadı ({type(e).__name__}: {e})")
                log(f"Uyarı: {rel} okunamadı: {e}")
                continue

            first = next((t for t in page_texts if t.strip()), "")
            title = find_title(first)
            cur = con.execute(
                "INSERT INTO docs(path, file_name, doc_title, product_version, doc_no, pages,"
                " title_mismatch, sha1) VALUES (?,?,?,?,?,?,?,?)",
                (rel, path.name, title, find_version(path.stem, first), find_doc_no(path.name, first),
                 len(page_texts), int(title_mismatch(path.name, title)), _file_sha1(path)))
            doc_id = cur.lastrowid
            stats["docs"] += 1
            empty: list[int] = []
            for no, text in enumerate(page_texts, start=1):
                stats["pages_total"] += 1
                if not text.strip():
                    empty.append(no)
                    continue
                h = content_hash(text)
                con.execute("INSERT INTO page_refs(content_hash, doc_id, page) VALUES (?,?,?)",
                            (h, doc_id, no))
                if h in seen_hashes:
                    stats["pages_duplicate"] += 1
                    continue
                seen_hashes.add(h)
                con.execute("INSERT INTO pages(text, heading, doc_id, page, page_kind, content_hash)"
                            " VALUES (?,?,?,?,?,?)", (text, page_heading(text), doc_id, no, kind, h))
                stats["pages_indexed"] += 1
            if empty and kind == "page":
                stats["pages_empty"] += len(empty)
                shown = ", ".join(map(str, empty[:20])) + (" …" if len(empty) > 20 else "")
                stats["unknown"].append(f"{rel}: {UNKNOWN_NO_TEXT} (s. {shown})")
            if stats["files_seen"] % 25 == 0:
                log(f"  {stats['files_seen']} dosya, {stats['pages_indexed']} sayfa indekslendi …")
        if no_pdf_files:
            stats["unknown"].append(f"{UNKNOWN_NO_PDFTOTEXT} ({len(no_pdf_files)} dosya)")
            stats["unknown"].extend(f"{f}: {UNKNOWN_NO_PDFTOTEXT}" for f in no_pdf_files[:50])
        meta = {"schema_version": SCHEMA_VERSION, "built_at": datetime.now().isoformat(timespec="seconds"),
                "root": str(root), "pdftotext": exe or "", "stats": json.dumps(stats, ensure_ascii=False)}
        con.executemany("INSERT INTO meta(key, value) VALUES (?,?)", meta.items())
        con.commit()
    finally:
        con.close()
    os.replace(tmp, db_path)
    log(f"KB hazır: {stats['docs']} doküman, {stats['pages_indexed']} sayfa "
        f"(+{stats['pages_duplicate']} tekrar), {stats['pdf_skipped']} PDF atlandı, "
        f"{stats['pages_empty']} boş sayfa, {stats['errors']} hata -> {db_path}")
    return stats


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
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(
            "SELECT p.text, p.heading, p.doc_id, p.page, p.page_kind, p.content_hash, bm25(pages) AS r,"
            " snippet(pages, 0, '', '', '…', 16)"
            " FROM pages p WHERE pages MATCH ? ORDER BY r LIMIT ?", (expr, max(limit * 5, 15))).fetchall()
        docs = {r[0]: r[1:] for r in con.execute(
            "SELECT id, path, file_name, doc_title, product_version FROM docs")}
        out: list[KbRef] = []
        seen: set[tuple[str, int]] = set()
        for text, heading, doc_id, page, kind, h, rank, snip in rows:
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
                matched_keys=sum(_token_hit(k, page_words) for k in (_keys or []))))
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


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pcs7_analyzer.kb",
                                 description="Offline Siemens doküman bilgi tabanı (SQLite FTS5)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="arşivi indeksle")
    b.add_argument("--root", required=True, type=Path, help="doküman arşivi kök klasörü (salt okunur)")
    b.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"veritabanı (varsayılan {DEFAULT_DB})")
    b.add_argument("--pdftotext", default=None, help="pdftotext.exe yolu")
    s = sub.add_parser("search", help="ara")
    s.add_argument("query")
    s.add_argument("--db", type=Path, default=DEFAULT_DB)
    s.add_argument("--target", default=None, help="hedef sürüm, ör. V10.0SP2")
    s.add_argument("--limit", type=int, default=3)
    s.add_argument("--json", action="store_true", help="JSON çıktı")
    a = ap.parse_args(argv)

    if a.cmd == "build":
        try:
            stats = build(a.root, a.db, pdftotext=a.pdftotext)
        except (OSError, ValueError, RuntimeError) as e:
            print(f"Hata: {e}", file=sys.stderr)
            return 2
        for u in stats["unknown"][:30]:
            print(f"  ? {u}")
        if len(stats["unknown"]) > 30:
            print(f"  … +{len(stats['unknown']) - 30} kayıt")
        return 0

    if not Path(a.db).is_file():
        print(f"Veritabanı yok: {a.db} (önce 'build')", file=sys.stderr)
        return 2
    refs = search(a.db, a.query, a.target, limit=a.limit)
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
