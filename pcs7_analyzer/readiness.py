"""
Upgrade hazırlık (readiness) tabloları — `Analysis` üzerinden, yeni okuma yapmaz.

- backup_coverage: backup'ta ne var / ne yok + eksikliğin analize etkisi (önce bu okunmalı)
- quote_inputs:    teklif için girdiler (AS / OS / PO / SFC / F / tag-alarm), her biri kaynaklı
- findings_rows:   tüm bulgular kaynak + güven (KANIT / ÇIKARIM) ile

Durum değerleri: "Var", "Kısmen", "Yok", "VERİ YOK" (backup'tan okunamaz, kullanıcıdan istenir).
"""
from __future__ import annotations

from collections import Counter

from .mlfb_info import describe
from .model import Confidence

VAR, KISMEN, YOK, VERI_YOK = "Var", "Kısmen", "Yok", "VERİ YOK"
KANIT, CIKARIM, VARSAYIM = "KANIT", "ÇIKARIM", "VARSAYIM"


def conf_label(c) -> str:
    """Confidence -> KANIT (dosyada birebir) / ÇIKARIM (heuristic, teyit edilmeli)."""
    return KANIT if c in (Confidence.HIGH, Confidence.HIGH.value) else CIKARIM


def _ex(items, n=2) -> str:
    items = list(items)
    if not items:
        return "-"
    return ", ".join(items[:n]) + (f" (+{len(items) - n})" if len(items) > n else "")


def backup_coverage(an) -> list[list[str]]:
    """[kontrol, durum, kanıt (adet / örnek path), analize etkisi]."""
    d = an.discovery
    mk = d.markers or {}
    rows = []

    def row(name, ok, evidence, impact_missing, partial=False, impact_partial=""):
        st = KISMEN if (ok and partial) else VAR if ok else YOK
        rows.append([name, st, evidence, impact_partial if st == KISMEN else "-" if ok else impact_missing])

    row("Multiproject / proje (.s7f / .s7p)", bool(d.projects),
        f"{len(d.multiprojects)} multiproject, {len(d.projects)} proje: {_ex(d.projects)}",
        "Retrieve edilebilir STEP 7 projesi yok: proje yapısı ve AS listesi çıkarılamaz")
    row("Library projesi (.s7l, master data)", bool(d.libraries), f"{len(d.libraries)}: {_ex(d.libraries)}",
        "Master data library backup'ta değil: OB_DIAG / OR_M_16 / OR_M_32 kontrolü sadece AS block klasörlerinde yapıldı")
    full = [b for b in d.block_folders if not b.is_empty]
    no_dbt = [b for b in full if not b.dbt]
    row("Block klasörleri (ombstx/offline)", bool(full),
        f"{len(full)} dolu, {len(d.block_folders) - len(full)} boş",
        "Block / library / instance analizi yapılamaz",
        partial=bool(no_dbt), impact_partial=f"{len(no_dbt)} klasörde SUBBLK.DBT yok: instance sayıları eksik")
    row("HW Config export (.cfg)", bool(d.cfg_exports), f"{len(d.cfg_exports)}: {_ex(d.cfg_exports)}",
        "Rack/slot, adres, F-capable, PDM bilgisi yok; HW sadece .s7h'den (MLFB/FW) okunur. "
        "F-I/O export'ta görünmeyebilir (F Configuration Pack)")
    row("HW backup içi (.s7h)", bool(d.s7h_files), f"{len(d.s7h_files)}", "Export da yoksa AS hardware'i çıkarılamaz")
    row("Symbol table (SYMLIST.DBF / .asc)", bool(d.symbol_tables or d.symbol_exports),
        f"{len(d.symbol_tables)} SYMLIST, {len(d.symbol_exports)} export",
        "Block klasörü ↔ AS eşlemesi ve header'sız F-block isimleri teyit edilemez")
    src_n = mk.get("s7asrcom", 0) + mk.get("awl", 0) + mk.get("scl", 0)
    row("Block source'ları (s7asrcom / AWL / SCL)", bool(src_n), f"{src_n} dosya",
        "Custom block source'u görülemedi: recompile edilebilirlik teyit edilmeli (RİSK)")
    row("CFC / SFC chart verisi (s7cfc)", bool(mk.get("s7cfc")), f"{mk.get('s7cfc', 0)} dosya",
        "Chart verisi yok", partial=bool(mk.get("s7cfc")),
        impact_partial="Var, ama chart / runtime group içeriği bu sürümde okunmuyor (FC 64 KB riski VERİ YOK)")
    row("OS projeleri (wincproj / .mcp)", bool(d.os_projects), f"{len(d.os_projects)}: {_ex(o.name for o in d.os_projects)}",
        "OS analizi yapılamaz (picture, script, OPC, SFC visualization)")
    row("OS picture'ları (.pdl)", bool(mk.get("pdl")), f"{mk.get('pdl', 0)} dosya",
        "Picture analizi yapılamaz; tahmin edilmez")
    row("OS veritabanı (.mdf)", bool(mk.get("mdf")), f"{mk.get('mdf', 0)} .mdf, {mk.get('ldf', 0)} .ldf",
        "Arşiv / SQL boyutu değerlendirilemez")
    row("Configuration Studio export (tag / alarm)", bool(d.wincc_exports), f"{len(d.wincc_exports)}",
        "Tag / alarm / connection sayıları ve 3rd party OPC VERİ YOK (.mdf export'suz okunamıyor)")
    copies = [o for o in an.os_projects if not o.in_es]
    row("OS PC'den alınmış wincproj kopyası", bool(copies), f"{len(copies)}: {_ex(o.info.path for o in copies)}",
        "ES ↔ OS server karşılaştırması yapılamaz (sadece ES içindeki OS projeleri karşılaştırıldı)")
    row("Aynı projenin farklı tarihli backup'ı", bool(an.backups), f"{len(an.backups)}",
        "Tek backup: güncellik karşılaştırması yok (normal)")
    diag_n = mk.get("sql_errorlog", 0) + mk.get("evtx", 0) + mk.get("diagnose", 0)
    row("DIAGNOSTICS (SQL ERRORLOG, evtx, WinCC diagnose)", bool(diag_n), f"{diag_n} dosya",
        "Server fail / redundancy analizi yapılamaz (gerekmiyorsa normal)")
    from pathlib import Path
    rows.append(["Released Modules listesi", VAR if an.released_list else YOK, Path(an.released_list).name if an.released_list else "-",
                 "-" if an.released_list else "HW uyumluluk kontrolü yapılamaz"])
    m = an.manual
    lic = [x for x in (m.as_rt_po, m.os_po, m.archive_tags) if x]
    rows.append(["Lisans (PO, archive tag, ALM key)", VAR if len(lic) == 3 else VERI_YOK, "manuel giriş" if lic else "-",
                 "Backup'tan okunamaz: PCS 7 License Information ve ALM key listesi müşteriden istenmeli"])
    rows.append(["Compatibility Tool çıktısı", VERI_YOK, "-",
                 "3rd party / add-on yazılım uyumu teyit edilemez; tesis PC'lerinde çalıştırılmalı"])
    rows.append(["CPU local data / F program şifresi", VERI_YOK, "-",
                 "Download'da local data yetersizliği ve F block update'te şifre sorusu öngörülemez; müşteriden alınmalı"])
    return rows


