"""
İki backup'ın karşılaştırılması (saha vs ES, eski vs yeni, ES projesi vs OS server kopyası).

Her iki taraf `open_source` ile açılır (klasör / .zip / iç içe zip; sadece okuma) ve `analyze_source` ile analiz
edilir; block detayları için SUBBLK.DBF tekrar okunur. Sonuç TEK bir fark listesidir (`DiffRow`, Kategori kolonu).
Eşleme: proje = proje klasör adı (büyük/küçük harf duyarsız) + S7 program sırası (program sayısı farklıysa
block klasörü hex adı); HW = station adı; OS = OS proje adı (aynı ad birden fazlaysa ES içindeki).
"Hangisi baz alınmalı" için sadece kanıt listesi ve öneri üretilir; karar kullanıcıya aittir.
"""
from __future__ import annotations

import json
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .analyze import Analysis, analyze_source
from .parsers.subblk import library_summary, parse_subblk
from .parsers.wincc import list_os_entries, normalize_os_rel
from .parsers.wincc_export import ExportDiff, compare_exports, parse_export
from .source import Source, open_source

KANIT, CIKARIM = "KANIT", "ÇIKARIM"
ONLY_A, ONLY_B, DIFF, NEWER_A, NEWER_B = "sadece A", "sadece B", "farklı", "A'da daha yeni", "B'de daha yeni"
CATEGORIES = ("Proje", "Block", "Library", "HW", "HW geçmişi", "OS dosyası", "Tag", "Alarm", "Alarm metni",
              "Connection")
MTIME_TOL = 2.0                       # zip zaman damgası çözünürlüğü 2 s
OS_FILE_EXT = (".pdl", ".bmo", ".bac", ".pas", ".act")
SKIP_LIBS = ("custom", "custom/unknown", "CFC generated")   # custom block'lar tek tek Block satırında
KINDS = ("FB", "FC", "DB", "OB")


@dataclass
class DiffRow:
    category: str        # CATEGORIES
    scope: str           # proje / S7 program etiketi / station / OS adı
    item: str            # 'FB1990 SINAMICS_G120', '6ES7 321-1BL00-0AA0 V1.0', 'GraCS/Tank1.pdl'
    change: str          # sadece A / sadece B / farklı / A'da daha yeni / B'de daha yeni
    a: str = ""
    b: str = ""
    source_a: str = ""   # A içindeki tam relatif path
    source_b: str = ""
    confidence: str = KANIT


@dataclass
class CompareResult:
    label_a: str
    label_b: str
    rows: list[DiffRow] = field(default_factory=list)
    summary: list[tuple[str, str]] = field(default_factory=list)     # (konu, değer)
    evidence: list[str] = field(default_factory=list)                # "hangisi baz alınmalı" kanıtları (karar yok)
    recommendation: str = ""                                         # öneri; karar kullanıcıya aittir
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> Counter:
        return Counter(r.category for r in self.rows)

    def to_dict(self) -> dict:
        return asdict(self)


def _ts(t: float | None) -> str:
    if not t:
        return "-"
    try:
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "-"


def _newer(ta: float, tb: float) -> str | None:
    """A / B / None (fark <= 2 s)."""
    if abs(ta - tb) <= MTIME_TOL:
        return None
    return "A" if ta > tb else "B"


@dataclass
class _Side:
    """Bir tarafın analiz sonucu + dosya indeksi (rel -> Entry)."""
    key: str                  # 'A' / 'B'
    src: Source
    an: Analysis | None
    entries: dict = field(default_factory=dict)

    def mtime(self, rel: str | None) -> float:
        e = self.entries.get(rel) if rel else None
        return e.mtime if e else 0.0

    def live(self, rel: str) -> bool:
        """Eski kopya (analiz dışı bırakılmış) klasörde değil mi."""
        stale = self.an.stale_dirs if self.an else []
        return not any(rel == s or rel.startswith(s + "/") for s in stale)


