"""
Test ve demo için minimal dBase III/IV (+ .DBT memo) yazıcı.

Gerçek SUBBLK.DBF'nin alan adlarını taklit eder; STEP 7'nin kullandığı tam dBase varyantı
(DB3 vs DB4 memo) gerçek dosyayla teyit edilmeli, bu yüzden testler iki varyantla da çalışır.
"""
from __future__ import annotations

import struct
from pathlib import Path

SUBBLK_FIELDS = [
    ("SUBBLKTYP", "C", 5), ("BLKNUMBER", "C", 5), ("BLOCKFNAME", "C", 24), ("BLOCKNAME", "C", 24),
    ("VERSION", "N", 3), ("USERNAME", "C", 8), ("BLKLANG", "C", 5),
    ("MC5CODE", "M", 10), ("SSBPART", "M", 10), ("ADDINFO", "M", 10),
    ("PASSWORD", "N", 11), ("LOCDATALEN", "N", 5), ("MC5LEN", "N", 11),     # gerçek SUBBLK.DBF'te de var
]


def write_dbf(path: Path, fields, records, *, memo: str | None = "db4", language_driver: int = 0x00,
              memo_block_size: int = 512) -> None:
    """
    records: list[dict]. Memo alanlarına bytes verilir (None = boş).
    memo: 'db3' (0x83, 1A 1A sonlandırıcı, DBT header ofset 16 = 0x03) veya 'db4' (0x8B; memo block'u
    FF FF 08 00 + int32 uzunluk (header dahil); DBT header ofset 20 = block boyutu) veya None (DBT yazma).
    memo_block_size: sadece db4 (db3'te sabit 512).
    """
    path = Path(path)
    has_memo = any(t == "M" for _, t, _ in fields)
    version = {"db3": 0x83, "db4": 0x8B}.get(memo, 0x03) if has_memo else 0x03
    memo_blocks: list[bytes] = []
    bs = memo_block_size if memo == "db4" else 512
    first_block = -(-512 // bs)          # DBT header 512 byte; ilk memo block'u header'dan sonra

    def memo_ref(data: bytes | None) -> bytes:
        if not data or memo is None:
            return b" " * 10
        if memo == "db3":
            raw = data + b"\x1a\x1a"
        else:
            raw = b"\xff\xff\x08\x00" + struct.pack("<I", len(data) + 8) + data
        raw += b"\x00" * (-len(raw) % bs)
        index = first_block + sum(len(b) // bs for b in memo_blocks)
        memo_blocks.append(raw)
        return str(index).rjust(10).encode()

    rec_len = 1 + sum(l for _, _, l in fields)
    hdr_len = 32 + 32 * len(fields) + 1
    body = b""
    for r in records:
        row = b" "
        for name, typ, length in fields:
            v = r.get(name)
            if typ == "M":
                row += memo_ref(v)
            elif typ == "N":
                row += (b"" if v is None else str(v).encode()).rjust(length)
            else:
                row += (v if isinstance(v, bytes) else str(v or "").encode("latin1")).ljust(length)[:length]
        body += row

    header = struct.pack("<B3BIHH", version, 26, 9, 24, len(records), hdr_len, rec_len)
    header += b"\x00" * 17 + bytes([language_driver]) + b"\x00\x00"
    for name, typ, length in fields:
        header += name.encode().ljust(11, b"\x00") + typ.encode() + b"\x00" * 4 + bytes([length, 0]) + b"\x00" * 14
    header += b"\x0d"
    path.write_bytes(header + body + b"\x1a")

    if has_memo and memo is not None:
        next_free = first_block + sum(len(b) // bs for b in memo_blocks)
        dbt_header = bytearray(struct.pack("<I", next_free) + b"\x00" * 508)
        if memo == "db3":
            dbt_header[16] = 0x03
        else:
            dbt_header[20:22] = struct.pack("<H", bs)
        dbt_header += b"\x00" * (first_block * bs - len(dbt_header))
        path.with_suffix(".DBT").write_bytes(dbt_header + b"".join(memo_blocks))


def fb_instance(fb: int) -> bytes:
    """SSBPART: 0x0A + FB no (LE) + devamı (interface verisi taklidi)."""
    return bytes([0x0A, fb & 0xFF, fb >> 8]) + b"\x00\x05IDB"


def sfb_instance(sfb: int) -> bytes:
    return bytes([0x0B, sfb & 0xFF, sfb >> 8]) + b"\x00\x05IDB"


def block(typ: str, nr: int, family: str = "", name: str = "", version: int | None = 0x10,
          author: str = "", lang: str = "00004", ssb: bytes | None = None) -> dict:
    return {"SUBBLKTYP": typ, "BLKNUMBER": f"{nr:05d}", "BLOCKFNAME": family, "BLOCKNAME": name,
            "VERSION": version, "USERNAME": author, "BLKLANG": lang, "SSBPART": ssb}


def write_project_links(proj: Path, programs: list[dict]) -> None:
    """
    Test / demo: STEP 7 V5 proje ID zinciri dosyaları (bkz. blockmap.py).
    programs: [{"id", "name", "folder_id", "cpu_id", "cpu_name", "station_id", "station_name", "station_type"(OBJTYP),
                "sym_id"(ops.), "cpu_dir"(ops., varsayılan s7hk41ax)}]
    """
    proj = Path(proj)
    (proj / "hrs").mkdir(parents=True, exist_ok=True)
    lnk = b""
    res = []
    for p in programs:
        off = len(lnk)
        rec = b"\x00" * 16 + b"\x04\x20\x11\x00\x00" + b"\x00" * 7 + b"\x01\x60\x11\x00" + struct.pack("<H", p["folder_id"])
        lnk += rec.ljust(0x200, b"\x00")
        res.append({"ID": p["id"], "NAME": p["name"], "RSRVD4_L": off})
    write_dbf(proj / "hrs" / "S7RESOFF.DBF", [("ID", "N", 10), ("NAME", "C", 24), ("RSRVD4_L", "N", 10)], res)
    (proj / "hrs" / "linkhrs.lnk").write_bytes(lnk)
    st = proj / "hOmSave7" / "s7hstatx"
    st.mkdir(parents=True, exist_ok=True)
    stations = {p["station_id"]: (p["station_name"], p.get("station_type", 1315650)) for p in programs}
    write_dbf(st / "HOBJECT1.DBF", [("ID", "N", 10), ("NAME", "C", 24), ("OBJTYP", "N", 10), ("UNITID", "N", 10)],
              [{"ID": k, "NAME": n, "OBJTYP": t, "UNITID": k} for k, (n, t) in stations.items()])
    by_dir: dict = {}
    for p in programs:
        by_dir.setdefault(p.get("cpu_dir", "s7hk41ax"), []).append(p)
    for d, ps in by_dir.items():
        cd = proj / "hOmSave7" / d
        cd.mkdir(parents=True, exist_ok=True)
        write_dbf(cd / "HOBJECT1.DBF", [("ID", "N", 10), ("NAME", "C", 24), ("SUBSTATN", "N", 5), ("MODULN", "N", 5)],
                  [{"ID": p["cpu_id"], "NAME": p["cpu_name"], "SUBSTATN": 0, "MODULN": 3} for p in ps])
        rel_fields = [("SOBJID", "N", 10), ("SOBJTYP", "N", 10), ("RELID", "N", 10), ("TOBJID", "N", 10),
                      ("TOBJTYP", "N", 10), ("TUNITID", "N", 10), ("TUNITTYP", "N", 10)]
        rows = []
        for p in ps:
            rows.append({"SOBJID": p["cpu_id"], "SOBJTYP": 1, "RELID": 16, "TOBJID": p["id"], "TOBJTYP": 2,
                         "TUNITID": 0, "TUNITTYP": 0})
            rows.append({"SOBJID": p["cpu_id"], "SOBJTYP": 1, "RELID": 1, "TOBJID": 0, "TOBJTYP": 1314972,
                         "TUNITID": p["station_id"], "TUNITTYP": 0})
        write_dbf(cd / "HRELATI1.DBF", rel_fields, rows)
    syms = [p for p in programs if p.get("sym_id")]
    if syms:
        yd = proj / "YDBs"
        yd.mkdir(parents=True, exist_ok=True)
        write_dbf(yd / "YLNKLIST.DBF", [("TOI", "N", 10), ("SOI", "N", 10)],
                  [{"TOI": p["id"], "SOI": p["sym_id"]} for p in syms])
        write_dbf(yd / "SYMLISTS.DBF", [("_ID", "N", 10), ("_UNAME", "C", 24), ("_DBPATH", "C", 24)],
                  [{"_ID": p["sym_id"], "_UNAME": "Symbols", "_DBPATH": str(p["sym_id"])} for p in syms])


XUTILS_CT_FIELDS = [("ID", "C", 10), ("BLTYPEDAD", "C", 2), ("BLNBDAD", "C", 5), ("BLTYPESON", "C", 2),
                    ("BLNBSON", "C", 5), ("OPTYPE", "C", 2), ("LANGDAD", "C", 2)] + \
                   [(f"LANGSPEC{i}", "C", 8) for i in range(1, 6)]
XUTILS_BS_FIELDS = [("ID", "N", 10), ("BLOCKTYPE", "C", 2), ("BLOCKNB", "C", 5), ("LANGUAGE", "C", 2),
                    ("TIMESTAMP", "C", 6), ("LOCDATALEN", "C", 8), ("LANGSPEC1", "C", 8), ("LANGSPEC2", "C", 8)]
XUTILS_LINK_FIELDS = [(n, "N", 10) for n in ("SOT", "SOI", "TUT", "TUI", "TOT", "TOI", "RID")]


def write_xutils(proj: Path, set_no: int, calls: list[tuple], blocks: list[tuple], *, toi: int | None = None,
                 name: str = "", xr_records: int = 0) -> Path:
    """
    Test / demo: <proj>/XUTILS/<set_no>/ cross-reference seti (bkz. parsers/xutils.py).
    calls: [(dad tip kodu, dad no, son tip kodu, son no, OPTYPE)] (tekrar = birden çok kayıt);
    blocks: [(tip kodu, no, dil kodu)]; toi: CTL/BSL/XRL00001 link tablosu TOI (None = yazılmaz).
    """
    d = Path(proj) / "XUTILS" / str(set_no)
    d.mkdir(parents=True, exist_ok=True)
    write_dbf(d / "CT000001.DBF", XUTILS_CT_FIELDS,
              [{"ID": i + 1, "BLTYPEDAD": dt, "BLNBDAD": dn, "BLTYPESON": st, "BLNBSON": sn, "OPTYPE": op,
                "LANGDAD": 4} for i, (dt, dn, st, sn, op) in enumerate(calls)], memo=None)
    write_dbf(d / "BS000001.DBF", XUTILS_BS_FIELDS,
              [{"ID": i + 1, "BLOCKTYPE": t, "BLOCKNB": n, "LANGUAGE": lg, "TIMESTAMP": "", "LOCDATALEN": 0}
               for i, (t, n, lg) in enumerate(blocks)], memo=None)
    if toi is not None:
        for f in ("CTL00001.DBF", "BSL00001.DBF", "XRL00001.DBF"):
            write_dbf(d / f, XUTILS_LINK_FIELDS, [{"SOT": 1, "SOI": set_no, "TUT": 0, "TUI": 0, "TOT": 2,
                                                   "TOI": toi, "RID": 1}], memo=None)
    if xr_records:
        write_dbf(d / "XR000001.DBF", [("ID", "C", 10), ("OPERAND", "C", 24)],
                  [{"ID": i, "OPERAND": f"M{i}.0"} for i in range(xr_records)], memo=None)
    ov = Path(proj) / "XUTILS" / "CT112001.DBF"
    rows = []
    if ov.exists():
        from ._vendor import dbfread
        rows = [dict(r) for r in dbfread.DBF(str(ov), encoding="latin1")]
    rows.append({"ID": set_no, "NAME": name, "CRDATE1": "", "CRDATE2": "", "VERSION": 1, "LASTID": len(calls)})
    write_dbf(ov, [("ID", "N", 10), ("NAME", "C", 40), ("CRDATE1", "C", 8), ("CRDATE2", "C", 8),
                   ("VERSION", "N", 5), ("LASTID", "N", 10)], rows, memo=None)
    return d
