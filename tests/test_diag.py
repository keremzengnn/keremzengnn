"""parsers/diag.py: sentetik DIAGNOSTICS arşivi (müşteri verisi yok)."""
from pcs7_analyzer.parsers import diag
from pcs7_analyzer.source import Entry

ERRORLOG = "\r\n".join([
    "2023-05-11 08:00:01.10 Server      Microsoft SQL Server 2014 - 12.0.4100.1 (Intel X86) ",
    "2023-05-11 08:00:01.10 Server      \tStandard Edition on Windows NT 6.3 <X64> (WOW64)",
    "2023-05-11 08:00:01.20 Server      Registry startup parameters: ",
    "2023-05-11 08:00:01.20 Server      \t -d C:\\MSSQL\\DATA\\master.mdf",
    "2023-05-11 08:00:01.20 Server      \t -g512",
    "2023-05-11 08:00:01.30 Server      Command Line Startup Parameters:",
    "2023-05-11 08:00:01.30 Server      \t -s \"WINCC\"",
    "2023-05-11 08:00:02.00 spid7s      Starting up database 'master'.",
    "2023-05-11 08:12:33.45 spid12s     Error: 17053, Severity: 16, State: 1.",
    "2023-05-11 08:12:33.45 spid12s     LogWriter: Operating system error 33.",
    "2023-05-11 08:13:00.00 spid51      Error: 823, Severity: 24, State: 2.",
    "2023-05-11 08:13:00.00 spid51      The operating system returned error 21 to SQL Server during a read.",
    "2023-05-11 08:14:10.00 spid3s      There is insufficient system memory in resource pool 'internal'.",
    "2023-05-11 08:15:00.00 spid9s      Database 'CC_OS_1_23_05_11' is marked SUSPECT.",
]) + "\r\n"

WINCC_LOG = "\r\n".join([
    "11.05.2023 08:12:40 Redundanz: Umschaltung auf Partner-Server",
    "2023-05-11 08:12:35.120 Redundancy switchover: this server is now standby",
    "05/11/2023 08:20:00 PM Connection lost to AS1",
    "11.05.2023 08:10:00 Verbindung zu AS2 unterbrochen (Störung)",
    "random line without keyword",
    "no timestamp but Fehler in Modul",
]).encode("latin1") + b"\r\nbad bytes \x81\xfe\xff error here\r\n"

EVT_CSV = ("\ufeffDüzey;Tarih ve Saat;Kaynak;Olay Kimliği;Görev Kategorisi\r\n"
           "Hata;11.05.2023 08:12:50;MSSQL$WINCC;17053;Server\r\n"
           "Bilgi;11.05.2023 08:13:00;Service Control Manager;7036;Yok\r\n"
           "Kritik;11.05.2023 08:16:00;Kernel-Power;41;(63)\r\n"
           "Hata;11.05.2023 08:17:00;MSSQL$WINCC;823;Server\r\n").encode("utf-8")


class FakeSource:
    def __init__(self, files: dict[str, bytes], extra: list[str] = ()):
        self.data = files
        self.entries = [Entry(k, len(v), 0.0) for k, v in files.items()] + [Entry(r, 10, 0.0) for r in extra]

    def read_bytes(self, rel: str) -> bytes:
        return self.data[rel]


SEGS = [f"OS1/wincproj/OS_SRV1/ArchiveManager/AlarmLogging/OS_SRV1_ALG_202301{i:04d}.mdf" for i in range(1200)]


def _scan():
    files = {
        "DIAGNOSTICS/MSSQL/Log/ERRORLOG": b"\xff\xfe" + ERRORLOG.encode("utf-16-le"),
        "DIAGNOSTICS/Siemens/Diagnose/WinCC_Redundancy_01.log": WINCC_LOG,
        "DIAGNOSTICS/EventLogs/System.evtx": b"ElfFile\x00" + bytes(range(256)),
        "DIAGNOSTICS/EventLogs/Application.csv": EVT_CSV,
        "DIAGNOSTICS/other/tags.csv": b"Name,Value\r\nx,1\r\n",
    }
    src = FakeSource(files, SEGS)
    return diag.scan_diagnostics(src.entries, src.read_bytes)


def test_is_diag_file():
    assert diag.is_diag_file("a/MSSQL/Log/ERRORLOG.3") == "sql_errorlog"
    assert diag.is_diag_file("a/diagnose/x.txt") == "wincc_log"
    assert diag.is_diag_file("a/CCAlgRtServer_01.log") == "wincc_log"
    assert diag.is_diag_file("a/b.evtx") == "evtx"
    assert diag.is_diag_file("p/OS_TLG_F_2023.ldf") == "archive_segment"
    assert diag.is_diag_file("p/other.log") is None


def test_parse_ts_formats():
    assert diag.parse_ts("2023-05-11 08:12:33.45 spid") == "2023-05-11T08:12:33"
    assert diag.parse_ts("11.05.2023 08:12:40 x") == "2023-05-11T08:12:40"
    assert diag.parse_ts("05/11/2023 08:20:00 PM x") == "2023-05-11T20:20:00"
    assert diag.parse_ts("no ts") == ""


