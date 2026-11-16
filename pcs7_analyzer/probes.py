"""
Yapı prob'ları: sadece SAYI / KOD / maskeli path üretir (müşteri adı, dosya içeriği yok). Kullanıcıdan gelen çıktı,
bilinmeyen backup yapıları (ör. WinCC Project Duplicator kopyası) için ayrıştırıcıyı yazmakta kullanılır.
Hiçbir yapı varsayımı yapılmaz; prob sadece ölçer. inventory'yi import etmez (döngü yok): küçük kendi maskeleme.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

_KNOWN = ("wincproj", "gracs", "scriptlib", "scriptact", "pas", "archivemanager", "sfcrtbase", "opc", "textlib")


def _mask(rel: str) -> str:
    """Bilinen yapı klasörleri / uzantılar kalır, diğer ad parçaları 'd<N>' (aynı ad = aynı kod)."""
    seen: dict[str, str] = {}
    out = []
    parts = rel.split("/")
    for i, p in enumerate(parts):
        low = p.lower()
        if low in _KNOWN:
            out.append(p)
        elif i == len(parts) - 1:
            ext = Path(p).suffix
            out.append(f"f{ext.lower()}" if ext else "f")
        else:
            out.append(seen.setdefault(low, f"d{len(seen) + 1}"))
    return "/".join(out)


def _ext(name: str) -> str:
    e = Path(name).suffix.lower()
    return e if e else "(uzantısız)"


def wincc_probe(src) -> list[str]:
    """WinCC proje klasörü yapısı prob'u -> madde satırları. Kendi hatasını yakalar."""
    try:
        return _probe(src)
    except Exception as ex:  # noqa: BLE001
        return [f"- wincc_probe: okunamadı ({type(ex).__name__})"]


def _probe(src) -> list[str]:
    entries = list(src.entries)
    lines = [f"- Dosya sayısı: {len(entries)}"]
    mcp = [e for e in entries if e.name.lower().endswith(".mcp")]
    lines.append(f"- .mcp sayısı: {len(mcp)}")
    for e in mcp[:10]:
        depth = e.rel.count("/")
        lines.append(f"  - .mcp derinlik {depth}: {_mask(e.rel)} ({e.size} bayt)")
    if mcp:
        mdirs = {e.parent for e in mcp}
        lines.append(f"- .mcp'nin bulunduğu klasör sayısı: {len(mdirs)}; kökte .mcp: {'evet' if '' in mdirs else 'hayır'}")
    # yapı klasörleri (path'in herhangi bir seviyesinde)
    present = Counter()
    for e in entries:
        for p in {x.lower() for x in e.rel.split("/")[:-1]}:
            if p in _KNOWN:
                present[p] += 1
    lines.append("- Yapı klasörleri (var/yok, dosya sayısı): " +
                 ", ".join(f"{k}={'var (' + str(present[k]) + ')' if present[k] else 'yok'}" for k in _KNOWN))
    exts = Counter(_ext(e.name) for e in entries)
    lines.append("- Dosya türleri (ilk 15): " + ", ".join(f"{k} ×{n}" for k, n in exts.most_common(15)))
    depths = Counter(e.rel.count("/") for e in entries)
    lines.append(f"- Klasör derinliği (max {max(depths) if depths else 0}): " +
                 ", ".join(f"{k}:{n}" for k, n in sorted(depths.items())[:12]))
    top = Counter(e.rel.split("/")[0] for e in entries if "/" in e.rel)
    lines.append(f"- Kök altı klasör sayısı: {len(top)}; kökteki dosya: {sum(1 for e in entries if '/' not in e.rel)}")
    s7 = sum(1 for e in entries if re.search(r"\.(s7p|s7f|s7l)$", e.name, re.I))
    lines.append(f"- STEP 7 proje dosyası (.s7p/.s7f/.s7l): {s7}" + (" (OS-only girdi)" if not s7 else ""))
    lines.append("- Not: Project Duplicator kopyası için maskeli yapi_tanisi.txt kullanıcıdan istenmeli; "
                 "dosya yapısı hakkında varsayım yapılmadı.")
    return lines
