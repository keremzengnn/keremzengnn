"""
Envanter modu: backup'taki her şeyi OKUR ve LİSTELER; değerlendirme / yorum yapmaz.

Çıktılar:
  envanter.xlsx     tüm tablolar (filtrelenebilir)
  envanter.html     özet + tabloların ilk satırları (Siemens renkleri)
  yapi_tanisi.txt   sadece yapı bilgisi (DBF alan adları, kayıt sayıları, dosya türleri) -> müşteri verisi İÇERMEZ;
                    formatı henüz çözülmemiş dosyalar (ör. hOmSave7 HW DBF'leri) için geliştiriciyle paylaşılabilir.
"""
from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import __version__
from ._vendor import dbfread
from .discovery import DiscoveryResult, discover_source, owner_project
from .parsers import library_summary, parse_cfg, parse_subblk, read_symbol_asc_all, read_symlist_all, scan_s7h
from .parsers.symbols import symbol_stats
from .mlfb_info import describe, label as mlfb_label
from .parsers.hwconfig import _MLFB
from .parsers.wincc import picture_kind
from .report import _css
from .source import Source, open_source
from .xlsx import Workbook

_CPU_RE = re.compile(r"^6ES7 ?(41\d|31[2-9])-")
_FW = re.compile(r"\bV\d{1,2}\.\d{1,2}(?:\.\d{1,3})?\b")
_KIND_LABEL = {"custom": "custom picture", "faceplate": "faceplate", "f_faceplate": "F faceplate",
               "typicals": "picture object template", "custom_typicals": "custom template"}
HTML_ROW_LIMIT = 300


@dataclass
class Sheet:
    name: str
    headers: list[str]
    rows: list[list] = field(default_factory=list)
    note: str = ""


