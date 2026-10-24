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


def write_dbf(path: Path, fields, records, *, memo: str | None = "db4", language_driver: int = 0x00) -> None:
    """
    records: list[dict]. Memo alanlarına bytes verilir (None = boş).
    memo: 'db3' (0x83, 0x1A sonlandırıcı), 'db4' (0x8B, uzunluk header'lı) veya None (DBT yazma).
    """
    path = Path(path)
    has_memo = any(t == "M" for _, t, _ in fields)
    version = {"db3": 0x83, "db4": 0x8B}.get(memo, 0x03) if has_memo else 0x03
    memo_blocks: list[bytes] = []

    def memo_ref(data: bytes | None) -> bytes:
        if not data or memo is None:
            return b" " * 10
        if memo == "db3":
            raw = data + b"\x1a\x1a"
        else:
            raw = b"\xff\xff\x08\x08" + struct.pack("<I", len(data) + 8) + data
        raw += b"\x00" * (-len(raw) % 512)
        index = 1 + sum(len(b) // 512 for b in memo_blocks)
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
        next_free = 1 + sum(len(b) // 512 for b in memo_blocks)
        dbt_header = struct.pack("<I", next_free) + b"\x00" * 508
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
