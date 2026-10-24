"""
STEP 7 V5 cross-reference veritabanı (XUTILS): custom / özel FB'lerin NEREDEN çağrıldığı (hangi FC / OB).

Dosyalar (gerçek projenin maskeli yapı tanısından; içerik semantiği gerçek projede TEYİT EDİLMEDİ -> ÇIKARIM):
  <proje>/XUTILS/CT112001.DBF          set listesi: ID, NAME:C40, CRDATE1, CRDATE2, VERSION, LASTID
  <proje>/XUTILS/<n>/CT000001.DBF      çağrı ağacı (call tree), S7 program başına bir set:
        ID:C10, BLTYPEDAD:C2, BLNBDAD:C5, BLTYPESON:C2, BLNBSON:C5, OPTYPE:C2, LANGDAD:C2, LANGSPEC1..5:C8
        "dad" "son"u kullanır. Block tipi kodları SUBBLKTYP ana kodlarıyla aynı (8 OB, 10 DB, 12 FC, 13 SFC, 14 FB,
        15 SFB). OPTYPE: 66 = çağrı (CALL), 80 = DB açma / instance DB, 64 = ? (ÇIKARIM: sayımlar 80 = DB son'u, 66 ≈
        FB + FC + SFC + SFB son'u ile örtüşüyor).
  <proje>/XUTILS/<n>/BS000001.DBF      block listesi: ID:N10, BLOCKTYPE:C2, BLOCKNB:C5, LANGUAGE:C2, TIMESTAMP:C6,
                                       LOCDATALEN:C8, LANGSPEC1/2:C8
  <proje>/XUTILS/<n>/XR000001.DBF      operand cross-reference (100k+ kayıt): OKUNMAZ, pakete de girmez
  <proje>/XUTILS/<n>/CTL00001.DBF, BSL00001.DBF, XRL00001.DBF
                                       tek kayıtlık link tablosu: SOT, SOI, TUT, TUI, TOT, TOI, RID.
                                       Varsayım (ÇIKARIM): YDBs/YLNKLIST gibi TOI = S7 program ID (hrs/S7RESOFF).

XUTILS seti -> block klasörü eşlemesi (hepsi ÇIKARIM, confidence low):
  1. link tablosu TOI = blockmap S7 program ID -> programın block klasörü (ID zinciri)
  2. TOI = block klasörü ID'si (ombstx/offline/<TOI 8 hex>)
  3. CT112001 NAME = S7 program adı (ID = set no)
  4. FB numarası seti benzerliği (Jaccard ≥ %50, aynı proje) — fallback
Eşleme yöntemi ve FB seti uyumu her sette tutulur; ID eşlemesi FB setiyle çelişirse `unknown`a yazılır.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .._vendor import dbfread
from .._vendor.dbfread.field_parser import FieldParser

TYPE_NAMES = {8: "OB", 10: "DB", 12: "FC", 13: "SFC", 14: "FB", 15: "SFB"}
TYPE_CODES = {v: k for k, v in TYPE_NAMES.items()}
OPTYPES = {66: "çağrı (CALL)", 80: "DB açma / instance DB", 64: "bilinmiyor"}      # ÇIKARIM
CONFIDENCE = "low"
MIN_JACCARD = 0.5

_RE_CT = re.compile(r"^ct\d+\.dbf$")
_RE_BS = re.compile(r"^bs\d+\.dbf$")
_RE_XR = re.compile(r"^xr\d+\.dbf$")
_RE_LINK = re.compile(r"^(ct|bs|xr)l\d+\.dbf$")


class _TolerantParser(FieldParser):
    """Bozuk sayısal / mantıksal alan çökme değil None."""

    def parseN(self, field, data):
        try:
            return super().parseN(field, data)
        except ValueError:
            return None

    def parseL(self, field, data):
        try:
            return super().parseL(field, data)
        except ValueError:
            return None


def type_name(code) -> str:
    c = _int(code)
    return TYPE_NAMES.get(c, f"T{code}" if c is None else f"T{c}")


def _int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace("\x00", "").strip()
    try:
        return int(s)
    except ValueError:
        return None


def _iter(src, rel: str):
    t = dbfread.DBF(str(src.materialize(rel)), encoding="latin1", char_decode_errors="ignore",
                    ignore_missing_memofile=True, parserclass=_TolerantParser, load=False)
    for r in t:
        yield {k.upper(): v for k, v in r.items()}


@dataclass
class XutilsSet:
    dir: str                                   # <proje>/XUTILS/<n> (rel)
    project: str                               # XUTILS'in üstündeki klasör (rel)
    set_no: int | None = None                  # <n>
    ct: str | None = None
    bs: str | None = None
    xr: str | None = None                      # okunmaz; sadece varlık + boyut
    xr_size: int | None = None
    links: dict = field(default_factory=dict)  # {dosya adı: {SOT, SOI, TUT, TUI, TOT, TOI, RID}}
    set_name: str = ""                         # CT112001.DBF NAME (ID = set no)
    edges: Counter = field(default_factory=Counter)   # {(dad tip, dad no, son tip, son no, OPTYPE): kayıt sayısı}
    blocks: dict = field(default_factory=dict)        # BS: {(tip, no): {"lang": kod, "locdata": n}}
    n_ct: int = 0
    n_bs: int = 0
    bad_records: int = 0
    optypes: Counter = field(default_factory=Counter)
    unknown: list[str] = field(default_factory=list)  # "dosya | neden"
    # eşleme (map_sets_to_folders doldurur)
    block_folder: str | None = None
    mapping: str = ""
    fb_jaccard: float | None = None

    def fb_numbers(self) -> set[int]:
        """Bu sette görülen FB numaraları (BS block listesi + CT dad/son)."""
        out = {no for (t, no) in self.blocks if t == "FB"}
        for (dt, dn, st, sn, _op) in self.edges:
            if dt == "FB":
                out.add(dn)
            if st == "FB":
                out.add(sn)
        return out

    def toi(self) -> int | None:
        for name in sorted(self.links):
            v = _int(self.links[name].get("TOI"))
            if v is not None:
                return v
        return None

    def summary(self) -> dict:
        """Analysis'e (rapor.json) giden hafif özet; kenar listesi değil."""
        return {"dir": self.dir, "project": self.project, "set_no": self.set_no, "set_name": self.set_name,
                "ct": self.ct, "bs": self.bs, "xr": self.xr, "xr_size": self.xr_size,
                "links": {k: dict(v) for k, v in sorted(self.links.items())},
                "ct_records": self.n_ct, "bs_records": self.n_bs, "bad_records": self.bad_records,
                "optypes": {str(k): v for k, v in sorted(self.optypes.items(), key=lambda kv: str(kv[0]))},
                "block_folder": self.block_folder, "mapping": self.mapping,
                "fb_jaccard": None if self.fb_jaccard is None else round(self.fb_jaccard, 3),
                "confidence": CONFIDENCE}


