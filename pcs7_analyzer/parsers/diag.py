"""
OS server DIAGNOSTICS arşivi (server fail sonrası müşteriden gelen): SQL ERRORLOG, WinCC diagnose log'ları,
Windows event log'ları (.evtx listelenir, CSV export'ları okunur), WinCC arşiv segment sayısı.

Girdi `Source.entries` + `read_bytes`; sadece okuma. Her bulgu kaynak dosya + confidence taşır
(KANIT = dosyada birebir görüldü, ÇIKARIM = keyword/isimden yorum, VARSAYIM = doğrulanmamış).
**Not:** WinCC diagnose log formatları gerçek örnekle teyit edilmedi; satır parser'ı toleranslıdır
(satır başında timestamp + keyword sınıflandırma).
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MAX_EVENTS = 5000
SEGMENT_WARN = 1000

# --- timestamp (satır başındaki ilk 40 karakterde) -------------------------------------------------
_TS_ISO = re.compile(r"(\d{4})[-/](\d{2})[-/](\d{2})[ T](\d{1,2}):(\d{2}):(\d{2})")
_TS_DE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})[ ,]+(\d{1,2}):(\d{2}):(\d{2})")
_TS_US = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})[ ,]+(\d{1,2}):(\d{2}):(\d{2})(?:[.,]\d+)?\s*([AaPp][Mm])?")

# --- SQL ERRORLOG ----------------------------------------------------------------------------------
_SQL_PREFIX = re.compile(r"^\s*\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s+\S+\s+")
_SQL_ERR = re.compile(r"Error:\s*(\d+),\s*Severity:\s*(\d+)", re.I)
_SQL_MEM = re.compile(r"insufficient system memory|significant part of sql server process memory has been paged out"
                      r"|FAIL_PAGE_ALLOCATION|AppDomain .* (?:is marked for )?unload|out of memory"
                      r"|memory pressure|failed to reserve contiguous memory", re.I)
_SQL_SUSPECT = re.compile(r"database\s+'?\[?([^'\]\s]+)\]?'?.{0,40}?marked\s+SUSPECT", re.I)
_SQL_OTHER = re.compile(r"Login failed|The log for database .* is not available"
                        r"|I/O requests taking longer than 15 seconds|is marked SUSPECT", re.I)
_SQL_PARAM = re.compile(r"^\s*(-[A-Za-z]\S*(?:\s+\S.*)?)\s*$")

# --- WinCC log sınıflandırma (sıra önemli: ilk eşleşen kategori) -----------------------------------
_CATS = [
    ("redundancy", re.compile(r"(?i:redundan|switchover|switch over|umschaltung|\bmaster\b|\bstandby\b|partner)")),
    ("connection", re.compile(r"(?i:connection lost|connection abort|disconnect|verbindung|time-?out|bağlantı)")),
    ("archive", re.compile(r"(?i:archiv|segment|taglogging|alarmlogging)|Alg|ALG|Tlg|TLG")),
    ("license", re.compile(r"(?i:licen|lizenz|lisans)|\bALM\b")),
    ("error", re.compile(r"(?i:error|fehler|failed|fail\b|exception|crash|access violation|hata)")),
]
_PRIO = {"sql_error": 0, "sql_memory": 0, "redundancy": 1, "eventlog": 1, "error": 2, "connection": 2,
         "license": 3, "archive": 4}

_EVT_LEVEL = ("level", "düzey", "ebene", "stufe")
_EVT_DATE = ("date", "tarih", "datum")
_EVT_SOURCE = ("source", "kaynak", "quelle")
_EVT_ID = ("event id", "olay kimliği", "ereignis-id", "ereignis id", "id")
_EVT_BAD = ("error", "critical", "hata", "kritik", "fehler", "kritisch")

_SEG = re.compile(r"(_ALG_|_TLG_|TLG_F_|TLG_S_)", re.I)
_DIAG_LOG_NAME = re.compile(r"^(wincc_|ccalgrtserver|pdlrt|ccredundancy|redundancy)", re.I)


@dataclass
class DiagEvent:
    """Timeline'daki bir satır."""
    ts: str           # ISO 'YYYY-MM-DDTHH:MM:SS' ('' = bilinmiyor)
    source: str       # dosya rel path
    category: str     # sql_error | sql_memory | redundancy | connection | archive | license | error | eventlog
    text: str         # kırpılmış satır (≤ 300)


@dataclass
class DiagFinding:
    title: str
    detail: str
    source: str
    confidence: str   # KANIT | ÇIKARIM | VARSAYIM
    severity: str     # Yüksek | Orta | Düşük


