"""Rapor METNİ için sayı / tarih biçimi (DECISIONS "Sayı ve tarih biçimi").

Binlik ayırıcı Türkçe nokta (``1.234``), tarih ``GG.AA.YYYY``. Sadece görüntülemede kullanılır:
JSON / IR / findings.json / log ve Excel sayısal hücreleri (``#,##0``) ham değer / ISO kalır.
Ondalıklı değerler (``30.0 KB``, ``V8.1``) bu yardımcıların konusu değildir.
"""
from __future__ import annotations

from datetime import date, datetime


def fmt_num(n) -> str:
    """Tam sayıyı binlik nokta ile yazar: 1234567 -> '1.234.567'. Ondalıklı / sayı olmayan değer olduğu gibi döner."""
    if n is None:
        return "-"
    if isinstance(n, bool):
        return str(n)
    if isinstance(n, float):
        if not n.is_integer():
            return str(n)
        n = int(n)
    if isinstance(n, str):
        s = n.strip()
        if not s.lstrip("-").isdigit():
            return n
        n = int(s)
    if not isinstance(n, int):
        return str(n)
    return f"{n:,}".replace(",", ".")


def _to_dt(d):
    if isinstance(d, datetime):
        return d
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day)
    if isinstance(d, (int, float)) and not isinstance(d, bool):
        return datetime.fromtimestamp(d)
    if isinstance(d, str):
        s = d.strip()
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def fmt_date(d) -> str:
    """date / datetime / ISO metin / epoch -> 'GG.AA.YYYY'. Boş -> ''; çözülemeyen metin olduğu gibi döner."""
    if d is None or d == "":
        return ""
    dt = _to_dt(d)
    if dt is None:
        return str(d)
    return f"{dt:%d.%m.%Y}"


def fmt_month(d) -> str:
    """Ay / yıl: 'AA.YYYY' (chart / arşiv tarih aralıkları)."""
    if d is None or d == "":
        return ""
    dt = _to_dt(d)
    return str(d) if dt is None else f"{dt:%m.%Y}"