# ---------------------------------------------------------------------------
# Keşif + okuma
# ---------------------------------------------------------------------------

def find_xutils_dirs(src, project_dirs: list[str] | None = None) -> dict[str, dict]:
    """
    {<proje>/XUTILS/<n>: {"ct", "bs", "xr", "xr_size", "links": [rel], "project", "overview"}}.
    project_dirs verilirse sadece bu projelerin altındakiler (eski kopyalar dışarıda kalır).
    """
    allowed = None if project_dirs is None else {p.lower() for p in project_dirs}
    out: dict[str, dict] = {}
    overview: dict[str, str] = {}
    for e in src.entries:
        parts = e.rel.split("/")
        low = [p.lower() for p in parts]
        if "xutils" not in low:
            continue
        i = len(low) - 1 - low[::-1].index("xutils")
        proj = "/".join(parts[:i])
        if allowed is not None and proj.lower() not in allowed:
            continue
        name = low[-1]
        if len(parts) == i + 2 and name.startswith("ct1") and name.endswith(".dbf") and not _RE_LINK.match(name):
            overview[proj.lower()] = e.rel                 # XUTILS/CT112001.DBF (set listesi)
            continue
        if len(parts) != i + 3:
            continue
        d = "/".join(parts[:-1])
        s = out.setdefault(d, {"ct": None, "bs": None, "xr": None, "xr_size": None, "links": [], "project": proj})
        if _RE_LINK.match(name):
            s["links"].append(e.rel)
        elif _RE_CT.match(name):
            s["ct"] = s["ct"] if s["ct"] and s["ct"] < e.rel else e.rel
        elif _RE_BS.match(name):
            s["bs"] = s["bs"] if s["bs"] and s["bs"] < e.rel else e.rel
        elif _RE_XR.match(name):
            s["xr"], s["xr_size"] = e.rel, e.size
    for d, s in out.items():
        s["overview"] = overview.get(s["project"].lower())
        s["links"].sort()
    return {d: s for d, s in sorted(out.items()) if s["ct"] or s["bs"]}


