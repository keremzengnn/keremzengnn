"""
Rapor: Analysis -> doküman modeli -> HTML / Markdown / JSON (Word: word.py).

Doküman yapısı son rapor şablonunu izler:
  ÖZET        Sonuç başlığı, sonuç paragrafı, Tablo 1 (Konu / Durum / Not)
  PROJE ENVANTERİ  Proje bilgileri (maddeler), Tablo 2 AS envanteri, Tablo 3 OS yapısı, Tablo 4 Yazılım içeriği
  RİSKLER     Zorluklar (Tablo 5: Konu / Etki / Açıklama, AS bazında gruplu)
  Referans dokümanlar
  (full=True: + Teklif öncesi netleşmesi gerekenler + Ek A/B detaylar; HTML/Markdown çalışma raporu)
Metinde **kalın** işaretlemesi kullanılabilir; tablo hücresinde satır sonu = yeni paragraf.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from .analyze import Analysis, author_version, staged_path_from
from .checks import CHECKS
from .model import Confidence, Finding, Severity

# ---------------------------------------------------------------------------
# Doküman modeli
# ---------------------------------------------------------------------------


@dataclass
class Topline:
    text: str


@dataclass
class Heading:
    level: int
    text: str


@dataclass
class Para:
    text: str


@dataclass
class Note:
    text: str


@dataclass
class Bullets:
    items: list[str]


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""
    badge_cols: list[int] = field(default_factory=list)   # durum/etki sütunları (HTML rozet, Word kalın)
    widths: list[int] = field(default_factory=list)       # yüzde; boşsa eşit


@dataclass
class ReportMeta:
    author: str = ""
    department: str = ""
    date: str = field(default_factory=lambda: date.today().isoformat())
    customer: str = ""        # kapak üst satırı, ör. "POLİPORT & POLİSAN7"
    classification: str = "Restricted"


STATUS_OK = "Uygun"
STATUS_ATTN = "Dikkat"
STATUS_DETAIL = "Detaylı İnceleme"
STATUS_CHANGE = "Değiştirilmeli"
STATUS_NOT_CHECKED = "Kontrol edilmedi"
STATUS_CONFIRM = "Teyit edilmeli"

REFERENCES = [
    ["[1]", "SIMATIC PCS 7 Software update V10.0 SP2, Service Manual", "A5E52547272-AD", "06/2026"],
    ["[2]", "SIMATIC PCS 7 Released Modules (V10.0 SP2), List Manual", "A5E52547920-AD", "07/2026"],
    ["[3]", "SIMATIC PCS 7 Basis Library Readme V10.0 SP2 (Online)", "A5E55678980-AA", "07/2026"],
    ["[4]", "SIMATIC PCS 7 Software update with utilization of new functions V9.1, Service Manual", "A5E50318285-AA", "02/2021"],
    ["[5]", "SIMATIC PCS 7 Advanced Process Library Readme V10.0 SP2 (Online)", "A5E55664721-AA", "2026"],
]

GENERIC_OPEN_ITEMS = [
    "PC hardware ve lisans envanteri (ES / OS server / client / Web / PH)",
    "AS bazında izin verilen duruş süreleri",
    "NetPro bağlantıları ve PC station konfigürasyonları",
    "Arşiv yapısı (PH / CAS / harici arşiv)",
    "OS PC'lerindeki 3rd party yazılımlar",
    "SIMATIC Logon / domain yapısı",
]

_SEV_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH]

# Zorluklar tablosu gruplaması: check id -> (grup etiketi, sıra). {as} = bulgunun AS'i.
GROUPS = {
    "HW_RELEASED": ("AS hardware", 10),
    "LIB_F_SYSTEM": ("{as} F-System", 20), "HW_F_EXPORT_MISSING": ("{as} F-System", 20),
    "AS_SIZE": ("{as} opsiyonları", 30), "LIB_LOGIC_MATRIX": ("{as} opsiyonları", 30), "LIB_SFC": ("{as} opsiyonları", 30),
    "LIB_MODBUS_TCP": ("{as} opsiyonları", 30), "LIB_PCS7_V71": ("{as} opsiyonları", 30),
    "LIB_MIXED_VERSIONS": ("{as} opsiyonları", 30), "IM_DRV": ("{as} opsiyonları", 30),
    "LIB_INTERFACE": ("Block interface değişiklikleri", 45), "HW_BOX_RTX": ("AS hardware", 10),
    "LIB_STD_LIB": ("Eski PCS 7 Standard Library", 35),
    "LIB_APL_V8": ("Library update (APL)", 40),
    "BLK_CUSTOM": ("Custom block'lar", 50), "COMM_AS_AS": ("Custom block'lar", 50),
    "BLK_SYMBOL_MISMATCH": ("Custom block'lar", 50), "BLK_UNUSED": ("Custom block'lar", 50),
    "OS_CUSTOM_TYPICALS": ("OS migration", 60), "OS_OPC": ("OS migration", 60), "OS_MIGRATION_VOLUME": ("OS migration", 60),
    "CONS_ES_SERVER": ("ENG / SRV / Client tutarlılığı", 70), "CONS_CLIENTS": ("ENG / SRV / Client tutarlılığı", 70),
    "CONS_BACKUP_DATES": ("ENG / SRV / Client tutarlılığı", 70), "WINCC_DIFF": ("ENG / SRV / Client tutarlılığı", 70),
    "OPC_3RD_PARTY": ("3rd party OPC", 72), "OS_CONN_REDUNDANCY": ("OS bağlantısı (redundans)", 74),
    "SFC_VISU": ("SFC görselleştirme", 76), "ARCHIVES": ("Arşivler", 86),
    "LICENSES": ("Lisanslar", 80),
    "CAS_PH": ("Arşiv (CAS / PH)", 85),
    "HW_GSD_3RD_PARTY": ("3rd party GSD", 90),
    "LIB_MASTERDATA_DELETE": ("Diğer notlar", 99), "OS_PO_INCREASE": ("Diğer notlar", 99),
    "AS_STOP_NO_TCIR": ("Diğer notlar", 99),
}
_CONS_PREFIX = {"CONS_ES_SERVER": "OS projeleri", "CONS_CLIENTS": "Client'lar", "CONS_BACKUP_DATES": "Backup'lar",
                "WINCC_DIFF": "Tag / alarm"}

SLAVE_FAMILY = [
    (r"^6ES7 ?152-", "ET 200iSP"), (r"^6ES7 ?153-", "ET 200M"), (r"^6ES7 ?151-", "ET 200S"),
    (r"^6ES7 ?155-", "ET 200SP / ET 200M"), (r"^6ES7 ?157-", "DP/PA Link"), (r"^PAYLINK", "Y-Link / PA Link"),
    (r"^6ES7 ?154-", "ET 200pro"), (r"^6SL3", "SINAMICS"), (r"^6ES7 ?15[0-9]-", "ET 200"),
]


def tr_upper(s: str) -> str:
    return s.replace("i", "İ").replace("ı", "I").upper()


def _fmt_list(items, n=6) -> str:
    items = [str(i) for i in items]
    if not items:
        return "-"
    s = ", ".join(items[:n])
    return s + (f" … (+{len(items) - n})" if len(items) > n else "")


def _b(lst):
    return [x.rsplit("/", 1)[-1] for x in lst]


def _sev_range(fs: list[Finding]) -> str:
    sv = sorted({f.severity for f in fs}, key=_SEV_ORDER.index)
    return sv[0].value if len(sv) == 1 else f"{sv[0].value}–{sv[-1].value}"


def _worst(fs: list[Finding]) -> Severity:
    return max((f.severity for f in fs), key=_SEV_ORDER.index)


# ---------------------------------------------------------------------------
# Bölüm içerikleri
# ---------------------------------------------------------------------------

def group_findings(an: Analysis) -> list[tuple[str, list[Finding]]]:
    groups: dict[str, list[Finding]] = defaultdict(list)
    order: dict[str, tuple] = {}
    for f in an.findings:
        label, o = GROUPS.get(f.check_id, (f.title, 95))
        if "{as}" in label:
            label = label.format(**{"as": f.scope or "Genel"})
        groups[label].append(f)
        order[label] = (o, label)
    return sorted(groups.items(), key=lambda kv: (-_SEV_ORDER.index(_worst(kv[1])), order[kv[0]]))


def _finding_text(f: Finding, group: str) -> str:
    d = f.detail
    if f.scope and group.startswith(f.scope + " ") and d.startswith(f.scope + ": "):
        d = d[len(f.scope) + 2:]
        d = d[:1].upper() + d[1:]
    if f.check_id in _CONS_PREFIX:
        d = f"**{_CONS_PREFIX[f.check_id]}:** {d}"
    if f.confidence is Confidence.LOW and "teyit" not in d.lower():
        d += " (teyit edilmeli)"
    return d


def decision(an: Analysis) -> tuple[str, str]:
    """(başlık, son cümle)"""
    blocking = [f for f in an.findings if f.blocking]
    if blocking:
        return ("Sonuç: Proje mevcut haliyle upgrade edilemez",
                "Upgrade'i engelleyen konular: " + "; ".join(f.detail for f in blocking) + ".")
    if not an.pcs7_family:
        return ("Sonuç: Mevcut versiyon tespit edilemedi",
                "Versiyon teyit edildikten sonra değerlendirme tamamlanmalı.")
    if any(f.severity is Severity.HIGH for f in an.findings):
        return ("Sonuç: Proje upgrade edilebilir, zorluklar var",
                "Upgrade'i engelleyen bir blok, library veya hardware bulunmadı; yüksek etkili konular aşağıda listelenmiştir.")
    return ("Sonuç: Proje upgrade edilebilir", "Upgrade'i engelleyen bir blok, library veya hardware bulunmadı.")


def version_note(fam: str) -> str:
    """Mevcut versiyona göre [1, 4.3] ve dokümantasyon tablosundaki kurallar."""
    m = re.match(r"V(\d+)\.(\d+)", fam or "")
    if not m:
        return ""
    major, minor = int(m.group(1)), int(m.group(2))
    notes = []
    if (major, minor) < (9, 1):
        notes.append("V9.1'den eski PCS 7 software'i doğrudan güncellenemez; PC'ler desteklenen OS ile sıfırdan kurulur [1, Bölüm 4.3].")
    if (major, minor) >= (9, 0):
        notes.append("Proje V9.0 SP3 ve üzeriyse AS library update'siz (AS STOP'suz) update mümkün [1] (SP seviyesi teyit edilmeli).")
    return " ".join(notes)


def _mp_phrase(an: Analysis) -> str:
    n = len({Path(m).stem for m in an.discovery.multiprojects})
    return {0: "Proje", 1: "Multiproject", 2: "İki multiproject de"}.get(n, f"{n} multiproject de")


def _summary_rows(an: Analysis, by_group: list[tuple[str, list[Finding]]]) -> list[list[str]]:
    fam = an.pcs7_family
    path = staged_path_from(fam)
    tgt = an.target.replace("SP", " SP")
    by_id: dict[str, list[Finding]] = defaultdict(list)
    for f in an.findings:
        by_id[f.check_id].append(f)
    nc = dict(an.not_checked)
    rows = []
    if fam:
        note = (f"{fam} → {' → '.join(path)} (iç prosedür).\nDoğrudan geçiş manual'a göre mümkün [1, Bölüm 4.3]."
                + (" V9.1 adımı için projenin V8.2.x olması şart [4]." if "V9.1" in path else ""))
        note += "\n" + version_note(fam)
        low = an.pcs7_family_confidence != Confidence.HIGH.value
        rows.append(["Proje migration", STATUS_CONFIRM if low else STATUS_OK,
                     note + (" Versiyon tek kaynaktan/heuristic tespit edildi, teyit edilmeli." if low else "")])
    else:
        rows.append(["Proje migration", STATUS_CONFIRM, f"Mevcut versiyon tespit edilemedi. Hedef: PCS 7 {tgt}."])

    hw = by_id.get("HW_RELEASED", [])
    if any(f.blocking for f in hw):
        rows.append(["AS hardware (CPU, CP, I/O)", STATUS_CHANGE, next(f.detail for f in hw if f.blocking)])
    elif hw and all(f.severity is Severity.LOW for f in hw):
        rows.append(["AS hardware (CPU, CP, I/O)", STATUS_OK,
                     f"Tüm modüller {tgt} Released Modules listesinde [2]. " + " ".join(f.detail for f in hw)])
    elif hw:
        rows.append(["AS hardware (CPU, CP, I/O)", STATUS_ATTN, next(f.detail for f in hw if f.severity is not Severity.LOW)])
    elif "HW_RELEASED" in nc:
        rows.append(["AS hardware (CPU, CP, I/O)", STATUS_NOT_CHECKED, nc["HW_RELEASED"]])
    else:
        rows.append(["AS hardware (CPU, CP, I/O)", STATUS_OK,
                     f"Tüm modüller {tgt} Released Modules listesinde [2]. Değişim gerekmiyor."])

    for label, fs in by_group:
        if label.endswith(" F-System"):
            note = "F-program ve safety."
            if any(f.check_id == "HW_F_EXPORT_MISSING" for f in fs):
                note += " HW export'ta F-I/O yok, export tekrar alınmalı."
            rows.append([label, STATUS_DETAIL, note])
    for label, fs in by_group:
        if label.endswith(" opsiyonları"):
            ids = {f.check_id for f in fs}
            if not ids - {"LIB_MIXED_VERSIONS"}:
                continue
            asl = label[: -len(" opsiyonları")]
            b = next((x for x in an.block_folders if x.as_label == asl), None)
            feats = [x for x in (b.features if b else []) if x not in ("APL", "Basis", "ELEMENTA", "F-System",
                                                                         "Logic Matrix", "SFC")]
            parts = (["En büyük AS."] if "AS_SIZE" in ids else [])
            if b and "SFC" in b.features:
                visu = [(o.info.name, o.sfc.get("charts", 0)) for o in an.os_projects
                        if o.in_es and o.sfc.get("filled")]
                parts.append("SFC: " + (", ".join(f"{n} chart {o}'de görselleştiriliyor" for o, n in visu)
                                        if visu else f"{b.fb_instances.get(300, 0)} instance") + ".")
            lm = an.lm_status.get(asl)
            if lm:
                parts.append(f"Logic Matrix {lm['status'].split(' (')[0]}.")
            if feats:
                parts.append(", ".join(feats) + ".")
            parts.append("CFC'ler kontrol edilmeli.")
            rows.append([asl, STATUS_ATTN, " ".join(parts)])
    if "LIB_STD_LIB" in by_id:
        rows.append(["Eski Standard Library", STATUS_CHANGE, "Library V7.1 paketleri veya APL'e migration gerekli [1, Bölüm 8.5]."])
    if "LIB_APL_V8" in by_id:
        rows.append(["Library (APL)", STATUS_ATTN, "APL V8.x block'ları: V10.0 SP2 faceplate'leri ile mixed operation yok, "
                                                   "library update zorunlu [1, Bölüm 9.10.4]."])
    if "BLK_CUSTOM" in by_id:
        n = len({f.scope for f in by_id["BLK_CUSTOM"]})
        n_all = len([b for b in an.block_folders if b.counts])
        who = "Tüm AS'lerde" if n == n_all and n > 1 else f"{n} AS'te"
        rows.append(["Custom block'lar", STATUS_ATTN, f"{who} integratör block'ları var. Kullanıldıkları CFC'ler kontrol edilmeli."])
    pairs = [d for d in an.os_diffs if d.kind == "os_pair"]
    if pairs or an.export_diffs:
        names = sorted({f"{d.a_label}/{d.b_label}" for d in pairs} | {f"{d.a}/{d.b}" for d in an.export_diffs})
        extra = []
        for d in an.export_diffs:
            extra.append(f"tag farkı {d.n_tags_only_a:,}/{d.n_tags_only_b:,}, alarm farkı {d.n_alarms_only_a:,}/{d.n_alarms_only_b:,}")
        rows.append([f"{', '.join(names)} OS projeleri", STATUS_ATTN,
                     "İki ayrı OS projesi (ENG, ES üzerinde çalışan tam OS; master/kopya değil) ayrışmış"
                     + (f" ({'; '.join(extra)})" if extra else "") + ". İkisinin de taşınıp taşınmayacağı teyit edilmeli."])
    copies = [f for f in by_id.get("CONS_ES_SERVER", []) if "OS PC kopyası" in f.detail]
    if copies:
        rows.append(["ES ↔ OS PC kopyası", STATUS_ATTN, copies[0].detail.split(";")[0] + "."])
    if not pairs and not copies and "CONS_ES_SERVER" in nc:
        rows.append(["ENG / SRV tutarlılığı", STATUS_NOT_CHECKED, nc["CONS_ES_SERVER"]])
    if "CONS_CLIENTS" in by_id:
        rows.append(["Client tutarlılığı", STATUS_ATTN,
                     f"Client'lar isim setine göre {len(an.client_groups)} gruba ayrılıyor; farklı gruplar teyit edilmeli."])
    if "OPC_3RD_PARTY" in by_id:
        vend = sorted({cn.opc_vendor or cn.name for w in an.wincc.values() for cn in w.connections if cn.kind == "opc"})
        rows.append(["3rd party OPC", STATUS_ATTN, f"{_fmt_list(vend, 4)}; hedef versiyonda uyum ve kapsam teyit edilmeli."])
    if "OS_CONN_REDUNDANCY" in by_id:
        rows.append(["OS bağlantısı", STATUS_ATTN, by_id["OS_CONN_REDUNDANCY"][0].detail.split(". ")[0] + "."])
    if "CAS_PH" in by_id:
        rows.append(["Arşiv (CAS / PH)", STATUS_ATTN, "CAS desteklenmiyor → Process Historian (teyit edilmeli)."])
    return rows


def _version_bullets(an: Analysis) -> list[str]:
    fam = an.pcs7_family
    step7 = sorted({re.sub(r" ->.*| \(.*", "", v.value) for v in an.versions if v.item.startswith("STEP 7")})
    wincc = sorted({re.sub(r" \(build.*", "", v.value) for v in an.versions if v.item == "WinCC"})
    inner = ", ".join([f"STEP 7 {s}" for s in step7] + wincc)
    libs = [v for v in an.versions if v.item in ("APL", "Basis Library", "S7 F Systems Failsafe Blocks")]
    lib_txt = "; ".join(f"{v.item} {v.value}" for v in libs)
    items = []
    head = f"PCS 7 {fam}" if fam else "PCS 7 versiyonu tespit edilemedi"
    items.append(f"**Versiyon:** {head}" + (f" ({inner})" if inner else "") + "."
                 + (f" Block klasörlerindeki library'ler: {lib_txt}." if lib_txt else ""))
    mps = defaultdict(set)
    for b in an.block_folders:
        if b.counts:
            mps[an.mp_of(b.info.project)].add(b.as_label)
    if an.discovery.multiprojects:
        items.append("**Multiproject'ler:** " + ", ".join(
            f"{tr_upper(mp) if mp != '-' else '-'} ({len(a)} AS)" for mp, a in sorted(mps.items())) or
                     "**Multiproject'ler:** " + _fmt_list([Path(m).stem for m in an.discovery.multiprojects]))
    if an.backups:
        items.append("**Farklı tarihli backup'lar:** " + "; ".join(
            f"{b.name}: referans {b.newest_path}" for b in an.backups) + ".")
    pdm = [s.pdm_used for s in an.stations if s.pdm_used is not None]
    if pdm:
        items.append("**PDM:** " + ("kullanılmıyor (tüm HW export'larında PDM_PARAM 0)." if not any(pdm) else
                                    "PDM ile parametrelenmiş cihaz var: " + ", ".join(s.name for s in an.stations if s.pdm_used) + "."))
    m = an.manual
    lic = [f"AS RT PO {m.as_rt_po}" if m.as_rt_po else "AS RT PO: eksik", f"OS PO {m.os_po}" if m.os_po else "OS PO: eksik",
           f"archive tag {m.archive_tags}" if m.archive_tags else "archive tag: eksik"]
    items.append("**Lisans ihtiyacı (PCS 7 License Information, manuel):** " + ", ".join(lic)
                 + ". V10 update'inde OS RT PO sayısı artabilir [1, Bölüm 4.3]; mevcut ALM key'leri ile karşılaştırılmalı.")
    if an.stations:
        h = [s for s in an.stations if any("-5H" in o.upper() or "5H" in n.upper() for o, _, n in s.cpus)]
        n_cpu = sum(len(s.cpus) for s in an.stations)
        if h and len(h) == len(an.stations):
            items.append(f"**Tüm AS'ler S7-400H** (redundant). Toplam {len(h)} H-system, {n_cpu} CPU (HW Config export).")
        else:
            items.append(f"**AS:** {len(an.stations)} station ({len(h)} H-system), {n_cpu} CPU.")
    return items


def _slave_family(order: str, name: str) -> str:
    for pat, fam in SLAVE_FAMILY:
        if re.match(pat, order.strip(), re.I):
            return fam
    return name or order


def _as_rows(an: Analysis) -> list[list[str]]:
    rows = []
    for s in sorted(an.stations, key=lambda s: _natkey(s.name)):
        cpu = Counter(f"{(n or o).strip()} {fw}".strip() for o, fw, n in s.cpus)
        cp = Counter(f"{(n or o).strip()} {fw}".strip() for o, fw, n in s.cps)
        comm = [k for k in cpu] + [k + (f" ({v // 2} çift)" if v > 2 and v % 2 == 0 else (f" ×{v}" if v > 2 else ""))
                                  for k, v in cp.items()]
        fam = Counter()
        for k, n in s.slaves.items():
            m = re.match(r"(.*) \((.*)\)$", k)
            fam[_slave_family(m.group(2), m.group(1)) if m else k] += n
        lines = [", ".join(f"{k} ×{v}" for k, v in fam.items())] if fam else []
        gsd = Counter()
        for k, n in s.gsd.items():
            m = re.match(r"(.*) \((.*)\)$", k)
            gsd[(m.group(1), m.group(2)) if m else (k, "")] += n
        for (nm, g), n in gsd.items():
            lines.append(f"{nm} ×{n} ({'GSD' if g.upper().endswith(('.GSD', '.GSE', '.GSG')) else g})")
        b = next((x for x in an.block_folders if x.info.project == s.project and x.counts), None)
        if b and "F-System" in b.features:
            lines.append("F-System")
        rows.append([s.name, tr_upper(an.mp_of(s.project)) if s.project != "-" else "-",
                     ", ".join(comm) or "-", "\n".join(l for l in lines if l) or "-"])
    return rows


def _natkey(s: str):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", s)]


def _os_rows(an: Analysis) -> list[list[str]]:
    by_mp: dict[str, list] = defaultdict(list)
    for o in an.os_projects:
        if o.in_es:
            by_mp[an.mp_of(o.info.project)].append(o)
    rows = []
    for mp, ops in sorted(by_mp.items()):
        servers = [o for o in ops if o.role == "server"]
        standby = [o for o in ops if o.role == "standby"]
        clients = [o for o in ops if o.role == "client"]
        eng = [o for o in ops if o.role == "es"]
        refs = [o for o in ops if o.role == "reference"]
        parts = []
        for s in servers:
            parts.append(("Redundant OS server" if standby else "OS server") + f" ({s.info.name}"
                         + (f" + {', '.join(x.info.name for x in standby)})" if standby else ")"))
        if clients:
            groups = len(an.client_groups)
            parts.append(f"{len(clients)} OS client" + (f" ({groups} içerik grubu)" if groups > 1 else ""))
        odd = [o.info.name for o in clients if o.role_note]
        if odd:
            parts.append(f"rolü teyit: {', '.join(odd)}")
        if eng:
            parts.append(", ".join(f"{o.info.name} (ES + tam OS)" for o in eng))
        else:
            parts.append("ES")
        if refs:
            parts.append(f"referans (client sayılmadı): {', '.join(o.info.name for o in refs)}")
        base = servers or ops
        pics = sum(o.pictures.get("custom", 0) for o in base)
        scripts = sorted({s.rsplit("/", 1)[-1].rsplit(".", 1)[0] for o in base for s in o.scripts})
        line2 = f"{pics} custom process picture" + (f", VBS global script'ler ({_fmt_list(scripts, 4)})" if scripts else "")
        rows.append([tr_upper(mp) if mp != "-" else "-", ", ".join(parts) + "\n" + line2])
    return rows


def _wincc_rows(an: Analysis) -> list[list[str]]:
    rows = []
    roles = {o.info.name: (o, an.mp_of(o.info.project)) for o in an.os_projects if o.in_es}
    for name, w in sorted(an.wincc.items()):
        mp = roles.get(name, (None, "-"))[1]
        kinds = Counter(c.kind for c in w.connections)
        conn = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
        opc = [f"{c.name} ({c.opc_vendor})" if c.opc_vendor else c.name for c in w.connections if c.kind == "opc"]
        rows.append([tr_upper(mp) if mp != "-" else "-", name, f"{w.total_tags:,}".replace(",", "."),
                     f"{w.alarms:,}".replace(",", "."),
                     f"{len(w.connections)} ({conn})" + (f"\nOPC: {_fmt_list(opc, 4)}" if opc else "")])
    return rows


def prep_list(an: Analysis) -> list[str]:
    """Otomatik upgrade hazırlık listesi (dry-run öncesi ES'e kurulacak/hazırlanacaklar)."""
    ids = {f.check_id for f in an.findings}
    feats = {x for b in an.block_folders for x in b.features}
    items = []
    fam = an.pcs7_family
    items.append(f"İç prosedür yolu: {fam or '?'} → {' → '.join(staged_path_from(fam))} "
                 "(manual V7.1 SP4+ → V10.0 SP2 doğrudan geçişe izin veriyor [1, Bölüm 4.3]).")
    if "F-System" in feats:
        items.append("S7 F Systems + F Configuration Pack (F-block'lar var): hedef versiyonla uyumlu sürüm Compatibility Tool'dan "
                     "teyit edilmeli; HW export F Configuration Pack kurulu PC'den alınmalı.")
    if "PCS 7 Lib V7.1" in feats or "LIB_STD_LIB" in ids:
        items.append("PCS 7 Library V7.1 SP3 Upd4 (ES) + PCS 7 Faceplates V7.1 SP3 Upd1 (ES + tüm OS) [1, Bölüm 8.5] "
                     "(Siemens 'Downloadable previous versions of SIMATIC PCS 7 Libraries', ID 109480136).")
    gsd = sorted({k for s in an.stations for k in s.gsd})
    if gsd:
        items.append("GSD dosyaları: " + _fmt_list(gsd, 6) + " — HW Config → Options → Install GSD File → 'from the STEP 7 "
                     "project' ile projeden alınabilir.")
    if "SFC" in feats:
        items.append("SFC system block'ları (FB245, FB246, FB300, FC240…FC250) güncel SFC library'den offline block "
                     "klasörüne kopyalanmalı, complete compile [1, Bölüm 9.5].")
    if "LIB_MASTERDATA_DELETE" in ids:
        items.append("Master data library'den OB_DIAG, OR_M_16, OR_M_32 silinmeli [1, Bölüm 4.3].")
    if any(o.custom_typicals for o in an.os_projects) or any(o.apc_typicals for o in an.os_projects):
        items.append("Picture object update: custom typicals ve @PCS7TypicalsAPC.pdl ayrıca ele alınmalı [1, Bölüm 9.6.4].")
    if any(o.sfc.get("filled") for o in an.os_projects):
        items.append("OS compile'da 'SFC visualization' işaretlenmeli (SFC görselleştirme verisi var).")
    if "IM_DRV" in ids:
        items.append("IM_DRV block'ları update öncesi system chart'lardan geçici chart'lara taşınmalı [1, Bölüm 6.1].")
    if "LIB_LOGIC_MATRIX" in ids:
        items.append("Logic Matrix: kullanılıyorsa library update zorunlu [1, Bölüm 9.9.4]; kullanılmıyorsa kaldırma kararı.")
    return items


def manual_items(an: Analysis) -> list[list[str]]:
    """[konu, durum/değer] — backup'tan okunamayan, kullanıcıdan istenen bilgiler (ek prompt bölüm 11)."""
    m = an.manual
    rows = [
        ["AS RT PO (PCS 7 License Information)", m.as_rt_po or "eksik"],
        ["OS PO", m.os_po or "eksik"],
        ["Archive tag", m.archive_tags or "eksik"],
        ["Tesisteki lisans key'leri (ALM)", m.license_keys or "eksik"],
        ["PC station listesi (wincproj karşılaştırması)", ", ".join(m.pc_stations) if m.pc_stations else "eksik"],
        ["Compile OS wizard ekranları (area→OS ataması, SFC visualization işareti)", "eksik (backup'tan okunamıyor)"],
        ["Tesis PC'lerinin 'Installed SIMATIC software' listesi (opsiyonel)", "eksik"],
    ]
    q = ["İki OS projesi (ENG ve SRV) de taşınacak mı?" if any(d.kind == "os_pair" for d in an.os_diffs) else "",
         "Modül arızası (diagnostic) alarmları operatör client'larında görünüyor mu?" if any(
             d.diag_only_a or d.diag_only_b for d in an.export_diffs) else "",
         "Rolü belirsiz OS projeleri: " + ", ".join(o.info.name for o in an.os_projects if o.role_note)
         if any(o.role_note for o in an.os_projects) else "",
         "Arşiv (runtime ALG/TLG) taşınacak mı?" if any(o.archives.get("segments") for o in an.os_projects) else "",
         "Logic Matrix kaldırılsın mı?" if any(s["status"].startswith("kurulu, kullanılmıyor")
                                             for s in an.lm_status.values()) else "",
         "3rd party OPC bağlantılarının durumu (hangi server hâlâ kullanılıyor)?" if any(
             c.kind == "opc" for w in an.wincc.values() for c in w.connections) else "",
         "TCP/IP OS bağlantısı hangi AS'e gidiyor (redundans)?" if any(
             c.kind == "tcpip" for w in an.wincc.values() for c in w.connections) else "",
         "AS bazında izin verilen duruş süreleri"]
    rows += [["Müşteri sorusu", x] for x in q if x]
    return rows


def _software_rows(an: Analysis) -> list[list[str]]:
    rows = []
    for b in sorted((b for b in an.block_folders if b.counts), key=lambda b: _natkey(b.as_label)):
        libs = []
        for lib, short in (("APL", "APL"), ("Basis Library", "Basis Library")):
            vs = sorted({author_version(a) or a for a in b.libraries.get(lib, {})})
            if vs:
                libs.append(f"{short} {'/'.join(vs)}")
        if "ELEMENTA" in b.features:
            libs.append("ELEMENTA")
        lines = [", ".join(libs)] if libs else []
        if "SFC" in b.features:
            n = b.fb_instances.get(300, 0)
            lines.append("SFC" + (f" ({n} instance)" if n else ""))
        if "Logic Matrix" in b.features:
            lines.append("Logic Matrix")
        if "Modbus TCP / Siemens add-on" in b.features:
            lines.append("Modbus TCP / Siemens add-on")
        if "PCS 7 Lib V7.1" in b.features:
            lines.append("PCS 7 Library V7.1 COMM")
        if "F-System" in b.features:
            vs = sorted({author_version(a) or a for a in b.libraries.get("S7 F Systems Failsafe Blocks", {})})
            fb = [x.split(" ", 1)[-1] for x in b.f_blocks_from_symbols]
            lines.append("S7 F Systems" + (f", Failsafe Blocks {'/'.join(vs)}" if vs else "")
                         + (f" ({_fmt_list(fb, 5)})" if fb else ""))
        custom = []
        if b.custom_blocks:
            names = [c.name.replace(" (symbol)", "") or f"FB{c.number}" for c in b.custom_blocks]
            n_inst = sum(c.instances for c in b.custom_blocks)
            custom.append(_fmt_list(names, 8) + (f" (toplam {n_inst} instance)" if b.memo_available else ""))
            for c in b.custom_blocks:
                if c.headerless:
                    custom.append(f"FB{c.number} {c.name.replace(' (symbol)', '')} header'sız"
                                  + (" STL" if c.lang.strip("0") == "1" else "") + " block")
            noinst = [c.name or f"FB{c.number}" for c in b.custom_blocks if c.instances == 0 and b.memo_available]
            if noinst:
                custom.append(f"{_fmt_list(noinst, 4)} (instance görünmüyor)")
        for s in b.symbol_only:
            custom.append(f"{s.split(' ', 1)[-1]} symbol table'da var, block klasöründe yok")
        rows.append([b.as_label, "\n".join(lines) or "-", "\n".join(custom) or "—"])
    return rows


def build_document(an: Analysis, full: bool = True) -> list:
    doc: list = []
    by_group = group_findings(an)
    fam = an.pcs7_family
    path = staged_path_from(fam)
    tgt = an.target.replace("SP", " SP")
    t = 0

    def cap(text):
        nonlocal t
        t += 1
        return f"Tablo {t}: {text}"

    # ---------------- ÖZET ----------------
    title, last = decision(an)
    doc.append(Topline("ÖZET"))
    doc.append(Heading(1, title))
    if fam:
        doc.append(Para(f"{_mp_phrase(an)} **PCS 7 {fam}** ailesinde. Software Update manual'ı [1] V7.1 SP4 ve üzeri "
                        f"projelerin doğrudan {tgt}'ye taşınmasına izin veriyor; iç prosedürümüz gereği geçiş "
                        f"**{fam} → {' → '.join(path)}** olacak şekilde kademeli yapılacak. {last}"))
    else:
        doc.append(Para(f"PCS 7 versiyonu backup'tan otomatik tespit edilemedi (HW Config export ve WinCC projesi "
                        f"bulunamadı veya tanınmadı). {last}"))
    doc.append(Table(["Konu", "Durum", "Not"], _summary_rows(an, by_group), cap("Genel değerlendirme"),
                     badge_cols=[1], widths=[26, 16, 58]))
    doc.append(Note("Planlı duruş (AS STOP) ve PC / Windows yenilemesi her upgrade'de zaten kapsamdadır; "
                    "zorluk olarak listelenmemiştir."))

    # ---------------- PROJE ENVANTERİ ----------------
    doc.append(Topline("PROJE ENVANTERİ"))
    doc.append(Heading(1, "Proje bilgileri"))
    doc.append(Bullets(_version_bullets(an)))
    if an.stations:
        doc.append(Table(["AS", "MP", "CPU / haberleşme", "Saha I/O ve cihazlar"], _as_rows(an), cap("AS envanteri"),
                         widths=[10, 16, 37, 37]))
    else:
        doc.append(Para("HW Config bulunamadı (.cfg export veya .s7h yok); AS envanteri çıkarılamadı."))
    if an.os_projects:
        doc.append(Table(["MP", "OS / PC yapısı"], _os_rows(an), cap("OS yapısı"), widths=[20, 80]))
    if an.wincc:
        doc.append(Table(["MP", "OS", "Tag (DmTag + struct)", "Alarm", "Connection"], _wincc_rows(an), cap("WinCC yapısı"),
                         widths=[14, 14, 16, 12, 44]))
    sw = _software_rows(an)
    if sw:
        doc.append(Table(["AS", "Library / opsiyon", "Custom block'lar"], sw, cap("Yazılım içeriği"), widths=[10, 45, 45]))

    # ---------------- RİSKLER ----------------
    doc.append(Topline("RİSKLER"))
    doc.append(Heading(1, "Zorluklar"))
    if by_group:
        rows = []
        for label, fs in by_group:
            texts = [_finding_text(f, label) for f in fs]
            if label == "Custom block'lar":
                texts.insert(0, "Recompile ve fonksiyon testi gerekli. **Bu block'ların kullanıldığı CFC'ler** kontrol edilmeli.")
            rows.append([label, _sev_range(fs), "\n".join(texts)])
        doc.append(Table(["Konu", "Etki", "Açıklama"], rows, cap("Zorluklar ve etkileri"), badge_cols=[1],
                         widths=[22, 12, 66]))
    else:
        doc.append(Para("Bulgu yok."))

    if full:
        doc.append(Heading(1, "Upgrade hazırlık listesi"))
        doc.append(Bullets(prep_list(an)))
        doc.append(Heading(1, "Manuel girişler ve müşteri soruları"))
        doc.append(Table(["Konu", "Değer / soru"], manual_items(an)))
        doc.append(Heading(1, "Teklif öncesi netleşmesi gerekenler"))
        titles = {c.id: c.title for c in CHECKS}
        doc.append(Bullets(list(an.open_items)
                           + [f"Kontrol edilemedi — {titles.get(i, i)}: {why}" for i, why in an.not_checked]
                           + GENERIC_OPEN_ITEMS))

    doc.append(Heading(1, "Referans dokümanlar"))
    doc.append(Table(["No", "Doküman", "Doküman no.", "Tarih"], REFERENCES, widths=[6, 56, 22, 16]))

    if full:
        _appendix(an, doc)
    return doc


def _appendix(an: Analysis, doc: list) -> None:
    d = an.discovery
    doc.append(Heading(1, "Ek A: Detaylar"))
    doc.append(Heading(2, "Versiyon kaynakları"))
    doc.append(Bullets([f"{v.item}: {v.value} — kaynak: {v.source}" + (" (teyit edilmeli)" if v.confidence == Confidence.LOW.value else "")
                        for v in an.versions] or ["-"]))
    if an.stations:
        doc.append(Heading(2, "HW Config detayı"))
        rows = []
        for s in an.stations:
            rows.append([s.name, "; ".join(f"{o} {fw}".strip() for o, fw, _ in s.cpus) or "-",
                         "; ".join(f"{o} {fw}".strip() for o, fw, _ in s.cps) or "-",
                         _fmt_list([f"{k} ×{n}" for k, n in s.slaves.items()], 6), _fmt_list([f"{k} ×{n}" for k, n in s.gsd.items()], 3),
                         str(s.h_sync or "-"), "-" if s.f_capable is None else ("Evet" if s.f_capable else "Hayır"),
                         "-" if s.pdm_used is None else ("Evet" if s.pdm_used else "Hayır"), f"{s.kind}: {s.source}"])
        doc.append(Table(["AS", "CPU", "CP", "Slave'ler", "GSD", "H-Sync", "F-capable", "PDM", "Kaynak"], rows))
    doc.append(Heading(2, "Hardware uyumluluk"))
    doc.append(Para(f"Released Modules listesi: {an.released_list}" if an.released_list else
                    "Released Modules listesi (data/released_modules_<versiyon>.csv) yok: eşleştirme yapılmadı."))
    if an.hw_matches:
        doc.append(Table(["MLFB", "FW", "Adet", "AS", "Durum"],
                         [[m.order, m.fw or "-", str(m.count), _fmt_list(m.stations, 4), m.status] for m in
                          sorted(an.hw_matches, key=lambda m: ("bulunamadı" not in m.status, m.order))], badge_cols=[4]))
    doc.append(Heading(2, "Block klasörleri"))
    rows = []
    for b in an.block_folders:
        c = b.counts
        cnt = "boş" if b.info.is_empty else f"{c.get('FB', 0)}/{c.get('FC', 0)}/{c.get('DB', 0)}/{c.get('OB', 0)}"
        rows.append([b.as_label, cnt, _fmt_list(b.features), f"{b.info.path} — eşleme: {b.mapping}"
                     + (f" — HATA: {b.error}" if b.error else "")])
    doc.append(Table(["AS", "FB/FC/DB/OB", "İçerik", "Klasör / eşleme"], rows))
    doc.append(Note("Block klasörü ↔ AS eşlemesi proje adı ve symbol table FB seti benzerliği ile yapıldı (heuristic, teyit edilmeli)."))
    for b in an.block_folders:
        if not b.counts:
            continue
        doc.append(Heading(2, f"{b.as_label}: library ve instance"))
        doc.append(Table(["Library", "Author (FB/FC sayısı)"],
                         [[lib, ", ".join(f"{a} ({n})" for a, n in sorted(c.items()))] for lib, c in b.libraries.items()]))
        if b.custom_blocks:
            doc.append(Table(["Block", "İsim", "Family", "Author", "Dil", "Versiyon", "Instance"],
                             [[f"{x.kind}{x.number}", x.name or "(header yok)", x.family or "-", x.author or "-",
                               "STL" if x.lang.strip("0") == "1" else x.lang, x.version, str(x.instances)] for x in b.custom_blocks]))
        if b.top_instances:
            doc.append(Table(["Block", "Instance"], [[k, str(n)] for k, n in b.top_instances]))
        extra = []
        if b.symbol_source:
            extra.append(f"Symbol table: {b.symbol_source}")
        if b.block_only:
            extra.append("Block'ta olup symbol'de olmayan FB: " + _fmt_list(b.block_only, 12))
        if not b.memo_available:
            extra.append("SUBBLK.DBT yok: instance sayıları hesaplanamadı")
        if b.unresolved_instances:
            extra.append(f"Çözülemeyen instance referansı: {b.unresolved_instances}")
        if extra:
            doc.append(Bullets(extra))
    if an.os_projects:
        doc.append(Heading(2, "OS projeleri"))
        doc.append(Table(["OS projesi", "Rol", "Yer", "WinCC", "Custom picture", "Faceplate", "Script", "Custom typicals", "OPC", "Klasör"],
                         [[o.info.name, o.role, "ES" if o.in_es else "OS PC kopyası", o.info.wincc_build or "?",
                           str(o.pictures.get("custom", 0)), str(o.pictures.get("faceplate", 0) + o.pictures.get("f_faceplate", 0)),
                           str(len(o.scripts)), _fmt_list(o.custom_typicals, 3), _fmt_list(o.opc, 3), o.info.path]
                          for o in an.os_projects]))
        doc.append(Note("OS rolü proje adından tahmin edilir (heuristic)."))
    for df in an.os_diffs:
        name = df.a.rsplit("/", 1)[-1]
        doc.append(Heading(2, f"{name}: ES ↔ {df.b_label}"))
        doc.append(Table(["Durum", "Adet", "Picture / script"], [
            [f"{df.b_label}'de daha yeni", str(len(df.relevant(df.newer_b))), _fmt_list(_b(df.relevant(df.newer_b)), 30)],
            [f"Sadece {df.b_label}'de", str(len(df.relevant(df.only_b))), _fmt_list(_b(df.relevant(df.only_b)), 30)],
            ["ES'te daha yeni", str(len(df.relevant(df.newer_a))), _fmt_list(_b(df.relevant(df.newer_a)), 30)],
            ["Sadece ES'te", str(len(df.relevant(df.only_a))), _fmt_list(_b(df.relevant(df.only_a)), 30)],
        ]))
    if an.client_groups:
        doc.append(Heading(2, "Client grupları"))
        doc.append(Table(["Client'lar", "Dosya", "Referansa göre", "Fazla dosyalar"],
                         [[_fmt_list(_b(g.members), 10), str(g.n_files), "referans" if g.is_reference else
                           f"+{len(g.only_in_group)} / -{len(g.missing_in_group)}", _fmt_list(_b(g.only_in_group), 6)]
                          for g in an.client_groups]))
    doc.append(Heading(1, "Ek B: Keşif ve uyarılar"))
    doc.append(Bullets([f"Kaynak: {an.source}", f"{d.n_files} dosya, {d.total_bytes / 1e9:.2f} GB",
                        f"Block klasörü: {len(d.block_folders)} ({sum(1 for b in d.block_folders if b.is_empty)} boş)",
                        f".cfg: {len(d.cfg_exports)}, .s7h: {len(d.s7h_files)}, symbol table: {len(d.symbol_tables)}, "
                        f"symbol export: {len(d.symbol_exports)}, OS projesi: {len(d.os_projects)}"]
                       + ([f"Analiz dışı bırakılan eski kopyalar: {', '.join(an.stale_dirs)}"] if an.stale_dirs else [])
                       + [f"Uyarı: {w}" for w in an.warnings]))


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", "<br>")


def render_markdown(an: Analysis, doc: list | None = None, meta: ReportMeta | None = None) -> str:
    doc = doc if doc is not None else build_document(an)
    meta = meta or ReportMeta()
    fam = an.pcs7_family or "?"
    out = [f"# {meta.customer or tr_upper(an.project_name)} | SIMATIC PCS 7 — Upgrade Ön Değerlendirmesi "
           f"{fam} → {an.target.replace('SP', ' SP')}", "",
           " | ".join(x for x in (meta.author, meta.department, meta.date) if x), ""]
    for b in doc:
        if isinstance(b, Topline):
            out += [f"**{b.text}**", ""]
        elif isinstance(b, Heading):
            out += [("## " if b.level == 1 else "### ") + b.text, ""]
        elif isinstance(b, Para):
            out += [b.text, ""]
        elif isinstance(b, Note):
            out += [f"> **Not:** {b.text}", ""]
        elif isinstance(b, Bullets):
            out += [f"- {i}" for i in b.items] + [""]
        elif isinstance(b, Table):
            out.append("| " + " | ".join(b.headers) + " |")
            out.append("|" + "---|" * len(b.headers))
            out += ["| " + " | ".join(_md_cell(c) for c in r) + " |" for r in b.rows]
            out.append("")
            if b.caption:
                out += [f"*{b.caption}*", ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML (Siemens renk skalası)
# ---------------------------------------------------------------------------

# Renk token'ları TEK yerde. Kaynak: Siemens Brand / Element renk paleti (deep-blue skalası, petrol,
# bold green). Kurum içi brand portal ile farklıysa sadece burayı güncelleyin.
SIEMENS_TOKENS = {
    "deep-blue": "#000028",
    "deep-blue-800": "#23233C",
    "deep-blue-700": "#37374D",
    "deep-blue-500": "#66667E",
    "deep-blue-300": "#9999A9",
    "deep-blue-100": "#CCCCD4",
    "deep-blue-50": "#EBEBEE",
    "petrol": "#009999",
    "bold-green": "#00FFB9",
    "light-sand": "#F3F3F0",
    "white": "#FFFFFF",
    # Durum renkleri
    "status-high": "#D72339",
    "status-medium": "#E9A000",
    "status-low": "#009999",
    "status-ok": "#00A36E",
    "status-neutral": "#66667E",
}


def badge_class(v: str) -> str | None:
    v = str(v)
    if v in (STATUS_OK, "listede"):
        return "ok"
    if v in (STATUS_NOT_CHECKED,):
        return "neutral"
    if v in (STATUS_CHANGE, "bulunamadı, teyit edilmeli") or v.endswith(Severity.HIGH.value):
        return "high"
    if v in (STATUS_ATTN, STATUS_DETAIL, STATUS_CONFIRM, "listede, FW listede yok") or v.endswith(Severity.MEDIUM.value):
        return "medium"
    if v.endswith(Severity.LOW.value):
        return "low"
    return None


def _css() -> str:
    t = SIEMENS_TOKENS
    root = "\n".join(f"  --{k}: {v};" for k, v in t.items())
    return f""":root {{
{root}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--light-sand); color: var(--deep-blue);
  font-family: "Siemens Sans", "Segoe UI", Arial, sans-serif; font-size: 14px; line-height: 1.5; }}
header {{ background: var(--deep-blue); color: var(--white); padding: 28px 40px 22px; border-bottom: 4px solid var(--petrol); }}
header .topline {{ color: var(--bold-green); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; }}
header h1 {{ margin: 6px 0 4px; font-size: 30px; font-weight: 400; }}
header h1 b {{ font-weight: 800; }}
header .sub {{ color: var(--deep-blue-100); font-size: 13px; }}
nav {{ background: var(--deep-blue-800); padding: 8px 40px; position: sticky; top: 0; z-index: 2; }}
nav a {{ color: var(--deep-blue-100); text-decoration: none; margin-right: 18px; font-size: 13px; }}
nav a:hover {{ color: var(--bold-green); }}
main {{ max-width: 1200px; margin: 0 auto; padding: 24px 40px 60px; }}
section {{ background: var(--white); border-radius: 4px; padding: 20px 28px; margin: 0 0 20px; box-shadow: 0 1px 2px rgba(0,0,40,.08); }}
.topline {{ font-size: 12px; font-weight: 700; letter-spacing: .06em; color: var(--deep-blue); margin: 4px 0 0; }}
h2 {{ color: var(--deep-blue); font-size: 26px; font-weight: 800; margin: 4px 0 12px; }}
h3 {{ color: var(--petrol); font-size: 16px; margin: 20px 0 8px; }}
p {{ margin: 8px 0; }}
.note {{ background: var(--deep-blue-50); border-left: 4px solid var(--petrol); padding: 8px 12px; margin: 10px 0; font-size: 13px; }}
ul {{ margin: 6px 0 6px 20px; padding: 0; }}
li {{ margin: 3px 0; }}
.tw {{ overflow-x: auto; margin: 10px 0 4px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
.caption {{ text-align: center; font-size: 12px; color: var(--deep-blue-700); margin: 4px 0 16px; }}
th {{ text-align: left; font-weight: 700; padding: 7px 10px; border-bottom: 2px solid var(--deep-blue); }}
td {{ padding: 6px 10px; border-bottom: 1px solid var(--deep-blue-300); vertical-align: top; }}
td p {{ margin: 0 0 4px; }}
tr:hover td {{ background: var(--light-sand); }}
.badge {{ display: inline-block; padding: 1px 9px; border-radius: 10px; font-size: 12px; font-weight: 700; color: var(--white); white-space: nowrap; }}
.badge.high {{ background: var(--status-high); }}
.badge.medium {{ background: var(--status-medium); color: var(--deep-blue); }}
.badge.low {{ background: var(--status-low); }}
.badge.ok {{ background: var(--status-ok); }}
.badge.neutral {{ background: var(--status-neutral); }}
.kpis {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0 16px; }}
.kpi {{ flex: 1 1 140px; background: var(--deep-blue); color: var(--white); border-radius: 4px; padding: 10px 14px; }}
.kpi b {{ display: block; font-size: 24px; color: var(--bold-green); }}
.kpi span {{ font-size: 12px; color: var(--deep-blue-100); }}
footer {{ text-align: center; font-size: 12px; color: var(--deep-blue-500); padding: 20px; }}
@media print {{
  body {{ background: var(--white); }} nav {{ display: none; }}
  section {{ box-shadow: none; padding: 0; }}
  header, .badge, .kpi {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}
@media (max-width: 700px) {{ header, nav, main {{ padding-left: 16px; padding-right: 16px; }} }}
"""


def _inline(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(str(s)))


def _cell(v: str, badge: bool) -> str:
    if badge:
        cls = badge_class(v)
        if cls:
            return f'<span class="badge {cls}">{html.escape(str(v))}</span>'
    parts = str(v).split("\n")
    return parts[0] and _inline(parts[0]) if len(parts) == 1 else "".join(f"<p>{_inline(p)}</p>" for p in parts)


def render_html(an: Analysis, doc: list | None = None, meta: ReportMeta | None = None) -> str:
    doc = doc if doc is not None else build_document(an)
    meta = meta or ReportMeta()
    e = html.escape
    n_high = sum(1 for f in an.findings if f.severity is Severity.HIGH)
    n_med = sum(1 for f in an.findings if f.severity is Severity.MEDIUM)
    d = an.discovery
    kpis = [(an.pcs7_family or "?", "PCS 7 (tespit)"), (str(len(an.stations)), "AS (HW Config)"),
            (str(sum(1 for b in an.block_folders if b.counts)), "Dolu block klasörü"),
            (str(len(d.os_projects)), "OS projesi"), (str(n_high), "Yüksek etki"), (str(n_med), "Orta etki")]
    body, toc, open_, n, pending_topline = [], [], False, 0, ""
    for b in doc:
        if isinstance(b, Topline):
            pending_topline = b.text
            continue
        if isinstance(b, Heading) and b.level == 1:
            if open_:
                body.append("</section>")
            n += 1
            toc.append(f'<a href="#s{n}">{e(pending_topline.title() if pending_topline else b.text)}</a>')
            body.append(f'<section id="s{n}">' + (f'<div class="topline">{e(pending_topline)}</div>' if pending_topline else "")
                        + f"<h2>{e(b.text)}</h2>")
            if n == 1:
                body.append('<div class="kpis">' + "".join(f"<div class='kpi'><b>{e(v)}</b><span>{e(k)}</span></div>"
                                                           for v, k in kpis) + "</div>")
            pending_topline, open_ = "", True
        elif isinstance(b, Heading):
            body.append(f"<h3>{e(b.text)}</h3>")
        elif isinstance(b, Para):
            body.append(f"<p>{_inline(b.text)}</p>")
        elif isinstance(b, Note):
            body.append(f'<div class="note"><b>Not:</b> {_inline(b.text)}</div>')
        elif isinstance(b, Bullets):
            body.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in b.items) + "</ul>")
        elif isinstance(b, Table):
            cols = "".join(f'<col style="width:{w}%">' for w in b.widths)
            head = "".join(f"<th>{e(h)}</th>" for h in b.headers)
            rows = "".join("<tr>" + "".join(f"<td>{_cell(c, i in b.badge_cols)}</td>" for i, c in enumerate(r)) + "</tr>"
                           for r in b.rows)
            body.append(f'<div class="tw"><table><colgroup>{cols}</colgroup><thead><tr>{head}</tr></thead>'
                        f"<tbody>{rows}</tbody></table></div>" + (f'<div class="caption">{e(b.caption)}</div>' if b.caption else ""))
    if open_:
        body.append("</section>")
    fam = an.pcs7_family or "?"
    who = " | ".join(x for x in (meta.author, meta.department, meta.date) if x)
    customer = meta.customer or tr_upper(an.project_name)
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PCS 7 Upgrade – {e(customer)}</title>
<style>{_css()}</style></head>
<body>
<header><div class="topline">{e(customer)} &nbsp;|&nbsp; SIMATIC PCS 7</div>
<h1>Upgrade Ön Değerlendirmesi {e(fam)} → <b>{e(an.target.replace('SP', ' SP'))}</b></h1>
<div class="sub">Proje backup'ı üzerinden yapılan upgrade edilebilirlik analizi{' · ' + e(who) if who else ''} · Kaynak: {e(an.source)}</div></header>
<nav>{''.join(toc)}</nav>
<main>{''.join(body)}</main>
<footer>{e(meta.classification)} · pcs7_analyzer {e(an.tool_version)} · Otomatik üretilmiştir; "teyit edilmeli" işaretli maddeler elle kontrol edilmelidir.</footer>
</body></html>
"""


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def _jsonable(o):
    if is_dataclass(o):
        return {k: _jsonable(v) for k, v in asdict(o).items()}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, dict):
        return {(k if isinstance(k, str) else "|".join(map(str, k)) if isinstance(k, tuple) else str(k)): _jsonable(v)
                for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in o]
    return o


def render_json(an: Analysis) -> str:
    return json.dumps(_jsonable(an), ensure_ascii=False, indent=2, default=str)
