"""
Risk / tutarlılık kontrollerinin TEK tanım yeri.

Yeni kontrol = aşağıya bir fonksiyon + CHECKS listesine bir satır.
`func(an) -> list[Finding]`. `func=None` ise kontrol planlanmış ama yazılmamıştır; raporda
"kontrol edilmedi" olarak listelenir (sessizce atlanmaz). Bir kontrol veri eksikliğinden
yapılamıyorsa `NotChecked(sebep)` fırlatır.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass

from .model import Confidence, Finding, Severity

SW_UPDATE = "[1] Software update V10.0 SP2"
RELEASED = "[2] Released Modules V10.0 SP2"
BASIS_README = "[3] Basis Library Readme V10.0 SP2"

H, M, L = Severity.HIGH, Severity.MEDIUM, Severity.LOW


class NotChecked(Exception):
    """Kontrol veri eksikliği nedeniyle yapılamadı (sebep mesajda)."""


@dataclass(frozen=True)
class Check:
    id: str
    topic: str              # rapordaki kısa "Konu"
    title: str
    severity: Severity
    manual_ref: str
    func: Callable[..., list[Finding]] | None = None

    @property
    def implemented(self) -> bool:
        return self.func is not None


def _f(c: "Check", detail: str, sources=(), confidence=Confidence.HIGH, severity=None, scope="",
       blocking=False) -> Finding:
    srcs = list(sources) + ([c.manual_ref] if c.manual_ref != "-" else [])
    return Finding(c.id, c.topic, severity or c.severity, detail, srcs, confidence, scope, blocking)


def _short(items, n=8) -> str:
    items = list(items)
    s = ", ".join(items[:n])
    return s + (f" … (+{len(items) - n})" if len(items) > n else "")


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------

def hw_released(c, an):
    if not an.stations:
        raise NotChecked("HW Config (.cfg / .s7h) bulunamadı")
    if not an.released_list:
        raise NotChecked("data/released_modules_<versiyon>.csv yok")
    out = []
    blocked = [m for m in an.hw_matches if re.search(r"not released|nicht freigegeben|unsupported|desteklenmiyor",
                                                     m.note, re.I)]
    if blocked:
        out.append(_f(c, "Hedef versiyonda desteklenmeyen modüller: " + _short(
            f"{m.order} {m.fw} ×{m.count} ({', '.join(m.stations)}; {m.note})" for m in blocked) + " -> değişim gerekli.",
            [an.released_list], blocking=True))
    bad = [m for m in an.hw_matches if m not in blocked and ("bulunamadı" in m.status or "FW" in m.status)]
    if bad:
        lines = [f"{m.order} {m.fw} ×{m.count} ({m.status}; {', '.join(m.stations)})".replace("  ", " ") for m in bad]
        out.append(_f(c, f"{len(bad)} MLFB/FW Released Modules listesinde bulunamadı, teyit edilmeli: " + _short(lines, 6),
                      [an.released_list]))
    return out


def hw_f_export_missing(c, an):
    out = []
    for b in an.block_folders:
        if "F-System" not in b.features and not b.f_driver_instances:
            continue
        sts = [s for s in an.stations if s.project == b.info.project]
        if not sts:
            out.append(_f(c, f"{b.as_label}: F-System var, HW Config bu AS ile eşlenemedi -> F-I/O kontrol edilemedi",
                          [b.info.dbf], Confidence.LOW, scope=b.as_label))
            continue
        for s in sts:
            if s.f_modules == 0:
                out.append(_f(c, f"{b.as_label}: F-block/F-driver var ({b.f_driver_instances} F-channel driver instance) "
                                 f"ama {s.name} HW export'unda F-I/O yok. Export S7 F Configuration Pack kurulu "
                                 f"PC'den tekrar alınmalı.", [b.info.dbf, s.source], scope=b.as_label))
    return out


def hw_gsd(c, an):
    out = []
    for s in an.stations:
        if s.gsd:
            out.append(_f(c, f"{s.name}: " + _short(f"{k} ×{n}" for k, n in s.gsd.items())
                          + ". GSD dosyaları V10 ES'e yeniden yüklenmeli.", [s.source], scope=s.name))
    return out


def as_stop(c, an):
    cpus = {o for s in an.stations for o, _, _ in s.cpus}
    non410 = sorted(o for o in cpus if not re.match(r"6ES7 ?410-", o))
    if not non410:
        return []
    return [_f(c, "Basis Library update TCiR ile sadece CPU 410-5H'de yapılabilir; bu CPU'larda AS STOP: "
                  + ", ".join(non410) + ". (Duruş zaten kapsamda.)")]


# ---------------------------------------------------------------------------
# Library / block
# ---------------------------------------------------------------------------

def _lib_versions(an, lib):
    from .analyze import author_version
    out = {}
    for b in an.block_folders:
        for a in b.libraries.get(lib, {}):
            out.setdefault(author_version(a) or a, set()).add(b.as_label)
    return out


def lib_apl_v8(c, an):
    vs = {v: a for v, a in _lib_versions(an, "APL").items() if v.startswith("V8")}
    if not vs:
        return []
    return [_f(c, "APL " + "; ".join(f"{v}: {', '.join(sorted(a))}" for v, a in sorted(vs.items()))
               + ". V10.0 SP2 faceplate'leri sadece APL V9.0/V9.1 block'larıyla mixed operation destekler -> library update zorunlu.")]


def lib_mixed(c, an):
    out = []
    for b in an.block_folders:
        for lib, vs in b.mixed_versions.items():
            out.append(_f(c, f"{b.as_label}: karışık {lib} versiyonları: " + ", ".join(vs), [b.info.dbf],
                          scope=b.as_label))
    return out


def _feature(c, an, feat, text):
    return [_f(c, f"{b.as_label}: {text}", [b.info.dbf], scope=b.as_label)
            for b in an.block_folders if feat in b.features]


def lib_v71(c, an):
    return _feature(c, an, "PCS 7 Lib V7.1", "PCS 7 Library V7.1 block'ları var. Kullanılmaya devam edecekse ES'e Library V7.1 SP3 Upd4, "
                                             "ES ve tüm OS'lara Faceplates V7.1 SP3 Upd1 kurulmalı.")


def lib_lm(c, an):
    return _feature(c, an, "Logic Matrix", "Logic Matrix block'ları var; upgrade without new functionality desteklenmez -> library update zorunlu.")


def lib_sfc(c, an):
    out = []
    for b in an.block_folders:
        if "SFC" not in b.features:
            continue
        n = b.fb_instances.get(300, 0)
        out.append(_f(c, f"{b.as_label}: SFC system block'ları (FB245/246/300, FC240…250) güncel SFC library'den "
                         f"offline block klasörüne elle kopyalanmalı, ardından complete compile zorunlu"
                         + (f"; SFC instance (FB300): {n}." if n else "."),
                      [b.info.dbf], scope=b.as_label))
    return out


def lib_f(c, an):
    from .analyze import author_version
    fp = sorted({x for o in an.os_projects for x in o.f_faceplates})
    out = []
    for b in an.block_folders:
        if "F-System" not in b.features:
            continue
        vs = sorted({author_version(a) or a for a in b.libraries.get("S7 F Systems Failsafe Blocks", {})})
        d = (f"{b.as_label}: F-program Failsafe Blocks " + ("/".join(vs) if vs else "(versiyon tespit edilemedi)")
             + " ile yazılmış. S7 F Systems ve F-library'nin V10 uyumlu versiyona geçişi S7 F Systems Readme'den "
               "doğrulanmalı. Collective signature değişirse safety kabul (re-validation) gerekir.")
        if b.f_driver_instances:
            d += f" Block klasöründe {b.f_driver_instances} F-channel driver instance var, yani F-I/O mevcut."
        if b.f_blocks_from_symbols:
            d += " F-block'lar: " + _short([x.split(" ", 1)[-1] for x in b.f_blocks_from_symbols], 6) + "."
        if fp:
            d += " OS'ta F faceplate'leri: " + _short(fp, 4) + "."
        out.append(_f(c, d, [b.info.dbf], scope=b.as_label))
    return out


def lib_modbus(c, an):
    return _feature(c, an, "Modbus TCP / Siemens add-on", "Modbus TCP / Siemens add-on block'ları; hedef versiyonda lisans ve block versiyonu teyit edilmeli.")


def lib_masterdata(c, an):
    if not any(b.libraries.get("APL") or b.libraries.get("Basis Library") for b in an.block_folders):
        return []
    return [_f(c, "Library update öncesi master data library'den OB_DIAG, OR_M_16, OR_M_32 silinmeli.")]


def blk_custom(c, an):
    out = []
    for b in an.block_folders:
        if not b.custom_blocks:
            continue
        items = [f"FB{x.number} {x.name or '(header yok)'}" + (" STL" if x.lang.strip("0") == "1" else "")
                 + f" [{x.instances} inst.]" for x in b.custom_blocks]
        out.append(_f(c, f"{b.as_label}: {len(items)} custom FB: " + _short(items, 6), [b.info.dbf], scope=b.as_label))
    return out


def blk_unused(c, an):
    out = []
    for b in an.block_folders:
        if not b.memo_available:
            continue
        unused = [f"FB{x.number} {x.name}" for x in b.custom_blocks if x.instances == 0]
        if unused or b.unused_library_fbs:
            out.append(_f(c, f"{b.as_label}: instance DB'si olmayan custom: {_short(unused, 5) or '-'}; library: "
                             f"{_short(b.unused_library_fbs, 5) or '-'} (multi-instance olabilir, teyit)", [b.info.dbf],
                          Confidence.LOW, scope=b.as_label))
    return out


def blk_symbol(c, an):
    out = []
    for b in an.block_folders:
        if b.symbol_only:
            out.append(_f(c, f"{b.as_label}: symbol'de olup block klasöründe olmayan: {_short(b.symbol_only, 6)}",
                          [b.symbol_source, b.info.dbf], Confidence.LOW, scope=b.as_label))
    return out


def comm_as_as(c, an):
    pat = re.compile(r"(^|_)(GET|PUT|SEND|REC|BSEND|BRCV|USEND|URCV|AG_L?SEND|AG_L?RECV|TSEND|TRCV)", re.I)
    out = []
    for b in an.block_folders:
        hits = [f"FB{x.number} {x.name}" for x in b.custom_blocks if pat.search(x.name)]
        if "PCS 7 Lib V7.1" in b.features:
            hits.append("COMM71 SEND_R/REC_R")
        if hits:
            out.append(_f(c, f"{b.as_label}: " + _short(hits, 6) + " -> karşı taraf (AS / multiproject / 3rd party) teyit edilmeli",
                          [b.info.dbf], Confidence.LOW, scope=b.as_label))
    return out


# PCS 7 Standard Library (V6/V7) block isimleri: APL öncesi library
STD_LIB_NAMES = {"MOT_SPED", "MOT_REV", "MOTOR", "VAL_MOT", "VALVE", "CTRL_PID", "CTRL_S", "MEAS_MON", "DOSE",
                 "RATIO_P", "INTERLOK", "OP_A", "OP_A_LIM", "OP_A_RJC", "OP_D", "OP_D3", "OP_TRIG", "SWIT_CNL",
                 "DIG_MON"}


def lib_std(c, an):
    out = []
    for b in an.block_folders:
        names = sorted({x.split(" ", 1)[-1] for x in b.unused_library_fbs} | {x.name for x in b.custom_blocks}
                       | set(b.block_names))
        hits = sorted(n for n in names if n.upper() in STD_LIB_NAMES)
        if hits:
            out.append(_f(c, f"{b.as_label}: eski PCS 7 Library (standard block) isimleri: {_short(hits, 8)}. "
                             "Devam edilecekse ES'e Library V7.1 SP3 Upd4, ES ve tüm OS'lara Faceplates V7.1 SP3 Upd1 "
                             "gerekir [1, 8.5]; APL'e dönüşüm yeni, uygulamaya özel konfigürasyon gerektirir [1, 9.11].",
                          [b.info.dbf, f"{SW_UPDATE}, 9.11"], Confidence.LOW, scope=b.as_label))
    return out


def _block_changes(an) -> list[dict]:
    import csv
    from .analyze import data_dirs
    for d in data_dirs():
        for p in sorted(d.glob(f"block_changes_{an.target}*.csv")) if d.is_dir() else []:
            with p.open(encoding="utf-8") as f:
                return list(csv.DictReader(f))
    return []


def lib_interface(c, an):
    changes = _block_changes(an)
    if not changes:
        raise NotChecked(f"data/block_changes_{an.target}.csv yok")
    iface = {}
    for r in changes:
        if r["interface_change"] == "yes":
            iface.setdefault(r["name"].upper(), r)
    out = []
    for b in an.block_folders:
        if not b.counts:
            continue
        hits = []
        for name, nr in b.fb_by_name.items():
            r = iface.get(name.upper())
            if r:
                hits.append((r["library"], name, b.fb_instances.get(nr, 0), r["section"]))
        for name in b.block_names:
            r = iface.get(name.upper())
            if r and r["kind"] == "FC" and name not in b.fb_by_name:
                hits.append((r["library"], name, 0, r["section"]))
        if not hits:
            continue
        parts = []
        for lib in ("APL", "Basis"):
            h = sorted((x for x in hits if x[0] == lib), key=lambda x: -x[2])
            if h:
                parts.append(f"{lib}: {len(h)} tip (" + _short([f'{n} ×{i}' if i else n for _, n, i, _ in h], 8) + ")")
        out.append(_f(c, f"{b.as_label}: V10.0'da interface'i değişen block tipleri kullanılıyor — " + "; ".join(parts)
                         + ". Update Block Types sonrası complete compile + complete download (AS STOP; CPU 410-5H'de TCiR). "
                           "V8.x'ten gelen projede ara versiyonların değişiklikleri de eklenir.",
                      [b.info.dbf, "APL Readme V10.0 SP2, 5.1.3", "Basis Library Readme V10.0 SP2, 6.1.3"], scope=b.as_label))
    return out


def im_drv(c, an):
    out = []
    for b in an.block_folders:
        if any(n.upper().startswith("IM_DRV") for n in b.block_names):
            out.append(_f(c, f"{b.as_label}: IM_DRV block'u var (high-precision time stamping). Update öncesi system "
                             "chart'lardaki IM_DRV block'ları geçici CFC chart'lara taşınmalı; taşındıktan sonra AS programı "
                             "generate edilmemeli.", [b.info.dbf], scope=b.as_label))
    return out


def box_rtx(c, an):
    hits = [s for s in an.stations if re.search(r"BOX\s*RTX|WinAC\s*RTX|WinLC\s*RTX", s.station_text, re.I)]
    return [_f(c, f"{s.name}: SIMATIC PCS 7 BOX RTX / WinAC RTX update edilemez (yeni Windows sürümlerini desteklemiyor) "
                  "-> AS donanımı değiştirilmeli.", [s.source], scope=s.name, blocking=True) for s in hits]


def as_size(c, an):
    full = [b for b in an.block_folders if b.counts]
    if len(full) < 2:
        return []
    big = max(full, key=lambda b: b.counts.get("DB", 0))
    rest = sorted((b.counts.get("DB", 0) for b in full if b is not big), reverse=True)
    if not rest or big.counts.get("DB", 0) < 2 * rest[0]:
        return []
    return [_f(c, f"{big.as_label}: en büyük AS: {big.counts.get('DB', 0)} DB, {big.counts.get('FC', 0)} FC. Compile ve "
                  "test süresinin diğer AS'lerden belirgin şekilde uzun olması bekleniyor.", [big.info.dbf],
               scope=big.as_label)]


def licenses(c, an):
    if not an.block_folders:
        return []
    opts = sorted({f for b in an.block_folders for f in b.features} & {"F-System", "Logic Matrix", "Modbus TCP / Siemens add-on", "SFC"})
    return [_f(c, "Upgrade paketleri kademeli (V7.1 → V8.2, V8.x → V9.x, V9.x → V10.0.x) [1, Bölüm 4.3]."
               + (f" {', '.join(opts)} gibi opsiyonların lisansları ayrıca kontrol edilmeli." if opts else ""))]


def cas_ph(c, an):
    out = []
    pck = sorted({f"{o.info.name}: {x.rsplit('/', 1)[-1]}" for o in an.os_projects for x in o.cas_packages})
    if pck:
        out.append(_f(c, "CAS server data package'ları var: " + _short(pck) + ". CAS V10'da desteklenmiyor: multiproject'ten "
                         "kaldırılıp gerekirse Process Historian eklenmeli; .PCK paketleri OS projelerinden silinmeli, CAS için "
                         "açılmış Alarm/Tag Logging backup ayarları kapatılmalı. CAS arşivleri PH'ye aktarılamaz.",
                      [f"{SW_UPDATE}, 9.8"]))
    pat = re.compile(r"(^|[^A-Z])(CAS|PH|HISTORIAN|INFOSERVER|IS)([^A-Z]|$)", re.I)
    hits = sorted({o.info.name for o in an.os_projects if pat.search(o.info.name)}
                  | {p.rsplit("/", 1)[-1] for p in an.discovery.projects if pat.search(Path(p).stem)})
    if hits:
        out.append(_f(c, f"Arşiv/raporlama bileşeni olabilecek projeler: {_short(hits)}. CAS V10'da desteklenmiyor → Process "
                         "Historian; PH/IS 2024 SP1 Update 3'e yükseltmede OS değişirse Windows Server 2019/2022 gerekir.",
                      confidence=Confidence.LOW))
    return out


# ---------------------------------------------------------------------------
# OS
# ---------------------------------------------------------------------------

def os_typicals(c, an):
    t = sorted({(x, o.info.name) for o in an.os_projects for x in o.custom_typicals})
    if not t:
        return []
    return [_f(c, "Standart dışı picture object template'leri: " + _short(f"{x} ({n})" for x, n in t) +
               " -> picture object update'te ayrıca ele alınmalı.")]


def os_opc(c, an):
    hits = [f"{o.info.name}: {', '.join(o.opc)}" for o in an.os_projects if o.opc]
    if not hits:
        return []
    return [_f(c, "OPC konfigürasyonu: " + _short(hits, 5) + ". Harici OPC client'lar teyit edilmeli.")]


def os_po(c, an):
    if not an.os_projects:
        return []
    return [_f(c, "Update sonrası OS RT PO sayısı artabilir; mevcut PO lisansı ve kullanımı teyit edilmeli.")]


def os_volume(c, an):
    if not an.os_projects:
        return []
    ref = [o for o in an.os_projects if o.in_es] or an.os_projects
    pics = sum(o.pictures.get("custom", 0) for o in ref)
    scr = sum(len(o.scripts) for o in ref)
    return [_f(c, f"ES'teki {len(ref)} OS projesinde {pics} custom picture, {scr} VBS script. CCMigrator migration saatler sürebilir.")]


# ---------------------------------------------------------------------------
# Tutarlılık
# ---------------------------------------------------------------------------

def cons_es_server(c, an):
    if not an.os_diffs:
        raise NotChecked("OS PC'lerinden alınmış wincproj kopyası yok (sadece ES projesi var)")
    out = []
    for d in an.os_diffs:
        oa, ob = d.relevant(d.only_a), d.relevant(d.only_b)
        na, nb = d.relevant(d.newer_a), d.relevant(d.newer_b)
        if not (oa or ob or na or nb):
            continue
        name = d.a.rsplit("/", 1)[-1]
        parts = []
        if nb:
            parts.append(f"{d.b_label}'de daha yeni {len(nb)} (online değişiklik, ES'e alınmamış): {_short(_base(nb), 6)}")
        if ob:
            parts.append(f"sadece {d.b_label}'de {len(ob)}: {_short(_base(ob), 6)}")
        if na:
            parts.append(f"ES'te daha yeni {len(na)}")
        if oa:
            parts.append(f"sadece ES'te {len(oa)}")
        sev = H if (nb or ob) else M
        out.append(_f(c, f"{name}: " + "; ".join(parts) + ". ES master değil -> migration öncesi reconciliation.",
                      [d.a, d.b], severity=sev))
    return out


def _base(lst):
    return [x.rsplit("/", 1)[-1] for x in lst]


def cons_clients(c, an):
    if len(an.client_groups) < 2:
        return []
    ref = next(g for g in an.client_groups if g.is_reference)
    lines = []
    for g in an.client_groups:
        if g.is_reference:
            continue
        lines.append(f"{_short(_base(g.members), 4)}: +{len(g.only_in_group)} / -{len(g.missing_in_group)} dosya "
                     f"(ör. {_short(_base(g.only_in_group), 3) or '-'})")
    return [_f(c, f"{len(an.client_groups)} farklı client içeriği. Referans: {_short(_base(ref.members), 4)}. " + " | ".join(lines),
               confidence=Confidence.LOW)]


def cons_backups(c, an):
    out = []
    for b in an.backups:
        out.append(_f(c, f"{b.name}: {len(b.paths)} kopya ({', '.join(f'{p} [{t}]' for p, t in zip(b.paths, b.newest))}). "
                         f"En güncel görünen: {b.newest_path}", b.paths, Confidence.LOW))
    return out


CHECKS: list[Check] = [
    # --- Hardware ---
    Check("HW_RELEASED", "Hardware uyumluluğu", "Released Modules listesinde bulunamayan MLFB/FW", H, RELEASED, hw_released),
    Check("HW_F_EXPORT_MISSING", "F-I/O HW export", "F-block/F-driver var ama HW export'ta F-I/O yok", H, "-", hw_f_export_missing),
    Check("HW_GSD_3RD_PARTY", "3rd party GSD", "3rd party GSD cihazlar", M, "-", hw_gsd),
    Check("AS_STOP_NO_TCIR", "AS STOP", "Basis Library update TCiR ile yapılamıyor (410-5H değil)", L, BASIS_README, as_stop),
    # --- Block / library ---
    Check("LIB_APL_V8", "APL library update", "APL V8.x block'ları: library update zorunlu", H, f"{SW_UPDATE}, 9.10.4", lib_apl_v8),
    Check("LIB_MIXED_VERSIONS", "Karışık library versiyonları", "Aynı library'nin karışık versiyonları", M, "-", lib_mixed),
    Check("LIB_PCS7_V71", "PCS 7 Library V7.1", "PCS 7 Library V7.1 block'ları", M, f"{SW_UPDATE}, 8.5", lib_v71),
    Check("LIB_LOGIC_MATRIX", "Logic Matrix", "Logic Matrix: library update zorunlu", H, f"{SW_UPDATE}, 9.9.4", lib_lm),
    Check("LIB_SFC", "SFC", "SFC system block'ları elle güncellenmeli", M, f"{SW_UPDATE}, 9.5", lib_sfc),
    Check("LIB_F_SYSTEM", "F-System", "F-System (Failsafe Blocks, F faceplate'leri)", H, "S7 F Systems Readme (eksik)", lib_f),
    Check("LIB_MODBUS_TCP", "Modbus TCP", "Modbus TCP / Siemens add-on block'ları", M, "-", lib_modbus),
    Check("LIB_MASTERDATA_DELETE", "Master data library", "OB_DIAG / OR_M_16 / OR_M_32 silinmeli", L, f"{SW_UPDATE}, 4.3", lib_masterdata),
    Check("LIB_INTERFACE", "Interface değişiklikleri", "V10'da interface'i değişen APL/Basis block tipleri", M,
          "APL / Basis Library Readme V10.0 SP2", lib_interface),
    Check("IM_DRV", "High-precision time stamping", "IM_DRV block'ları update öncesi taşınmalı", M, f"{SW_UPDATE}, 6.1", im_drv),
    Check("HW_BOX_RTX", "BOX RTX", "PCS 7 BOX RTX update edilemez", H, f"{SW_UPDATE}, 4.1", box_rtx),
    Check("LIB_STD_LIB", "Eski Standard Library", "PCS 7 Standard Library (APL öncesi) block'ları", H, f"{SW_UPDATE}, 8.5", lib_std),
    Check("AS_SIZE", "AS büyüklüğü", "Diğerlerinden belirgin büyük AS (compile/test süresi)", M, "-", as_size),
    Check("LICENSES", "Lisanslar", "Kademeli upgrade paketleri ve opsiyon lisansları", M, f"{SW_UPDATE}, 4.3", licenses),
    Check("CAS_PH", "Arşiv (CAS / PH)", "CAS desteklenmiyor, PH/IS OS gereksinimi", M, "-", cas_ph),
    Check("BLK_CUSTOM", "Custom block'lar", "Custom block'lar (CFC kontrolü gerekli)", M, "-", blk_custom),
    Check("BLK_UNUSED", "Kullanılmayan block'lar", "Instance'sız custom/library FB'ler", L, "-", blk_unused),
    Check("BLK_SYMBOL_MISMATCH", "Symbol ↔ block", "Symbol'de olup block'u olmayan block'lar", M, "-", blk_symbol),
    Check("COMM_AS_AS", "AS-AS haberleşme", "AS-AS / multiproject'ler arası haberleşme", M, "-", comm_as_as),
    # --- OS ---
    Check("OS_CUSTOM_TYPICALS", "Custom typicals", "Custom picture object template'leri", M, f"{SW_UPDATE}, 9.6.4", os_typicals),
    Check("OS_OPC", "OPC", "OPC konfigürasyonu / harici OPC client", M, "-", os_opc),
    Check("OS_PO_INCREASE", "PO lisansı", "Update sonrası OS RT PO sayısı artabilir", L, f"{SW_UPDATE}, 4.3", os_po),
    Check("OS_MIGRATION_VOLUME", "OS migration", "OS migration hacmi", L, f"{SW_UPDATE}, 9.2.2", os_volume),
    # --- Tutarlılık (ayrı analiz maddesi) ---
    Check("CONS_ES_SERVER", "ES ↔ OS server tutarlılığı", "ES OS projesi ile OS PC kopyası farkları", H, "-", cons_es_server),
    Check("CONS_CLIENTS", "Client tutarlılığı", "Client'lar arası içerik farkları", M, "-", cons_clients),
    Check("CONS_BACKUP_DATES", "Farklı tarihli backup'lar", "Aynı projenin farklı tarihli kopyaları", M, "-", cons_backups),
]


def get_check(check_id: str) -> Check:
    for c in CHECKS:
        if c.id == check_id:
            return c
    raise KeyError(check_id)


def run_checks(an) -> None:
    for c in CHECKS:
        if c.func is None:
            an.not_checked.append((c.id, "henüz implement edilmedi"))
            continue
        try:
            an.findings.extend(c.func(c, an))
        except NotChecked as e:
            an.not_checked.append((c.id, str(e)))
        except Exception as e:  # noqa: BLE001  - bir kontrol hatası raporu durdurmaz
            an.not_checked.append((c.id, f"hata: {e}"))
    order = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
    an.findings.sort(key=lambda f: order[f.severity])