def _overview_names(src, rel: str | None, cache: dict) -> dict[int, str]:
    if not rel:
        return {}
    if rel not in cache:
        names = {}
        for r in _iter(src, rel):
            i = _int(r.get("ID"))
            if i is not None:
                names[i] = str(r.get("NAME") or "").replace("\x00", "").strip()
        cache[rel] = names
    return cache[rel]


def read_xutils_set(src, d: str, info: dict, progress=None, _cache: dict | None = None) -> XutilsSet:
    """Bir XUTILS setini okur (CT + BS + link tabloları, streaming). Okunamayan dosya `unknown`a yazılır."""
    xs = XutilsSet(dir=d, project=info["project"], set_no=_int(d.rsplit("/", 1)[-1]), ct=info["ct"], bs=info["bs"],
                   xr=info.get("xr"), xr_size=info.get("xr_size"))
    for rel in info.get("links", []):
        try:
            rows = list(_iter(src, rel))
            if rows:
                xs.links[rel.rsplit("/", 1)[-1].upper()] = {k: (_int(v) if _int(v) is not None else v)
                                                           for k, v in rows[0].items()}
            if len(rows) != 1:
                xs.unknown.append(f"{rel} | link tablosunda {len(rows)} kayıt (1 bekleniyordu)")
        except Exception as e:  # noqa: BLE001 - tek dosya hatası seti durdurmaz
            xs.unknown.append(f"{rel} | okunamadı: {type(e).__name__}: {e}")
    try:
        names = _overview_names(src, info.get("overview"), {} if _cache is None else _cache)
        if xs.set_no is not None:
            xs.set_name = names.get(xs.set_no, "")
    except Exception as e:  # noqa: BLE001
        xs.unknown.append(f"{info.get('overview')} | okunamadı: {type(e).__name__}: {e}")
    if xs.ct:
        try:
            for r in _iter(src, xs.ct):
                xs.n_ct += 1
                dt, dn, st, sn = (_int(r.get(k)) for k in ("BLTYPEDAD", "BLNBDAD", "BLTYPESON", "BLNBSON"))
                op = _int(r.get("OPTYPE"))
                if None in (dt, dn, st, sn):
                    xs.bad_records += 1
                    continue
                xs.optypes[op] += 1
                xs.edges[(type_name(dt), dn, type_name(st), sn, op)] += 1
                if progress and xs.n_ct % 20000 == 0:
                    progress(f"  {xs.ct}: {xs.n_ct} kayıt")
        except Exception as e:  # noqa: BLE001
            xs.unknown.append(f"{xs.ct} | call tree okunamadı ({xs.n_ct}. kayıtta): {type(e).__name__}: {e}")
    if xs.bs:
        try:
            for r in _iter(src, xs.bs):
                xs.n_bs += 1
                t, n = _int(r.get("BLOCKTYPE")), _int(r.get("BLOCKNB"))
                if t is None or n is None:
                    xs.bad_records += 1
                    continue
                xs.blocks[(type_name(t), n)] = {"lang": _int(r.get("LANGUAGE")), "locdata": _int(r.get("LOCDATALEN"))}
        except Exception as e:  # noqa: BLE001
            xs.unknown.append(f"{xs.bs} | block listesi okunamadı: {type(e).__name__}: {e}")
    if xs.bad_records:
        xs.unknown.append(f"{xs.ct or xs.bs} | {xs.bad_records} kayıt okunamadı (tip / numara boş), atlandı")
    unk_ops = sorted(str(o) for o in xs.optypes if o not in OPTYPES)
    if unk_ops:
        xs.unknown.append(f"{xs.ct} | tanınmayan OPTYPE kodları: {', '.join(unk_ops)}")
    return xs


