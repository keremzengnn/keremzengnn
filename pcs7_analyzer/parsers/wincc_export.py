"""
WinCC Configuration Studio export'ları (Tag Management / Alarm Logging -> Export, .txt, UTF-16LE + BOM).

Dosya bölümlerden oluşur:
    <TabloAdı>\\t<çoğul>\\t<tekil>        <- bölüm başı (bir sonraki satır ID satırıysa)
    [ID][n]...                           <- ID satırı: ^\\[[A-Z_0-9]+\\]\\[\\d+\\]
    <kolon başlıkları, tab>              <- sonda \\n/boşluk olabilir -> strip
    <satırlar, tab>                      <- bir sonraki bölüm başına kadar
Tag export: DmConnection, DmTag, DmStructtype, DmStructtag, DmGroup … ; Alarm export: ALG_Alarm.
Kolon adları dil/versiyona göre değişebilir: anahtar kelimeyle, büyük/küçük harf duyarsız eşlenir.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_ID_LINE = re.compile(r"^\[[A-Z_0-9]+\]\[\d+\]")
_IP = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})")
_NONPRINT = re.compile(r"[^ -~]")
_LM = re.compile(r"(?<![A-Za-z])LM_(Matrix|Cause|Effect|Node)", re.I)

# OPC ProgID -> üretici / ürün (ek prompt, bölüm 2)
OPC_VENDORS = {
    "saabtankradar": "Saab / Rosemount TankRadar",
    "daniel.danopchub": "Emerson Daniel",
    "opc.deltav": "Emerson DeltaV",
    "opc.simaticnet": "Siemens SIMATIC NET",
    "opcserver.wincc": "Siemens WinCC",
    "matrikon": "Matrikon",
    "kepware": "Kepware",
}


@dataclass
class Section:
    name: str
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)

    def col(self, *keys: str) -> int | None:
        """İlk eşleşen kolon: tam ad, sonra 'içerir' (büyük/küçük harf duyarsız)."""
        low = [h.lower() for h in self.headers]
        for k in keys:
            if k.lower() in low:
                return low.index(k.lower())
        for k in keys:
            for i, h in enumerate(low):
                if k.lower() in h:
                    return i
        return None

    def values(self, *keys: str) -> list[str]:
        i = self.col(*keys)
        return [r[i].strip() if i is not None and i < len(r) else "" for r in self.rows]


@dataclass
class WinccExport:
    path: str
    os_name: str
    sections: dict[str, Section] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        if "ALG_Alarm" in self.sections:
            return "alarm"
        if "DmTag" in self.sections or "DmConnection" in self.sections:
            return "tag"
        return "?"


def decode_text(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if len(data) > 4 and data[1:2] == b"\x00" and data[3:4] == b"\x00":      # BOM'suz UTF-16LE
        return data.decode("utf-16-le", "replace")
    return data.decode("utf-8", "replace")


def looks_like_export(head: bytes) -> bool:
    """Dosya başına bakarak Configuration Studio export'u mu (DmConnection/DmTag/ALG_… bölüm adı)."""
    t = decode_text(head)[:4000] if head else ""
    return bool(re.search(r"^(Dm[A-Z][A-Za-z]+|ALG_[A-Za-z]+|TLG_[A-Za-z]+)\t", t, re.M)) and bool(_ID_LINE.search(
        "\n".join(t.splitlines()[:40])) or re.search(r"^\[[A-Z_0-9]+\]\[\d+\]", t, re.M))


def parse_export(data: bytes, path: str = "", os_name: str = "") -> WinccExport:
    text = decode_text(data)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    exp = WinccExport(path=path, os_name=os_name)
    starts = [i for i in range(len(lines) - 1) if _ID_LINE.match(lines[i + 1]) and lines[i].strip()]
    for k, s in enumerate(starts):
        name = lines[s].split("\t", 1)[0].strip()
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        if s + 2 >= end:
            continue
        headers = [h.strip() for h in lines[s + 2].split("\t")]
        rows = [ln.split("\t") for ln in lines[s + 3:end] if ln.strip()]
        exp.sections[name] = Section(name, headers, rows)
    if not exp.sections:
        exp.warnings.append(f"{path}: export bölümü bulunamadı (format tanınmadı)")
    return exp


