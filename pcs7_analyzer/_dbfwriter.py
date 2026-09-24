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
