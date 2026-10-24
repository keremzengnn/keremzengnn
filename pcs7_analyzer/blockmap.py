"""
Block klasörü ↔ S7 program ↔ CPU ↔ station eşlemesi (STEP 7 V5 proje dosyalarındaki ID zinciri).

Zincir (açık kaynak STEP 7 V5 proje okuyucularında kullanılan yapı; bu araçta GERÇEK projeyle henüz teyit edilmedi,
bkz. docs/blockmap_findings.md):
  1. hrs/S7RESOFF.DBF            S7 program: ID, NAME, RSRVD4_L (= hrs/linkhrs.lnk içindeki 512 byte'lık kaydın ofseti)
  2. hrs/linkhrs.lnk             kayıtta 01 60 11 00 imzasından sonraki int16 LE = block klasörü ID'si
                                 -> ombstx/offline/<ID 8 hex>/  (ombstx/offline/BSTCNTOF.DBF'de de ID olarak durur)
  3. hOmSave7/<s7hk41ax|s7hk31ax|s7hkcomx>/HRELATI1.DBF
                                 RELID = 16: SOBJID = CPU nesnesi, TOBJID = S7 program ID
                                 TOBJTYP 1314972 / 1315656 (H yedek CPU): SOBJID = CPU, TUNITID = station ID
  4. aynı klasörde HOBJECT1.DBF  ID = CPU -> NAME, SUBSTATN (rack), MODULN (slot)
  5. hOmSave7/s7hstatx/HOBJECT1.DBF  station: ID, NAME, OBJTYP (1314969 S7-300, 1314970 S7-400, 1315650 S7-400H,
                                 1315651 RTX); station HW dosyası hOmSave7/s7hstatx/<station ID hex>.s7h
  6. YDBs/YLNKLIST.DBF TOI = program ID -> SOI; YDBs/SYMLISTS.DBF _ID = SOI -> _DBPATH -> YDBs/<_DBPATH>/SYMLIST.DBF

Her adımın kanıtı (`evidence`) tutulur; eksik / tutarsız adım `unknown` listesine yazılır, tahmin yapılmaz.
Güven: zincir tam + bağımsız çapraz kontrol (HW export station adı, .s7h CPU MLFB, symbol table) tutarsa KANIT,
zincir tam ama çapraz kontrol yoksa ÇIKARIM.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ._vendor import dbfread
from ._vendor.dbfread.field_parser import FieldParser


class _TolerantParser(FieldParser):
    """STEP 7 DBF'lerinde mantıksal (L) alan \\x00 olabilir (ör. YDBs/SYMLISTS.DBF _SAVED/_DELETED): None döner, hata değil."""

    def parseL(self, field, data):
        try:
            return super().parseL(field, data)
        except ValueError:
            return None

STATION_TYPES = {1314969: "S7-300", 1314970: "S7-400", 1315650: "S7-400H", 1315651: "RTX"}
CPU_DIRS = ("s7hk41ax", "s7hk31ax", "s7hkcomx")
REL_PROGRAM = 16
REL_CPU_IN_STATION = (1314972, 1315656)
LINK_RECORD = 0x200
SIG_BLOCKFOLDER = b"\x01\x60\x11\x00"


@dataclass
class ProgramLink:
    project: str                         # proje klasörü (rel)
    program_id: int
    program_name: str
    block_folder: str | None = None      # ombstx/offline/<hex> (rel)
    cpu_name: str = ""
    rack: int | None = None
    slot: int | None = None
    station_id: int | None = None
    station_name: str = ""
    station_type: str = ""
    s7h: str | None = None
    symbol_table: str | None = None      # YDBs/<n>/SYMLIST.DBF (rel)
    evidence: list[str] = field(default_factory=list)
    confidence: str = "ÇIKARIM"          # KANIT / ÇIKARIM (cross_check sonrası)

    @property
    def label(self) -> str:
        """Rapor etiketi: station adı (yoksa S7 program adı)."""
        return self.station_name or self.program_name or f"program {self.program_id}"


@dataclass
class BlockMap:
    links: list[ProgramLink] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)       # modül | dosya | neden
    files: dict = field(default_factory=dict)              # {proje: {dosya: var/yok}}
    stats: dict = field(default_factory=dict)              # {proje: {sayısal tanı}} (isim yok)
    stations: dict = field(default_factory=dict)           # {(proje, station ID): (ad, tip)} (s7hstatx/HOBJECT1)

    def station_for_s7h(self, project: str, s7h_rel: str) -> tuple[str, str] | None:
        """hOmSave7/s7hstatx/<ID hex>.s7h -> (station adı, tip); bulunamazsa None."""
        stem = s7h_rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        try:
            sid = int(stem, 16)
        except ValueError:
            return None
        return self.stations.get((project, sid))

    def for_folder(self, path: str) -> ProgramLink | None:
        low = path.lower()
        return next((x for x in self.links if x.block_folder and x.block_folder.lower() == low), None)