@dataclass
class DiagResult:
    files: dict = field(default_factory=lambda: {k: [] for k in
                                                 ("sql_errorlog", "wincc_log", "evtx", "eventlog_csv")})
    sql: dict = field(default_factory=lambda: {"version": "", "bits": "", "startup_params": [], "errors": Counter(),
                                               "memory_pressure": 0, "suspect_dbs": [], "source": ""})
    events: list[DiagEvent] = field(default_factory=list)
    findings: list[DiagFinding] = field(default_factory=list)
    archive_segments: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    category_counts: Counter = field(default_factory=Counter)   # cap'ten önceki tam sayılar


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def decode_log(data: bytes) -> tuple[str, str]:
    """(metin, kullanılan encoding). BOM -> UTF-16/UTF-8; BOM'suz UTF-16LE sezgisi; utf-8, olmazsa latin1."""
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", "replace"), "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", "replace"), "utf-16-be"
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace"), "utf-8-sig"
    head = data[:2000]
    if len(head) >= 4 and head[1::2].count(0) > len(head) * 0.4:           # BOM'suz UTF-16LE
        return data.decode("utf-16-le", "replace"), "utf-16-le"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin1"), "latin1"


def parse_ts(s: str, anywhere: bool = False) -> str:
    """Satır başındaki (ilk 40 karakter) timestamp -> ISO; bulunamazsa ''."""
    t = s if anywhere else s[:40]
    for rx, order in ((_TS_ISO, "ymd"), (_TS_DE, "dmy"), (_TS_US, "mdy")):
        m = rx.search(t)
        if not m:
            continue
        g = m.groups()
        a, b, c = int(g[0]), int(g[1]), int(g[2])
        y, mo, d = {"ymd": (a, b, c), "dmy": (c, b, a), "mdy": (c, a, b)}[order]
        h, mi, se = int(g[3]), int(g[4]), int(g[5])
        if order == "mdy" and g[6]:
            h = h % 12 + (12 if g[6].lower() == "pm" else 0)
        try:
            return datetime(y, mo, d, h, mi, se).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return ""


def classify_line(line: str) -> str | None:
    for cat, rx in _CATS:
        if rx.search(line):
            return cat
    return None


def is_diag_file(rel: str) -> str | None:
    """Sadece path/isimden tür: sql_errorlog | wincc_log | evtx | eventlog_csv (aday) | archive_segment | None."""
    low = rel.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    parts = low.split("/")[:-1]
    if re.fullmatch(r"errorlog(\.\d+)?", name):
        return "sql_errorlog"
    if name.endswith(".evtx"):
        return "evtx"
    if name.endswith(".csv"):
        return "eventlog_csv"
    if name.endswith((".mdf", ".ldf")) and (_SEG.search(name) or any("archivemanager" in p for p in parts)):
        return "archive_segment"
    if name.endswith((".log", ".txt")) and ("diagnose" in parts or "diagnostics" in parts
                                              or _DIAG_LOG_NAME.match(name)):
        return "wincc_log"
    return None


def segment_folder(rel: str) -> str:
    """Segment dosyasının OS proje klasörü: '.../wincproj/<OS>' varsa o, yoksa üst klasör."""
    parts = rel.split("/")
    for i, p in enumerate(parts[:-1]):
        if p.lower() == "wincproj" and i + 1 < len(parts) - 1:
            return "/".join(parts[:i + 2])
    return "/".join(parts[:-1])


def _ev(ts: str, src: str, cat: str, text: str) -> DiagEvent:
    return DiagEvent(ts, src, cat, " ".join(text.split())[:300])


# ---------------------------------------------------------------------------
# Parser'lar
# ---------------------------------------------------------------------------

def parse_errorlog(text: str, rel: str, res: DiagResult, events: list[DiagEvent]) -> None:
    sql = res.sql
    lines = text.splitlines()
    in_params = False
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        msg = _SQL_PREFIX.sub("", line, count=1)
        ts = parse_ts(line)
        if i < 40 and not sql["version"] and "Microsoft SQL Server" in msg:
            sql["version"], sql["source"] = msg.strip()[:200], rel
            up = msg.upper()
            sql["bits"] = "32" if ("X86" in up and "X64" not in up.split("ON WINDOWS")[0]) else (
                "64" if "X64" in up or "64-BIT" in up else "")
        if re.search(r"startup parameters\s*:", msg, re.I):
            in_params = True
            continue
        if in_params:
            m = _SQL_PARAM.match(msg)
            if m:
                p = m.group(1).strip()
                if p not in sql["startup_params"]:
                    sql["startup_params"].append(p)
                continue
            in_params = False
        m = _SQL_ERR.search(msg)
        if m:
            sql["errors"][(int(m.group(1)), int(m.group(2)))] += 1
            nxt = _SQL_PREFIX.sub("", lines[i + 1], count=1) if i + 1 < len(lines) else ""
            extra = f" | {nxt.strip()}" if nxt.strip() and not _SQL_ERR.search(nxt) else ""
            events.append(_ev(ts, rel, "sql_error", msg.strip() + extra))
            continue
        if _SQL_MEM.search(msg):
            sql["memory_pressure"] += 1
            events.append(_ev(ts, rel, "sql_memory", msg))
            continue
        s = _SQL_SUSPECT.search(msg)
        if s and s.group(1) not in sql["suspect_dbs"]:
            sql["suspect_dbs"].append(s.group(1))
        if _SQL_OTHER.search(msg):
            events.append(_ev(ts, rel, "sql_error", msg))


