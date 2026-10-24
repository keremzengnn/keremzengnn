"""
Analiz Excel'i (rapor.xlsx) — 8 sayfa, Siemens renkleri (header #009999), Arial, freeze pane, filtre, sayılar #,##0,
özet sayfası formüllerle diğer sayfalara bağlı. Yeni analizler bu 8 sayfaya yerleşir (sayfa sayısı artırılmaz).

  1 Ozet                 genel bilgiler, lisans ihtiyacı (+toplam), ENG↔SRV fark özeti (COUNTIFS), hazırlık listesi, bulgular
  2 AS_Envanter          AS başına OS connection, CPU, CP, F, DP slave, FB/FC/DB, APL author, opsiyonlar (+toplam)
  3 HW_Moduller          Released Modules durumu + projedeki / listedeki FW (kırmızı: listede yok, sarı: GSD)
  4 Custom_Blocklar
  5 Instance_Sayilari
  6 OS_WinCC             A) OS projeleri  B) connection ve tag sayıları (+MP toplamları)  C) alarm class  D) SFC / LM
  7 ENG_SRV1_Farklar     picture/script, tag, alarm, alarm metni farkları tek listede (Kategori sütunu)
  8 Acik_Konular_Kaynak  müşteri soruları, eksik veriler, açık konular, kaynaklar
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .fmt import fmt_month, fmt_num
from .analyze import Analysis, author_version, staged_path_from
from .checks import CHECKS
from .model import Severity
from .mlfb_info import describe
from .parsers.subblk import lang_name
from .report import GENERIC_OPEN_ITEMS, REFERENCES, _natkey, decision, manual_items, prep_list, tr_upper
from .xlsx import Cell, Workbook

PETROL = "009999"
SHEETS = ["Ozet", "AS_Envanter", "HW_Moduller", "Custom_Blocklar", "Instance_Sayilari", "OS_WinCC",
          "ENG_SRV1_Farklar", "Acik_Konular_Kaynak", "Backup_Yeterlilik", "Teklif_Girdileri", "Bulgular",
          "Analiz_Edilemeyenler"]
# DIAGNOSTICS arşivi varsa ayrıca "Diagnostics" sayfası eklenir.
DIFF_CATEGORIES = ["Picture / script", "Connection", "Tag", "Tag adres", "Alarm", "Alarm metni", "Alarm class"]


def _num(v) -> int | str:
    try:
        return int(str(v).replace(".", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return v if v else ""


def _no_data(rows: list[list], reason: str, header_index: int | None = None) -> list[list]:
    """Boş sayfa olmasın: tablo sadece başlıktan ibaretse tek satır "Veri yok: <neden>" eklenir."""
    if header_index is None:
        if len(rows) <= 1:
            rows.append([Cell(f"Veri yok: {reason}", "gray")])
    elif len(rows) == header_index + 1:
        rows.append([Cell(f"Veri yok: {reason}", "gray")])
    return rows


# Bulgular: Durum hücresi rengi
STATUS_STYLE = {"BLOCKER": "red", "RİSK": "orange", "VERİ YOK": "gray"}


def _mps(an: Analysis) -> list[str]:
    mps = sorted({an.mp_of(b.info.project) for b in an.block_folders if b.counts}
                 | {an.mp_of(o.info.project) for o in an.os_projects if o.in_es})
    return mps or ["-"]


# ---------------------------------------------------------------------------

def _diff_rows(an: Analysis) -> list[list]:
    rows = []
    for d in an.os_diffs:
        comp = f"{d.a_label} ↔ {d.b_label}"
        for lst, status in ((d.only_a, f"sadece {d.a_label}"), (d.only_b, f"sadece {d.b_label}"),
                            (d.newer_a, f"{d.a_label} daha yeni"), (d.newer_b, f"{d.b_label} daha yeni")):
            for x in d.relevant(lst):
                rows.append(["Picture / script", comp, x, status, ""])
    for d in an.export_diffs:
        comp = f"{d.a} ↔ {d.b}"
        for a, x, y in d.conn_pairs:
            rows.append(["Connection", comp, f"{x} / {y}", "aynı AS, farklı ad (beklenen)", a])
        rows += [["Connection", comp, n, f"sadece {d.a}", ""] for n in d.conn_only_a]
        rows += [["Connection", comp, n, f"sadece {d.b}", ""] for n in d.conn_only_b]
        rows += [["Tag", comp, n, f"sadece {d.a}", ""] for n in d.tag_names_only_a]
        rows += [["Tag", comp, n, f"sadece {d.b}", ""] for n in d.tag_names_only_b]
        rows += [["Tag adres", comp, n, "connection/adres farklı", f"{x} | {y}"] for n, x, y in d.tags_changed]
        for al, side in ((d.alarm_rows_only_a, d.a), (d.alarm_rows_only_b, d.b)):
            rows += [["Alarm", comp, a.number, f"sadece {side}", f"{a.message_tag} | {a.msg_class} | {a.area or '(area yok)'} | "
                      f"{a.event}"] for a in al]
        rows += [["Alarm metni", comp, n, "metin farklı", f"{x} | {y}"] for n, x, y in d.alarm_text_diff]
        rows += [["Alarm class", comp, n, "class farklı", f"{x} | {y}"] for n, x, y in d.alarm_class_diff]
    return rows


def build_workbook(an: Analysis, meta=None) -> Workbook:
    wb = Workbook(header_color=PETROL)
    diff_rows = _diff_rows(an)
    n_diff = len(diff_rows)
    diff_ref = f"ENG_SRV1_Farklar!$A$2:$A${max(2, n_diff + 1)}"

    # ---------------- 1 Ozet ----------------
    title, last = decision(an)
    fam = an.pcs7_family
    rows: list[list] = [["Konu", "Değer", "Not"]]
    headers = {0}
    for k, v in [("Kaynak", an.source), ("Analiz tarihi", an.created), ("Sonuç", title.replace("Sonuç: ", "")),
                 ("Mevcut versiyon", f"PCS 7 {fam}" if fam else "tespit edilemedi"),
                 ("Hedef", an.target.replace("SP", " SP")),
                 ("İç prosedür yolu", f"{fam or '?'} → {' → '.join(staged_path_from(fam))}"),
                 ("Multiproject", ", ".join(tr_upper(m) for m in _mps(an))),
                 ("AS (dolu block klasörü)", sum(1 for b in an.block_folders if b.counts)),
                 ("OS projesi (ES içinde)", sum(1 for o in an.os_projects if o.in_es))]:
        rows.append([k, v, ""])
    rows.append([])
    headers.add(len(rows))
    rows.append(["Lisans ihtiyacı (manuel: PCS 7 License Information)", "AS RT PO", "OS PO", "Archive tag"])
    first = len(rows) + 1
    m = an.manual
    for mp in _mps(an):
        vals = m.per_mp.get(mp) or m.per_mp.get(tr_upper(mp)) or ({"as_rt_po": m.as_rt_po, "os_po": m.os_po,
                                                                     "archive_tags": m.archive_tags}
                                                                    if len(_mps(an)) == 1 else {})
        rows.append([tr_upper(mp)] + [_num(vals.get(k)) if vals.get(k) else "eksik" for k in ("as_rt_po", "os_po", "archive_tags")])
    lastr = len(rows)
    rows.append([Cell("Toplam", "bold")] + [Cell(None, "bold_num", f"SUM({c}{first}:{c}{lastr})") for c in "BCD"])
    rows.append(["Not: V10 update'inde OS RT PO sayısı artabilir [1, Bölüm 4.3]; mevcut lisans key'leri (ALM) ile karşılaştırılmalı. "
                 "SFC visualization lisans ihtiyacı teyit edilmeli."])
    rows.append([])
    headers.add(len(rows))
    rows.append(["OS projeleri fark özeti (ENG_SRV1_Farklar)", "Adet", ""])
    cnt = Counter(r[0] for r in diff_rows)
    for cat in DIFF_CATEGORIES:
        rows.append([cat, Cell(cnt.get(cat, 0), "num", f'COUNTIFS({diff_ref},"{cat}")'), ""])
    rows.append([])
    headers.add(len(rows))
    rows.append(["Upgrade hazırlık listesi", "", ""])
    rows += [[Cell(x, "wrap"), "", ""] for x in prep_list(an)]
    rows.append([])
    headers.add(len(rows))
    rows.append(["Öne çıkan bulgular", "Etki", "Açıklama"])
    for f in an.findings:
        if f.severity in (Severity.HIGH, Severity.MEDIUM):
            rows.append([f.title + (f" ({f.scope})" if f.scope else ""),
                         Cell(f.severity.value, "red" if f.severity is Severity.HIGH else "yellow"), f.detail])
    wb.add_sheet("Ozet", rows, header_rows=headers, freeze=1, widths=[48, 22, 16, 100])

    # ---------------- 2 AS_Envanter ----------------
    hdr = ["AS", "MP", "OS connection", "CPU", "CP", "F-capable / F-System", "DP/PN slave", "GSD", "FB", "FC", "DB", "OB",
           "APL author dağılımı", "Opsiyonlar", "Klasör / eşleme"]
    rows = [hdr]
    conns_by_as: dict[str, list[str]] = {}
    for w in an.wincc.values():
        for c in w.connections:
            if c.as_label:
                conns_by_as.setdefault(c.as_label, []).append(f"{w.name}:{c.name}")
    for b in sorted((b for b in an.block_folders if b.counts), key=lambda b: _natkey(b.as_label)):
        st = next((s for s in an.stations if s.project == b.info.project), None)
        apl = ", ".join(f"{a} ({n})" for a, n in sorted(b.libraries.get("APL", {}).items()))
        rows.append([b.as_label, tr_upper(an.mp_of(b.info.project)), ", ".join(conns_by_as.get(b.as_label.upper(), [])),
                     "; ".join(f"{(n or o).strip()} {fw}".strip() for o, fw, n in st.cpus) if st else "",
                     "; ".join(f"{(n or o).strip()} {fw}".strip() for o, fw, n in st.cps) if st else "",
                     ("F-capable" if st and st.f_capable else "") + (" / F-System" if "F-System" in b.features else ""),
                     ", ".join(f"{k} ×{v}" for k, v in st.slaves.items()) if st else "",
                     ", ".join(f"{k} ×{v}" for k, v in st.gsd.items()) if st else "",
                     b.counts.get("FB", 0), b.counts.get("FC", 0), b.counts.get("DB", 0), b.counts.get("OB", 0),
                     apl, ", ".join(x for x in b.features if x not in ("APL", "Basis")), f"{b.info.path} ({b.mapping})"])
    n = len(rows)
    if n > 1:
        rows.append([Cell("Toplam", "bold")] + [""] * 7 + [Cell(None, "bold_num", f"SUM({c}2:{c}{n})") for c in "IJKL"])
    else:
        _no_data(rows, "backup'ta dolu block klasörü (AS) bulunamadı")
        n = len(rows)
    wb.add_sheet("AS_Envanter", rows, header_rows={0}, filter_row=0, filter_last=n - 1, freeze=1)

    # ---------------- 3 HW_Moduller ----------------
    rows = [["MLFB / GSD", "Model / açıklama", "FW (proje)", "Listedeki FW", "FW uyumu", "Released Modules durumu", "Discontinued", "Adet",
             "AS", "Tür", "Bölüm / not"]]
    for mm in sorted(an.hw_matches, key=lambda x: (x.kind != "modül", "bulunamadı" not in x.status, x.order)):
        style = "yellow" if mm.kind != "modül" else "red" if "bulunamadı" in mm.status or mm.fw_status == "uyumsuz" else ""
        rows.append([Cell(v, style) for v in (mm.order, describe(mm.order)[0], mm.fw, mm.listed_fw, mm.fw_status, mm.status, mm.discontinued)]
                    + [Cell(mm.count, style), Cell(", ".join(mm.stations), style), Cell(mm.kind, style), Cell(mm.note, style)])
    _no_data(rows, "backup'ta HW Config (.cfg / .s7h) bulunamadı veya modül okunamadı")
    wb.add_sheet("HW_Moduller", rows, header_rows={0}, filter_row=0, freeze=1)

    # ---------------- 4 Custom_Blocklar ----------------
    rows = [["AS", "Block", "İsim", "Family", "Author", "Dil", "Versiyon", "Instance", "Not"]]
    for b in an.block_folders:
        for c in b.custom_blocks:
            rows.append([b.as_label, f"{c.kind}{c.number}", c.name or "(header yok)", c.family, c.author,
                         lang_name(c.lang), c.version,
                         c.instances if b.memo_available else "", "header'sız" if c.headerless else ""])
        for s in b.symbol_only:
            rows.append([b.as_label, s.split(" ", 1)[0], s.split(" ", 1)[-1], "", "", "", "", "",
                         "symbol table'da var, block klasöründe yok"])
    _no_data(rows, "custom block bulunamadı (sadece library block'ları) veya block klasörü yok")
    wb.add_sheet("Custom_Blocklar", rows, header_rows={0}, filter_row=0, freeze=1)

    # ---------------- 5 Instance_Sayilari ----------------
    rows = [["AS", "Block", "İsim", "Library", "Author", "Versiyon (author)", "Instance"]]
    for b in an.block_folders:
        for nr, n in sorted(b.fb_instances.items(), key=lambda kv: -kv[1]):
            name, lib, author = b.fb_library.get(nr, ("", "", ""))
            rows.append([b.as_label, f"FB{nr}", name, lib, author, author_version(author), n])
    _no_data(rows, "FB instance bulunamadı (SUBBLK.DBT yok veya instance DB yok)")
    wb.add_sheet("Instance_Sayilari", rows, header_rows={0}, filter_row=0, freeze=1)

    # ---------------- 6 OS_WinCC ----------------
    rows = [[Cell("A) OS projeleri", "section")], ["MP", "OS projesi", "Rol", "Rol notu", "Yer", "Client grubu", "Dosya", "Custom picture",
                                  "Faceplate", "Script", "SFC görselleştirme", "Arşiv segment", "Klasör"]]
    headers = {1}
    group_of = {}
    for i, g in enumerate(an.client_groups, 1):
        for mbr in g.members:
            group_of[mbr] = f"G{i}" + (" (referans)" if g.is_reference else "")
    for o in sorted(an.os_projects, key=lambda o: (not o.in_es, o.info.name)):
        s = o.sfc or {}
        rows.append([tr_upper(an.mp_of(o.info.project)) if o.in_es else "-", o.info.name, o.role, o.role_note,
                     "ES" if o.in_es else "OS PC kopyası", group_of.get(o.info.path, ""), o.info.n_files,
                     o.pictures.get("custom", 0), o.pictures.get("faceplate", 0) + o.pictures.get("f_faceplate", 0),
                     len(o.scripts),
                     (f"{s.get('charts', 0)} chart" if s.get("filled") else "boş şablon") if s.get("present") else "-",
                     len((o.archives or {}).get("segments", [])), o.info.path])
    _no_data(rows, "backup'ta WinCC OS projesi (.mcp) bulunamadı", header_index=1)
    rows.append([])
    rows.append([Cell("B) Connection ve tag sayıları", "section")])
    headers.add(len(rows))
    rows.append(["MP", "OS", "Connection", "Tür", "AS", "Driver", "Channel unit", "Parametre", "OPC üretici", "Tag",
                 "Struct tag", "Toplam"])
    first = len(rows) + 1
    mp_of_os = {o.info.name: tr_upper(an.mp_of(o.info.project)) for o in an.os_projects if o.in_es}
    for name, w in sorted(an.wincc.items()):
        for c in w.connections:
            r = len(rows) + 1
            rows.append([mp_of_os.get(name, "-"), name, c.name, c.kind, c.as_label, c.driver, c.unit, c.parameter,
                         c.opc_vendor, c.tags, c.struct_tags, Cell(c.tags + c.struct_tags, "num", f"J{r}+K{r}")])
    lastr = len(rows)
    if an.wincc:
        for mp in sorted(set(mp_of_os.get(n, "-") for n in an.wincc)):
            rows.append([Cell(f"{mp} toplam", "bold"), "", "", "", "", "", "", "", ""]
                        + [Cell(None, "bold_num", f'SUMIF($A${first}:$A${lastr},"{mp}",{c}${first}:{c}${lastr})')
                           for c in "JKL"])
        for name, w in sorted(an.wincc.items()):
            rows.append([Cell(f"{name}: DmTag {fmt_num(w.dm_tag)} + DmStructtag {fmt_num(w.dm_structtag)} = {fmt_num(w.total_tags)} tag; "
                              f"alarm {fmt_num(w.alarms)}", "bold")])
    else:
        rows.append(["WinCC Configuration Studio export'u yok (Tag Management / Alarm Logging → Export)."])
    rows.append([])
    rows.append([Cell("C) Alarm class / area", "section")])
    headers.add(len(rows))
    rows.append(["OS", "Tür", "Değer", "Adet"])
    for name, w in sorted(an.wincc.items()):
        rows += [[name, "Message class", k, v] for k, v in w.alarm_classes.most_common()]
        rows += [[name, "Area", k, v] for k, v in w.alarm_areas.most_common(15)]
    _no_data(rows, "backup'ta WinCC export yok (Alarm Logging → Export)", header_index=max(headers))
    rows.append([])
    rows.append([Cell("D) SFC / Logic Matrix", "section")])
    headers.add(len(rows))
    rows.append(["Konu", "Kapsam", "Durum / kanıt"])
    for o in an.os_projects:
        s = o.sfc or {}
        if s.get("present") and o.in_es:
            grp = ", ".join(f"{k} ×{v}" for k, v in s["groups"].most_common(10))
            rng = (f"{fmt_month(s['first'])} → {fmt_month(s['last'])}"
                   if s.get("first") else "")
            rows.append(["SFC görselleştirme", o.info.name, f"{s['charts']} chart, {len(s['groups'])} grup {rng}; {grp}"
                         if s.get("filled") else "boş şablon (görselleştirme verisi yok)"])
    for asl, st in an.lm_status.items():
        rows.append(["Logic Matrix", asl, f"{st['status']} (LM block tipi {st['blocks']}, instance {st['instances']}, "
                                          f"WinCC LM referansı {st['wincc']})"])
    rows.append(["Not", "", "@pg_@sfc_rts*.pdl ve @PG_LM_* faceplate'leri her OS'te standart gelir: kullanım kanıtı değildir."])
    wb.add_sheet("OS_WinCC", rows, header_rows=headers, freeze=0)

    # ---------------- 7 ENG_SRV1_Farklar ----------------
    rows = [["Kategori", "Karşılaştırma", "Öğe", "Durum", "Detay"]] + diff_rows
    _no_data(rows, "karşılaştırılacak OS projesi çifti / WinCC export yok veya fark bulunmadı")
    wb.add_sheet("ENG_SRV1_Farklar", rows, header_rows={0}, filter_row=0, freeze=1)

    # ---------------- 8 Acik_Konular_Kaynak ----------------
    rows = [["Tür", "Konu", "Detay"]]
    for k, v in manual_items(an):
        rows.append(["Müşteri sorusu" if k == "Müşteri sorusu" else "Manuel giriş",
                     v if k == "Müşteri sorusu" else k, "" if k == "Müşteri sorusu" else v])
    rows += [["Açık konu", x, ""] for x in an.open_items]
    titles = {c.id: c.title for c in CHECKS}
    rows += [["Kontrol edilemedi", titles.get(i, i), why] for i, why in an.not_checked]
    rows += [["Açık konu", x, ""] for x in GENERIC_OPEN_ITEMS]
    rows += [["Uyarı", w, ""] for w in an.warnings]
    rows += [["Kaynak", f"{r[0]} {r[1]}", f"{r[2]} ({r[3]})"] for r in REFERENCES]
    _no_data(rows, "açık konu yok")
    wb.add_sheet("Acik_Konular_Kaynak", rows, header_rows={0}, filter_row=0, freeze=1)

    # ---------------- 9-11 Readiness ----------------
    from .readiness import backup_coverage, findings_rows, quote_inputs
    sty = {"Var": "green", "Kısmen": "yellow", "Yok": "yellow", "VERİ YOK": "red"}
    rows = [["Kontrol", "Durum", "Kanıt", "Analize etkisi"]]
    rows += [[Cell(r[0]), Cell(r[1], sty.get(r[1], "")), Cell(r[2]), Cell(r[3])] for r in backup_coverage(an)]
    _no_data(rows, "backup kapsamı değerlendirilemedi")
    wb.add_sheet("Backup_Yeterlilik", rows, header_rows={0}, freeze=1, widths=[40, 12, 50, 80])
    rows = [["Girdi", "Değer", "Kaynak / güven"]]
    rows += [[Cell(r[0]), Cell(r[1], "red" if r[1] == "VERİ YOK" else ""), Cell(r[2])] for r in quote_inputs(an)]
    _no_data(rows, "teklif girdisi üretilemedi")
    wb.add_sheet("Teklif_Girdileri", rows, header_rows={0}, freeze=1, widths=[36, 70, 40])
    from .readiness import FINDINGS_COLUMNS
    rows = [list(FINDINGS_COLUMNS)]
    i_status, i_conf, i_detail = (FINDINGS_COLUMNS.index(c) for c in ("Durum", "Güven", "Detay"))
    for r in findings_rows(an):
        assumption = r[i_conf] not in ("KANIT", "-")       # ÇIKARIM -> sarı (Güven + Detay)
        cells = [Cell(v) for v in r]
        cells[i_status].style = STATUS_STYLE.get(r[i_status], "")
        if assumption:
            cells[i_conf].style = cells[i_detail].style = "yellow"
        rows.append(cells)
    _no_data(rows, "bulgu yok ve kontrol edilemeyen kontrol yok")
    wb.add_sheet("Bulgular", rows, header_rows={0}, filter_row=0, freeze=1, widths=[8, 28, 10, 10, 12, 100, 60, 50])
    rows = [["Modül", "Dosya (backup içi tam yol)", "Neden", "Alan / ofset", "Ham değer"]] + an.unknown.rows()
    _no_data(rows, "okunamayan / tanınmayan dosya kaydı yok")
    wb.add_sheet("Analiz_Edilemeyenler", rows, header_rows={0}, filter_row=0, freeze=1, widths=[14, 70, 90, 14, 20])
    if an.diag is not None:
        dg = an.diag
        rows = [["Tür", "Zaman / önem", "Kategori / güven", "Metin", "Kaynak"]]
        rows += [["Bulgu", f.severity, f.confidence, f"{f.title}: {f.detail}", f.source] for f in dg.findings]
        rows += [["Olay", ev.ts, ev.category, ev.text, ev.source] for ev in dg.events]
        _no_data(rows, "DIAGNOSTICS arşivinde bulgu / olay yok")
        wb.add_sheet("Diagnostics", rows, header_rows={0}, filter_row=0, freeze=1, widths=[10, 20, 14, 100, 50])
    return wb


def write_excel(an: Analysis, path: Path, meta=None) -> Path:
    return build_workbook(an, meta).save(path)
