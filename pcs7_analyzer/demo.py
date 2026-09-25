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
        block(FB, 1700, "AdvLibLM", "LM_Matrix", 0x10, "AdvLibLM"),
        block(FB, 1701, "AdvLibLM", "LM_Cause", 0x10, "AdvLibLM"),
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
            _sym("Pcs7DiIn", "FB  1800"), _sym("LM_Matrix", "FB  1700"), _sym("LM_Cause", "FB  1701"), _sym("SFC_FB", "FB   300"),
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


def _export_text(sections: list[tuple[str, list[str], list[list[str]]]]) -> bytes:
    """Configuration Studio export formatı: bölüm başı, [ID][n] satırı, başlıklar, satırlar; UTF-16LE + BOM."""
    lines = []
    for i, (name, headers, rows) in enumerate(sections):
        lines.append(f"{name}\t{name}s\t{name}")
        lines.append(f"[{name.upper()}][{i + 1}]")
        lines.append("\t".join(headers) + " ")
        lines += ["\t".join(r) for r in rows]
    return "\r\n".join(lines).encode("utf-16")


def _tag_export(conns: list[tuple[str, str, str, str]], tags: list[tuple[str, str]], sfc: int) -> bytes:
    struct = [[f"CHART{i:03d}/SFC", "@SFC_RTS", conns[0][0]] for i in range(sfc)]
    return _export_text([
        ("DmConnection", ["Name", "Communication driver", "Channel unit", "Connection parameter"], [list(c) for c in conns]),
        ("DmTag", ["Name", "Connection", "Data type", "Address"],
         [[n, c, "Floating-point number 32-bit IEEE 754", "DB1,DD0"] for n, c in tags]),
        ("DmStructtag", ["Name", "Structure type", "Connection"], struct),
    ])


def _alarm_export(rows: list[list[str]]) -> bytes:
    return _export_text([("ALG_Alarm", ["Number", "Message tag", "Message class", "Message Type", "Message Group",
                                        "Source (ENU)", "Area (ENU)", "Event (ENU)"], rows)])


def _wincc_exports(bk: Path) -> None:
    tags = [(f"TIC{i:03d}/PV_Out#Value", "AS01") for i in range(40)] + [(f"FI{i:03d}/PV_Out#Value", "AS02") for i in range(20)]
    eng_conns = [("AS01_ES", "SIMATIC S7 Protocol Suite", "Named Connections", "NC,AS01_ES,WinCC Appl."),
                 ("AS02_ES", "SIMATIC S7 Protocol Suite", "Named Connections", "NC,AS02_ES,WinCC Appl."),
                 ("TANKSRV_A", "OPC", "OPCGroup (OPCHN Unit #1)", "SaabTankRadar.TankServer.1;10.0.0.5;"),
                 ("DANIEL_1", "OPC", "OPCGroup (OPCHN Unit #1)", "Daniel.DanOPCHub;10.0.0.6;"),
                 ("TANK", "SIMATIC S7 Protocol Suite", "TCP/IP", "192.168.0.70,,02,03")]
    srv_conns = [("AS01_SRV", "SIMATIC S7 Protocol Suite", "Named Connections", "NC,AS01_SRV,WinCC Appl."),
                 ("AS02_SRV", "SIMATIC S7 Protocol Suite", "Named Connections", "NC,AS02_SRV,WinCC Appl."),
                 ("TANKSRV_A", "OPC", "OPCGroup (OPCHN Unit #1)", "SaabTankRadar.TankServer.1;10.0.0.5;"),
                 ("DELTAV_WS", "OPC", "OPCGroup (OPCHN Unit #1)", "OPC.DeltaV.1;192.168.4.130;\x01\x7f\x02"),
                 ("TANK", "SIMATIC S7 Protocol Suite", "TCP/IP", "192.168.0.70,,02,03")]
    eng_tags = [(n, c.replace("AS01", "AS01_ES").replace("AS02", "AS02_ES")) for n, c in tags] + \
               [("TANKSRV_A/LEVEL1", "TANKSRV_A"), ("DANIEL_1/FLOW", "DANIEL_1"), ("TANK/T1", "TANK"),
                ("TEST65/PT03#Value", "AS01_ES")]
    srv_tags = [(n, c.replace("AS01", "AS01_SRV").replace("AS02", "AS02_SRV")) for n, c in tags] + \
               [("TANKSRV_A/LEVEL1", "TANKSRV_A"), ("DELTAV_WS/F1", "DELTAV_WS"), ("TANK/T1", "TANK")]
    _file(bk, "exports/wincc/ENG_Tags.txt", _tag_export(eng_conns, eng_tags, sfc=0))
    _file(bk, "exports/wincc/OS_SRV1_Tags.txt", _tag_export(srv_conns, srv_tags, sfc=6))
    common = [[str(1000 + i), f"TIC{i:03d}/Alarm#Value", "AS process control message", "Alarm High", "", f"TIC{i:03d}",
               "Area1", f"Tank {i} level high"] for i in range(10)]
    diag = [[str(2000 + i), f"AS01_1/@(1)/MOD_D1_{i}#RawEvent", "AS control system message", "Failure", "", "", "",
             "Error channel"] for i in range(7)]
    split = [["continued text of a multi-line event", "", "", "", "", "", "", ""]]
    eng_alarms = [r[:] for r in common] + diag + split
    eng_alarms[3][7] = "Tank XX level high"                       # şablon metin (ENG) vs gerçek metin (SRV1)
    srv_alarms = [r[:] for r in common] + [["3001", "TANKSRV_A/Conn", "System, does not require acknowledgment", "", "",
                                            "", "Area1", "TANK_MASTER_SERVER connection lost"]]
    _file(bk, "exports/wincc/ENG_Alarms.txt", _alarm_export(eng_alarms))
    _file(bk, "exports/wincc/OS_SRV1_Alarms.txt", _alarm_export(srv_alarms))