class _Ctx:
    def __init__(self, res: CompareResult, a: _Side, b: _Side, log):
        self.res, self.a, self.b, self.log = res, a, b, log
        self.indicators: list[tuple[str, str]] = []      # (gösterge, 'A' | 'B') -> öneri sayımı

    def row(self, *args, **kw) -> None:
        self.res.rows.append(DiffRow(*args, **kw))

    def summary(self, k: str, v: str) -> None:
        self.res.summary.append((k, v))

    def part(self, name: str, fn) -> None:
        """Her karşılaştırma bölümü yalıtılmış: hata uyarıya yazılır, diğer bölümler devam eder."""
        try:
            fn(self)
        except Exception as e:  # noqa: BLE001 - gerçek backup'ta beklenmeyen format
            self.res.warnings.append(f"{name} karşılaştırması tamamlanamadı: {type(e).__name__}: {e}")
            self.log(f"UYARI: {name} karşılaştırması tamamlanamadı\n{traceback.format_exc()}")


def _pair_ab(n_a: int, n_b: int, what: str) -> str:
    return f"A: {n_a or f'{what} yok'} | B: {n_b or f'{what} yok'}"


# ---------------------------------------------------------------------------
# Proje / block / library
# ---------------------------------------------------------------------------

def _project_dirs(s: _Side) -> dict[str, str]:
    """{proje adı küçük harf: proje klasörü} (.s7p), eski kopyalar hariç."""
    out = {}
    for p in s.an.discovery.projects:
        d = p.rsplit("/", 1)[0] if "/" in p else ""
        if s.live(p):
            out.setdefault((d.rsplit("/", 1)[-1] or Path(p).stem).lower(), d)
    return out


def _folders(s: _Side) -> dict[str, list]:
    out = defaultdict(list)
    for b in s.an.block_folders:
        if not b.info.is_empty:
            out[b.info.owner_name.lower()].append(b)
    for v in out.values():
        v.sort(key=lambda b: (b.info.program_no, b.info.path.lower()))
    return out


def _hexname(b) -> str:
    return b.info.path.rsplit("/", 1)[-1].lower()


def _block_pairs(c: _Ctx) -> list[tuple]:
    """Eşlenen block klasörü çiftleri; tek tarafta kalan proje / program 'Proje' satırı olur."""
    fa, fb = _folders(c.a), _folders(c.b)
    pa, pb = _project_dirs(c.a), _project_dirs(c.b)
    pairs = []
    for name in sorted(set(pa) | set(pb) | set(fa) | set(fb)):
        la, lb = fa.get(name, []), fb.get(name, [])
        disp = (la or lb)[0].info.owner_name if (la or lb) else (pa.get(name) or pb.get(name) or name).rsplit("/", 1)[-1]
        in_a, in_b = name in pa or bool(la), name in pb or bool(lb)
        if in_a != in_b:
            items = la or lb
            c.row("Proje", disp, f"Proje {disp}", ONLY_A if in_a else ONLY_B,
                  *((f"{len(items)} S7 program", "") if in_a else ("", f"{len(items)} S7 program")),
                  source_a=pa.get(name, la[0].info.path if la else "") if in_a else "",
                  source_b=pb.get(name, lb[0].info.path if lb else "") if in_b else "")
            continue
        if len(la) == len(lb):
            pairs += list(zip(la, lb))
            continue
        c.row("Proje", disp, f"{disp} S7 program sayısı", DIFF, str(len(la)), str(len(lb)),
              pa.get(name, ""), pb.get(name, ""))
        c.res.warnings.append(f"{disp}: S7 program sayısı farklı (A {len(la)}, B {len(lb)}) -> block klasörü hex adıyla eşlendi")
        ha, hb = {_hexname(x): x for x in la}, {_hexname(x): x for x in lb}
        for h in sorted(set(ha) | set(hb)):
            if h in ha and h in hb:
                pairs.append((ha[h], hb[h]))
            else:
                x = ha.get(h) or hb.get(h)
                c.row("Proje", disp, f"{disp} block klasörü {x.info.path.rsplit('/', 1)[-1]}",
                      ONLY_A if h in ha else ONLY_B, source_a=x.info.path if h in ha else "",
                      source_b=x.info.path if h in hb else "")
    return pairs


def _read_folder(s: _Side, bfr):
    if bfr.info.dbt:
        s.src.materialize(bfr.info.dbt)
    return parse_subblk(s.src.materialize(bfr.info.dbf))


def _blk_val(b) -> str:
    return f"{b.name or '(no header)'}, {b.author or '-'}, {b.version}"


