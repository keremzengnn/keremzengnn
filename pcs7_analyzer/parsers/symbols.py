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


def read_symlist_all(path: Path) -> tuple[list[dict], list[str]]:
    """
    SYMLIST.DBF'in TÜM sembolleri (I/O, M, block…): [{symbol, operand, datatype, comment}], alan adları.
    Alanlar isimdeki anahtar kelimeyle eşlenir (gerçek dosyayla teyit edilmedi); tanınmazsa ValueError.
    """
    from .._vendor import dbfread

    table = dbfread.DBF(str(path), encoding="latin1", char_decode_errors="ignore", ignore_missing_memofile=True)
    fields = table.field_names
    f_name = _pick(fields, "SKZ", "SYMBOL", "NAME")
    f_op = _pick(fields, "OPIEC", "OPHIST", "OPERAND", "ADDR")
    f_typ = _pick(fields, "DATATYP", "TYPE")
    f_com = _pick(fields, "KOMMENTAR", "COMMENT")
    if not f_name or not f_op:
        raise ValueError(f"SYMLIST.DBF alanları tanınmadı: {fields}")
    rows = []
    for rec in table:
        name = str(rec.get(f_name) or "").strip()
        op = re.sub(r"\s+", " ", str(rec.get(f_op) or "")).strip()
        if not name and not op:
            continue
        rows.append({"symbol": name, "operand": op,
                     "datatype": str(rec.get(f_typ) or "").strip() if f_typ else "",
                     "comment": str(rec.get(f_com) or "").strip() if f_com else ""})
    return rows, fields


def read_symbol_asc_all(path: Path) -> list[dict]:
    """.ASC export'unun tüm satırları: '126,<isim 24><operand 12><tip 10><yorum>' (sabit genişlik, yaklaşık)."""
    rows = []
    for line in Path(path).read_text(encoding="latin1").splitlines():
        if not line.startswith("126,"):
            continue
        s = line[4:]
        rest = s[24:]
        m = re.match(r"\s*(\S+\s+[\d.]+)\s+(\S+(?:\s+\d+)?)\s*(.*)", rest)
        rows.append({"symbol": s[:24].strip(), "operand": re.sub(r"\s+", " ", m.group(1)) if m else rest[:12].strip(),
                     "datatype": m.group(2).strip() if m else "", "comment": m.group(3).strip() if m else rest.strip()})
    return rows


_OP = re.compile(r"^(PIW|PQW|PIB|PQB|PID|PQD|PEW|PAW|IW|QW|MW|IB|QB|MB|ID|QD|MD|EW|AW|EB|AB|ED|AD|I|Q|E|A|M|T|C|Z|"
                 r"FB|FC|SFB|SFC|DB|UDT|OB|VAT)\s*(\d+)(?:\.(\d))?$", re.I)
_AREA = {"E": "I", "A": "Q", "Z": "C", "EB": "IB", "AB": "QB", "EW": "IW", "AW": "QW", "ED": "ID", "AD": "QD",
         "PEW": "PIW", "PAW": "PQW"}   # Almanca mnemonic -> İngilizce


def symbol_stats(rows: list[dict]) -> dict:
    """
    Symbol table kontrolleri (KANIT: tablo içeriğinden):
    - dup_operand: aynı operanda birden fazla sembol
    - dup_symbol:  aynı sembol adı birden fazla satırda (STEP 7 normalde izin vermez -> bozuk / birleştirilmiş tablo)
    - areas:       alan bazında sembol sayısı ve adres aralığı (I/Q/M/PIW…: byte; block'lar: numara)
    - unparsed:    tanınmayan operand sayısı
    Not: bit / word çakışması (M10.0 ile MW10) kontrol edilmez.
    """
    by_op: dict[str, list[str]] = {}
    by_sym: dict[str, int] = {}
    areas: dict[str, list[int]] = {}
    unparsed = 0
    for r in rows:
        op = re.sub(r"\s+", " ", str(r.get("operand") or "")).strip().upper()
        sym = str(r.get("symbol") or "").strip()
        if sym:
            by_sym[sym] = by_sym.get(sym, 0) + 1
        m = _OP.match(op)
        if not m:
            if op:
                unparsed += 1
            continue
        area = _AREA.get(m.group(1).upper(), m.group(1).upper())
        key = f"{area} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) is not None else "")
        by_op.setdefault(key, []).append(sym)
        areas.setdefault(area, []).append(int(m.group(2)))
    return {
        "dup_operand": {k: v for k, v in sorted(by_op.items()) if len(v) > 1},
        "dup_symbol": {k: n for k, n in sorted(by_sym.items()) if n > 1},
        "areas": {a: (len(v), min(v), max(v)) for a, v in sorted(areas.items())},
        "unparsed": unparsed,
        "total": len(rows),
    }