def _rows(src, rel: str) -> list[dict]:
    """DBF kayıtları; alan adları büyük harfe çevrilir (silinmiş kayıtlar dbfread tarafından atlanır)."""
    t = dbfread.DBF(str(src.materialize(rel)), encoding="latin1", char_decode_errors="replace",
                    ignore_missing_memofile=True, parserclass=_TolerantParser)
    return [{k.upper(): v for k, v in r.items()} for r in t]


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _str(v) -> str:
    return str(v or "").replace("\x00", "").strip()


def resolve(src, project_dirs: list[str]) -> BlockMap:
    """Her proje klasörü için zinciri çözer. src: pcs7_analyzer.source.Source."""
    bm = BlockMap()
    index = {e.rel.lower(): e.rel for e in src.entries}
    for pd in project_dirs:
        base = f"{pd}/" if pd else ""

        def find(sub: str) -> str | None:
            return index.get((base + sub).lower())

        try:
            _resolve_project(src, pd, find, index, bm)
        except Exception as e:  # noqa: BLE001 - bir projenin hatası diğerlerini durdurmaz
            bm.unknown.append(f"blockmap | {pd or '.'} | zincir okunamadı: {type(e).__name__}: {e}")
    return bm


def _resolve_project(src, pd: str, find, index: dict, bm: BlockMap) -> None:
    files = {"hrs/S7RESOFF.DBF": find("hrs/S7RESOFF.DBF"), "hrs/linkhrs.lnk": find("hrs/linkhrs.lnk"),
             "hOmSave7/s7hstatx/HOBJECT1.DBF": find("hOmSave7/s7hstatx/HOBJECT1.DBF"),
             "YDBs/YLNKLIST.DBF": find("YDBs/YLNKLIST.DBF"), "YDBs/SYMLISTS.DBF": find("YDBs/SYMLISTS.DBF")}
    for d in CPU_DIRS:
        files[f"hOmSave7/{d}/HRELATI1.DBF"] = find(f"hOmSave7/{d}/HRELATI1.DBF")
        files[f"hOmSave7/{d}/HOBJECT1.DBF"] = find(f"hOmSave7/{d}/HOBJECT1.DBF")
    bm.files[pd or "."] = {k: ("var" if v else "yok") for k, v in files.items()}
    if not files["hrs/S7RESOFF.DBF"]:
        if any(k.startswith(f"{pd}/ombstx/offline/".lower() if pd else "ombstx/offline/") for k in index):
            bm.unknown.append(f"blockmap | {pd or '.'}/hrs/S7RESOFF.DBF | yok: S7 program listesi okunamadı")
        return

    # 1) S7 program'lar
    progs: dict[int, ProgramLink] = {}
    for r in _rows(src, files["hrs/S7RESOFF.DBF"]):
        pid = _int(r.get("ID"))
        if pid is None:
            bm.unknown.append(f"blockmap | {files['hrs/S7RESOFF.DBF']} | ID okunamadı: {r.get('ID')!r}")
            continue
        p = ProgramLink(pd, pid, _str(r.get("NAME")))
        p.evidence.append(f"{files['hrs/S7RESOFF.DBF']}: program ID {pid}")
        off = _int(r.get("RSRVD4_L"))
        p._link_offset = off  # type: ignore[attr-defined]
        progs[pid] = p

    # 2) linkhrs.lnk -> block klasörü
    if files["hrs/linkhrs.lnk"]:
        data = src.materialize(files["hrs/linkhrs.lnk"]).read_bytes()
        for p in progs.values():
            off = getattr(p, "_link_offset", None)
            if off is None or off < 0 or off >= len(data):
                bm.unknown.append(f"blockmap | {files['hrs/linkhrs.lnk']} | program {p.program_id}: ofset geçersiz ({off})")
                continue
            rec = data[off:off + LINK_RECORD]
            i = rec.find(SIG_BLOCKFOLDER)
            if i < 0 or i + 6 > len(rec):
                bm.unknown.append(f"blockmap | {files['hrs/linkhrs.lnk']} | program {p.program_id}: block klasörü imzası yok "
                                  f"(ofset {off})")
                continue
            fid = struct.unpack_from("<H", rec, i + 4)[0]
            rel = f"{pd}/ombstx/offline/{fid:08X}" if pd else f"ombstx/offline/{fid:08X}"
            hit = next((v for k, v in index.items() if k.startswith(rel.lower() + "/")), None)
            if hit is None:
                bm.unknown.append(f"blockmap | {files['hrs/linkhrs.lnk']} | program {p.program_id}: block klasörü "
                                  f"{fid:08X} backup'ta yok")
                continue
            p.block_folder = hit.rsplit("/", 1)[0]
            p.evidence.append(f"{files['hrs/linkhrs.lnk']} @0x{off:X}: block klasörü {fid:08X}")
    else:
        bm.unknown.append(f"blockmap | {pd or '.'}/hrs/linkhrs.lnk | yok: program ↔ block klasörü bağı kurulamadı")

    # 3-5) program -> CPU -> station
    stations = {}
    if files["hOmSave7/s7hstatx/HOBJECT1.DBF"]:
        for r in _rows(src, files["hOmSave7/s7hstatx/HOBJECT1.DBF"]):
            sid, typ = _int(r.get("ID")), _int(r.get("OBJTYP"))
            if sid is not None and typ in STATION_TYPES:
                stations[sid] = (_str(r.get("NAME")), STATION_TYPES[typ])
                bm.stations[(pd, sid)] = stations[sid]
    st = bm.stats.setdefault(pd or ".", {})
    st["program"] = len(progs)
    st["program_with_block_folder"] = sum(1 for p in progs.values() if p.block_folder)
    st["station_in_s7hstatx"] = len(stations)
    for d in CPU_DIRS:
        rel_f, obj_f = files[f"hOmSave7/{d}/HRELATI1.DBF"], files[f"hOmSave7/{d}/HOBJECT1.DBF"]
        if not rel_f:
            continue
        rels = _rows(src, rel_f)
        st[f"{d}: HRELATI1 satır"] = len(rels)
        st[f"{d}: RELID=16 satır"] = sum(1 for r in rels if _int(r.get("RELID")) == REL_PROGRAM)
        hist: dict = {}
        for r in rels:
            for col in ("TOBJID", "SOBJID"):
                if _int(r.get(col)) in progs:
                    k = f"{col}=program, RELID {_int(r.get('RELID'))}, TOBJTYP {_int(r.get('TOBJTYP'))}"
                    hist[k] = hist.get(k, 0) + 1
        st[f"{d}: program ID geçen ilişkiler"] = hist or "yok"
        st[f"{d}: CPU-station ilişkisi (TOBJTYP 1314972/1315656)"] = sum(
            1 for r in rels if _int(r.get("TOBJTYP")) in REL_CPU_IN_STATION)
        cpus = {}
        cpu_unit: dict = {}
        if obj_f:
            for r in _rows(src, obj_f):
                cid = _int(r.get("ID"))
                if cid is not None:
                    cpus[cid] = (_str(r.get("NAME")), _int(r.get("SUBSTATN")), _int(r.get("MODULN")))
                    cpu_unit[cid] = _int(r.get("UNITID"))
        cpu_station = {}
        for r in rels:
            if _int(r.get("TOBJTYP")) in REL_CPU_IN_STATION and _int(r.get("SOBJID")) is not None:
                cpu_station.setdefault(_int(r.get("SOBJID")), _int(r.get("TUNITID")))
        for r in rels:
            if _int(r.get("RELID")) != REL_PROGRAM:
                continue
            cid, pid = _int(r.get("SOBJID")), _int(r.get("TOBJID"))
            p = progs.get(pid)
            if p is None:
                continue
            if cid in cpus:
                p.cpu_name, p.rack, p.slot = cpus[cid]
            p.evidence.append(f"{rel_f}: RELID 16 CPU {cid} -> program {pid}")
            sid = cpu_station.get(cid)
            if sid is None and cpu_unit.get(cid) in stations:      # H-system yedek CPU: HOBJECT1.UNITID = station
                sid = cpu_unit[cid]
                p.evidence.append(f"{obj_f}: CPU {cid} UNITID -> station {sid}")
            if sid is not None:
                p.station_id = sid
                if sid in stations:
                    p.station_name, p.station_type = stations[sid]
                    p.evidence.append(f"{files['hOmSave7/s7hstatx/HOBJECT1.DBF']}: station {sid}")
                s7h = index.get(f"{pd}/hOmSave7/s7hstatx/{sid:x}.s7h".lower() if pd else f"homsave7/s7hstatx/{sid:x}.s7h")
                p.s7h = s7h
    is_library = any(k.endswith(".s7l") and k.rsplit("/", 1)[0] == (pd.lower() if pd else "") for k in index)
    for p in progs.values():
        if p.block_folder and p.station_id is None and not is_library:
            bm.unknown.append(f"blockmap | {pd or '.'} | program {p.program_id}: CPU / station bağı "
                              "bulunamadı (HRELATI1 RELID 16 yok; CPU'suz program olabilir)")

    # 6) symbol table (hata olursa program/CPU/station sonuçları kaybolmaz)
    try:
        _symbol_links(src, pd, files, index, progs)
    except Exception as e:  # noqa: BLE001
        bm.unknown.append(f"blockmap | {pd or '.'}/YDBs | symbol table bağı okunamadı: {type(e).__name__}: {e}")
    bm.links += sorted(progs.values(), key=lambda x: (x.block_folder or "~", x.program_id))