def test_sql_errorlog():
    r = _scan()
    assert r.files["sql_errorlog"] == ["DIAGNOSTICS/MSSQL/Log/ERRORLOG"]
    assert "SQL Server 2014" in r.sql["version"] and r.sql["bits"] == "32"
    assert "-g512" in r.sql["startup_params"] and '-s "WINCC"' in r.sql["startup_params"]
    assert r.sql["errors"][(17053, 16)] == 1 and r.sql["errors"][(823, 24)] == 1
    assert r.sql["memory_pressure"] == 1
    assert r.sql["suspect_dbs"] == ["CC_OS_1_23_05_11"]
    e823 = next(e for e in r.events if "823" in e.text and e.category == "sql_error")
    assert "read" in e823.text                                        # sonraki mesaj satırı eklendi


def test_wincc_log_eventlog_and_segments():
    r = _scan()
    cats = [(e.ts, e.category) for e in r.events if e.source.endswith("WinCC_Redundancy_01.log")]
    assert ("2023-05-11T08:12:40", "redundancy") in cats
    assert ("2023-05-11T08:12:35", "redundancy") in cats
    assert ("2023-05-11T20:20:00", "connection") in cats
    assert ("2023-05-11T08:10:00", "connection") in cats
    assert ("", "error") in cats and len(cats) == 6                   # keyword'süz satır alınmaz
    assert any("bad bytes" in e.text for e in r.events)                # latin1 fallback, çökme yok
    assert r.files["eventlog_csv"] == ["DIAGNOSTICS/EventLogs/Application.csv"]   # tags.csv elendi
    evl = [e for e in r.events if e.category == "eventlog"]
    assert len(evl) == 3 and evl[0].ts == "2023-05-11T08:12:50" and "17053" in evl[0].text
    assert r.files["evtx"] == ["DIAGNOSTICS/EventLogs/System.evtx"]
    assert r.archive_segments == {"OS1/wincproj/OS_SRV1": 1200}


def test_findings_and_timeline():
    r = _scan()
    f = {x.title: x for x in r.findings}
    assert f["SQL Server 32-bit"].confidence == "KANIT"
    assert "memory-to-leave" in f["SQL startup parametresi -g512"].detail
    assert f["SQL bellek baskısı"].confidence == "KANIT"
    hi = f["SQL Severity ≥ 17 hata"]
    assert hi.severity == "Yüksek" and "823" in hi.detail and "17053" not in hi.detail
    assert f["SUSPECT database"].severity == "Yüksek"
    red = f["Redundancy / switchover olayları"]
    assert red.confidence == "ÇIKARIM" and "2 satır" in red.detail and "ilk 2023-05-11T08:12:35" in red.detail
    assert f["Connection kaybı olayları"].confidence == "ÇIKARIM"
    ev = f["Event log Error/Critical"]
    assert "MSSQL$WINCC x2" in ev.detail and "Kernel-Power x1" in ev.detail
    assert f["evtx okunamadı"].confidence == "KANIT" and "okunmadı" in f["evtx okunamadı"].detail
    seg = f["Arşiv segment sayısı çok yüksek"]
    assert seg.source == "OS1/wincproj/OS_SRV1" and "~200" in seg.detail and seg.confidence == "ÇIKARIM"
    assert all(x.source for x in r.findings)
    assert any("evtx okunamadı" in w for w in r.warnings)

    ts = [e.ts for e in r.events]
    known = [t for t in ts if t]
    assert known == sorted(known) and ts[-1] == ""                   # bilinmeyen ts sonda
    win = diag.timeline_window(r.events, "2023-05-11 08:13:00", minutes=2)
    assert win and all("2023-05-11T08:11:00" <= e.ts <= "2023-05-11T08:15:00" for e in win)
    assert {"sql_error", "redundancy", "eventlog"} <= {e.category for e in win}
    assert diag.timeline_window(r.events, "yok") == []


def test_bad_bytes_and_cap_do_not_crash():
    junk = bytes(range(256)) * 50
    big = b"\r\n".join(b"2023-05-11 08:00:%02d archive segment error" % (i % 60) for i in range(6000))
    files = {"x/Diagnose/junk.log": junk, "x/MSSQL/Log/ERRORLOG.1": b"\xff\xfe\x00\xd8",
             "x/diagnose/big.log": big, "x/ev.csv": b"\xff\xfe" + "Level,Date\r\n".encode("utf-16-le")}
    src = FakeSource(files)
    r = diag.scan_diagnostics(src.entries, src.read_bytes)
    assert len(r.events) == diag.MAX_EVENTS and r.category_counts["archive"] == 6000
    assert any("sınırlandı" in w for w in r.warnings)
    r2 = diag.scan_diagnostics(src.entries, src.read_bytes, max_bytes_per_file=10)
    assert any("okunmadı" in w for w in r2.warnings)