# ---------------------------------------------------------------------------
# Tag / connection
# ---------------------------------------------------------------------------

@dataclass
class Connection:
    name: str
    driver: str
    unit: str
    parameter: str
    kind: str              # named / tcpip / opc / other
    as_label: str = ""
    opc_vendor: str = ""
    ip: str = ""
    tags: int = 0
    struct_tags: int = 0


def classify_connection(name: str, driver: str, unit: str, param: str) -> Connection:
    p = _NONPRINT.sub("", param).strip()
    c = Connection(name, driver.strip(), unit.strip(), p, "other")
    low = p.lower()
    if low.startswith("nc,"):
        c.kind = "named"
        m = re.search(r"(AS\s*\d+)", p, re.I)
        c.as_label = m.group(1).replace(" ", "").upper() if m else ""
    elif "opc" in (driver + unit).lower() or re.match(r"^[A-Za-z][\w]*\.[\w.]+[;,]", p):
        c.kind = "opc"
        progid = re.split(r"[;,]", p)[0].strip()
        c.opc_vendor = next((v for k, v in OPC_VENDORS.items() if progid.lower().startswith(k)), "")
        ip = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", p)
        c.ip = ip.group(1) if ip else ""
    elif _IP.match(p):
        c.kind = "tcpip"
        c.ip = _IP.match(p).group(1)
    if not c.as_label:
        m = re.match(r"(AS\s*\d+)", name, re.I)
        c.as_label = m.group(1).replace(" ", "").upper() if m else ""
    return c


def connections(exp: WinccExport) -> dict[str, Connection]:
    out: dict[str, Connection] = {}
    sec = exp.sections.get("DmConnection")
    if sec:
        names = sec.values("Name")
        drivers = sec.values("Communication driver", "driver")
        units = sec.values("Channel unit", "unit")
        params = sec.values("Connection parameter", "parameter")
        for n, d, u, p in zip(names, drivers, units, params):
            if n:
                out[n] = classify_connection(n, d, u, p)
    tag = exp.sections.get("DmTag")
    if tag:
        for cn in tag.values("Connection"):
            if cn:
                out.setdefault(cn, Connection(cn, "", "", "", "other")).tags += 1
    st = exp.sections.get("DmStructtag")
    if st:
        for cn in st.values("Connection"):
            if cn:
                out.setdefault(cn, Connection(cn, "", "", "", "other")).struct_tags += 1
    return out


def tag_totals(exp: WinccExport) -> dict:
    t = exp.sections.get("DmTag")
    s = exp.sections.get("DmStructtag")
    n_tag = len([n for n in t.values("Name") if n]) if t else 0
    n_st = len([n for n in s.values("Name") if n]) if s else 0
    return {"DmTag": n_tag, "DmStructtag": n_st, "total": n_tag + n_st}


def struct_type_counts(exp: WinccExport) -> Counter:
    """{struct type adı: struct tag sayısı}; kolon yoksa 0."""
    s = exp.sections.get("DmStructtag")
    if not s:
        return Counter()
    return Counter(v for v in s.values("Structure type", "Struct type", "Structuretype", "type") if v)


def sfc_struct_tags(exp: WinccExport) -> int:
    return sum(n for k, n in struct_type_counts(exp).items() if "@sfc_rts" in k.lower())


def lm_usage(exp: WinccExport) -> int:
    """Logic Matrix izi: struct type / struct tag / tag / alarm message tag'lerinde LM_Matrix|Cause|Effect|Node."""
    n = 0
    for sec_name in ("DmStructtype", "DmStructtag", "DmTag"):
        sec = exp.sections.get(sec_name)
        if sec:
            n += sum(1 for r in sec.rows if any(_LM.search(c) for c in r[:4]))
    alg = exp.sections.get("ALG_Alarm")
    if alg:
        n += sum(1 for v in alg.values("Message tag") if _LM.search(v))
    return n