def _symbol_links(src, pd: str, files: dict, index: dict, progs: dict) -> None:
    if files["YDBs/YLNKLIST.DBF"]:
        soi = {}
        for r in _rows(src, files["YDBs/YLNKLIST.DBF"]):
            if _int(r.get("TOI")) in progs:
                soi.setdefault(_int(r.get("TOI")), _int(r.get("SOI")))
        paths = {}
        if files["YDBs/SYMLISTS.DBF"]:
            for r in _rows(src, files["YDBs/SYMLISTS.DBF"]):
                paths[_int(r.get("_ID"))] = _str(r.get("_DBPATH"))
        for pid, sid in soi.items():
            sub = paths.get(sid) or (str(sid) if sid is not None else "")
            rel = index.get(f"{pd}/YDBs/{sub}/SYMLIST.DBF".lower() if pd else f"ydbs/{sub}/symlist.dbf")
            if rel:
                progs[pid].symbol_table = rel
                progs[pid].evidence.append(f"{files['YDBs/YLNKLIST.DBF']}: program {pid} -> symbol table {sub}")


def cross_check(bm: BlockMap, station_names: set[str], symtab_jaccard: dict | None = None) -> None:
    """Bağımsız kanıtla güveni yükseltir: HW export station adı eşleşmesi veya symbol table FB seti uyumu."""
    norm = {s.strip().lower() for s in station_names}
    for p in bm.links:
        why = []
        if p.station_name and p.station_name.strip().lower() in norm:
            why.append("station adı HW export ile aynı")
        if symtab_jaccard and p.symbol_table and symtab_jaccard.get(p.symbol_table, 0) >= 0.5:
            why.append(f"symbol table FB seti uyumu {symtab_jaccard[p.symbol_table]:.0%}")
        if p.block_folder and p.station_id is not None and why:
            p.confidence = "KANIT"
            p.evidence.append("çapraz kontrol: " + ", ".join(why))