def _lib_val(c: Counter) -> str:
    return ", ".join(f"{a}: {n}" for a, n in sorted(c.items()))


def _counts_str(counts: dict) -> str:
    return ", ".join(f"{k} {counts.get(k, 0)}" for k in KINDS)


def _compare_blocks(c: _Ctx) -> None:
    pairs = _block_pairs(c)
    newest = {"A": 0.0, "B": 0.0}
    newer = {"A": [], "B": []}           # SUBBLK.DBF'i daha yeni olan programlar
    only = {"A": 0, "B": 0}
    for ra, rb in pairs:
        scope = ra.info.label
        sa, sb = ra.info.dbf, rb.info.dbf
        ta, tb = c.a.mtime(sa), c.b.mtime(sb)
        newest["A"], newest["B"] = max(newest["A"], ta), max(newest["B"], tb)
        if ta and tb and _newer(ta, tb):
            newer[_newer(ta, tb)].append(f"{scope} ({_ts(ta)} / {_ts(tb)})")
        try:
            fa = _read_folder(c.a, ra)
        except Exception as e:  # noqa: BLE001
            c.res.warnings.append(f"Block karşılaştırması yapılamadı: {scope} (A: {sa} okunamadı: {e})")
            continue
        try:
            fb = _read_folder(c.b, rb)
        except Exception as e:  # noqa: BLE001
            c.res.warnings.append(f"Block karşılaştırması yapılamadı: {scope} (B: {sb} okunamadı: {e})")
            continue
        c.summary(f"Block sayıları: {scope}", f"A: {_counts_str(fa.counts)} | B: {_counts_str(fb.counts)}")
        ba = {(x.kind, x.number): x for x in fa.blocks}
        bb = {(x.kind, x.number): x for x in fb.blocks}
        for k in sorted(set(ba) | set(bb)):
            xa, xb = ba.get(k), bb.get(k)
            name = (xa or xb).name
            item = f"{k[0]}{k[1]} {name}".strip()
            if xa and xb:
                if (xa.name, xa.author, xa.version) != (xb.name, xb.author, xb.version):
                    c.row("Block", scope, item, DIFF, _blk_val(xa), _blk_val(xb), sa, sb)
            elif xa:
                only["A"] += 1
                c.row("Block", scope, item, ONLY_A, _blk_val(xa), "", sa, "")
            else:
                only["B"] += 1
                c.row("Block", scope, item, ONLY_B, "", _blk_val(xb), "", sb)
        for kind in KINDS:
            na, nb = fa.counts.get(kind, 0), fb.counts.get(kind, 0)
            if na != nb:
                c.row("Block", scope, f"{kind} sayısı", DIFF, str(na), str(nb), sa, sb)
        ia, ib = Counter(fa.instances_per_fb), Counter(fb.instances_per_fb)
        for k in sorted(set(ia) | set(ib)):       # instance sayısı: CFC değişikliğinin dolaylı göstergesi
            if ia[k] != ib[k]:
                nm = ba.get(k) or bb.get(k)
                c.row("Block", scope, f"{k[0]}{k[1]} {nm.name if nm else ''}".strip() + " instance", DIFF,
                      str(ia[k]), str(ib[k]), sa, sb)
        la, lb = library_summary(fa), library_summary(fb)
        for lib in sorted((set(la) | set(lb)) - set(SKIP_LIBS)):
            va, vb = la.get(lib, Counter()), lb.get(lib, Counter())
            if va != vb:
                ch = DIFF if va and vb else ONLY_A if va else ONLY_B
                c.row("Library", scope, lib, ch, _lib_val(va), _lib_val(vb), sa, sb)
    if not pairs:
        c.summary("Block klasörleri", _pair_ab(len(c.a.an.block_folders), len(c.b.an.block_folders), "block klasörü")
                  + " (eşlenen program yok)")
    c.summary("En yeni SUBBLK.DBF", f"A: {_ts(newest['A'])} | B: {_ts(newest['B'])}")
    for side in ("A", "B"):
        if newer[side]:
            c.res.evidence.append(f"SUBBLK.DBF (block klasörü) {side} tarafında daha yeni (A / B): "
                                  + "; ".join(newer[side]) + ".")
            c.indicators += [("SUBBLK.DBF tarihi", side)] * len(newer[side])
    if only["A"] or only["B"]:
        c.res.evidence.append(f"Sadece A'da olan block: {only['A']}, sadece B'de olan block: {only['B']}.")
        if only["A"] != only["B"]:
            c.indicators.append(("block sayısı", "A" if only["A"] > only["B"] else "B"))


