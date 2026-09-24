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

