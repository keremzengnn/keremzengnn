"""
Yol haritası: analiz sonucundan projeye özel, sıralı upgrade yolu (hedef PCS 7 V10.0 SP2).

Yeni bilgi ÜRETMEZ: her adım ya bir bulgudan (Finding ID + check'in manual referansı) ya da `report.prep_list` /
`readiness` içindeki manual kaynaklı kurallardan gelir. Manual'da olmayan, iç prosedürden gelen adımlar
"genel prosedür (iç)" kaynağıyla ve ÇIKARIM güveniyle işaretlenir.

    build_roadmap(an)  -> list[Phase]        (boş faz dönmez)
    roadmap_rows(an)   -> list[list[str]]    (ROADMAP_COLUMNS sırasıyla; Excel için)
    write_roadmap(an, out_dir, meta=None) -> Path   (yol_haritasi.html + yol_haritasi.md; dönüş: html)

Fazlar: P0 teklif öncesi, P1 hazırlık, P2 proje migration (ES), P3 AS / library, P4 OS / WinCC, P5 test / devreye alma.
Bulgu tetiklemeyen adım çıkarılır; zorunlu genel adımlar kalır (`generic=True`, "genel").
Yeni adım = ilgili `_phaseN` fonksiyonuna bir `_from_checks(...)` / `_generic(...)` satırı.
"""
from __future__ import annotations

import html
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from .analyze import staged_path_from
from .checks import BASIS_README, SW_UPDATE, action_for, get_check
from .model import Confidence
from .readiness import CIKARIM, KANIT, VERI_YOK, YOK, backup_coverage, quote_inputs

INTERNAL = "genel prosedür (iç)"
OWNER_SIEMENS, OWNER_CUSTOMER, OWNER_BOTH = "Siemens", "Müşteri", "Siemens + Müşteri"

ROADMAP_COLUMNS = ["Faz", "ID", "Adım", "Detay", "Neden (Finding ID)", "Sorumlu", "BLOCKER", "Kapsam (AS)", "Kaynak",
                   "Güven", "Tip"]


@dataclass
class Step:
    id: str                    # "P3-02" (faz içinde sıralı, deterministik)
    title: str
    detail: str
    why: list[str] = field(default_factory=list)       # Finding ID'leri (F-001 …)
    checks: list[str] = field(default_factory=list)    # tetikleyen check id'leri
    owner: str = OWNER_SIEMENS
    blocking: bool = False
    scope: list[str] = field(default_factory=list)     # AS / station etiketleri
    sources: list[str] = field(default_factory=list)   # manual bölümü / check id / INTERNAL
    confidence: str = KANIT                            # KANIT / ÇIKARIM
    generic: bool = False                              # bulgudan değil, zorunlu genel adım


@dataclass
class Phase:
    id: str
    title: str
    steps: list[Step] = field(default_factory=list)


PHASES = [
    ("P0", "Teklif öncesi / müşteriden istenecekler"),
    ("P1", "Hazırlık (ES/OS PC, lisans, backup)"),
    ("P2", "Proje migration (ES)"),
    ("P3", "AS / library update"),
    ("P4", "OS / WinCC"),
    ("P5", "Test / devreye alma"),
]


# ---------------------------------------------------------------------------
# yardımcılar
# ---------------------------------------------------------------------------

def _fid_key(fid: str):
    m = re.search(r"(\d+)$", fid or "")
    return int(m.group(1)) if m else 10 ** 9


def _findings(an, *check_ids):
    ids = set(check_ids)
    return sorted((f for f in an.findings if f.check_id in ids), key=lambda f: _fid_key(f.fid))


def _join_owner(owners) -> str:
    s = set()
    for o in owners:
        if not o:
            continue
        s |= {x.strip() for x in o.split("+")}
    if not s:
        return OWNER_SIEMENS
    if s >= {OWNER_SIEMENS, OWNER_CUSTOMER}:
        return OWNER_BOTH
    return next(iter(s)) if len(s) == 1 else " + ".join(sorted(s))


def _refs(check_ids) -> list[str]:
    out = []
    for cid in check_ids:
        try:
            c = get_check(cid)
        except KeyError:
            continue
        out.append(cid)
        if c.manual_ref and c.manual_ref != "-" and c.manual_ref not in out:
            out.append(c.manual_ref)
    return out