# ---------------------------------------------------------------------------
# HW
# ---------------------------------------------------------------------------

def _hw_item(order: str, fw: str) -> str:
    return f"{order} {fw}".strip()


def _compare_hw(c: _Ctx) -> None:
    sa = {}
    sb = {}
    for s, out in ((c.a, sa), (c.b, sb)):
        for st in s.an.stations:
            if st.name.lower() in out:
                c.res.warnings.append(f"{s.key}: aynı isimli ikinci HW station ({st.name}, {st.source}) karşılaştırılmadı")
                continue
            out[st.name.lower()] = st
    c.summary("HW station", _pair_ab(len(sa), len(sb), "HW Config"))
    for k in sorted(set(sa) | set(sb)):
        xa, xb = sa.get(k), sb.get(k)
        if not (xa and xb):
            x = xa or xb
            n = str(sum(x.inventory.values())) + " modül"
            c.row("HW", x.name, f"Station {x.name}", ONLY_A if xa else ONLY_B, n if xa else "", n if xb else "",
                  xa.source if xa else "", xb.source if xb else "", KANIT if x.kind == "cfg" else CIKARIM)
            continue
        conf = KANIT if xa.kind == xb.kind == "cfg" else CIKARIM
        if xa.kind != xb.kind:
            c.res.warnings.append(f"HW {xa.name}: A {xa.kind}, B {xb.kind} kaynaklı; farklar format farkından olabilir")
        for key in sorted(set(xa.inventory) | set(xb.inventory)):
            na, nb = xa.inventory.get(key, 0), xb.inventory.get(key, 0)
            if na == nb:
                continue
            ch = DIFF if na and nb else ONLY_A if na else ONLY_B
            c.row("HW", xa.name, _hw_item(*key), ch, f"{na} adet" if na else "", f"{nb} adet" if nb else "",
                  xa.source, xb.source, conf)


def _hw_history(s: _Side) -> dict[str, dict]:
    """{proje adı: {'s7h': [(rel, mtime)], 'dbf': {proje içi rel: (rel, mtime)}, 'dir': proje klasörü}}."""
    out = {}
    for name, d in _project_dirs(s).items():
        pre = (d + "/") if d else ""
        h = {"dir": d, "s7h": [], "dbf": {}}
        for rel, e in s.entries.items():
            if not rel.startswith(pre):
                continue
            sub = rel[len(pre):]
            low = sub.lower()
            if not low.startswith("homsave7/"):
                continue
            if low.startswith("homsave7/s7hstatx/") and low.endswith(".s7h"):
                h["s7h"].append((rel, e.mtime))
            elif e.name.upper() in ("HOBJECT1.DBF", "HATTRIB1.DBF"):
                h["dbf"][low] = (rel, e.mtime)
        if h["s7h"] or h["dbf"]:
            out[name] = h
    return out