def read_all(src, project_dirs: list[str] | None = None, progress=None) -> list[XutilsSet]:
    cache: dict = {}
    return [read_xutils_set(src, d, info, progress, cache) for d, info in find_xutils_dirs(src, project_dirs).items()]


# ---------------------------------------------------------------------------
# Çağrı ağacı
# ---------------------------------------------------------------------------

def call_tree(xs: XutilsSet, son_kind: str = "FB", ops: set | None = None) -> dict[int, list[tuple[str, int, int]]]:
    """
    {son no: [(çağıran tip, çağıran no, kayıt sayısı)]} — kayıt sayısına göre azalan, sonra tip / no.
    ops: sadece bu OPTYPE'lar (None = hepsi). Kayıt sayısı = CT kaydı; çağrı sayısına eşit olduğu ÇIKARIM.
    """
    agg: dict[int, Counter] = {}
    for (dt, dn, st, sn, op), c in xs.edges.items():
        if st != son_kind or (ops is not None and op not in ops):
            continue
        agg.setdefault(sn, Counter())[(dt, dn)] += c
    return {sn: sorted(((t, n, c) for (t, n), c in cnt.items()), key=lambda x: (-x[2], x[0], x[1]))
            for sn, cnt in sorted(agg.items())}


def map_sets_to_folders(sets: list[XutilsSet], block_folders: list, blockmap=None) -> dict[str, XutilsSet]:
    """
    Her XUTILS setini en fazla bir block klasörüne eşler; {block klasörü path: set}. Set'e mapping / fb_jaccard yazılır.
    block_folders: analyze.BlockFolderResult (info.path, fb_numbers) listesi.
    """
    out: dict[str, XutilsSet] = {}
    links = list(getattr(blockmap, "links", []) or [])
    by_path = {b.info.path.lower(): b for b in block_folders}

    def jac(xs, bfr) -> float | None:
        a, b = xs.fb_numbers(), set(bfr.fb_numbers)
        return len(a & b) / len(a | b) if (a and b) else None

    def under(xs, bfr) -> bool:
        p = xs.project.lower()
        return bfr.info.path.lower().startswith(p + "/") if p else True

    pending = []
    for xs in sets:
        cands = [b for b in block_folders if under(xs, b) and b.counts]
        hit, how = None, ""
        toi = xs.toi()
        if toi is not None:
            lk = next((x for x in links if x.program_id == toi and x.block_folder
                       and x.project.lower() == xs.project.lower()), None)
            if lk and lk.block_folder.lower() in by_path:
                hit = by_path[lk.block_folder.lower()]
                how = f"link tablosu TOI={toi} = S7 program '{lk.program_name}' (S7RESOFF) → block klasörü"
            else:
                hit = next((b for b in cands if _hex_id(b.info.path) == toi), None)
                how = f"link tablosu TOI={toi} = block klasörü ID" if hit else ""
        if hit is None and xs.set_name:
            lk = next((x for x in links if x.program_name == xs.set_name and x.block_folder
                       and x.project.lower() == xs.project.lower()), None)
            if lk and lk.block_folder.lower() in by_path:
                hit = by_path[lk.block_folder.lower()]
                how = f"CT112001 NAME '{xs.set_name}' = S7 program adı"
        if hit is not None and hit.info.path.lower() not in out:
            xs.fb_jaccard = jac(xs, hit)
            xs.block_folder, xs.mapping = hit.info.path, f"{how} (ÇIKARIM)"
            if xs.fb_jaccard is not None and xs.fb_jaccard < MIN_JACCARD:
                xs.unknown.append(f"{xs.dir} | ID eşlemesi ({how}) FB setiyle çelişiyor: benzerlik "
                                  f"{xs.fb_jaccard:.0%} -> eşleme teyit edilmeli")
            out[hit.info.path.lower()] = xs
        else:
            pending.append((xs, cands))
    # fallback: FB seti benzerliği (en yüksek skor önce, bire bir)
    scored = []
    for xs, cands in pending:
        for b in cands:
            j = jac(xs, b)
            if j is not None and j >= MIN_JACCARD:
                scored.append((-j, xs.dir, b.info.path, xs, b))
    used_sets = set()
    for negj, _d, _p, xs, b in sorted(scored, key=lambda x: x[:3]):
        if xs.dir in used_sets or b.info.path.lower() in out:
            continue
        xs.fb_jaccard = -negj
        xs.block_folder = b.info.path
        xs.mapping = f"FB seti benzerliği {-negj:.0%} (heuristic, ÇIKARIM)"
        out[b.info.path.lower()] = xs
        used_sets.add(xs.dir)
    for xs, _c in pending:
        if xs.dir not in used_sets:
            xs.mapping = "block klasörüyle eşlenemedi (ID bağlantısı yok, FB seti benzerliği < %50)"
            xs.unknown.append(f"{xs.dir} | XUTILS seti hiçbir block klasörüyle eşlenemedi")
    return out


