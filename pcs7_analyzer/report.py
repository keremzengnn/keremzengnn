"""
Rapor: Analysis -> doküman modeli (Heading/Para/Bullets/Table/Note) -> Markdown / HTML / JSON.

Doküman modeli render'dan bağımsızdır; Word template'ine aktarım aynı modeli kullanacak.
Bölüm yapısı: Özet (sonuç + Tablo 1 + duruş notu) -> Proje bilgileri -> Zorluklar ->
Teklif öncesi netleşmesi gerekenler -> Referans dokümanlar -> Ekler. "Upgrade yaklaşımı" bölümü yok.
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path

from .analyze import Analysis, staged_path_from
from .checks import CHECKS
from .model import Confidence, Severity

# ---------------------------------------------------------------------------
# Doküman modeli
# ---------------------------------------------------------------------------


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
    badge_cols: list[int] = field(default_factory=list)   # durum/etki rozetleri


STATUS_OK = "Uygun"
STATUS_NOT_CHECKED = "Kontrol edilmedi"
STATUS_CONFIRM = "Teyit edilmeli"

REFERENCES = [
    ["[1]", "SIMATIC PCS 7 Software update V10.0 SP2, Service Manual", "A5E52547272-AD", "06/2026"],
    ["[2]", "SIMATIC PCS 7 Released Modules (V10.0 SP2), List Manual", "A5E52547920-AD", "07/2026"],
    ["[3]", "SIMATIC PCS 7 Basis Library Readme V10.0 SP2 (Online)", "A5E55678980-AA", "07/2026"],
    ["[4]", "PCS 7 Software update with utilization of new functions V9.1, Service Manual", "A5E50318285-AA", "02/2021"],
]

# Tablo 1 satırları: (Konu, ilgili check id'leri)
SUMMARY_TOPICS = [
    ("Hardware uyumluluğu", ["HW_RELEASED", "HW_GSD_3RD_PARTY"]),
    ("Library (APL / Basis)", ["LIB_APL_V8", "LIB_MIXED_VERSIONS", "LIB_PCS7_V71"]),
    ("F-System", ["LIB_F_SYSTEM", "HW_F_EXPORT_MISSING"]),
    ("SFC / Logic Matrix / Modbus", ["LIB_SFC", "LIB_LOGIC_MATRIX", "LIB_MODBUS_TCP"]),
    ("Custom block'lar ve haberleşme", ["BLK_CUSTOM", "BLK_SYMBOL_MISMATCH", "COMM_AS_AS"]),
    ("OS (typicals, OPC, migration)", ["OS_CUSTOM_TYPICALS", "OS_OPC", "OS_MIGRATION_VOLUME"]),
    ("ES ↔ OS server tutarlılığı", ["CONS_ES_SERVER"]),
    ("Client / backup tutarlılığı", ["CONS_CLIENTS", "CONS_BACKUP_DATES"]),
]

GENERIC_OPEN_ITEMS = [
    "PC hardware ve lisans envanteri (ES / OS server / client / Web / PH)",
    "AS bazında izin verilen duruş süreleri",
    "NetPro bağlantıları ve PC station konfigürasyonları",
    "Arşiv yapısı (PH / CAS / harici arşiv)",
    "OS PC'lerindeki 3rd party yazılımlar",
    "SIMATIC Logon / domain yapısı",
]


def _count(v) -> str:
    return str(v) if v else "-"


def _fmt_list(items, n=6) -> str:
    items = list(items)
    s = ", ".join(items[:n])
    return s + (f" … (+{len(items) - n})" if len(items) > n else "") if items else "-"


def build_document(an: Analysis) -> list:
    doc: list = []
    fam = an.pcs7_family
    by_check = {}
    for f in an.findings:
        by_check.setdefault(f.check_id, []).append(f)
    not_checked = dict(an.not_checked)
    n_high = sum(1 for f in an.findings if f.severity is Severity.HIGH)
    n_med = sum(1 for f in an.findings if f.severity is Severity.MEDIUM)

    # ---------------- 1. Özet ----------------
    doc.append(Heading(1, "Özet"))
    path = staged_path_from(fam)
    target = an.target.replace("SP", " SP")
    if fam:
        doc.append(Para(f"Proje PCS 7 {fam} ailesinde. V7.1 SP4 ve üstü projeler PCS 7 {target}'ye update edilebilir [1, 4.3]; "
                        f"iç prosedüre göre kademeli yol: {fam} → {' → '.join(path)}. "
                        f"{n_high} yüksek, {n_med} orta etkili konu tespit edildi."))
    else:
        doc.append(Para(f"PCS 7 versiyonu otomatik tespit edilemedi (teyit edilmeli). "
                        f"{n_high} yüksek, {n_med} orta etkili konu tespit edildi."))

    rows = [["Proje versiyonu", STATUS_OK if fam else STATUS_CONFIRM,
             f"PCS 7 {fam} → {' → '.join(path)}" if fam else "Versiyon kaynağı bulunamadı"]]
    for topic, ids in SUMMARY_TOPICS:
        fs = [f for i in ids for f in by_check.get(i, [])]
        if fs:
            worst = min(fs, key=lambda f: [Severity.HIGH, Severity.MEDIUM, Severity.LOW].index(f.severity))
            status = worst.severity.value
            note = worst.detail if len(worst.detail) < 180 else worst.detail[:177] + "…"
        elif all(i in not_checked for i in ids):
            status, note = STATUS_NOT_CHECKED, not_checked[ids[0]]
        else:
            status, note = STATUS_OK, "Bulgu yok"
        rows.append([topic, status, note])
    doc.append(Table(["Konu", "Durum", "Not"], rows, "Tablo 1: Genel değerlendirme", badge_cols=[1]))
    doc.append(Note("Planlı duruş (AS STOP) ve PC / Windows yenilemesi her upgrade'de zaten kapsamdadır; "
                    "zorluk olarak listelenmemiştir."))

    # ---------------- 2. Proje bilgileri ----------------
    doc.append(Heading(1, "Proje bilgileri"))
    d = an.discovery
    doc.append(Heading(2, "Versiyonlar"))
    items = [f"Multiproject: {_fmt_list([Path(m).stem for m in d.multiprojects])}; proje: {len(d.projects)}"]
    for v in an.versions:
        items.append(f"{v.item}: {v.value} — kaynak: {v.source}" + (" (teyit edilmeli)" if v.confidence == Confidence.LOW.value else ""))
    doc.append(Bullets(items))

    doc.append(Heading(2, "AS envanteri"))
    if an.stations:
        rows = []
        for s in an.stations:
            cpu = "; ".join(f"{o} {fw}".strip() for o, fw, _ in s.cpus) or "-"
            cp = "; ".join(f"{o} {fw}".strip() for o, fw, _ in s.cps) or "-"
            field_ = _fmt_list([f"{k} ×{n}" for k, n in s.slaves.items()], 5)
            gsd = _fmt_list([f"{k} ×{n}" for k, n in s.gsd.items()], 3)
            fcap = "-" if s.f_capable is None else ("Evet" if s.f_capable else "Hayır")
            pdm = "-" if s.pdm_used is None else ("Evet" if s.pdm_used else "Hayır")
            rows.append([s.name, cpu, cp, field_, gsd, _count(s.h_sync), fcap, pdm, f"{s.kind}: {s.source}"])
        doc.append(Table(["AS", "CPU", "CP", "Saha", "GSD", "H-Sync", "F-capable", "PDM", "Kaynak"], rows))
    else:
        doc.append(Para("HW Config bulunamadı (.cfg export veya .s7h yok)."))

    doc.append(Heading(2, "Hardware uyumluluk"))
    if an.released_list:
        doc.append(Para(f"Released Modules listesi: {an.released_list}. Listede olmayan modül \"bulunamadı\" olarak raporlanır, uyumlu kabul edilmez."))
    else:
        doc.append(Para("Released Modules listesi (data/released_modules_<versiyon>.csv) yok: eşleştirme yapılmadı."))
    if an.hw_matches:
        rows = [[m.order, m.fw or "-", str(m.count), _fmt_list(m.stations, 4), m.status] for m in
                sorted(an.hw_matches, key=lambda m: ("bulunamadı" not in m.status, m.order))]
        doc.append(Table(["MLFB", "FW", "Adet", "AS", "Durum"], rows, badge_cols=[4]))

    doc.append(Heading(2, "Block klasörleri"))
    rows = []
    for b in an.block_folders:
        if b.info.is_empty:
            rows.append([b.as_label, "boş", "-", "-", "-", b.info.path])
            continue
        c = b.counts
        cnt = f"{c.get('FB', 0)}/{c.get('FC', 0)}/{c.get('DB', 0)}/{c.get('OB', 0)}"
        libs = []
        from .analyze import author_version
        for lib in ("APL", "Basis Library", "S7 F Systems Failsafe Blocks"):
            vs = sorted({author_version(a) or a for a in b.libraries.get(lib, {})})
            if vs:
                libs.append(f"{lib.split(' ')[0] if lib != 'S7 F Systems Failsafe Blocks' else 'Failsafe'} {'/'.join(vs)}")
        mapping = b.mapping + (" (heuristic)" if "heuristic" not in b.mapping and b.mapping != "-" else "")
        rows.append([b.as_label, cnt, _fmt_list(libs), _fmt_list(b.features), str(len(b.custom_blocks)),
                     f"{b.info.path} — eşleme: {mapping}" + (f" — HATA: {b.error}" if b.error else "")])
    if rows:
        doc.append(Table(["AS", "FB/FC/DB/OB", "Library", "İçerik", "Custom FB", "Klasör / eşleme"], rows))
        doc.append(Note("Block klasörü ↔ AS eşlemesi proje dosyalarında doğrudan bulunamadı; proje adı ve symbol table FB seti "
                        "benzerliği ile yapıldı (heuristic, teyit edilmeli)."))
    else:
        doc.append(Para("Block klasörü bulunamadı."))

    doc.append(Heading(2, "OS yapısı"))
    if an.os_projects:
        rows = []
        for o in an.os_projects:
            p = o.pictures
            rows.append([o.info.name, o.role, "ES" if o.in_es else "OS PC kopyası", o.info.wincc_build or "?",
                         _count(p.get("custom")), _count(p.get("faceplate", 0) + p.get("f_faceplate", 0)),
                         _count(len(o.scripts)), _fmt_list(o.custom_typicals, 3), _fmt_list(o.opc, 3), o.info.path])
        doc.append(Table(["OS projesi", "Rol", "Yer", "WinCC", "Custom picture", "Faceplate", "Script",
                          "Custom typicals", "OPC", "Klasör"], rows))
        doc.append(Note("Rol proje adından tahmin edilir (heuristic)."))
    else:
        doc.append(Para("WinCC OS projesi bulunamadı."))

    doc.append(Heading(2, "Tutarlılık"))
    if an.os_diffs:
        for df in an.os_diffs:
            name = df.a.rsplit("/", 1)[-1]
            rows = [
                [f"{df.b_label}'de daha yeni", str(len(df.relevant(df.newer_b))), _fmt_list(_b(df.relevant(df.newer_b)), 12)],
                [f"Sadece {df.b_label}'de", str(len(df.relevant(df.only_b))), _fmt_list(_b(df.relevant(df.only_b)), 12)],
                ["ES'te daha yeni", str(len(df.relevant(df.newer_a))), _fmt_list(_b(df.relevant(df.newer_a)), 12)],
                ["Sadece ES'te", str(len(df.relevant(df.only_a))), _fmt_list(_b(df.relevant(df.only_a)), 12)],
            ]
            doc.append(Table(["Durum", "Adet", "Picture / script"], rows,
                             f"{name}: ES ↔ {df.b_label} (toplam boyut farklı dosya: {df.n_size_diff})"))
    else:
        doc.append(Para("ES ↔ OS server karşılaştırması yapılamadı: backup'ta OS PC'lerinden alınmış wincproj kopyası yok."))
    if an.client_groups:
        rows = [[_fmt_list(_b(g.members), 8), str(g.n_files), "referans" if g.is_reference else
                 f"+{len(g.only_in_group)} / -{len(g.missing_in_group)}", _fmt_list(_b(g.only_in_group), 5)]
                for g in an.client_groups]
        doc.append(Table(["Client'lar", "Dosya", "Referansa göre", "Fazla dosyalar"], rows, "Client grupları (içerik imzası)"))
    if an.backups:
        doc.append(Bullets([f"Farklı tarihli kopya — {b.name}: " + ", ".join(f"{p} [{t}]" for p, t in zip(b.paths, b.newest))
                            + f" → en güncel: {b.newest_path}" for b in an.backups]))
        if an.stale_dirs:
            doc.append(Note("Eski kopyalar analiz dışı bırakıldı: " + ", ".join(an.stale_dirs)
                            + ". En güncel kopyanın gerçekten güncel olduğu teyit edilmeli."))

    # ---------------- 3. Zorluklar ----------------
    doc.append(Heading(1, "Zorluklar"))
    if an.findings:
        rows = [[f.title, f.severity.value, f.detail + (" (teyit edilmeli)" if f.confidence is Confidence.LOW else ""),
                 _fmt_list(f.sources, 3)] for f in an.findings]
        doc.append(Table(["Konu", "Etki", "Açıklama", "Kaynak"], rows, badge_cols=[1]))
    else:
        doc.append(Para("Bulgu yok."))

    # ---------------- 4. Teklif öncesi ----------------
    doc.append(Heading(1, "Teklif öncesi netleşmesi gerekenler"))
    items = list(an.open_items)
    titles = {c.id: c.title for c in CHECKS}
    items += [f"Kontrol edilemedi — {titles.get(i, i)}: {why}" for i, why in an.not_checked]
    items += GENERIC_OPEN_ITEMS
    doc.append(Bullets(items))

    # ---------------- 5. Referanslar ----------------
    doc.append(Heading(1, "Referans dokümanlar"))
    doc.append(Table(["No", "Doküman", "Doküman no.", "Tarih"], REFERENCES))

    # ---------------- Ekler ----------------
    doc.append(Heading(1, "Ek A: Block klasörü detayları"))
    for b in an.block_folders:
        if b.info.is_empty or not b.counts:
            continue
        doc.append(Heading(2, b.as_label))
        lib_rows = [[lib, ", ".join(f"{a} ({n})" for a, n in sorted(c.items()))] for lib, c in b.libraries.items()]
        doc.append(Table(["Library", "Author (FB/FC sayısı)"], lib_rows))
        if b.custom_blocks:
            doc.append(Table(["Block", "İsim", "Family", "Author", "Dil", "Versiyon", "Instance"],
                             [[f"{x.kind}{x.number}", x.name or "(header yok)", x.family or "-", x.author or "-",
                               "STL" if x.lang.strip("0") == "1" else x.lang, x.version, str(x.instances)]
                              for x in b.custom_blocks], "Custom block'lar"))
        if b.top_instances:
            doc.append(Table(["Block", "Instance"], [[k, str(n)] for k, n in b.top_instances], "En çok instance"))
        extra = []
        if b.f_blocks_from_symbols:
            extra.append("F-block'lar (symbol'den): " + _fmt_list(b.f_blocks_from_symbols, 12))
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

    doc.append(Heading(1, "Ek B: Keşif ve uyarılar"))
    doc.append(Bullets([f"Kaynak: {an.source}", f"{d.n_files} dosya, {d.total_bytes / 1e9:.2f} GB",
                        f"Block klasörü: {len(d.block_folders)} ({sum(1 for b in d.block_folders if b.is_empty)} boş)",
                        f".cfg: {len(d.cfg_exports)}, .s7h: {len(d.s7h_files)}, symbol table: {len(d.symbol_tables)}, "
                        f"symbol export: {len(d.symbol_exports)}, OS projesi: {len(d.os_projects)}"]
                       + [f"Uyarı: {w}" for w in an.warnings]))
    return doc


def _b(lst):
    return [x.rsplit("/", 1)[-1] for x in lst]


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_markdown(an: Analysis, doc: list | None = None) -> str:
    doc = doc if doc is not None else build_document(an)
    out = [f"# PCS 7 Upgrade Ön Değerlendirme — {an.project_name}", "",
           f"Hedef: PCS 7 {an.target} · Tarih: {an.created} · Araç: pcs7_analyzer {an.tool_version}", ""]
    h = [0, 0]
    for b in doc:
        if isinstance(b, Heading):
            if b.level == 1:
                h = [h[0] + 1, 0]
                num = f"{h[0]}." if not b.text.startswith("Ek ") else ""
                out += [f"## {num} {b.text}".replace("  ", " "), ""]
            else:
                h[1] += 1
                out += [f"### {b.text}", ""]
        elif isinstance(b, Para):
            out += [b.text, ""]
        elif isinstance(b, Note):
            out += [f"> **Not:** {b.text}", ""]
        elif isinstance(b, Bullets):
            out += [f"- {i}" for i in b.items] + [""]
        elif isinstance(b, Table):
            if b.caption:
                out += [f"**{b.caption}**", ""]
            out.append("| " + " | ".join(b.headers) + " |")
            out.append("|" + "---|" * len(b.headers))
            out += ["| " + " | ".join(_md_cell(c) for c in r) + " |" for r in b.rows]
            out.append("")
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

BADGE_CLASS = {
    Severity.HIGH.value: "high", Severity.MEDIUM.value: "medium", Severity.LOW.value: "low",
    STATUS_OK: "ok", STATUS_NOT_CHECKED: "neutral", STATUS_CONFIRM: "medium",
    "listede": "ok", "bulunamadı, teyit edilmeli": "high", "listede, FW listede yok": "medium",
}


def _css() -> str:
    t = SIEMENS_TOKENS
    root = "\n".join(f"  --{k}: {v};" for k, v in t.items())
    return f""":root {{
{root}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--light-sand); color: var(--deep-blue);
  font-family: "Siemens Sans", "Segoe UI", Arial, sans-serif; font-size: 14px; line-height: 1.5; }}