def _compare_hw_history(c: _Ctx) -> None:
    ha, hb = _hw_history(c.a), _hw_history(c.b)
    c.summary("HW Config kayıtları (.s7h)", f"A: {sum(len(h['s7h']) for h in ha.values())} | "
                                            f"B: {sum(len(h['s7h']) for h in hb.values())}")
    for name in sorted(set(ha) | set(hb)):
        xa, xb = ha.get(name), hb.get(name)
        disp = ((xa or xb)["dir"].rsplit("/", 1)[-1]) or name
        if not (xa and xb):
            x = xa or xb
            n = f"{len(x['s7h'])} s7h"
            c.row("HW geçmişi", disp, "hOmSave7", ONLY_A if xa else ONLY_B, n if xa else "", n if xb else "",
                  x["dir"] if xa else "", x["dir"] if xb else "", CIKARIM)
            continue
        ta = [t for _, t in xa["s7h"]]
        tb = [t for _, t in xb["s7h"]]

        def rng(ts):
            return f"{len(ts)} ({_ts(min(ts))} … {_ts(max(ts))})" if ts else "0"
        s7h_dir = f"{xa['dir']}/hOmSave7/s7hstatx" if xa["dir"] else "hOmSave7/s7hstatx"
        s7h_dir_b = f"{xb['dir']}/hOmSave7/s7hstatx" if xb["dir"] else "hOmSave7/s7hstatx"
        if len(ta) != len(tb):
            c.row("HW geçmişi", disp, "s7h kayıt sayısı", DIFF, rng(ta), rng(tb), s7h_dir, s7h_dir_b, CIKARIM)
        if ta and tb:
            side = _newer(max(ta), max(tb))
            if side:
                c.row("HW geçmişi", disp, "son s7h kaydı", NEWER_A if side == "A" else NEWER_B, _ts(max(ta)),
                      _ts(max(tb)), max(xa["s7h"], key=lambda x: x[1])[0], max(xb["s7h"], key=lambda x: x[1])[0],
                      CIKARIM)
                c.indicators.append((f"{disp} son HW kaydı", side))
                old, new, other = (ta, tb, "A") if side == "B" else (tb, ta, "B")
                n_after = sum(1 for t in new if t > max(old) + MTIME_TOL)
                c.res.evidence.append(
                    f"{disp}: {side} tarafı {_ts(max(old))} tarihinden sonra {n_after} HW kaydı almış; "
                    f"{other}'yı baz almak bu değişiklikleri kaybettirir (doğrudan download riski).")
        for k in sorted(set(xa["dbf"]) | set(xb["dbf"])):
            da, db = xa["dbf"].get(k), xb["dbf"].get(k)
            item = (da or db)[0].rsplit("/", 3)[-2:]
            item = "/".join(item)
            if not (da and db):
                c.row("HW geçmişi", disp, item, ONLY_A if da else ONLY_B, _ts(da[1]) if da else "",
                      _ts(db[1]) if db else "", da[0] if da else "", db[0] if db else "", CIKARIM)
                continue
            side = _newer(da[1], db[1])
            if side:
                c.row("HW geçmişi", disp, item, NEWER_A if side == "A" else NEWER_B, _ts(da[1]), _ts(db[1]),
                      da[0], db[0], CIKARIM)
                c.indicators.append((f"{disp} {item} tarihi", side))


# ---------------------------------------------------------------------------
# OS / WinCC
# ---------------------------------------------------------------------------

def _os_projects(s: _Side) -> dict[str, object]:
    """{OS adı küçük harf: OsProject}; aynı ad birden fazlaysa ES içindeki (in_es) tercih edilir."""
    out = {}
    for op in s.an.os_projects:
        k = op.info.name.lower()
        if k not in out or (op.in_es and not out[k].in_es):
            out[k] = op
    return out


def _os_files(s: _Side, os_dir: str) -> tuple[dict, dict]:
    """(picture/script listesi {normalize rel: (size, mtime)}, {normalize rel: orijinal rel})."""
    lst = list_os_entries(s.entries.values(), os_dir)
    disp = {}
    pre = os_dir + "/"
    for rel in s.entries:
        if rel.startswith(pre):
            disp.setdefault(normalize_os_rel(rel[len(pre):]), rel[len(pre):])
    return {k: v for k, v in lst.items() if k.endswith(OS_FILE_EXT)}, disp