def _uniq(xs) -> list[str]:
    out = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def _from_checks(an, title: str, check_ids, detail: str | None = None, extra_sources=(), owner: str | None = None,
                 force_low: bool = False) -> Step | None:
    """Bulgu varsa adım; yoksa None. detail verilmezse check aksiyonları (ACTIONS) birleştirilir."""
    fs = _findings(an, *check_ids)
    if not fs:
        return None
    hit_ids = _uniq(f.check_id for f in fs)
    if detail is None:
        detail = " ".join(_uniq(action_for(c)[0] for c in hit_ids))
    conf = CIKARIM if force_low or any(f.confidence != Confidence.HIGH for f in fs) else KANIT
    return Step("", title, detail, why=[f.fid for f in fs if f.fid], checks=hit_ids,
                owner=owner or _join_owner(action_for(c)[1] for c in hit_ids),
                blocking=any(f.blocking for f in fs),
                scope=sorted({f.scope for f in fs if f.scope}),
                sources=_uniq(_refs(hit_ids) + list(extra_sources)), confidence=conf)


def _generic(title: str, detail: str, sources=(INTERNAL,), owner: str = OWNER_SIEMENS, why_an=None,
             check_ids=()) -> Step:
    """Zorunlu genel adım. Kaynak INTERNAL ise ÇIKARIM; ilgili bulgular varsa why'a eklenir."""
    srcs = list(sources)
    why, hit = [], []
    if why_an is not None and check_ids:
        fs = _findings(why_an, *check_ids)
        why = [f.fid for f in fs if f.fid]
        hit = _uniq(f.check_id for f in fs)
        srcs = _uniq(srcs + _refs(hit))
    conf = CIKARIM if INTERNAL in srcs else KANIT
    return Step("", title, detail, why=why, checks=hit, owner=owner, sources=srcs, confidence=conf, generic=True)


