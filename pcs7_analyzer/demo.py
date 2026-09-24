"""
Sahte ama gerçekçi bir PCS 7 V8.1 multiproject backup'ı üretir (test ortamı / demo).

Müşteri verisi içermez. Gerçek projedeki tipik durumları taklit eder: karışık APL versiyonları,
header'sız STL block, Logic Matrix, SFC, COMM71, F-System (HW export'ta F-I/O eksik),
H-Sync modülü (Released Modules listesinde yok), ES ↔ OS server farkları, farklı client grupları,
farklı tarihli ikinci backup.

  python -m pcs7_analyzer --demo <hedef_klasör>
"""
from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path

from ._dbfwriter import SUBBLK_FIELDS, block, fb_instance, sfb_instance, write_dbf

FB, FC, OB, DB = "00004", "00005", "00008", "00010"
DAY = 86400.0
T0 = time.mktime((2023, 6, 1, 12, 0, 0, 0, 0, -1))

SYMLIST_FIELDS = [("_SKZ", "C", 24), ("_OPIEC", "C", 12), ("_DATATYP", "C", 10), ("_KOMMENTAR", "C", 80)]

DEMO_RELEASED_CSV = """mlfb,fw,status,note
6ES7 414-5HM06-0AB0,V6.0,released,
6ES7 400-2JA00-0AA0,,released,
6GK7 443-1EX30-0XE0,V3.0,released,
6ES7 152-1AA00-0AB0,,released,
6ES7 131-7RF00-0AB0,,released,
6ES7 134-7TD00-0AB0,,released,
6ES7 153-2BA10-0XB0,,released,
6ES7 321-1BH02-0AA0,,released,
6ES7 138-7FA00-0AB0,,released,
"""


def _file(root: Path, rel: str, data: bytes = b"x", mtime: float | None = None) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _sym(name, op, typ="", comment=""):
    return {"_SKZ": name, "_OPIEC": op, "_DATATYP": typ, "_KOMMENTAR": comment}


def _cfg(station: str, *, f_capable: bool, extra: list[str]) -> bytes:
    used = " ".join(f"{b:02X}" for b in b"5.5.4.9_10.1.0.1\x00")
    lines = [
        'FILEVERSION "3.2"', "#STEP7_VERSION V5.5 SP4", f'STATION S7400H , "{station}"',
        'SUBNET PROFIBUS , "PROFIBUS(1)"', 'SUBNET INDUSTRIAL_ETHERNET , "Plant bus"',
        'RACK 0, "6ES7 400-2JA00-0AA0", "UR2-H"',
        'RACK 0, SLOT 3, "6ES7 414-5HM06-0AB0" "V6.0", "CPU 414-5H"',
        'RACK 0, SLOT 3, SUBSLOT 1, "_S7H_IF1", "IF1"',
        'RACK 0, SLOT 3, SUBSLOT 2, "_S7H_IF2", "IF2"',
        'RACK 0, SLOT 3, SUBSLOT 1, SUBMODULE 1, "6ES7 960-1AA06-0XA0", "H-Sync"',
        'RACK 0, SLOT 3, SUBSLOT 1, SUBMODULE 2, "6ES7 960-1AA06-0XA0", "H-Sync"',
        'RACK 0, SLOT 5, "6GK7 443-1EX30-0XE0" "V3.0", "CP 443-1"',
        "CPU_ATTRIBUTES", f'  CAPABLE_F_SAFETY "{1 if f_capable else 0}"', f'  USED_S7_VERSIONS "{used}"',
        'DPSUBSYSTEM 1, DPADDRESS 3, "6ES7 152-1AA00-0AB0", "ET 200iSP"',
        'DPSUBSYSTEM 1, DPADDRESS 3, SLOT 4, "6ES7 131-7RF00-0AB0", "8DI NAMUR"',
        'DPSUBSYSTEM 1, DPADDRESS 3, SLOT 5, "6ES7 134-7TD00-0AB0", "4AI HART"',
        '  PDM_PARAM "0"',
    ] + extra
    return ("\r\n".join(lines) + "\r\n").encode("latin1")


def _s7h(orders: list[tuple[str, str]]) -> bytes:
    out = b"\x00\x01S7H\x00"
    for o, fw in orders:
        out += o.encode() + b"\x00" + (fw.encode() + b"\x00" if fw else b"\x02\x03")
    return out