def _compare_os(c: _Ctx) -> None:
    oa, ob = _os_projects(c.a), _os_projects(c.b)
    c.summary("OS projeleri", _pair_ab(len(oa), len(ob), "OS projesi"))
    newest = {"A": 0.0, "B": 0.0}
    newer = {"A": 0, "B": 0}
    for k in sorted(set(oa) | set(ob)):
        pa, pb = oa.get(k), ob.get(k)
        if not (pa and pb):
            p = pa or pb
            c.row("Proje", p.info.name, f"OS projesi {p.info.name}", ONLY_A if pa else ONLY_B,
                  f"{p.info.n_files} dosya" if pa else "", f"{p.info.n_files} dosya" if pb else "",
                  p.info.path if pa else "", p.info.path if pb else "")
            continue
        scope = pa.info.name
        la, da = _os_files(c.a, pa.info.path)
        lb, db = _os_files(c.b, pb.info.path)
        for _, t in la.values():
            newest["A"] = max(newest["A"], t)
        for _, t in lb.values():
            newest["B"] = max(newest["B"], t)
        for rel in sorted(set(la) | set(lb)):
            fa, fb = la.get(rel), lb.get(rel)
            name = (da.get(rel) if fa else db.get(rel)) or rel
            sa = f"{pa.info.path}/{da.get(rel, rel)}" if fa else ""
            sb = f"{pb.info.path}/{db.get(rel, rel)}" if fb else ""
            if not (fa and fb):
                v = lambda f: f"{f[0]} B, {_ts(f[1])}" if f else ""  # noqa: E731
                c.row("OS dosyası", scope, name, ONLY_A if fa else ONLY_B, v(fa), v(fb), sa, sb)
                continue
            side = _newer(fa[1], fb[1])
            if fa[0] == fb[0] and not side:
                continue
            ch = DIFF if not side else NEWER_A if side == "A" else NEWER_B
            if side:
                newer[side] += 1
            c.row("OS dosyası", scope, name, ch, f"{fa[0]} B, {_ts(fa[1])}", f"{fb[0]} B, {_ts(fb[1])}", sa, sb,
                  KANIT if fa[0] != fb[0] else CIKARIM)
    if oa and ob:
        c.summary("En yeni OS dosyası (picture/script)", f"A: {_ts(newest['A'])} | B: {_ts(newest['B'])}")
    if newer["A"] or newer["B"]:
        c.res.evidence.append(f"Aynı isimli OS dosyalarında (picture/script) daha yeni olan: A'da {newer['A']}, "
                              f"B'de {newer['B']} dosya.")
        if newer["A"] != newer["B"]:
            c.indicators.append(("OS dosya tarihleri", "A" if newer["A"] > newer["B"] else "B"))
    side = _newer(newest["A"], newest["B"]) if newest["A"] and newest["B"] else None
    if side:
        c.res.evidence.append(f"En yeni OS picture/script dosyası {side} tarafında: A {_ts(newest['A'])}, "
                              f"B {_ts(newest['B'])}.")


def _exports(s: _Side) -> dict[str, list]:
    """{OS adı: [WinccExport]}: analizin bulduğu export dosyaları yeniden okunur."""
    out = {}
    for os_name, w in s.an.wincc.items():
        exps = []
        for p in w.files:
            data = s.src.read_bytes(p) if p in s.entries else Path(p).read_bytes()
            exps.append(parse_export(data, p, os_name))
        out[os_name] = exps
    return out


def _export_rows(c: _Ctx, d: ExportDiff, scope: str, src_a: str, src_b: str) -> None:
    def add(cat, item, ch, a="", b=""):
        c.row(cat, scope, item, ch, a, b, src_a if ch != ONLY_B else "", src_b if ch != ONLY_A else "")
    for n in d.conn_only_a:
        add("Connection", n, ONLY_A)
    for n in d.conn_only_b:
        add("Connection", n, ONLY_B)
    for n in d.tag_names_only_a:
        add("Tag", n, ONLY_A)
    for n in d.tag_names_only_b:
        add("Tag", n, ONLY_B)
    for t, va, vb in d.tags_changed:
        add("Tag", t, DIFF, va, vb)
    for al in d.alarm_rows_only_a:
        add("Alarm", f"{al.number} {al.message_tag}".strip(), ONLY_A, al.event)
    for al in d.alarm_rows_only_b:
        add("Alarm", f"{al.number} {al.message_tag}".strip(), ONLY_B, "", al.event)
    for n, va, vb in d.alarm_class_diff:
        add("Alarm", f"{n} message class", DIFF, va, vb)
    for n, va, vb in d.alarm_text_diff:
        add("Alarm metni", str(n), DIFF, va, vb)