header {{ background: var(--deep-blue); color: var(--white); padding: 28px 40px 22px;
  border-bottom: 4px solid var(--petrol); }}
header .topline {{ color: var(--bold-green); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }}
header h1 {{ margin: 6px 0 4px; font-size: 26px; font-weight: 700; }}
header .sub {{ color: var(--deep-blue-100); font-size: 13px; }}
nav {{ background: var(--deep-blue-800); padding: 8px 40px; position: sticky; top: 0; z-index: 2; }}
nav a {{ color: var(--deep-blue-100); text-decoration: none; margin-right: 18px; font-size: 13px; }}
nav a:hover {{ color: var(--bold-green); }}
main {{ max-width: 1280px; margin: 0 auto; padding: 24px 40px 60px; }}
section {{ background: var(--white); border-radius: 4px; padding: 20px 28px; margin: 0 0 20px;
  box-shadow: 0 1px 2px rgba(0,0,40,.08); }}
h2 {{ color: var(--deep-blue); font-size: 20px; margin: 0 0 12px; padding-bottom: 6px;
  border-bottom: 2px solid var(--petrol); }}
h3 {{ color: var(--petrol); font-size: 16px; margin: 20px 0 8px; }}
p {{ margin: 8px 0; }}
.lead {{ font-size: 15px; }}
.note {{ background: var(--deep-blue-50); border-left: 4px solid var(--petrol); padding: 8px 12px; margin: 10px 0; font-size: 13px; }}
ul {{ margin: 6px 0 6px 20px; padding: 0; }}
li {{ margin: 3px 0; }}
.tw {{ overflow-x: auto; margin: 8px 0 14px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
caption {{ text-align: left; font-weight: 700; color: var(--deep-blue-700); padding: 4px 0 6px; }}
th {{ background: var(--deep-blue); color: var(--white); text-align: left; font-weight: 600; padding: 7px 10px; }}
td {{ padding: 6px 10px; border-bottom: 1px solid var(--deep-blue-50); vertical-align: top; }}
tr:nth-child(even) td {{ background: var(--light-sand); }}
.badge {{ display: inline-block; padding: 1px 9px; border-radius: 10px; font-size: 12px; font-weight: 600;
  color: var(--white); white-space: nowrap; }}
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
  section {{ box-shadow: none; padding: 0; page-break-inside: auto; }}
  header {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  th, .badge, .kpi {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}
@media (max-width: 700px) {{ header, nav, main {{ padding-left: 16px; padding-right: 16px; }} }}
"""


def _cell(v: str, badge: bool) -> str:
    e = html.escape(str(v))
    if badge:
        cls = BADGE_CLASS.get(str(v))
        if cls:
            return f'<span class="badge {cls}">{e}</span>'
    return e


def render_html(an: Analysis, doc: list | None = None) -> str:
    doc = doc if doc is not None else build_document(an)
    e = html.escape
    n_high = sum(1 for f in an.findings if f.severity is Severity.HIGH)
    n_med = sum(1 for f in an.findings if f.severity is Severity.MEDIUM)
    d = an.discovery
    kpis = [(an.pcs7_family or "?", "PCS 7 (tespit)"), (str(len(an.stations)), "AS (HW Config)"),
            (str(sum(1 for b in d.block_folders if not b.is_empty)), "Dolu block klasörü"),
            (str(len(d.os_projects)), "OS projesi"), (str(n_high), "Yüksek etki"), (str(n_med), "Orta etki")]

    body, toc, sec_open, num = [], [], False, 0
    for b in doc:
        if isinstance(b, Heading) and b.level == 1:
            if sec_open:
                body.append("</section>")
            num += 1
            sid = f"s{num}"
            label = b.text if b.text.startswith("Ek ") else f"{num}. {b.text}"
            toc.append(f'<a href="#{sid}">{e(label)}</a>')
            body.append(f'<section id="{sid}"><h2>{e(label)}</h2>')
            if num == 1:
                body.append('<div class="kpis">' + "".join(f"<div class='kpi'><b>{e(v)}</b><span>{e(k)}</span></div>"
                                                           for v, k in kpis) + "</div>")
            sec_open = True
        elif isinstance(b, Heading):
            body.append(f"<h3>{e(b.text)}</h3>")
        elif isinstance(b, Para):
            body.append(f'<p class="lead">{e(b.text)}</p>' if num == 1 else f"<p>{e(b.text)}</p>")
        elif isinstance(b, Note):
            body.append(f'<div class="note"><b>Not:</b> {e(b.text)}</div>')
        elif isinstance(b, Bullets):
            body.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in b.items) + "</ul>")
        elif isinstance(b, Table):
            cap = f"<caption>{e(b.caption)}</caption>" if b.caption else ""
            head = "".join(f"<th>{e(h)}</th>" for h in b.headers)
            rows = "".join("<tr>" + "".join(f"<td>{_cell(c, i in b.badge_cols)}</td>" for i, c in enumerate(r)) + "</tr>"
                           for r in b.rows)
            body.append(f'<div class="tw"><table>{cap}<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
    if sec_open:
        body.append("</section>")

    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PCS 7 Upgrade – {e(an.project_name)}</title>
<style>{_css()}</style></head>
<body>
<header><div class="topline">SIMATIC PCS 7 · Upgrade ön değerlendirme</div>
<h1>{e(an.project_name)}</h1>
<div class="sub">Hedef: PCS 7 {e(an.target)} · {e(an.created)} · Kaynak: {e(an.source)}</div></header>
<nav>{''.join(toc)}</nav>
<main>{''.join(body)}</main>
<footer>pcs7_analyzer {e(an.tool_version)} · Otomatik üretilmiştir; "teyit edilmeli" işaretli maddeler elle kontrol edilmelidir. · Restricted</footer>
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