def parse_wincc_log(text: str, rel: str, events: list[DiagEvent]) -> None:
    for line in text.splitlines():
        if line.strip():
            cat = classify_line(line)
            if cat:
                events.append(_ev(parse_ts(line), rel, cat, line))


def _col(headers: list[str], keys: tuple[str, ...]) -> int | None:
    low = [h.strip().lower() for h in headers]
    for k in keys:
        if k in low:
            return low.index(k)
    for k in keys:
        for i, h in enumerate(low):
            if h.startswith(k):
                return i
    return None


def parse_eventlog_csv(text: str, rel: str, events: list[DiagEvent]) -> Counter | None:
    """Event Viewer CSV export'u ise {source: Error/Critical sayısı}; değilse None."""
    first = text.split("\n", 1)[0]
    try:
        delim = csv.Sniffer().sniff(first, delimiters=";,\t").delimiter
    except csv.Error:
        delim = ","
    rows = csv.reader(io.StringIO(text), delimiter=delim)
    headers = next(rows, [])
    li, di, si = _col(headers, _EVT_LEVEL), _col(headers, _EVT_DATE), _col(headers, _EVT_SOURCE)
    if li is None or di is None or si is None:
        return None
    ii = _col(headers, _EVT_ID)
    bad: Counter = Counter()
    for r in rows:
        if len(r) <= max(li, di, si):
            continue
        level, src = r[li].strip(), r[si].strip()
        if not any(b in level.lower() for b in _EVT_BAD):
            continue
        bad[src] += 1
        rest = [c.strip() for k, c in enumerate(r) if k not in (li, di, si, ii) and c.strip()]
        eid = f" ID {r[ii].strip()}" if ii is not None and ii < len(r) else ""
        events.append(_ev(parse_ts(r[di], anywhere=True), rel, "eventlog",
                          f"{level} {src}{eid}: {' '.join(rest)}"))
    return bad


# ---------------------------------------------------------------------------
# Ana tarama
# ---------------------------------------------------------------------------

def scan_diagnostics(entries, read_bytes, max_bytes_per_file: int = 50_000_000) -> DiagResult:
    """DIAGNOSTICS arşivinin entry listesini tarar; hata dosya bazında uyarıya döner, çökmez."""
    res = DiagResult()
    events: list[DiagEvent] = []
    seg: dict[str, set] = defaultdict(set)
    evt_bad: dict[str, Counter] = {}
    for e in entries:
        kind = is_diag_file(e.rel)
        if kind is None:
            continue
        if kind == "archive_segment":
            seg[segment_folder(e.rel)].add(e.rel.rsplit(".", 1)[0].lower())   # mdf+ldf = 1 segment
            continue
        if kind == "evtx":
            res.files["evtx"].append(e.rel)
            continue
        if e.size > max_bytes_per_file:
            res.warnings.append(f"{e.rel}: {e.size} byte > {max_bytes_per_file}, okunmadı")
            continue
        try:
            text, enc = decode_log(read_bytes(e.rel))
            if kind == "sql_errorlog":
                parse_errorlog(text, e.rel, res, events)
            elif kind == "wincc_log":
                parse_wincc_log(text, e.rel, events)
            else:
                bad = parse_eventlog_csv(text, e.rel, events)
                if bad is None:
                    continue                                    # event log export'u değil (ör. tag CSV)
                evt_bad[e.rel] = bad
            res.files[kind].append(e.rel)
            if "�" in text:
                res.warnings.append(f"{e.rel}: çözülemeyen byte'lar var ({enc}, '�' ile değiştirildi)")
        except Exception as ex:                                  # noqa: BLE001 - dosya bazında yalıtım
            res.warnings.append(f"{e.rel}: okunamadı ({type(ex).__name__}: {ex})")
    res.archive_segments = {k: len(v) for k, v in sorted(seg.items())}
    res.category_counts = Counter(ev.category for ev in events)
    if len(events) > MAX_EVENTS:
        res.warnings.append(f"timeline {len(events)} olay, {MAX_EVENTS} ile sınırlandı (öncelik: SQL error, "
                            f"redundancy, event log)")
        events = sorted(events, key=lambda ev: _PRIO.get(ev.category, 9))[:MAX_EVENTS]
    res.events = sorted(events, key=lambda ev: (ev.ts == "", ev.ts))
    if res.files["evtx"]:
        res.warnings.append(f"evtx okunamadı ({len(res.files['evtx'])} dosya): Event Viewer'dan CSV/TXT olarak "
                            f"export edilmeli (Application, System)")
    res.findings = _findings(res, events, evt_bad)
    return res