def _hex_id(path: str) -> int | None:
    try:
        return int(path.rsplit("/", 1)[-1], 16)
    except ValueError:
        return None


def attach(bfr, xs: XutilsSet) -> None:
    """BlockFolderResult'a çağıran listelerini yazar (callers: FB son'ları, fc_callers: FC son'ları)."""
    bfr.callers = call_tree(xs, "FB")
    bfr.fc_callers = call_tree(xs, "FC")
    bfr.callers_source = f"{xs.ct} ({xs.mapping})"
    bfr.callers_confidence = CONFIDENCE


def callers_text(bfr, fb_no: int, max_items: int = 3) -> str:
    """
    Rapor hücresi için: 'FC12 (runtime group?, OB35) ×5, OB1, +2'. Çağıran yoksa / XUTILS yoksa ''.
    'runtime group?' = OB'den çağrılan FC (CFC runtime group'u olduğu ÇIKARIM); FB çağıran = multi-instance? (ÇIKARIM).
    """
    lst = (getattr(bfr, "callers", None) or {}).get(fb_no) or []
    fc_up = getattr(bfr, "fc_callers", None) or {}
    parts = []
    for t, n, c in lst[:max_items]:
        s = f"{t}{n}"
        if t == "FC":
            obs = [f"{a}{b}" for a, b, _ in fc_up.get(n, []) if a == "OB"]
            if obs:
                s += f" (runtime group?, {'/'.join(obs[:2])}{'…' if len(obs) > 2 else ''})"
        elif t == "FB":
            s += " (multi-instance?)"
        if c > 1:
            s += f" ×{c}"
        parts.append(s)
    if len(lst) > max_items:
        parts.append(f"+{len(lst) - max_items}")
    return ", ".join(parts)


__all__ = ["XutilsSet", "TYPE_NAMES", "OPTYPES", "find_xutils_dirs", "read_xutils_set", "read_all", "call_tree",
           "map_sets_to_folders", "attach", "callers_text"]
