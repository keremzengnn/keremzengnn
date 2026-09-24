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


def _f(c: "Check", detail: str, sources=(), confidence=Confidence.HIGH, severity=None) -> Finding:
    srcs = list(sources) + ([c.manual_ref] if c.manual_ref != "-" else [])
    return Finding(c.id, c.topic, severity or c.severity, detail, srcs, confidence)


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
    bad = [m for m in an.hw_matches if "bulunamadı" in m.status or "FW" in m.status]
    if not bad:
        return []
    lines = [f"{m.order} {m.fw} ×{m.count} ({m.status}; {', '.join(m.stations)})" for m in bad]
    return [_f(c, f"{len(bad)} MLFB/FW listede teyit edilemedi: " + _short(lines, 6), [an.released_list])]


def hw_f_export_missing(c, an):
    out = []
    for b in an.block_folders:
        if "F-System" not in b.features and not b.f_driver_instances:
            continue
        sts = [s for s in an.stations if s.project == b.info.project]
        if not sts:
            out.append(_f(c, f"{b.as_label}: F-System var, HW Config bu AS ile eşlenemedi -> F-I/O kontrol edilemedi",
                          [b.info.dbf], Confidence.LOW))
            continue
        for s in sts:
            if s.f_modules == 0:
                out.append(_f(c, f"{b.as_label}: F-block/F-driver var ({b.f_driver_instances} F-channel driver instance) "
                                 f"ama {s.name} HW export'unda F-I/O yok. Export S7 F Configuration Pack kurulu "
                                 f"PC'den tekrar alınmalı.", [b.info.dbf, s.source]))
    return out


def hw_gsd(c, an):
    out = []
    for s in an.stations:
        if s.gsd:
            out.append(_f(c, f"{s.name}: " + _short(f"{k} ×{n}" for k, n in s.gsd.items()), [s.source]))
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
            out.append(_f(c, f"{b.as_label}: {lib} " + ", ".join(vs), [b.info.dbf]))
    return out


def _feature(c, an, feat, text):
    hits = [b for b in an.block_folders if feat in b.features]
    if not hits:
        return []
    return [_f(c, f"{', '.join(b.as_label for b in hits)}: {text}", [b.info.dbf for b in hits])]


def lib_v71(c, an):
    return _feature(c, an, "PCS 7 Lib V7.1", "PCS 7 Library V7.1 block'ları var. Kullanılmaya devam edecekse ES'e Library V7.1 SP3 Upd4, "
                                             "ES ve tüm OS'lara Faceplates V7.1 SP3 Upd1 kurulmalı.")


def lib_lm(c, an):
    return _feature(c, an, "Logic Matrix", "Logic Matrix block'ları var; upgrade without new functionality desteklenmez -> library update zorunlu.")


def lib_sfc(c, an):
    out = _feature(c, an, "SFC", "SFC system block'ları (FB245/246/300, FC240…250) güncel SFC library'den elle kopyalanıp complete compile yapılmalı.")
    for f in out:
        n = sum(b.fb_instances.get(300, 0) for b in an.block_folders if "SFC" in b.features)
        if n:
            f.detail += f" SFC instance (FB300): {n}."
    return out


def lib_f(c, an):
    hits = [b for b in an.block_folders if "F-System" in b.features]
    if not hits:
        return []
    vs = _lib_versions(an, "S7 F Systems Failsafe Blocks")
    fp = sorted({x for o in an.os_projects for x in o.f_faceplates})
    d = (f"{', '.join(b.as_label for b in hits)}: F-System. Failsafe Blocks: "
         + (", ".join(sorted(vs)) or "versiyon tespit edilemedi") + ". F-program kapsamı ve S7 F Systems Readme ile uyumluluk teyit edilmeli.")
    if fp:
        d += " F faceplate'leri: " + _short(fp, 5) + "."
    return [_f(c, d, [b.info.dbf for b in hits])]


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
        out.append(_f(c, f"{b.as_label}: {len(items)} custom FB: " + _short(items, 6), [b.info.dbf]))
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
                          Confidence.LOW))
    return out


def blk_symbol(c, an):
    out = []
    for b in an.block_folders:
        if b.symbol_only:
            out.append(_f(c, f"{b.as_label}: symbol'de olup block klasöründe olmayan: {_short(b.symbol_only, 6)}",
                          [b.symbol_source, b.info.dbf], Confidence.LOW))
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
                          [b.info.dbf], Confidence.LOW))
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
