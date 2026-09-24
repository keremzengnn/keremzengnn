"""Symbol table export (.ASC) parser'ı."""
from __future__ import annotations

import re
from pathlib import Path

_SYM = re.compile(r"\s*(FB|FC|SFB|SFC|UDT|OB|DB|VAT)\s+(\d+)")


def parse_symbol_asc(path: Path) -> list[tuple[str, int, str, str]]:
    """'126,<name 24 char><type> <nr>  <type> <nr> <comment>' satırları -> (type, nr, name, comment)."""
    out = []
    for line in Path(path).read_text(encoding="latin1").splitlines():
        if not line.startswith("126,"):
            continue
        s = line[4:]
        name, rest = s[:24].strip(), s[24:]
        m = _SYM.match(rest)
        if not m:
            continue
        comment = re.sub(r"^\s*\S+\s+\d+\s", "", rest[m.end():]).strip()
        out.append((m.group(1), int(m.group(2)), name, comment))
    return out



def _pick(fields: list[str], *keys: str) -> str | None:
    for k in keys:
        for f in fields:
            if k in f.upper():
                return f
    return None


def parse_symlist_dbf(path: Path) -> list[tuple[str, int, str, str]]:
    """
    YDBs/<n>/SYMLIST.DBF -> (type, nr, name, comment); sadece block sembolleri (FB/FC/DB/…).
    Alan adları (STEP 7 V5.x'te `_SKZ`, `_OPIEC`, `_DATATYP`, `_KOMMENTAR`) gerçek dosyayla teyit
    edilmedi; bu yüzden isimde geçen anahtar kelimeyle eşlenir. Bulunamazsa ValueError.
    """
    from .._vendor import dbfread

    table = dbfread.DBF(str(path), encoding="latin1", char_decode_errors="ignore",
                        ignore_missing_memofile=True)
    fields = table.field_names
    f_name = _pick(fields, "SKZ", "SYMBOL", "NAME")
    f_op = _pick(fields, "OPIEC", "OPHIST", "OPERAND", "ADDR")
    f_com = _pick(fields, "KOMMENTAR", "COMMENT")
    if not f_name or not f_op:
        raise ValueError(f"SYMLIST.DBF alanları tanınmadı: {fields}")
    out = []
    for rec in table:
        m = _SYM.match(str(rec.get(f_op) or ""))
        if not m:
            continue
        out.append((m.group(1), int(m.group(2)), str(rec.get(f_name) or "").strip(),
                    str(rec.get(f_com) or "").strip() if f_com else ""))
    return out