def _as01(root: Path, base: str, mtime: float) -> None:
    recs = [
        block(FB, 1827, "AdvLib81", "Intlk16", 0x10, "AdvLib81"),
        block(FB, 1850, "AdvLib80", "PIDConL", 0x10, "AdvLib80"),
        block(FB, 1851, "AdvLib82", "MotL", 0x10, "AdvLib82"),
        block(FB, 1800, "AdvLib81", "Pcs7DiIn", 0x10, "AdvLib81"),
        block(FB, 1700, "AdvLibLM", "LMatrix", 0x10, "AdvLibLM"),
        block(FB, 300, "SFC", "SFC_FB", 0x71, "ES_SFC"),
        block(FB, 60, "COMM", "SEND_R", 0x10, "COMM71"),
        block(FB, 2500, "", "", None, "", lang="00001"),                  # header'sız STL
        block(FB, 2501, "ESA", "STATECTRL8", 0x10, "MANAR"),
        block(FB, 1990, "DRIVE", "SINAMICS_G120", 0x11, "BM", lang="00004"),
        block(FB, 1993, "COMM", "E_AS_GET", 0x10, "BM", lang="00001"),
        block(FC, 1, "", "", 0x10, "ES_MAP"), block(FC, 2, "", "", 0x10, "ES_MAP"),
        block(FC, 256, "CONVERT", "SEL_R", 0x10, "DRIVER81"),
        block(OB, 1, "", "CYC_INT", None, ""), block(OB, 35, "", "", None, ""), block(OB, 100, "", "", None, ""),
    ]
    dbn = 100
    for fb, n in [(1827, 5), (1850, 3), (1851, 2), (1800, 6), (300, 2), (1990, 1), (2500, 1), (1993, 1)]:
        for _ in range(n):
            recs.append(block(DB, dbn, "", "", ssb=fb_instance(fb)))
            dbn += 1
    recs.append(block(DB, dbn, "", "", ssb=sfb_instance(14)))
    recs.append(block(DB, dbn + 1, "", "", ssb=b"\x01\x00\x00"))
    d = f"{base}/AS01/ombstx/offline/00000001"
    write_dbf(_file(root, f"{d}/SUBBLK.DBF"), SUBBLK_FIELDS, recs, memo="db4")
    _file(root, f"{d}/BAUSTEIN.DBF")
    write_dbf(_file(root, f"{base}/AS01/ombstx/offline/00000002/SUBBLK.DBF"), SUBBLK_FIELDS, [], memo="db4")
    syms = [_sym("Intlk16", "FB  1827"), _sym("PIDConL", "FB  1850"), _sym("MotL", "FB  1851"),
            _sym("Pcs7DiIn", "FB  1800"), _sym("LMatrix", "FB  1700"), _sym("SFC_FB", "FB   300"),
            _sym("SEND_R", "FB    60"), _sym("E_AUTSIMRST", "FB  2500"), _sym("STATECTRL8", "FB  2501"),
            _sym("SINAMICS_G120", "FB  1990"), _sym("E_AS_GET", "FB  1993"), _sym("E_AS_PUT", "FB  1994"),
            _sym("CYC_INT", "OB     1"), _sym("Motor_Run", "I   0.0", "BOOL")]
    write_dbf(_file(root, f"{base}/AS01/YDBs/1/SYMLIST.DBF"), SYMLIST_FIELDS, syms, memo=None)
    _file(root, f"{base}/AS01/AS01.s7p", b"s7p")
    _file(root, f"{base}/AS01/hOmSave7/s7hstatx/S00001.s7h",
          _s7h([("6ES7 414-5HM06-0AB0", "V6.0"), ("6GK7 443-1EX30-0XE0", "V3.0")]))
    for p in (root / base / "AS01").rglob("*"):
        if p.is_file():
            os.utime(p, (mtime, mtime))


def _as02(root: Path, base: str) -> None:
    recs = [
        block(FB, 1827, "AdvLib82", "Intlk16", 0x10, "AdvLib82"),
        block(FB, 1800, "AdvLib81", "Pcs7DiIn", 0x10, "AdvLib81"),
        block(FB, 351, "", "", None, ""), block(FB, 352, "", "", None, ""), block(FB, 353, "", "", None, ""),
        block(FC, 300, "F_LIB", "F_CTRL", 0x13, "F_SAFE13"),
        block(OB, 1, "", "", None, ""),
    ]
    dbn = 200
    for fb, n in [(1827, 4), (1800, 3), (351, 4), (352, 2), (353, 1)]:
        for _ in range(n):
            recs.append(block(DB, dbn, "", "", ssb=fb_instance(fb)))
            dbn += 1
    d = f"{base}/AS02/ombstx/offline/0000000A"
    write_dbf(_file(root, f"{d}/SUBBLK.DBF"), SUBBLK_FIELDS, recs, memo="db4")
    syms = [_sym("Intlk16", "FB  1827"), _sym("Pcs7DiIn", "FB  1800"), _sym("F_CH_DI", "FB   351"),
            _sym("F_CH_DO", "FB   352"), _sym("F_PLK", "FB   353")]
    write_dbf(_file(root, f"{base}/AS02/YDBs/1/SYMLIST.DBF"), SYMLIST_FIELDS, syms, memo=None)
    _file(root, f"{base}/AS02/AS02.s7p", b"s7p")