def _compare_wincc(c: _Ctx) -> None:
    ea, eb = _exports(c.a), _exports(c.b)
    c.summary("WinCC tag/alarm export'u", _pair_ab(len(ea), len(eb), "export"))
    la, lb = {k.lower(): k for k in ea}, {k.lower(): k for k in eb}
    for k in sorted(set(la) | set(lb)):
        if k not in la or k not in lb:
            side = "A" if k in la else "B"
            c.summary(f"Export sadece {side}'da: {la.get(k) or lb.get(k)}", "tag/alarm karşılaştırması yapılamadı")
            continue
        na, nb = la[k], lb[k]
        d = compare_exports(na, ea[na], nb, eb[nb])
        _export_rows(c, d, na, ", ".join(e.path for e in ea[na]), ", ".join(e.path for e in eb[nb]))


# ---------------------------------------------------------------------------
# Öneri
# ---------------------------------------------------------------------------

def _recommend(c: _Ctx) -> str:
    res = c.res
    tail = "Karar kullanıcıya aittir."
    if not res.rows:
        return ("Karşılaştırılan kapsamda (proje, block, library, HW, HW geçmişi, OS dosyaları, WinCC export) fark "
                "bulunmadı. Karşılaştırılmayan içerik (CFC chart, NetPro, PC station) ayrıca kontrol edilmeli. " + tail)
    votes = Counter(s for _, s in c.indicators)
    lose = {"A": sum(1 for r in res.rows if r.change in (ONLY_A, NEWER_A)),
            "B": sum(1 for r in res.rows if r.change in (ONLY_B, NEWER_B))}
    if not votes:
        return (f"{len(res.rows)} fark var ancak hangi tarafın daha güncel olduğuna dair tarih göstergesi yok. "
                "Farklar tek tek incelenmeli. " + tail)
    if len(votes) == 1 or votes.most_common(1)[0][1] > sum(votes.values()) / 2:
        side, n = votes.most_common(1)[0]
        other = "B" if side == "A" else "A"
        kind = "tamamı" if n == sum(votes.values()) else "çoğu"
        txt = (f"Göstergelerin {kind} ({n}/{sum(votes.values())}) {side} tarafının daha güncel olduğunu gösteriyor. "
               f"{side} baz alınacaksa {other} tarafına özgü {lose[other]} satır ('sadece {other}' / "
               f"'{other}'{'da' if other == 'A' else 'de'} daha yeni') tek tek kontrol edilmeli; bunlar kaybolur.")
        return f"{txt} {tail}"
    return (f"Göstergeler çelişkili (A: {votes['A']}, B: {votes['B']}): iki tarafta da diğerinde olmayan değişiklik "
            f"var (sadece A/A'da daha yeni: {lose['A']}, sadece B/B'de daha yeni: {lose['B']}). Tek tarafı baz almak "
            f"değişiklik kaybına yol açar; birleştirme gerekebilir. {tail}")


# ---------------------------------------------------------------------------
# Ana giriş
# ---------------------------------------------------------------------------

def _analyze(key: str, src: Source, res: CompareResult, log) -> _Side:
    s = _Side(key, src, None, {e.rel: e for e in src.entries})
    try:
        s.an = analyze_source(src, log=lambda m: log(f"{key}: {m}"))
        res.warnings += [f"{key}: {w}" for w in s.an.warnings]
    except Exception as e:  # noqa: BLE001
        res.warnings.append(f"{key} analiz edilemedi: {type(e).__name__}: {e}")
        log(traceback.format_exc())
    return s


def compare_sources(src_a: Source, src_b: Source, log=None) -> CompareResult:
    """İki açık kaynağı karşılaştırır (kaynağa yazmaz)."""
    log = log or (lambda m: None)
    res = CompareResult(src_a.label, src_b.label)
    a, b = _analyze("A", src_a, res, log), _analyze("B", src_b, res, log)
    c = _Ctx(res, a, b, log)
    res.summary += [("A", res.label_a), ("B", res.label_b)]
    if a.an is None or b.an is None:
        res.recommendation = "Taraflardan biri analiz edilemedi; karşılaştırma yapılamadı. Karar kullanıcıya aittir."
        return res
    for name, fn in (("Proje / block / library", _compare_blocks), ("HW", _compare_hw),
                     ("HW geçmişi", _compare_hw_history), ("OS dosyaları", _compare_os),
                     ("WinCC export", _compare_wincc)):
        log(f"Karşılaştırma: {name}")
        c.part(name, fn)
    cnt = res.counts()
    res.summary.insert(2, ("Fark satırı (toplam)", str(len(res.rows))))
    res.summary[3:3] = [(f"Fark: {k}", str(cnt.get(k, 0))) for k in CATEGORIES]
    res.recommendation = _recommend(c)
    return res