def _ver(fam: str | None):
    m = re.match(r"V(\d+)\.(\d+)", fam or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _feats(an) -> set:
    return {x for b in an.as_folders for x in b.features}


# ---------------------------------------------------------------------------
# fazlar
# ---------------------------------------------------------------------------

def _phase0(an) -> list:
    steps = []
    for name, status, _ev, impact in backup_coverage(an):
        if status not in (YOK, VERI_YOK) or impact in ("", "-") or "normal)" in impact:
            continue
        steps.append(Step("", f"Eksik veri: {name}", impact, owner=OWNER_CUSTOMER,
                          sources=["Backup kapsamı (readiness.backup_coverage)"], confidence=KANIT, generic=True))
    for name, value, src in quote_inputs(an):
        if VERI_YOK in (value, src) or "eksik" in value:
            steps.append(Step("", f"Teklif girdisi: {name}", f"Mevcut değer: {value}. Müşteriden alınmalı veya "
                              "manuel giriş (--manual) ile tamamlanmalı.", owner=OWNER_CUSTOMER,
                              sources=["Teklif girdileri (readiness.quote_inputs)"], confidence=KANIT, generic=True))
    for cid, why in an.not_checked:
        try:
            title = get_check(cid).title
        except KeyError:
            title = cid
        steps.append(Step("", f"Kontrol edilemedi: {title}", f"{why}. Eksik veri sağlanınca analiz tekrarlanmalı.",
                          checks=[cid], owner=OWNER_CUSTOMER, sources=[cid], confidence=KANIT, generic=True))
    steps.append(_from_checks(an, "Referans backup kararı", ["CONS_BACKUP_DATES"]))
    steps.append(_from_checks(an, "F-I/O için HW Config export'u", ["HW_F_EXPORT_MISSING"]))
    steps.append(_from_checks(an, "F program şifresi ve safety acceptance planı", ["LIB_F_SYSTEM"],
                              detail="F program şifresi müşteriden alınmalı (Update Block Types / compile sorar); "
                                     "safety acceptance (re-validation) planı müşteriyle netleşmeli.",
                              owner=OWNER_CUSTOMER))
    steps.append(_from_checks(an, "Know-how protected block şifreleri", ["BLK_KNOW_HOW"]))
    steps.append(_from_checks(an, "AS-AS / harici haberleşme bilgisi", ["COMM_AS_AS"]))
    return steps


def _phase1(an) -> list:
    fam = an.pcs7_family
    v = _ver(fam)
    path = staged_path_from(fam)
    feats = _feats(an)
    steps = [
        _generic("License key backup'ı",
                 "License key'ler update öncesi yedeklenmeli. Software update konfigürasyon değişikliğinden önce "
                 "tamamlanmalı.", sources=[f"{SW_UPDATE}, 4.3"]),
        _generic("Proje backup'ı", "Update öncesi multiproject archive (backup) alınmalı.",
                 sources=[INTERNAL]),
        _generic(f"Kademeli yol: {fam or '?'} → {' → '.join(path)}",
                 "İç prosedürde ara versiyonlardan geçilir; manual V7.1 SP4 ve üzeri projenin V10.0 SP2'ye doğrudan "
                 "update edilmesine izin veriyor [1, Bölüm 4.3]."
                 + ("" if fam else " Mevcut versiyon tespit edilemedi: yol varsayılan, teyit edilmeli."),
                 sources=[INTERNAL, f"{SW_UPDATE}, 4.3"]),
    ]
    if v is None or v < (9, 1):
        steps.append(_generic("ES / OS PC'ler: temiz kurulum",
                              "V9.1'den eski PCS 7 software'i doğrudan güncellenemez; PC'ler desteklenen OS ile sıfırdan "
                              "kurulur. Desteklenen OS: Windows 10 Enterprise LTSC 2019/2021, Windows 11 Enterprise LTSC "
                              "2024, Windows Server 2019/2022/2025; SQL Server 2019. OS server, BATCH, Route Control, Web "
                              "server, PH ve central ES için server OS."
                              + (" Mevcut versiyon tespit edilemedi: teyit edilmeli." if v is None else ""),
                              sources=[f"{SW_UPDATE}, 4.3"]))
    else:
        steps.append(_generic("ES / OS PC'ler: OS ve SQL Server gereksinimi",
                              "Desteklenen OS (Windows 10 Enterprise LTSC 2019/2021, Windows 11 Enterprise LTSC 2024, "
                              "Windows Server 2019/2022/2025) ve SQL Server 2019 teyit edilmeli.",
                              sources=[f"{SW_UPDATE}, 4.3"]))
    steps += [
        _from_checks(an, "Upgrade lisansları (kademeli paketler)", ["LICENSES"]),
        _from_checks(an, "OS RT PO lisansı", ["OS_PO_INCREASE"]),
        _from_checks(an, "BOX RTX: donanım değişimi", ["HW_BOX_RTX"]),
        _from_checks(an, "Hardware uyumluluğu (Released Modules)", ["HW_RELEASED"]),
        _from_checks(an, "3rd party GSD dosyaları", ["HW_GSD_3RD_PARTY"],
                     detail="GSD dosyaları V10 ES'e kurulmalı (HW Config → Options → Install GSD File → 'from the STEP 7 "
                            "project'); üreticiden V10 uyumu teyit edilmeli."),
    ]
    if "F-System" in feats:
        steps.append(_generic("S7 F Systems + F Configuration Pack kurulumu",
                              "F-block'lar var: hedef versiyonla uyumlu S7 F Systems / F Configuration Pack sürümü "
                              "Compatibility Tool'dan teyit edilmeli.", sources=[INTERNAL],
                              why_an=an, check_ids=["LIB_F_SYSTEM"]))
    steps.append(_from_checks(an, "PCS 7 Library V7.1 paketleri (ES + OS)", ["LIB_PCS7_V71", "LIB_STD_LIB"],
                              detail="Devam edilecekse ES'e PCS 7 Library V7.1 SP3 Upd4, ES ve tüm OS'lara Faceplates "
                                     "V7.1 SP3 Upd1 kurulmalı; aksi halde APL'e geçiş kararı (yeni konfigürasyon, "
                                     "[1, Bölüm 9.11]).",
                              extra_sources=[f"{SW_UPDATE}, 8.5"]))
    steps.append(_from_checks(an, "Modbus TCP / Siemens add-on", ["LIB_MODBUS_TCP"]))
    return steps


def _phase2(an) -> list:
    fam = an.pcs7_family
    v = _ver(fam)
    path = staged_path_from(fam)
    steps = [_from_checks(an, "Proje minimum versiyonu (V7.1 SP4)", ["PROJ_MIN_VERSION"])]
    apc = [f for f in _findings(an, "OS_CUSTOM_TYPICALS") if "@PCS7TypicalsAPC" in f.detail]
    for i, ver in enumerate(path, 1):
        st = _generic(f"Migration adımı {i}/{len(path)}: {ver}",
                      f"ES'e {ver} software kurulumu; multiproject {ver}'de açılır ve migrate edilir; adım sonunda "
                      "multiproject archive alınır.", sources=[INTERNAL])
        if ver.startswith("V8.2") and apc:
            st.detail += " Bu adımda @PCS7TypicalsAPC.pdl silinir (iç prosedür)."
            st.why = [f.fid for f in apc]
            st.checks = ["OS_CUSTOM_TYPICALS"]
            st.sources = _uniq(st.sources + _refs(["OS_CUSTOM_TYPICALS"]))
        steps.append(st)
    if v is not None and v >= (9, 0):
        steps.append(_generic("AS library update'siz geçiş seçeneği",
                              "Proje V9.0 SP3 ve üzeriyse AS library update'siz (AS STOP'suz) update mümkün; SP seviyesi "
                              "teyit edilmeli.", sources=[f"{SW_UPDATE} (dokümantasyon tablosu)"]))
    steps.append(_from_checks(an, "OS projeleri: CCMigrator süresi", ["OS_MIGRATION_VOLUME"]))
    return steps


def _tcir_step(an) -> Step | None:
    if not an.stations:
        return None
    parts, scope = [], []
    for s in sorted(an.stations, key=lambda s: s.name):
        for order, fw, name in s.cpus:
            label = f"{s.name}: {name or order}" + (f" {fw}" if fw else "")
            if re.match(r"6ES7 ?410-", order or ""):
                m = re.match(r"V(\d+)\.(\d+)", fw or "")
                if m and (int(m.group(1)), int(m.group(2))) >= (8, 2):
                    parts.append(f"{label} → TCiR mümkün")
                else:
                    parts.append(f"{label} → FW >= V8.2 değil / tespit edilemedi: TCiR teyit edilmeli")
            else:
                parts.append(f"{label} → AS STOP")
            scope.append(s.name)
    if not parts:
        return None
    fs = _findings(an, "AS_STOP_NO_TCIR")
    return Step("", "Library update yöntemi: TCiR / AS STOP (CPU bazında)",
                "Basis Library update TCiR ile sadece CPU 410-5H (FW >= V8.2); APL ≤V9.1 SP2 → ≥V10.0 geçişinde TCiR "
                "sadece 410-5H'de. " + "; ".join(parts) + ".",
                why=[f.fid for f in fs if f.fid], checks=["AS_STOP_NO_TCIR"] if fs else [],
                owner=_join_owner([OWNER_SIEMENS, action_for("AS_STOP_NO_TCIR")[1]]),
                scope=sorted(set(scope)), sources=_uniq((["AS_STOP_NO_TCIR"] if fs else [])
                                                        + [f"{BASIS_README}, 5.2", "APL Readme V10.0 SP2, 4.4"]),
                confidence=KANIT)


def _phase3(an) -> list:
    return [
        _from_checks(an, "Master data: eski block'ları sil", ["LIB_MASTERDATA_DELETE"]),
        _from_checks(an, "IM_DRV block'larını system chart'tan taşı", ["IM_DRV"]),
        _from_checks(an, "Logic Matrix kararı / library update", ["LIB_LOGIC_MATRIX"]),
        _tcir_step(an),
        _from_checks(an, "APL / Basis library update + Update Block Types", ["LIB_APL_V8", "LIB_MIXED_VERSIONS"],
                     detail="APL / Basis library update, Update Block Types ve tüm block'ları tek versiyona getirme; "
                            "ardından entire program compile (dry-run'da)."),
        _from_checks(an, "Interface'i değişen block tipleri", ["LIB_INTERFACE"]),
        _from_checks(an, "SFC system block'ları", ["LIB_SFC"]),
        _from_checks(an, "F-System (Failsafe Blocks)", ["LIB_F_SYSTEM"],
                     detail="F-library V1.3 veya üzeri olmalı; F-@ chart'lar silinmemeli; F block update / compile "
                            "signature'ı değiştirirse safety acceptance gerekir."),
        _from_checks(an, "Modbus TCP / haberleşme block'ları", ["LIB_MODBUS_TCP", "COMM_STD"]),
        _from_checks(an, "Runtime group FC'leri (64 KB)", ["BLK_FC_SIZE"]),
        _from_checks(an, "Custom block'lar: source + compile", ["BLK_CUSTOM", "BLK_KNOW_HOW"]),
        _from_checks(an, "Symbol table ↔ block klasörü / kullanılmayan block'lar", ["BLK_SYMBOL_MISMATCH", "BLK_UNUSED"]),
        _from_checks(an, "Büyük AS: compile / test süresi", ["AS_SIZE"]),
    ]


def _phase4(an) -> list:
    steps = [
        _from_checks(an, "Baz alınacak OS projesi (ENG / SRV / OS PC kopyası)", ["CONS_ES_SERVER", "WINCC_DIFF"]),
        _from_checks(an, "Client içerik farkları", ["CONS_CLIENTS"]),
    ]
    if an.os_projects:
        steps.append(_generic("OS design ve picture object update",
                              "OS design 'WinCC 3D' olmalı (diğer design'lar PCS 7'de onaylı değil); picture object "
                              "update için @TemplateAPLVer10.PDL / @PCS7TypicalsAPLVer10.PDL + TemplateControl.cfg.",
                              sources=[f"{SW_UPDATE}, 9.6.1"]))
    steps += [
        _from_checks(an, "Custom typicals (picture object template)", ["OS_CUSTOM_TYPICALS"]),
        _from_checks(an, "OPC / 3rd party OPC server", ["OPC_3RD_PARTY", "OS_OPC"]),
        _from_checks(an, "OS bağlantısı: named connection", ["OS_CONN_REDUNDANCY"]),
        _from_checks(an, "SFC visualization", ["SFC_VISU"]),
        _from_checks(an, "Arşiv: CAS → Process Historian", ["CAS_PH"], extra_sources=[f"{SW_UPDATE}, 9.8"]),
        _from_checks(an, "Arşiv segmentleri / SQL log", ["ARCHIVES"]),
    ]
    return steps


def _phase5(an) -> list:
    steps = []
    if an.as_folders:
        steps.append(_generic("AS: complete compile + download",
                              "Update Block Types sonrası complete compile + complete download (AS STOP; CPU 410-5H'de "
                              "TCiR). Download'da CPU local data yeterliliği kontrol edilmeli.",
                              sources=[INTERNAL], why_an=an, check_ids=["LIB_INTERFACE", "LIB_SFC", "BLK_FC_SIZE"]))
    steps.append(_from_checks(an, "Custom block fonksiyon testleri", ["BLK_CUSTOM"],
                              detail="Custom block'lar için dry-run'da compile ve fonksiyon testi (AS bazında)."))
    steps.append(_from_checks(an, "F-System: safety acceptance", ["LIB_F_SYSTEM"],
                              detail="F program signature'ı değiştiyse safety acceptance (re-validation) yapılmalı.",
                              owner=OWNER_BOTH))
    if an.os_projects:
        sfc = bool(_findings(an, "SFC_VISU"))
        steps.append(_generic("OS compile + download",
                              "OS compile ve download" + (" ('SFC visualization' işaretli)" if sfc else "")
                              + "; server / standby / client'lara dağıtım.",
                              sources=[INTERNAL], why_an=an, check_ids=["SFC_VISU"]))
    fat = ["AS ↔ OS connection'ları", "alarm ve archive", "faceplate / picture'lar"]
    if any(any("5H" in (n or o).upper() for o, _, n in s.cpus) for s in an.stations):
        fat.append("H-system redundancy switchover")
    if [o for o in an.os_projects if o.role == "standby"]:
        fat.append("OS server ↔ standby redundancy")
    if _findings(an, "OPC_3RD_PARTY", "OS_OPC"):
        fat.append("OPC bağlantıları")
    if _findings(an, "COMM_STD", "COMM_AS_AS", "LIB_MODBUS_TCP"):
        fat.append("AS-AS / harici haberleşme")
    if "F-System" in _feats(an):
        fat.append("F-I/O ve safety fonksiyonları")
    steps.append(_generic("FAT / SAT kontrol listesi", "Test edilecekler: " + ", ".join(fat) + ".", sources=[INTERNAL],
                          owner=OWNER_BOTH))
    return steps


_BUILDERS = {"P0": _phase0, "P1": _phase1, "P2": _phase2, "P3": _phase3, "P4": _phase4, "P5": _phase5}


def build_roadmap(an) -> list[Phase]:
    """Sıralı fazlar; boş faz dönmez. Bir faz üretilemezse (beklenmeyen veri) hata adımı + an.warnings."""
    out = []
    for pid, title in PHASES:
        try:
            steps = [s for s in _BUILDERS[pid](an) if s is not None]
        except Exception as e:  # noqa: BLE001 - gerçek backup'ta çökme yok
            if hasattr(an, "warnings"):
                an.warnings.append(f"Yol haritası {pid}: {e}\n{traceback.format_exc()}")
            steps = [Step("", "Bu faz otomatik üretilemedi", f"hata: {e}", sources=[INTERNAL], confidence=CIKARIM,
                          generic=True)]
        if not steps:
            continue
        for i, s in enumerate(steps, 1):
            s.id = f"{pid}-{i:02d}"
        out.append(Phase(pid, title, steps))
    return out


def roadmap_rows(an, phases: list[Phase] | None = None) -> list[list[str]]:
    """ROADMAP_COLUMNS sırasıyla satırlar (başlık hariç)."""
    phases = phases if phases is not None else build_roadmap(an)
    return [[f"{p.id} {p.title}", s.id, s.title, s.detail, ", ".join(s.why) or "-", s.owner,
             "BLOCKER" if s.blocking else "-", ", ".join(s.scope) or "-", "; ".join(s.sources) or "-", s.confidence,
             "genel" if s.generic else "bulgu"] for p in phases for s in p.steps]


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def _title(an) -> str:
    fam = an.pcs7_family or "?"
    return f"Upgrade yol haritası {fam} → {an.target.replace('SP', ' SP')}"


def render_markdown(an, phases: list[Phase] | None = None) -> str:
    phases = phases if phases is not None else build_roadmap(an)
    cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = [f"# {_title(an)}", "",
             f"Proje: {an.project_name} · Kaynak: {an.source}",
             "",
             "Her adım bir bulgudan (Finding ID, ayrıntı: rapor / Excel 'Bulgular') veya manual kuralından gelir. "
             f"'{INTERNAL}' kaynaklı adımlar ÇIKARIM: teyit edilmeli.", ""]
    for p in phases:
        lines += [f"## {p.id} · {p.title}", "",
                  "| ID | Adım | Detay | Neden | Sorumlu | Kapsam | Kaynak | Güven |",
                  "|---|---|---|---|---|---|---|---|"]
        for s in p.steps:
            t = ("**BLOCKER** " if s.blocking else "") + s.title + (" (genel)" if s.generic else "")
            lines.append("| " + " | ".join(cell(x) for x in (s.id, t, s.detail, ", ".join(s.why) or "-", s.owner,
                                                               ", ".join(s.scope) or "-", "; ".join(s.sources),
                                                               s.confidence)) + " |")
        lines.append("")
    return "\n".join(lines)


_EXTRA_CSS = """
.path { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 10px 0 4px; }
.path span { background: var(--deep-blue); color: var(--white); padding: 3px 12px; border-radius: 12px; font-weight: 700; }
.path i { color: var(--petrol); font-style: normal; font-weight: 700; }
.step-id { font-family: Consolas, monospace; white-space: nowrap; }
.gen { color: var(--deep-blue-500); font-size: 12px; }
.fid { font-family: Consolas, monospace; font-size: 12px; }
"""

_MIN_CSS = """
body { margin: 0; background: #F3F3F0; color: #000028; font-family: "Segoe UI", Arial, sans-serif; font-size: 14px; }
header { background: #000028; color: #fff; padding: 24px 40px; border-bottom: 4px solid #009999; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 40px; }
section { background: #fff; padding: 16px 24px; margin: 0 0 18px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; border-bottom: 2px solid #000028; padding: 6px 8px; }
td { border-bottom: 1px solid #9999A9; padding: 6px 8px; vertical-align: top; }
.badge { padding: 1px 8px; border-radius: 10px; font-size: 12px; font-weight: 700; color: #fff; }
.badge.high { background: #D72339; } .badge.medium { background: #E9A000; color: #000028; }
.badge.ok { background: #00A36E; } .badge.neutral { background: #66667E; } .badge.low { background: #009999; }
:root { --deep-blue: #000028; --white: #fff; --petrol: #009999; --deep-blue-500: #66667E; }
"""


def _css() -> str:
    try:
        from .report import _css as report_css
        return report_css() + _EXTRA_CSS
    except Exception:  # noqa: BLE001 - report.py yoksa / değişmişse minimal stil
        return _MIN_CSS + _EXTRA_CSS


def _badge(v: str) -> str:
    try:
        from .report import badge_class
        cls = badge_class(v)
    except Exception:  # noqa: BLE001
        cls = {"KANIT": "ok", "ÇIKARIM": "medium", "BLOCKER": "high"}.get(v)
    e = html.escape(v)
    return f'<span class="badge {cls}">{e}</span>' if cls else e


def render_html(an, phases: list[Phase] | None = None, meta=None) -> str:
    phases = phases if phases is not None else build_roadmap(an)
    e = html.escape
    fam = an.pcs7_family or "?"
    customer = (getattr(meta, "customer", "") or an.project_name)
    path = staged_path_from(an.pcs7_family)
    n_steps = sum(len(p.steps) for p in phases)
    n_block = sum(1 for p in phases for s in p.steps if s.blocking)
    n_low = sum(1 for p in phases for s in p.steps if s.confidence != KANIT)
    kpis = [(str(len(phases)), "Faz"), (str(n_steps), "Adım"), (str(n_block), "BLOCKER"), (str(n_low), "ÇIKARIM (teyit)")]
    toc = "".join(f'<a href="#{p.id}">{e(p.id)} {e(p.title)}</a>' for p in phases)
    body = [
        '<section><div class="topline">YOL HARİTASI</div><h2>Özet</h2>'
        '<div class="kpis">' + "".join(f"<div class='kpi'><b>{e(v)}</b><span>{e(k)}</span></div>" for v, k in kpis) + "</div>"
        '<div class="path"><span>' + e(fam) + "</span>" + "".join(f"<i>→</i><span>{e(x)}</span>" for x in path) + "</div>"
        f'<div class="note"><b>Not:</b> Her adım bir bulgudan (Finding ID; ayrıntı rapor / Excel \'Bulgular\') veya manual '
        f"kuralından gelir. '{e(INTERNAL)}' kaynaklı adımlar ÇIKARIM: teyit edilmeli.</div></section>"
    ]
    for p in phases:
        rows = []
        for s in p.steps:
            title = (_badge("BLOCKER") + " " if s.blocking else "") + f"<b>{e(s.title)}</b>" \
                + (' <span class="gen">(genel)</span>' if s.generic else "")
            rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in (
                f'<span class="step-id">{e(s.id)}</span>', title, e(s.detail),
                f'<span class="fid">{e(", ".join(s.why) or "-")}</span>', e(s.owner), e(", ".join(s.scope) or "-"),
                e("; ".join(s.sources)), _badge(s.confidence))) + "</tr>")
        widths = [6, 18, 34, 9, 9, 7, 11, 6]
        cols = "".join(f'<col style="width:{w}%">' for w in widths)
        head = "".join(f"<th>{h}</th>" for h in ("ID", "Adım", "Detay", "Neden", "Sorumlu", "Kapsam", "Kaynak", "Güven"))
        body.append(f'<section id="{e(p.id)}"><div class="topline">FAZ {e(p.id[1:])}</div><h2>{e(p.title)}</h2>'
                    f'<div class="tw"><table><colgroup>{cols}</colgroup><thead><tr>{head}</tr></thead>'
                    f"<tbody>{''.join(rows)}</tbody></table></div></section>")
    classification = getattr(meta, "classification", "Restricted") if meta else "Restricted"
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yol Haritası – {e(customer)}</title>
<style>{_css()}</style></head>
<body>
<header><div class="topline">{e(customer)} &nbsp;|&nbsp; SIMATIC PCS 7</div>
<h1>{e(_title(an))}</h1>
<div class="sub">Analiz sonucundan üretilen sıralı upgrade yolu · Kaynak: {e(an.source)}</div></header>
<nav>{toc}</nav>
<main>{''.join(body)}</main>
<footer>{e(classification)} · pcs7_analyzer {e(getattr(an, 'tool_version', ''))} · Otomatik üretilmiştir; ÇIKARIM işaretli adımlar elle teyit edilmelidir.</footer>
</body></html>
"""


def write_roadmap(an, out_dir, meta=None) -> Path:
    """yol_haritasi.html + yol_haritasi.md yazar; html yolunu döner."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    phases = build_roadmap(an)
    (out / "yol_haritasi.md").write_text(render_markdown(an, phases), encoding="utf-8")
    p = out / "yol_haritasi.html"
    p.write_text(render_html(an, phases, meta), encoding="utf-8")
    return p


__all__ = ["Phase", "Step", "PHASES", "ROADMAP_COLUMNS", "INTERNAL", "build_roadmap", "roadmap_rows", "render_markdown",
           "render_html", "write_roadmap"]
