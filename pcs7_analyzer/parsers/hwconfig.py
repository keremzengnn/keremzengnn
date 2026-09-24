"""HW Config export (.cfg) ve .s7h binary fallback parser'ları."""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from pathlib import Path

_CFG_LINE = re.compile(
    r'^(RACK|DPSUBSYSTEM|IOSUBSYSTEM)\s[^"]*"([^"]+)"(?:\s*"(V[^"]*)")?,\s*"([^"]*)"'
)


@dataclass
class HwModule:
    location: str   # 'RACK 0, SLOT 3' / 'DPSUBSYSTEM 1, DPADDRESS 5, SLOT 4'
    order_no: str   # MLFB veya GSD dosya adı (CPX_059E.GSE) / HSP kodu
    firmware: str
    name: str

    @property
    def is_station_header(self) -> bool:
        """DP/IO slave'in kendisi (SLOT içermeyen satır)."""
        return ("DPADDRESS" in self.location or "IOADDRESS" in self.location) and "SLOT" not in self.location

    @property
    def is_internal(self) -> bool:
        return self.order_no.startswith("_")  # HSP submodule, port vb.

    @property
    def is_gsd(self) -> bool:
        return self.order_no.upper().endswith((".GSD", ".GSE", ".GSG")) or ":" in self.order_no


def parse_cfg(cfg_path: Path) -> dict:
    """HW Config export'unu okur (latin1, CRLF)."""
    txt = Path(cfg_path).read_text(encoding="latin1")
    lines = txt.splitlines()
    station = next((l for l in lines if l.startswith("STATION")), "")
    subnets = [l for l in lines if l.startswith("SUBNET")]
    modules = []
    for l in lines:
        m = _CFG_LINE.match(l)
        if m:
            modules.append(HwModule(l.split('"')[0].strip().rstrip(","), m.group(2), m.group(3) or "", m.group(4)))
    used = re.search(r'USED_S7_VERSIONS "([^"]*)"', txt)
    used_versions = ""
    if used:
        try:
            used_versions = bytes.fromhex(used.group(1).replace(" ", "")).decode("latin1").strip("\x00|")
        except ValueError:
            pass
    step7 = re.search(r"#STEP7_VERSION (.*)", txt)
    return {
        "station": station,
        "subnets": subnets,
        "modules": modules,
        "used_s7_versions": used_versions,      # örn '5.5.4.9_10.1.0.1' -> STEP 7 V5.5 SP4 -> PCS 7 V8.1
        "export_step7_version": step7.group(1).strip() if step7 else "",
        "f_capable": 'CAPABLE_F_SAFETY "1"' in txt,
        "pdm_used": bool(re.search(r'PDM_PARAM "1"', txt)),
    }


def hw_inventory(cfg: dict) -> collections.Counter:
    """{(order_no, fw, 'slave'|'mod'): adet}; internal HSP submodule'ler hariç."""
    c = collections.Counter()
    for m in cfg["modules"]:
        if m.is_internal:
            continue
        c[(m.order_no, m.firmware, "slave" if m.is_station_header else "mod")] += 1
    return c


# ---------------------------------------------------------------------------
# .s7h (hOmSave7/s7hstatx/*.s7h) -> cfg export yoksa fallback
# ---------------------------------------------------------------------------

_MLFB = re.compile(rb"6(?:ES|GK|AV|SL|EP)\d ?[0-9A-Z]{3}-[0-9A-Z]{5}-[0-9A-Z]{4}")


def scan_s7h(path: Path) -> collections.Counter:
    """Binary .s7h içinden MLFB ve hemen ardından gelen firmware string'ini çıkarır."""
    data = Path(path).read_bytes()
    strings = re.findall(rb"[ -~]{4,}", data)
    out = collections.Counter()
    for i, s in enumerate(strings):
        if _MLFB.fullmatch(s):
            fw = strings[i + 1].decode() if i + 1 < len(strings) and re.fullmatch(rb"V\d+\.\d+", strings[i + 1]) else ""
            out[(s.decode(), fw)] += 1
    return out