def _tag_map(exp: WinccExport) -> dict[str, tuple[str, str]]:
    t = exp.sections.get("DmTag")
    if not t:
        return {}
    return {n: (c, a) for n, c, a in zip(t.values("Name"), t.values("Connection"), t.values("Address")) if n}


def tag_prefix(name: str) -> str:
    return re.split(r"[/.]", name, 1)[0] if name else ""


# ---------------------------------------------------------------------------
# Alarm
# ---------------------------------------------------------------------------

@dataclass
class Alarm:
    number: int
    message_tag: str
    msg_class: str
    msg_type: str
    group: str
    source: str
    area: str
    event: str


def alarms(exp: WinccExport) -> dict[int, Alarm]:
    sec = exp.sections.get("ALG_Alarm")
    if not sec:
        return {}
    cols = [sec.col(k) for k in ("Number", "Message tag", "Message class", "Message Type", "Message Group",
                                 "Source (ENU)", "Area (ENU)", "Event (ENU)")]
    out = {}
    for r in sec.rows:
        vals = [r[i].strip() if i is not None and i < len(r) else "" for i in cols]
        if not vals[0].isdigit():            # çok satırlı metinlerin bölünmüş parçaları
            continue
        out[int(vals[0])] = Alarm(int(vals[0]), *vals[1:])
    return out


def is_diagnostic(a: Alarm) -> bool:
    """'Generate module drivers' çıktısı (@(n) chart'ları): area'sız, message tag '…#RawEvent' / '@(n)'."""
    return not a.area and ("#rawevent" in a.message_tag.lower() or "@(" in a.message_tag)


def alarm_prefix(a: Alarm) -> str:
    conn = re.split(r"[/]", a.message_tag, 1)[0] if a.message_tag else ""
    words = " ".join(a.event.split()[:2])
    return f"{conn} | {words}".strip(" |")


# ---------------------------------------------------------------------------
# İki OS projesinin karşılaştırılması (ör. ENG <-> SRV1)
# ---------------------------------------------------------------------------

@dataclass
class ExportDiff:
    a: str
    b: str
    conn_only_a: list[str] = field(default_factory=list)
    conn_only_b: list[str] = field(default_factory=list)
    conn_both: list[str] = field(default_factory=list)
    conn_pairs: list[tuple[str, str, str]] = field(default_factory=list)   # (AS, a connection, b connection): aynı AS'e farklı ad
    tags_only_a: Counter = field(default_factory=Counter)      # prefix -> adet
    tags_only_b: Counter = field(default_factory=Counter)
    tags_changed: list[tuple[str, str, str]] = field(default_factory=list)   # (tag, a conn/addr, b conn/addr)
    alarms_only_a: Counter = field(default_factory=Counter)    # grup -> adet
    alarms_only_b: Counter = field(default_factory=Counter)
    alarm_text_diff: list[tuple[int, str, str]] = field(default_factory=list)
    alarm_class_diff: list[tuple[int, str, str]] = field(default_factory=list)
    n_tags_only_a: int = 0
    n_tags_only_b: int = 0
    n_alarms_only_a: int = 0
    n_alarms_only_b: int = 0
    diag_only_a: Counter = field(default_factory=Counter)      # area'sız modül/kanal diagnostic mesajları, AS/connection bazında
    diag_only_b: Counter = field(default_factory=Counter)
    tag_names_only_a: list[str] = field(default_factory=list)  # Excel fark listesi için tek tek öğeler
    tag_names_only_b: list[str] = field(default_factory=list)
    alarm_rows_only_a: list = field(default_factory=list)      # [Alarm]
    alarm_rows_only_b: list = field(default_factory=list)