def compare(path_a: Path, path_b: Path, log=None) -> CompareResult:
    with open_source(Path(path_a), log) as sa, open_source(Path(path_b), log) as sb:
        return compare_sources(sa, sb, log)


# ---------------------------------------------------------------------------
# Çıktı: fark.md + fark.json + fark.xlsx
# ---------------------------------------------------------------------------

HEADERS = ["Kategori", "Kapsam", "Öğe", "Değişiklik", "A", "B", "Kaynak A", "Kaynak B", "Güven"]
MD_MAX_PER_CATEGORY = 300


def _md_cell(v: str) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def render_markdown(res: CompareResult) -> str:
    out = ["# Backup karşılaştırması", "", f"- **A:** `{res.label_a}`", f"- **B:** `{res.label_b}`", "",
           "## Özet", "", "| Konu | Değer |", "|---|---|"]
    out += [f"| {_md_cell(k)} | {_md_cell(v)} |" for k, v in res.summary]
    out += ["", "## Hangisi baz alınmalı: kanıtlar", ""]
    out += [f"- {e}" for e in res.evidence] or ["- Tarih/sayı göstergesi bulunamadı."]
    out += ["", f"**Öneri:** {res.recommendation}", "", "## Farklar", ""]
    if not res.rows:
        out.append("Fark bulunmadı.")
    by_cat = defaultdict(list)
    for r in res.rows:
        by_cat[r.category].append(r)
    for cat in [k for k in CATEGORIES if k in by_cat] + sorted(set(by_cat) - set(CATEGORIES)):
        rows = by_cat[cat]
        out += [f"### {cat} ({len(rows)})", "", "| " + " | ".join(HEADERS[1:]) + " |", "|" + "---|" * (len(HEADERS) - 1)]
        for r in rows[:MD_MAX_PER_CATEGORY]:
            out.append("| " + " | ".join(_md_cell(x) for x in (r.scope, r.item, r.change, r.a, r.b, r.source_a,
                                                                 r.source_b, r.confidence)) + " |")
        if len(rows) > MD_MAX_PER_CATEGORY:
            out.append(f"\n… {len(rows) - MD_MAX_PER_CATEGORY} satır daha: tam liste fark.xlsx")
        out.append("")
    if res.warnings:
        out += ["## Uyarılar", ""] + [f"- {w}" for w in res.warnings]
    out += ["", "_KANIT: dosya içeriği/boyutu. ÇIKARIM: dosya tarihi veya formatı teyit edilmemiş veri "
            "(.s7h geçmişi, kopyalama ile değişebilen mtime)._", ""]
    return "\n".join(out)


_CHANGE_STYLE = {ONLY_A: "yellow", ONLY_B: "yellow", DIFF: "red", NEWER_A: "green", NEWER_B: "green"}


def write_outputs(res: CompareResult, out_dir: Path) -> Path:
    """fark.md + fark.json + fark.xlsx yazar; fark.md path'ini döndürür."""
    from .xlsx import Cell, Workbook
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "fark.md"
    md.write_text(render_markdown(res), encoding="utf-8")
    (out_dir / "fark.json").write_text(json.dumps(res.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    wb = Workbook()
    rows = [HEADERS] + [[r.category, r.scope, r.item, Cell(r.change, _CHANGE_STYLE.get(r.change, "")), r.a, r.b,
                         r.source_a, r.source_b, r.confidence] for r in res.rows]
    wb.add_sheet("Farklar", rows, header_rows={0}, filter_row=0, freeze=1)
    ozet = [["Konu", "Değer"]] + [list(x) for x in res.summary]
    ozet += [[], [Cell("Hangisi baz alınmalı: kanıtlar", "bold")]] + [["", e] for e in res.evidence]
    ozet += [[], [Cell("Öneri", "bold"), res.recommendation]]
    if res.warnings:
        ozet += [[], [Cell("Uyarılar", "bold")]] + [["", w] for w in res.warnings]
    wb.add_sheet("Ozet", ozet, header_rows={0}, freeze=1)
    wb.save(out_dir / "fark.xlsx")
    return md