def diagnostics(bm: BlockMap) -> str:
    """Müşteri adı İÇERMEYEN tanı metni (ID'ler, dosya var/yok, çözüm durumu) — geliştiriciyle paylaşılabilir."""
    out = ["Block klasörü ↔ AS zinciri tanısı (isimler maskeli)", ""]
    masks = {}
    for i, (pd, fs) in enumerate(sorted(bm.files.items()), 1):
        masks[pd] = f"<proje {i}>"
        out.append(f"## proje {i}")
        out += [f"- {k}: {v}" for k, v in fs.items()]
    out.append("")
    for i, (pd, stt) in enumerate(sorted(bm.stats.items()), 1):
        out.append(f"## proje {list(sorted(bm.files)).index(pd) + 1 if pd in bm.files else i} sayılar")
        out += [f"- {k}: {v}" for k, v in stt.items()]
    out.append("")
    for p in bm.links:
        out.append(f"- program {p.program_id}: block klasörü {p.block_folder.rsplit('/', 1)[-1] if p.block_folder else '-'}, "
                   f"CPU {'var' if p.cpu_name else '-'}, station {p.station_id if p.station_id is not None else '-'} "
                   f"({p.station_type or '-'}), symbol {'var' if p.symbol_table else '-'}, güven {p.confidence}")
    if bm.unknown:
        out += ["", "## çözülemeyenler"]
        for u in bm.unknown:
            for pd, m in sorted(masks.items(), key=lambda x: -len(x[0])):
                if pd not in (".", ""):
                    u = u.replace(pd, m)
            out.append(f"- {u}")
    return "\n".join(out) + "\n"


__all__ = ["BlockMap", "ProgramLink", "resolve", "cross_check", "diagnostics"]