def compare_exports(a_name: str, a: list[WinccExport], b_name: str, b: list[WinccExport]) -> ExportDiff:
    d = ExportDiff(a_name, b_name)
    ca, cb = {}, {}
    ta, tb = {}, {}
    aa, ab = {}, {}
    for e in a:
        ca.update(connections(e))
        ta.update(_tag_map(e))
        aa.update(alarms(e))
    for e in b:
        cb.update(connections(e))
        tb.update(_tag_map(e))
        ab.update(alarms(e))
    d.conn_both = sorted(set(ca) & set(cb))
    only_ca, only_cb = set(ca) - set(cb), set(cb) - set(ca)
    # Named connection adları OS'e göre farklıdır (AS2_ES / AS2_SRV): aynı AS'e gidenler eş sayılır
    by_as_b = {cb[n].as_label: n for n in only_cb if cb[n].kind == "named" and cb[n].as_label}
    for n in sorted(only_ca):
        c = ca[n]
        if c.kind == "named" and c.as_label in by_as_b:
            d.conn_pairs.append((c.as_label, n, by_as_b.pop(c.as_label)))
    paired_a = {x[1] for x in d.conn_pairs}
    paired_b = {x[2] for x in d.conn_pairs}
    d.conn_only_a = sorted(only_ca - paired_a)
    d.conn_only_b = sorted(only_cb - paired_b)

    def key(conns, name):
        c = conns.get(name)
        return c.as_label if c is not None and c.kind == "named" and c.as_label else name
    only_a, only_b = set(ta) - set(tb), set(tb) - set(ta)
    d.n_tags_only_a, d.n_tags_only_b = len(only_a), len(only_b)
    d.tag_names_only_a, d.tag_names_only_b = sorted(only_a), sorted(only_b)
    d.tags_only_a = Counter(tag_prefix(t) for t in only_a)
    d.tags_only_b = Counter(tag_prefix(t) for t in only_b)
    d.tags_changed = [(t, " ".join(ta[t]), " ".join(tb[t])) for t in sorted(set(ta) & set(tb))
                      if (key(ca, ta[t][0]), ta[t][1]) != (key(cb, tb[t][0]), tb[t][1])]
    oa, ob = set(aa) - set(ab), set(ab) - set(aa)
    d.n_alarms_only_a, d.n_alarms_only_b = len(oa), len(ob)
    d.alarm_rows_only_a = [aa[n] for n in sorted(oa)]
    d.alarm_rows_only_b = [ab[n] for n in sorted(ob)]
    d.alarms_only_a = Counter(alarm_prefix(aa[n]) for n in oa)
    d.alarms_only_b = Counter(alarm_prefix(ab[n]) for n in ob)
    d.diag_only_a = Counter(re.split(r"[/]", aa[n].message_tag, 1)[0] or "?" for n in oa if is_diagnostic(aa[n]))
    d.diag_only_b = Counter(re.split(r"[/]", ab[n].message_tag, 1)[0] or "?" for n in ob if is_diagnostic(ab[n]))
    for n in sorted(set(aa) & set(ab)):
        if aa[n].event != ab[n].event:
            d.alarm_text_diff.append((n, aa[n].event, ab[n].event))
        if aa[n].msg_class != ab[n].msg_class:
            d.alarm_class_diff.append((n, aa[n].msg_class, ab[n].msg_class))
    return d


def assign_os(filename: str, os_names: list[str]) -> str:
    """Dosya adındaki OS projesi adı (tam token) -> OS; bulunmazsa dosya adı kökü."""
    stem = Path(filename).stem
    tokens = re.split(r"[^A-Za-z0-9()]+", stem)
    for n in sorted(os_names, key=len, reverse=True):
        if n and (n in tokens or re.search(rf"(^|[^A-Za-z0-9]){re.escape(n)}([^A-Za-z0-9]|$)", stem, re.I)):
            return n
    return tokens[0] if tokens else stem


def by_os(exports: list[WinccExport]) -> dict[str, list[WinccExport]]:
    out = defaultdict(list)
    for e in exports:
        out[e.os_name].append(e)
    return dict(out)