def _first_last(evs: list[DiagEvent]) -> str:
    ts = sorted(ev.ts for ev in evs if ev.ts)
    return f"ilk {ts[0]}, son {ts[-1]}" if ts else "zaman bilgisi yok"


def _srcs(evs) -> str:
    return ", ".join(sorted({ev.source for ev in evs}))


def _findings(res: DiagResult, events: list[DiagEvent], evt_bad: dict[str, Counter]) -> list[DiagFinding]:
    out: list[DiagFinding] = []
    sql, logs = res.sql, ", ".join(res.files["sql_errorlog"])
    if sql["bits"] == "32":
        out.append(DiagFinding("SQL Server 32-bit", f"Version satırı: {sql['version']}. 32-bit SQL'de "
                               f"adreslenebilir bellek sınırlı.", sql["source"], "KANIT", "Orta"))
    g = [p for p in sql["startup_params"] if p.lower().startswith("-g")]
    if g:
        out.append(DiagFinding("SQL startup parametresi " + ", ".join(g),
                               "32-bit SQL'de memory-to-leave ayarı; bellek baskısı göstergesi.", logs, "KANIT", "Orta"))
    if sql["memory_pressure"]:
        out.append(DiagFinding("SQL bellek baskısı", f"{sql['memory_pressure']} memory pressure mesajı "
                               f"(insufficient memory / paged out / FAIL_PAGE_ALLOCATION / AppDomain unload).",
                               _srcs(e for e in events if e.category == "sql_memory"), "KANIT", "Orta"))
    hi = {k: n for k, n in sql["errors"].items() if k[1] >= 17}
    if hi:
        lst = ", ".join(f"Error {en} (Severity {sv}) x{n}" for (en, sv), n in sorted(hi.items()))
        io_hint = " 823/824/825 = disk I/O / sayfa bütünlüğü hatası (DBCC CHECKDB önerilir)." \
            if any(en in (823, 824, 825) for en, _ in hi) else ""
        out.append(DiagFinding("SQL Severity ≥ 17 hata", lst + "." + io_hint, logs, "KANIT", "Yüksek"))
    if sql["suspect_dbs"]:
        out.append(DiagFinding("SUSPECT database", "SUSPECT işaretli: " + ", ".join(sql["suspect_dbs"]) + ".",
                               logs, "KANIT", "Yüksek"))
    for cat, title, sev in (("redundancy", "Redundancy / switchover olayları", "Yüksek"),
                            ("connection", "Connection kaybı olayları", "Orta"),
                            ("license", "License mesajları", "Orta")):
        evs = [e for e in events if e.category == cat]
        if evs:
            n = res.category_counts[cat]
            out.append(DiagFinding(title, f"{n} satır (keyword eşleşmesi), {_first_last(evs)}.",
                                   _srcs(evs), "ÇIKARIM", sev))
    for rel, bad in evt_bad.items():
        if bad:
            top = ", ".join(f"{s} x{n}" for s, n in bad.most_common(10))
            out.append(DiagFinding("Event log Error/Critical", f"Source bazında: {top}.", rel, "KANIT", "Orta"))
    if res.files["evtx"]:
        out.append(DiagFinding("evtx okunamadı", "Dosya mevcut, içerik okunmadı (binary). Event Viewer'dan CSV/TXT "
                               "olarak export edilmeli (Application, System).", ", ".join(res.files["evtx"]),
                               "KANIT", "Düşük"))
    for folder, n in res.archive_segments.items():
        if n > SEGMENT_WARN:
            out.append(DiagFinding("Arşiv segment sayısı çok yüksek",
                                   f"{n} segment (dosya adı bazında, mdf+ldf = 1): segment sayısı çok yüksek "
                                   f"(önerilen ~200).", folder, "ÇIKARIM", "Orta"))
    return out


def timeline_window(events: list[DiagEvent], center_ts: str, minutes: int = 30) -> list[DiagEvent]:
    """center_ts (ISO veya desteklenen format) ± minutes içindeki olaylar, zamana göre sıralı."""
    c = parse_ts(center_ts, anywhere=True)
    if not c:
        return []
    mid = datetime.fromisoformat(c)
    lo, hi = (mid - timedelta(minutes=minutes)).isoformat(), (mid + timedelta(minutes=minutes)).isoformat()
    return sorted((e for e in events if e.ts and lo <= e.ts <= hi), key=lambda e: e.ts)