@dataclass
class Inventory:
    source: str
    created: str
    discovery: DiscoveryResult
    sheets: list[Sheet] = field(default_factory=list)
    summary: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: str = ""
    block_data: list = field(default_factory=list)      # [(BlockFolderInfo, BlockFolder)] -> Mevcut durum
    blockmap_diag: str = ""                              # blockmap_tanisi.txt (isimler maskeli)

    def sheet(self, name: str) -> Sheet:
        return next(s for s in self.sheets if s.name == name)


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).isoformat(sep=" ", timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""


def _proj_dirs(d: DiscoveryResult) -> list[str]:
    return [p.rsplit("/", 1)[0] if "/" in p else "" for p in d.projects]


def _mp_of(d: DiscoveryResult, rel_dir: str) -> str:
    best = None
    for m in d.multiprojects:
        md = m.rsplit("/", 1)[0] if "/" in m else ""
        if (md == "" or rel_dir == md or rel_dir.startswith(md + "/")) and (best is None or len(md) > len(best[0])):
            best = (md, m)
    if best:
        return Path(best[1]).stem
    return Path(d.multiprojects[0]).stem if len(d.multiprojects) == 1 else ""


# ---------------------------------------------------------------------------
# Bölümler
# ---------------------------------------------------------------------------

def _projects(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    sh = Sheet("Projeler", ["Tür", "Ad", "Dosya", "Multiproject", "Dosya sayısı", "En yeni dosya tarihi"])
    for m in d.multiprojects:
        sh.rows.append(["Multiproject", Path(m).stem, m, Path(m).stem, "", ""])
    for p in d.projects:
        pd = p.rsplit("/", 1)[0] if "/" in p else ""
        files = [e for e in src.entries if e.rel.startswith(pd + "/")] if pd else src.entries
        sh.rows.append(["Proje", Path(p).stem, p, _mp_of(d, pd), len(files), _iso(max((e.mtime for e in files), default=0))])
    inv.sheets.append(sh)


def _hw_exports(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    mods = Sheet("HW modüller (export)", ["Station", "Export dosyası", "Konum", "MLFB / GSD", "Model / açıklama", "FW",
                                          "İsim (HW Config)", "Tür"],
                 note="HW Config -> Station -> Export (.cfg) dosyalarından")
    stations = Sheet("HW station (export)", ["Station", "Export dosyası", "F-capable", "PDM kullanımı",
                                             "USED_S7_VERSIONS", "Export eden STEP 7", "Subnet'ler"])
    for rel in d.cfg_exports:
        try:
            cfg = parse_cfg(src.materialize(rel))
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{rel}: okunamadı ({e})")
            continue
        m = re.match(r'STATION\s+\S+\s*,\s*"([^"]*)"', cfg["station"])
        name = m.group(1) if m else Path(rel).stem
        stations.rows.append([name, rel, cfg["f_capable"], cfg["pdm_used"], cfg["used_s7_versions"],
                              cfg["export_step7_version"], "; ".join(re.sub(r"^SUBNET\s+", "", s) for s in cfg["subnets"])])
        for mo in cfg["modules"]:
            kind = ("dahili (HSP/port)" if mo.is_internal else "GSD cihaz" if mo.is_gsd and mo.is_station_header
                    else "GSD modül" if mo.is_gsd else "slave (IM)" if mo.is_station_header else
                    "CPU" if _CPU_RE.match(mo.order_no) else "CP" if mo.order_no.startswith("6GK7") else "modül")
            mods.rows.append([name, rel, mo.location, mo.order_no, describe(mo.order_no)[0], mo.firmware, mo.name, kind])
    inv.sheets += [stations, mods]


def _hw_internal(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    """Export olmadan backup içinden HW: .s7h (MLFB + ardışık FW) ve hOmSave7 DBF'lerindeki MLFB'ler (ham tarama)."""
    sh = Sheet("HW (backup içi)", ["Proje", "Kaynak", "Yöntem", "MLFB", "Model / açıklama", "Açıklama kaynağı", "FW", "Adet"],
               note="Export'suz ham tarama: MLFB doğru; FW her zaman okunamaz; rack/slot/adres yok; adetler kayıt "
                    "sayısıdır (teyit edilmeli). Açıklama: Released Modules listesi veya MLFB ailesi (çıkarım).")
    pdirs = _proj_dirs(d)
    for rel in d.s7h_files:
        try:
            for (mlfb, fw), n in sorted(scan_s7h(src.materialize(rel)).items()):
                sh.rows.append([owner_project(rel.rsplit("/", 1)[0], pdirs), rel, ".s7h tarama", mlfb, *describe(mlfb), fw, n])
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{rel}: okunamadı ({e})")
    for e in src.entries:
        low = e.rel.lower()
        if "/homsave7/" not in "/" + low or not low.endswith(".dbf"):
            continue
        try:
            table = dbfread.DBF(str(src.materialize(e.rel)), encoding="latin1", char_decode_errors="ignore",
                                ignore_missing_memofile=True)
            found: Counter = Counter()
            for rec in table:
                vals = [v for v in rec.values() if isinstance(v, str) and v.strip()]
                text = " ".join(vals)
                for m in _MLFB.finditer(text.encode("latin1", "ignore")):
                    fw = _FW.search(text)
                    found[(m.group().decode(), fw.group() if fw else "")] += 1
            for (mlfb, fw), n in sorted(found.items()):
                sh.rows.append([owner_project(e.parent, pdirs), e.rel, "hOmSave7 DBF tarama", mlfb, *describe(mlfb), fw, n])
        except Exception as ex:  # noqa: BLE001
            inv.warnings.append(f"{e.rel}: DBF okunamadı ({ex})")
    inv.sheets.append(sh)


def _blocks(src: Source, d: DiscoveryResult, inv: Inventory, log) -> dict[str, set[int]]:
    folders = Sheet("Block klasörleri", ["Proje", "Multiproject", "Klasör", "Kayıt", "FB", "FC", "DB", "OB",
                                         "DBT (instance bilgisi)", "Symbol table (FB seti eşleşmesi)"])
    blocks = Sheet("Bloklar", ["Proje", "Klasör", "Tür", "No", "İsim", "Family", "Author", "Library", "Versiyon",
                               "Dil (BLKLANG)", "Instance DB sayısı"],
                   note="FB'ler ve isimli FC'ler (CFC'nin ürettiği isimsiz FC'ler hariç); instance = SSBPART'tan")
    inst = Sheet("Instance sayıları", ["Proje", "Klasör", "Tür", "No", "İsim", "Instance DB sayısı"])
    libs = Sheet("Library özeti", ["Proje", "Klasör", "Library", "Author", "Block sayısı"])
    dbfam = Sheet("DB family", ["Proje", "Klasör", "DB family", "DB sayısı"])
    fb_sets: dict[str, set[int]] = {}
    for i, info in enumerate(d.block_folders, 1):
        pname = Path(info.project).name
        folder = info.path.rsplit("/", 1)[-1]
        row = [pname, _mp_of(d, info.project), info.path, info.n_records]
        if info.is_empty:
            folders.rows.append(row + [0, 0, 0, 0, "boş klasör", ""])
            continue
        log(f"[{i}/{len(d.block_folders)}] {info.path} ({info.n_records} kayıt)")
        try:
            if info.dbt:
                src.materialize(info.dbt)
            bf = parse_subblk(src.materialize(info.dbf), progress=lambda n, t: log(f"  {n}/{t}"))
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"{info.path}: okunamadı ({e})")
            folders.rows.append(row + ["", "", "", "", f"HATA: {e}", ""])
            continue
        c = bf.counts
        folders.rows.append(row + [c.get("FB", 0), c.get("FC", 0), c.get("DB", 0), c.get("OB", 0),
                                   "var" if bf.memo_available else "yok (instance sayılamaz)", ""])
        fb_sets[info.path] = {b.number for b in bf.blocks if b.kind == "FB"}
        names = {b.number: b.name for b in bf.blocks if b.kind == "FB"}
        for b in bf.blocks:
            n = bf.instances_per_fb.get(("FB", b.number), 0) if b.kind == "FB" else ""
            blocks.rows.append([pname, folder, b.kind, b.number, b.name, b.family, b.author, b.library, b.version,
                                b.language, n if bf.memo_available else ""])
        for (kind, nr), n in bf.instances_per_fb.most_common():
            inst.rows.append([pname, folder, kind, nr, names.get(nr, "") if kind == "FB" else "", n])
        for lib, cnt in sorted(library_summary(bf).items()):
            for author, n in sorted(cnt.items()):
                libs.rows.append([pname, folder, lib, author, n])
        for fam, n in bf.db_families.most_common():
            dbfam.rows.append([pname, folder, fam or "(boş)", n])
        if bf.unresolved_instances:
            inv.warnings.append(f"{info.path}: {bf.unresolved_instances} instance referansı çözülemedi")
        if bf.bad_records:
            inv.warnings.append(f"{info.path}: {bf.bad_records} SUBBLK kaydı okunamadı (atlandı)")
        inv.block_data.append((info, bf))
    inv.sheets += [folders, blocks, inst, libs, dbfam]
    return fb_sets


def _programs(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    """S7 program -> block klasörü -> CPU -> station (blockmap ID zinciri)."""
    from .blockmap import diagnostics as bm_diag, resolve
    bm = resolve(src, _proj_dirs(d))
    inv.blockmap_diag = bm_diag(bm)
    sh = Sheet("S7 program ↔ AS", ["Proje", "S7 program", "Block klasörü", "CPU", "Rack/slot", "Station", "Station tipi",
                                    "Symbol table", "Güven", "Kanıt"],
               note="STEP 7 proje ID zinciri (hrs/S7RESOFF, linkhrs.lnk, HRELATI1, YLNKLIST); gerçek projede teyit edilmedi "
                    "-> güven ÇIKARIM (analiz modunda HW export ile çapraz kontrol KANIT'a yükseltebilir)")
    for lk in bm.links:
        sh.rows.append([Path(lk.project).name, lk.program_name, lk.block_folder or "-", lk.cpu_name or "-",
                        f"{lk.rack}/{lk.slot}" if lk.rack is not None else "-", lk.station_name or "-",
                        lk.station_type or "-", lk.symbol_table or "-", lk.confidence, "; ".join(lk.evidence)])
    inv.sheets.append(sh)
    inv.warnings += [f"S7 program ↔ AS: {u}" for u in bm.unknown]


def _symbols(src: Source, d: DiscoveryResult, inv: Inventory, fb_sets: dict[str, set[int]]) -> None:
    sh = Sheet("Semboller", ["Kaynak", "Proje", "Eşlenen block klasörü", "Sembol", "Operand", "Veri tipi", "Yorum"],
               note="YDBs/SYMLIST.DBF (backup içi) ve .asc export'ları; block klasörü eşlemesi FB seti benzerliği (heuristic)")
    pdirs = _proj_dirs(d)
    folders = inv.sheet("Block klasörleri")
    chk = Sheet("Sembol kontrolleri", ["Kaynak", "Proje", "Kontrol", "Değer", "Detay", "Güven"],
                note="Çift operand / çift sembol adı / alan bazında adres aralığı. Bit-word çakışması (M10.0 - MW10) "
                     "kontrol edilmez.")
    for rel in d.symbol_tables + d.symbol_exports:
        try:
            p = src.materialize(rel)
            if rel.lower().endswith(".dbf"):
                rows, _ = read_symlist_all(p)
            else:
                rows = read_symbol_asc_all(p)
        except Exception as e:  # noqa: BLE001
            inv.warnings.append(f"Symbol table okunamadı: {rel} ({e})")
            continue
        sfb = set()
        for r in rows:
            m = re.match(r"(FB|SFB)\s*(\d+)$", r["operand"])
            if m and m.group(1) == "FB":
                sfb.add(int(m.group(2)))
        best, score = "", 0.0
        sym_proj = owner_project(rel.rsplit("/", 1)[0], pdirs)
        same = {pth: f for pth, f in fb_sets.items() if sym_proj != "-" and pth.startswith(sym_proj + "/")}
        for path, fbs in (same or fb_sets).items():
            if sfb and fbs:
                j = len(sfb & fbs) / len(sfb | fbs)
                if j > score:
                    best, score = path, j
        match = f"{best} (%{score * 100:.0f})" if score >= 0.5 else ""
        if match:
            for fr in folders.rows:
                if fr[2] == best:
                    fr[9] = (fr[9] + "; " if fr[9] else "") + f"{rel} (%{score * 100:.0f})"
        proj = Path(owner_project(rel.rsplit("/", 1)[0], pdirs)).name
        for r in rows:
            sh.rows.append([rel, proj, match, r["symbol"], r["operand"], r["datatype"], r["comment"]])
        st = symbol_stats(rows)
        chk.rows.append([rel, proj, "toplam sembol", st["total"], "", ""])
        for area, (n, lo, hi) in st["areas"].items():
            chk.rows.append([rel, proj, "adres aralığı", f"{area}: {n}", f"{lo} … {hi}", ""])
        for op, syms in st["dup_operand"].items():
            chk.rows.append([rel, proj, "aynı operanda birden fazla sembol", op, ", ".join(syms[:5]), "KANIT"])
        for sym, n in st["dup_symbol"].items():
            chk.rows.append([rel, proj, "aynı sembol adı birden fazla satırda", sym, f"{n} satır", "KANIT"])
        if st["unparsed"]:
            chk.rows.append([rel, proj, "tanınmayan operand", st["unparsed"], "", "-"])
    inv.sheets.append(sh)
    inv.sheets.append(chk)


def _os(src: Source, d: DiscoveryResult, inv: Inventory) -> None:
    projs = Sheet("OS projeleri", ["OS projesi", "Klasör", "Yer", "Multiproject", "WinCC build", "Dosya", "Custom picture",
                                   "Faceplate/template (@)", "VBS modül (.bmo)", "VBS action (.bac)", "C action (.pas)",
                                   "En yeni dosya"])
    files = Sheet("OS dosyaları", ["OS projesi", "Yer", "Dosya", "Kategori", "Boyut (byte)", "Değişiklik tarihi"],
                  note="Picture, script, action ve OPC dosyaları (WinCC runtime/veritabanı dosyaları hariç)")
    for o in d.os_projects:
        in_es = o.project != "-"
        projs.rows.append([o.name, o.path, "ES (proje içinde)" if in_es else "proje dışı kopya (OS PC?)",
                           _mp_of(d, o.project) if in_es else "", o.wincc_build, o.n_files, o.custom_pictures,
                           o.faceplates_and_templates, o.vbs_modules, o.vbs_actions, o.c_actions, o.newest_mtime])
        from .parsers.wincc import OS_IGNORE_EXT, normalize_os_rel
        for e in sorted((x for x in src.entries if x.rel.startswith(o.path + "/")), key=lambda x: x.rel.lower()):
            rel_orig = e.rel[len(o.path) + 1:]
            rel = normalize_os_rel(rel_orig)
            if rel.endswith(OS_IGNORE_EXT):
                continue
            k = picture_kind(rel)
            if k != "other":
                cat = _KIND_LABEL.get(k, k)
            elif rel.endswith(".bmo"):
                cat = "VBS modül"
            elif rel.endswith(".bac"):
                cat = "VBS global action"
            elif rel.endswith(".act"):
                cat = "action"
            elif rel.endswith(".pas"):
                cat = "C action"
            elif rel.startswith("opc/"):
                cat = "OPC"
            else:
                continue
            files.rows.append([o.name, "ES" if in_es else "kopya", rel_orig, cat, e.size, _iso(e.mtime)])
    inv.sheets += [projs, files]


def _file_types(src: Source, inv: Inventory) -> None:
    c: Counter = Counter()
    s: Counter = Counter()
    for e in src.entries:
        ext = Path(e.name).suffix.lower() or "(uzantısız)"
        c[ext] += 1
        s[ext] += e.size
    inv.sheets.append(Sheet("Dosya türleri", ["Uzantı", "Adet", "Toplam boyut (MB)"],
                            [[k, n, round(s[k] / 1e6, 2)] for k, n in c.most_common()]))


# Yapı tanısında açık yazılan (müşteriye özgü olmayan) STEP 7 / WinCC klasör adları
KNOWN_DIRS = {"ombstx", "offline", "online", "homsave7", "s7hstatx", "ydbs", "global", "xutils", "s7asrcom", "s7cfc",
              "s7wb53ax", "s7netze", "s7nfrdbx", "s7nfrdb", "s7nfrsbx", "s7nfrsb", "s7ncfgx", "s7ncfg", "dbmhdbx", "hrs",
              "s7hk41ax", "s7hkdmax", "s7hkimdx", "s7pfaxdb", "subblk", "wincproj", "gracs", "scriptlib", "scriptact",
              "pas", "opc", "library", "text", "prt", "cfcdata", "chartsfc", "apilog", "s7fcpnx", "s7obbsx", "amobjs",
              "ssdb", "tmp", "sfcdata", "s7topdb", "s7techx", "s7pdiagx", "s7mdb"}


def mask_path(rel: str) -> str:
    """Son 3 seviye; bilinen klasör adları açık, hex -> <hex>, sayı -> <n>, diğerleri (proje/müşteri adı olabilir) -> <klasör>."""
    parts = rel.split("/")[-3:]
    out = []
    for i, p in enumerate(parts):
        if i == len(parts) - 1:
            out.append(p.upper() if p.lower().endswith(".dbf") and len(p) <= 16 else "<dosya>")
        elif re.fullmatch(r"[0-9A-Fa-f]{8}", p):
            out.append("<hex>")
        elif p.isdigit():
            out.append("<n>")
        elif p.lower() in KNOWN_DIRS:
            out.append(p)
        else:
            out.append("<klasör>")
    return "/".join(out)


def diagnostics(src: Source) -> str:
    """Müşteri verisi içermeyen yapı raporu: DBF şemaları (alan adı/tip/uzunluk) + kayıt sayıları, dosya türleri."""
    lines = [f"PCS 7 backup yapı tanısı — pcs7_analyzer {__version__} — {datetime.now():%Y-%m-%d %H:%M}",
             "Bu dosya sadece yapı bilgisi içerir (dosya türleri, DBF alan adları, kayıt sayıları, kod dağılımları, "
             "block author kodları); sembol / block / proje adı YOKTUR.", ""]
    schemas: dict[tuple, list] = defaultdict(list)
    bad: list[str] = []
    for e in src.entries:
        if not e.name.lower().endswith(".dbf"):
            continue
        pattern = mask_path(e.rel)
        try:
            head = src.read_head(e.rel, 8192)
            if len(head) < 32:
                continue
            nrec = int.from_bytes(head[4:8], "little")
            hlen = int.from_bytes(head[8:10], "little")
            fields = []
            for i in range(32, min(hlen, len(head)) - 1, 32):
                if head[i] == 0x0D:
                    break
                fname = head[i:i + 11].split(b"\x00", 1)[0].decode("latin1", "replace")
                fields.append(f"{fname}:{chr(head[i + 11])}{head[i + 16]}")
            key_name = e.name.upper() if len(e.name) <= 16 else "<dosya>.DBF"
            schemas[(key_name, tuple(fields))].append((pattern, nrec, e.size))
        except Exception as ex:  # noqa: BLE001 - tanı dosyasında sayılır
            bad.append(f"{pattern}: {type(ex).__name__}")
    lines.append(f"## DBF şemaları ({len(schemas)} farklı şema)")
    if bad:
        lines.append(f"Okunamayan DBF başlığı: {len(bad)} (" + ", ".join(sorted(set(bad))[:10]) + ")")
    for (name, fields), occ in sorted(schemas.items()):
        recs = [o[1] for o in occ]
        pats = sorted({o[0] for o in occ})
        lines.append(f"- {name}  ×{len(occ)} dosya, kayıt: min {min(recs)} / max {max(recs)} / toplam {sum(recs)}")
        lines.append(f"    konum: {', '.join(pats[:4])}{' …' if len(pats) > 4 else ''}")
        lines.append(f"    alanlar: {', '.join(fields)}")
    ext = Counter(Path(e.name).suffix.lower() for e in src.entries)
    lines += ["", "## Dosya türleri", ", ".join(f"{k or '(yok)'}: {n}" for k, n in ext.most_common())]
    s7h = [e for e in src.entries if e.name.lower().endswith(".s7h")]
    if s7h:
        lines += ["", f"## .s7h dosyaları: {len(s7h)} adet, boyut min {min(e.size for e in s7h)} / max {max(e.size for e in s7h)} byte"]
    lines += _format_probe(src)
    return "\n".join(lines) + "\n"


# Kod alanları (müşteri verisi değil: tip / dil / işlem kodları). FC 64 KB (runtime group) ve block tipi analizleri için.
_PROBE_FIELDS = {"CT": ("BLTYPEDAD", "BLTYPESON", "OPTYPE", "LANGDAD"), "BS": ("BLOCKTYPE", "LANGUAGE"),
                 "BAUSTEIN": ("TYP",), "SUBBLK": ("SUBBLKTYP", "PASSWORD", "BLKLANG", "USERNAME"), "XR": ("OPTYPE", "OPACCESS",
                 "BLOCKTYPE")}
_VER_TOKEN = re.compile(rb"V?\d{1,2}\.\d{2}\.\d{2}\.\d{2}")


def _format_probe(src: Source, max_records: int = 200_000) -> list[str]:
    """Format çözümü için sayısal tanı: kod alanlarının değer dağılımı, .mcp versiyon dizileri (isim / içerik yok)."""
    out = ["", "## Kod alanı dağılımları (ilk dosya / tür, değerler kod; isim yok)"]
    done = set()
    for e in src.entries:
        name = e.name.upper()
        kind = ("CT" if name.startswith("CT0") else "BS" if name.startswith("BS0") else "XR" if name.startswith("XR0")
                else "BAUSTEIN" if name == "BAUSTEIN.DBF" else "SUBBLK" if name == "SUBBLK.DBF" else None)
        if not kind or not name.endswith(".DBF") or kind in done or e.size < 200:
            continue
        try:
            t = dbfread.DBF(str(src.materialize(e.rel)), encoding="latin1", char_decode_errors="replace",
                            ignore_missing_memofile=True)
            fields = [f for f in _PROBE_FIELDS[kind] if f in t.field_names]
            hist = {f: Counter() for f in fields}
            n = 0
            for rec in t:
                for f in fields:
                    if f == "USERNAME" and str(rec.get("SUBBLKTYP")).strip() not in ("00008", "00012", "00014"):
                        continue                    # author: sadece OB/FC/FB ana kayıtları (library tanıma için)
                    hist[f][str(rec.get(f)).strip()[:8] or "(boş)"] += 1
                n += 1
                if n >= max_records:
                    break
            done.add(kind)
            out.append(f"- {kind} ({n} kayıt, {mask_path(e.rel)}):")
            for f, c in hist.items():
                out.append(f"    {f}: " + ", ".join(f"{k}×{v}" for k, v in c.most_common(40)))
        except Exception as ex:  # noqa: BLE001 - tanı bölümü; hata metni yazılır
            out.append(f"- {kind}: okunamadı ({type(ex).__name__})")
    toks = Counter()
    for e in src.entries:
        if e.name.lower().endswith(".mcp") and e.size < 50_000_000:
            try:
                raw = src.read_bytes(e.rel)
                for t in set(_VER_TOKEN.findall(raw) + _VER_TOKEN.findall(raw.replace(b"\x00", b""))):
                    toks[t.decode("latin1")] += 1
            except Exception as ex:  # noqa: BLE001
                out.append(f"- .mcp okunamadı ({type(ex).__name__})")
    out += ["", "## .mcp içindeki versiyon dizileri", ", ".join(f"{k}×{v}" for k, v in toks.most_common(20)) or "-"]
    return out


# ---------------------------------------------------------------------------
# Ana giriş ve çıktılar
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mevcut durum: diğer sayfalardan tek bakışta özet (yazılım, library, hardware, OS). Yorum yok, kaynak var.
# ---------------------------------------------------------------------------

def _norm_name(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", x.lower())


_LIB_SKIP = {"custom", "custom/unknown", "CFC generated"}


def step7_label(used: str) -> str:
    """USED_S7_VERSIONS '5.5.4.9_10.1.0.1' -> 'STEP 7 V5.5 SP4'."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", used or "")
    if not m:
        return ""
    return f"STEP 7 V{m.group(1)}.{m.group(2)}" + (f" SP{m.group(3)}" if m.group(3) != "0" else "")


def _current_state(inv: Inventory, d: DiscoveryResult) -> Sheet:
    from .analyze import STEP7_TO_PCS7, WINCC_TO_PCS7, author_version
    sh = Sheet("Mevcut durum", ["Bölüm", "Konu", "Değer", "Kaynak"],
               note="Backup'ta bulunanların özeti. Versiyonlar proje dosyalarından (analizi yapan PC'nin yazılımı değil). "
                    "'aday' = tek kaynaktan çıkarım, teyit edilmeli.")
    rows = sh.rows
    names = {s.name for s in inv.sheets}

    def get(name):
        return inv.sheet(name).rows if name in names else []

    # Aynı isimli proje birden fazla yerde (farklı tarihli backup): özette sadece en yeni kopya; diğerleri sayfalarda durur
    copies: dict = defaultdict(list)
    for r in get("Projeler"):
        if r[0] == "Proje":
            copies[r[1].lower()].append((str(r[5] or ""), r[2].rsplit("/", 1)[0] if "/" in r[2] else ""))
    stale: set = set()
    dup_notes = []
    for name, cs in sorted(copies.items()):
        if len(cs) > 1:
            cs.sort(reverse=True)
            stale |= {c[1] for c in cs[1:]}
            dup_notes.append(f"{cs[0][1] or name} (en yeni, {cs[0][0]}) kullanıldı; özet dışı: "
                             + ", ".join(f"{c[1]} ({c[0]})" for c in cs[1:]))

    def plabel(proj_dir: str) -> str:
        return Path(proj_dir).name or proj_dir or "-"

    # 1) Yazılım
    for r in get("HW station (export)"):
        lab = step7_label(r[4])
        if lab:
            fam = STEP7_TO_PCS7.get(".".join(re.match(r"(\d+)\.(\d+)\.(\d+)", r[4]).groups()))
            rows.append(["Yazılım", f"STEP 7 ({r[0]})", lab + (f" (PCS 7 {fam} ailesi, aday)" if fam else ""), r[1]])
    builds: dict = defaultdict(list)
    for o in d.os_projects:
        if o.wincc_build:
            builds[o.wincc_build].append(o)
    fams = []
    for b, os_list in sorted(builds.items()):
        mm = re.match(r"V0?(\d+)\.(\d\d)", b)
        key = f"{int(mm.group(1)):02d}.{mm.group(2)}" if mm else ""
        wn, fam, ok = WINCC_TO_PCS7.get(key, (f"WinCC {b}", None, False))
        if fam:
            fams.append((fam, ok))
        names_ = ", ".join(sorted({o.name for o in os_list}))
        rows.append(["Yazılım", "WinCC", f"{wn} (build {b})" + (f" -> PCS 7 {fam}" + ("" if ok else ", aday") if fam else "")
                     + f" — {len(os_list)} OS projesi: {names_}", f"{os_list[0].path}/{os_list[0].mcp}"])
    if fams:
        best = sorted(fams, key=lambda x: not x[1])[0]
        val = best[0] + ("" if best[1] else " (aday, teyit edilmeli)")
        if len({f for f, _ in fams}) > 1:
            val += " — farklı WinCC build'leri var: " + ", ".join(sorted({f for f, _ in fams}))
        rows.insert(0, ["Yazılım", "PCS 7 versiyonu", val, "WinCC build (.mcp)"])
    for n in dup_notes:
        rows.append(["Not", "Aynı proje birden fazla yerde (farklı tarihli backup?)", n
                     + " — 'en yeni' dosya tarihine göre, teyit edilmeli", "*.s7p"])

    # 2) Library'ler (block header author'larından), proje klasörü bazında
    libs: dict = defaultdict(lambda: defaultdict(lambda: [0, set()]))
    custom: Counter = Counter()
    for info, bf in inv.block_data:
        if info.project in stale:
            continue
        lab = plabel(info.project)
        for lib, cnt in library_summary(bf).items():
            if lib in _LIB_SKIP:
                continue
            for author, n in cnt.items():
                v = author_version(author) or author or "-"
                libs[lib][v][0] += n
                libs[lib][v][1].add(lab)
        custom[(lab, "custom")] += sum(1 for b in bf.blocks if b.kind == "FB" and b.library == "custom")
        custom[(lab, "headerless")] += sum(1 for b in bf.blocks if b.kind == "FB" and b.library == "custom/unknown")
    for lib in sorted(libs):
        val = "; ".join(f"{v}: {n} block ({', '.join(sorted(ps))})" for v, (n, ps) in sorted(libs[lib].items()))
        if len(libs[lib]) > 1:
            val += " — karışık versiyon"
        rows.append(["Library", lib, val, "block header author (SUBBLK.DBF)"])
    for (lab, kind), n in sorted(custom.items()):
        if n and kind == "custom":
            rows.append(["Library", f"Custom FB ({lab})", f"{n} FB (integratör author'lu; liste: 'Bloklar', Library = custom)",
                         "block header author (SUBBLK.DBF)"])
        elif n:
            rows.append(["Library", f"Header'sız FB ({lab})", f"{n} FB (korumalı F-block veya custom; liste: 'Bloklar', "
                         "Library = custom/unknown)", "block header boş (SUBBLK.DBF)"])

    # 3) Hardware: HW Config export'larından; export'u olmayan projeler için backup içi .s7h taraması
    by_station: dict = defaultdict(lambda: {"cpu": [], "cp": [], "mod": 0, "slave": 0, "gsd": 0, "src": ""})
    for st, rel, _loc, mlfb, _desc, fw, name, kind in get("HW modüller (export)"):
        x = by_station[st]
        x["src"] = rel
        if kind == "CPU":
            x["cpu"].append(f"{name or mlfb} ({mlfb}) {fw}".strip())
        elif kind == "CP":
            x["cp"].append(f"{name or mlfb} ({mlfb}) {fw}".strip())
        elif kind == "slave (IM)":
            x["slave"] += 1
        elif kind == "GSD cihaz":
            x["gsd"] += 1
        elif kind == "modül":
            x["mod"] += 1

    def counted(items):
        return ", ".join(f"{k} ×{n}" if n > 1 else k for k, n in Counter(items).items())
    for st in sorted(by_station):
        x = by_station[st]
        rows.append(["Hardware", f"{st}: CPU", counted(x["cpu"]) or "-", x["src"]])
        if x["cp"]:
            rows.append(["Hardware", f"{st}: CP", counted(x["cp"]), x["src"]])
        rows.append(["Hardware", f"{st}: saha", f"{x['slave']} slave (IM), {x['gsd']} GSD cihaz, {x['mod']} modül",
                     x["src"]])
    exported = {_norm_name(s) for s in by_station}
    internal: dict = defaultdict(Counter)
    for proj, _rel, method, mlfb, _desc, _dsrc, fw, n in get("HW (backup içi)"):
        if method == ".s7h tarama":
            internal[proj][(mlfb, fw)] += n
    for proj, c in sorted(internal.items()):
        if proj in stale or _norm_name(Path(proj).name) in exported:
            continue                                    # eski kopya / export'u var: yukarıda
        cpus = [f"{mlfb_label(m)} {fw}".strip() + (f" ×{n}" if n > 1 else "") for (m, fw), n in sorted(c.items())
                if _CPU_RE.match(m)]
        cps = [f"{mlfb_label(m)} {fw}".strip() for (m, fw), n in sorted(c.items()) if m.startswith("6GK7")]
        lab = plabel(proj)
        rows.append(["Hardware", f"{lab}: CPU (backup içi)", ", ".join(cpus) or "-", ".s7h tarama (export yok)"])
        if cps:
            rows.append(["Hardware", f"{lab}: CP (backup içi)", ", ".join(cps), ".s7h tarama (export yok)"])
        rows.append(["Hardware", f"{lab}: diğer (backup içi)",
                     f"{len(c)} farklı MLFB/FW; rack/slot yok (liste: 'HW (backup içi)' sayfası)", ".s7h tarama"])
    if not by_station and not internal:
        rows.append(["Hardware", "-", "HW bilgisi bulunamadı: HW Config → Station → Export (.cfg) alınmalı", ""])
    # 4) OS
    for r in get("OS projeleri"):
        rows.append(["OS", r[0], f"{r[2]}; WinCC {r[4] or '-'}; custom picture {r[6]}, VBS {r[8]}+{r[9]}, C action {r[10]}",
                     r[1]])
    if not rows:
        rows.append(["-", "Backup'ta tanınan PCS 7 içeriği bulunamadı", "", ""])
    return sh


def build_inventory_source(src: Source, log=None) -> Inventory:
    log = log or (lambda m: None)
    log("Keşif...")
    d = discover_source(src)
    inv = Inventory(source=src.label, created=datetime.now().isoformat(sep=" ", timespec="minutes"), discovery=d)
    inv.warnings += d.warnings
    def stage(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 - bir bölümün hatası envanteri durdurmaz
            inv.warnings.append(f"{name} bölümü tamamlanamadı: {type(e).__name__}: {e}")
            log(f"UYARI: {name} bölümü tamamlanamadı ({e})")
            return None

    log("Projeler...")
    stage("Projeler", _projects, src, d, inv)
    log("HW Config export'ları...")
    stage("HW Config export", _hw_exports, src, d, inv)
    log("HW (backup içi tarama)...")
    stage("HW (backup içi)", _hw_internal, src, d, inv)
    log("Block klasörleri...")
    fb_sets = stage("Block klasörleri", _blocks, src, d, inv, log) or {}
    log("S7 program ↔ AS zinciri...")
    stage("S7 program ↔ AS", _programs, src, d, inv)
    log("Symbol table'lar...")
    stage("Symbol table", _symbols, src, d, inv, fb_sets)
    log("OS projeleri...")
    stage("OS projeleri", _os, src, d, inv)
    stage("Dosya türleri", _file_types, src, inv)
    log("Yapı tanısı...")
    inv.diagnostics = stage("Yapı tanısı", diagnostics, src) or ""
    names = {x.name for x in inv.sheets}

    authors = Counter()
    for r in (inv.sheet("Library özeti").rows if "Library özeti" in names else []):
        if r[2] in ("APL", "Basis Library", "S7 F Systems Failsafe Blocks", "Logic Matrix", "PCS 7 Library V7.1 COMM"):
            authors[f"{r[2]}: {r[3]}"] += r[4]
    step7 = sorted({r[4] for r in (inv.sheet("HW station (export)").rows if "HW station (export)" in names else [])
                    if r[4]})
    wincc = sorted({o.wincc_build for o in d.os_projects if o.wincc_build})
    inv.summary = [
        ("Kaynak", inv.source), ("Tarih", inv.created),
        ("Dosya / boyut", f"{d.n_files} dosya, {d.total_bytes / 1e9:.2f} GB"),
        ("Multiproject", ", ".join(Path(m).stem for m in d.multiprojects) or "-"),
        ("Proje", str(len(d.projects))),
        ("Block klasörü", f"{len(d.block_folders)} ({sum(1 for b in d.block_folders if b.is_empty)} boş)"),
        ("HW Config export (.cfg)", str(len(d.cfg_exports))), (".s7h (backup içi HW)", str(len(d.s7h_files))),
        ("Symbol table (SYMLIST.DBF / export)", f"{len(d.symbol_tables)} / {len(d.symbol_exports)}"),
        ("OS projesi", str(len(d.os_projects))),
        ("USED_S7_VERSIONS (export)", ", ".join(step7) or "-"),
        ("WinCC build (.mcp)", ", ".join(wincc) or "-"),
        ("Library author'ları", "; ".join(f"{k} ({n})" for k, n in sorted(authors.items())) or "-"),
        ("Uyarı", str(len(inv.warnings))),
    ]
    inv.sheets.insert(0, Sheet("Özet", ["Konu", "Değer"], [list(x) for x in inv.summary]))
    cur = stage("Mevcut durum", _current_state, inv, d)
    if cur is not None:
        inv.sheets.insert(0, cur)
    inv.sheets.append(Sheet("Uyarılar", ["Uyarı"], [[w] for w in inv.warnings]))
    return inv


def build_inventory(path: Path, log=None) -> Inventory:
    with open_source(path, log) as src:
        return build_inventory_source(src, log)


def write_xlsx(inv: Inventory, path: Path) -> Path:
    wb = Workbook()
    for s in inv.sheets:
        wb.add(s.name, s.headers, s.rows)
    return wb.save(path)


def render_html(inv: Inventory) -> str:
    e = html.escape
    toc, body = [], []
    for i, s in enumerate(inv.sheets):
        toc.append(f'<a href="#t{i}">{e(s.name)} ({len(s.rows)})</a>')
        rows = [["Evet" if v is True else "Hayır" if v is False else v for v in r] for r in s.rows[:HTML_ROW_LIMIT]]
        more = (f'<div class="caption">İlk {HTML_ROW_LIMIT} / {len(s.rows)} satır gösteriliyor — tam liste envanter.xlsx içinde.</div>'
                if len(s.rows) > HTML_ROW_LIMIT else "")
        table = ("<div class='tw'><table><thead><tr>" + "".join(f"<th>{e(h)}</th>" for h in s.headers) + "</tr></thead><tbody>"
                 + "".join("<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in r) + "</tr>" for r in rows)
                 + "</tbody></table></div>") if s.rows else "<p>Kayıt yok.</p>"
        body.append(f'<section id="t{i}"><h2>{e(s.name)}</h2>' + (f'<div class="note">{e(s.note)}</div>' if s.note else "")
                    + table + more + "</section>")
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>PCS 7 Envanter</title>
<style>{_css()} nav a {{ display:inline-block; margin: 2px 14px 2px 0; }}</style></head><body>
<header><div class="topline">SIMATIC PCS 7 · Proje envanteri</div><h1>Backup envanteri</h1>
<div class="sub">{e(inv.created)} · Kaynak: {e(inv.source)} · Değerlendirme içermez, sadece backup'ta bulunanlar listelenir.</div></header>
<nav>{''.join(toc)}</nav><main>{''.join(body)}</main>
<footer>pcs7_analyzer {e(__version__)} · Envanter modu</footer></body></html>"""


def write_outputs(inv: Inventory, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_xlsx(inv, out_dir / "envanter.xlsx")
    p = out_dir / "envanter.html"
    p.write_text(render_html(inv), encoding="utf-8")
    (out_dir / "yapi_tanisi.txt").write_text(inv.diagnostics, encoding="utf-8")
    if inv.blockmap_diag:
        (out_dir / "blockmap_tanisi.txt").write_text(inv.blockmap_diag, encoding="utf-8")
    return p


__all__ = ["Inventory", "build_inventory", "build_inventory_source", "write_outputs", "write_xlsx", "diagnostics"]