PICS = ["Tank_1.pdl", "Tank_2.pdl", "Tank_3.pdl", "Overview.pdl", "@PG_MotL.pdl", "@PG_Intlk16.pdl",
        "@PG_SWC_MOS1.pdl", "@PCS7TypicalsDemoAPL.pdl", "@Template.pdl"]


def _os_project(root: Path, rel: str, name: str, mtime: float, pics=PICS, extra: dict | None = None) -> None:
    _file(root, f"{rel}/{name}.mcp", b"\x00WinCC\x00V07.03.20.04\x00", mtime)
    _file(root, f"{rel}/{name}.MDF", b"db", mtime)
    for p in pics:
        _file(root, f"{rel}/GraCS/{p}", f"pdl {p}".encode(), mtime)
    _file(root, f"{rel}/ScriptLib/Module1.bmo", b"vbs", mtime)
    _file(root, f"{rel}/ScriptAct/Global1.bac", b"vbs", mtime)
    _file(root, f"{rel}/ESPC/PAS/Action1.pas", b"c", mtime)
    for k, v in (extra or {}).items():
        _file(root, f"{rel}/{k}", v[0], v[1])


def build_demo_project(root: Path) -> Path:
    """root altında DEMO backup klasörü oluşturur, backup kökünü döndürür."""
    root = Path(root)
    bk = root / "DEMO_BACKUP"
    base = "DEMO_MP"
    _file(bk, f"{base}/DEMO_MP.s7f", b"s7f")
    _as01(bk, base, T0)
    _as02(bk, base)
    _file(bk, f"{base}/OS/OS.s7p", b"s7p")
    es = f"{base}/OS/wincproj/OS_SRV1"
    _os_project(bk, es, "OS_SRV1", T0, extra={
        "GraCS/Tank_3.pdl": (b"pdl Tank_3 ES yeni", T0 + 5 * DAY),
        "GraCS/Tank_old.pdl": (b"eski", T0),
        "OPC/DataAccess/config.xml": (b"<x/>", T0),
    })
    for c in ("OSC01", "OSC02"):
        _os_project(bk, f"{base}/OS/wincproj/{c}", c, T0, pics=["@PG_MotL.pdl", "@PG_Intlk16.pdl"])
    _os_project(bk, f"{base}/OS/wincproj/OSC03", "OSC03", T0,
                pics=["@PG_MotL.pdl", "@PG_Intlk16.pdl", "@PG_APL_Message_AOTC.pdl"])
    # OS server PC'sinden alınmış kopya: online değişiklikler
    srv = "PC_KOPYALARI/SRV1/wincproj/OS_SRV1"
    _os_project(bk, srv, "OS_SRV1", T0, extra={
        "GraCS/Tank_2.pdl": (b"pdl Tank_2 server'da degisti", T0 + 30 * DAY),
        "GraCS/Tank_3.pdl": (b"pdl Tank_3", T0),
        "GraCS/Tank_New.pdl": (b"sadece server", T0 + 30 * DAY),
        "GraCS/@ServerButtons.pdl": (b"sadece server", T0 + 30 * DAY),
        "ScriptAct/Global_new.bac": (b"sadece server", T0 + 30 * DAY),
        "OPC/DataAccess/config.xml": (b"<x/>", T0),
    })
    (bk / srv / "ESPC").rename(bk / srv / "SRV1PC")   # PC adı klasörü farklı -> normalize edilmeli
    _file(bk, "exports/AS01.cfg", _cfg("AS01", f_capable=False, extra=[
        'DPSUBSYSTEM 1, DPADDRESS 20, "CPX_059E.GSE", "Festo CPX"',
        'DPSUBSYSTEM 1, DPADDRESS 21, "CPX_059E.GSE", "Festo CPX"']))
    _file(bk, "exports/AS02.cfg", _cfg("AS02", f_capable=True, extra=[]))
    # Eski tarihli ikinci backup
    _as01(bk, "ESKI_BACKUP/DEMO_MP", T0 - 400 * DAY)
    _file(Path(root), "released_demo.csv", DEMO_RELEASED_CSV.encode())
    return bk


def build_demo_zip(root: Path) -> Path:
    bk = build_demo_project(root)
    z = Path(root) / "DEMO_BACKUP.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(bk.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(bk).as_posix())
    return z