CHARTLST = "\r\n".join(
    f"V701.{n}.{ts}.{n}.0.0.{c}.0" for n, ts, c in [
        ("TK01_OP1_FILL_CYCLE", 1481000000, "Tank 1 fill"), ("TK01_OP2_DRAIN", 1482000000, ""),
        ("TK02_OP1_FILL_CYCLE", 1500000000, ""), ("GO_TRANSFER", 1510000000, "gas oil"),
        ("MN_SEL_A", 1530000000, ""), ("MN_SEL_B", 1531000000, "")]) + "\r\n"


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
    # SRV1: dolu SFC görselleştirme + arşiv segmentleri + büyük SQL log
    _file(bk, f"{es}/SfcRtBase/ChartLst", CHARTLST.encode("latin1"), T0 + 10 * DAY)
    _file(bk, f"{es}/SfcRtBase/objects.dat", b"\x00" * 30000, T0 + 10 * DAY)
    _file(bk, f"{es}/SfcRtBase/objects.idx", b"\x00" * 150000, T0 + 10 * DAY)
    for i in range(2):
        _file(bk, f"{es}/OS_SRV1ALG_201608{i + 1:02d}0000.mdf", b"\x00" * 100, T0 - 300 * DAY)
    for i in range(3):
        _file(bk, f"{es}/OS_SRV1TLG_F_201608{i + 1:02d}0000.mdf", b"\x00" * 100, T0 - 300 * DAY)
    _file(bk, f"{es}/OS_SRV1Alg.mdf", b"\x00" * 100, T0 - 300 * DAY)
    _file(bk, f"{es}/OS_SRV1.MDF", b"\x00" * 1000, T0)
    _file(bk, f"{es}/OS_SRV1.ldf", b"\x00" * 5000, T0)
    _file(bk, f"{es}/GraCS/@PCS7TypicalsAPC.pdl", b"apc", T0)
    # Standby (2 dosya), referans (1 dosya, client sayılmaz), OS1000 (kendi custom picture'ları)
    _file(bk, f"{base}/OS/wincproj/OS_SRV1_StBy/OS_SRV1_StBy.mcp", b"\x00V07.03.20.04\x00", T0)
    _file(bk, f"{base}/OS/wincproj/OS_SRV1_StBy/OS_SRV1_StBy.MDF", b"db", T0)
    _file(bk, f"{base}/OS/wincproj/OSC90_Ref(1)/OSC90_Ref(1).mcp", b"\x00V07.03.20.04\x00", T0)
    _os_project(bk, f"{base}/OS/wincproj/OS1000", "OS1000", T0,
                pics=["@PG_MotL.pdl", "@PG_Intlk16.pdl", "Tank_A.pdl", "Tank_B.pdl", "@ServerButtons.pdl"])
    # ENG: ES üzerinde çalışan ayrı ve tam OS (SRV1'in master kopyası değil); SFC görselleştirmesi boş şablon
    _file(bk, f"{base}/ENG/ENG.s7p", b"s7p")
    eng = f"{base}/ENG/wincproj/ENG"
    _os_project(bk, eng, "ENG", T0, extra={
        "GraCS/Tank_2.pdl": (b"pdl Tank_2 ENG", T0 - 10 * DAY),
        "GraCS/NewPdl1.pdl": (b"test", T0),
        "ScriptAct/Global_old.bac": (b"vbs", T0),
    })
    _file(bk, f"{eng}/SfcRtBase/objects.dat", b"\x00" * 10240, T0)
    _file(bk, f"{eng}/SfcRtBase/objects.idx", b"\x00" * 141312, T0)
    _wincc_exports(bk)
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