def quote_inputs(an) -> list[list[str]]:
    """[girdi, değer, kaynak / güven] — teklif hazırlığı için sayılar. Süre / fiyat üretilmez."""
    rows = []
    sts = an.stations
    cpus = Counter()
    for s in sts:
        for o, fw, n in s.cpus:
            cpus[(describe(o)[0] or n or o) + (f" {fw}" if fw else "")] += 1
    h = sum(1 for s in sts if any("-5H" in o.upper() or "5H" in (n or "").upper() for o, _, n in s.cpus))
    rows.append(["AS (HW station)", f"{len(sts)} station, {h} H-system" if sts else VERI_YOK,
                 f"HW Config / .s7h ({KANIT})" if sts else "HW bulunamadı"])
    if cpus:
        rows.append(["CPU tipleri", ", ".join(f"{k} ×{n}" for k, n in sorted(cpus.items())), KANIT])
    progs = [b for b in an.as_folders if b.counts]
    rows.append(["S7 program (dolu block klasörü)", str(len(progs)), f"ombstx ({KANIT})"])
    roles = Counter(o.role for o in an.os_projects if o.in_es)
    rows.append(["OS projeleri (ES içinde)", ", ".join(f"{r}: {n}" for r, n in sorted(roles.items())) or "-",
                 f"wincproj, rol proje adından ({CIKARIM})"])
    m = an.manual
    rows.append(["AS RT PO / OS PO / archive tag",
                 " / ".join(x or "eksik" for x in (m.as_rt_po, m.os_po, m.archive_tags)),
                 "manuel giriş" if any((m.as_rt_po, m.os_po, m.archive_tags)) else VERI_YOK])
    fb300 = sum(b.fb_instances.get(300, 0) for b in an.as_folders if "SFC" in b.features)
    charts = sum(o.sfc.get("charts", 0) for o in an.os_projects if o.in_es and o.role in ("server", "es"))
    rows.append(["SFC", f"FB300 instance {fb300}; OS'te görselleştirilen chart {charts}" if fb300 or charts else "yok",
                 f"SUBBLK + SfcRtBase/ChartLst ({KANIT})"])
    rows.append(["SFC visualization lisansı", "runtime station başına (chart başına değil); chart'lar OS RT PO'ya sayılır"
                 if charts else "-", "kullanıcı bilgisi (manual'dan teyit edilmeli)" if charts else "-"])
    f_as = [b.as_label for b in an.as_folders if "F-System" in b.features]
    rows.append(["F-System", ", ".join(f_as) if f_as else "yok", f"F-block / F-driver ({KANIT})" if f_as else "-"])
    lm = [k for k, v in an.lm_status.items() if not str(v.get("status", "")).startswith("kurulu, kullanılmıyor")]
    rows.append(["Logic Matrix (kullanılan)", ", ".join(lm) or "yok / kullanılmıyor", f"instance + WinCC ({CIKARIM})"])
    if an.wincc:
        for name, w in sorted(an.wincc.items()):
            rows.append([f"WinCC {name}: tag / alarm / connection", f"{w.total_tags} / {w.alarms} / {len(w.connections)}",
                         f"Configuration Studio export ({KANIT})"])
    else:
        rows.append(["Tag / alarm sayıları", VERI_YOK, "Configuration Studio export yok"])
    cust = sum(len(b.custom_blocks) for b in an.as_folders)
    rows.append(["Custom FB", str(cust), f"block author ({KANIT})"])
    gsd = sorted({k for s in sts for k in s.gsd})
    rows.append(["3rd party GSD cihaz tipi", str(len(gsd)), f"HW Config export ({KANIT})" if sts else "-"])
    return rows


def findings_rows(an) -> list[list[str]]:
    """[konu, önem, güven, detay, kaynak]."""
    return [[f.title, f.severity.value, conf_label(f.confidence), f.detail, "; ".join(f.sources) or "-"]
            for f in an.findings]


__all__ = ["backup_coverage", "quote_inputs", "findings_rows", "conf_label", "VAR", "KISMEN", "YOK", "VERI_YOK",
           "KANIT", "CIKARIM", "VARSAYIM"]
