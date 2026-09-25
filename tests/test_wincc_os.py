"""Ek prompt (WinCC, OS, alarm, arşiv, SFC, Logic Matrix, lisans) kapsamındaki analizler — sahte demo ile."""
import pytest

from pcs7_analyzer.analyze import ManualInputs, analyze, os_role
from pcs7_analyzer.demo import build_demo_project
from pcs7_analyzer.parsers.wincc import chart_group, parse_chartlst
from pcs7_analyzer.parsers.wincc_export import (
    alarms, classify_connection, connections, looks_like_export, parse_export, tag_totals,
)
from pcs7_analyzer.report import manual_items, prep_list, render_markdown


@pytest.fixture(scope="module")
def an(tmp_path_factory):
    root = tmp_path_factory.mktemp("w")
    return analyze(build_demo_project(root), manual=ManualInputs(as_rt_po="250", pc_stations=["OSC01", "OSC02", "OSC99"]))


# --- export formatı ---------------------------------------------------------

def _exp(sections):
    lines = []
    for i, (name, headers, rows) in enumerate(sections):
        lines += [f"{name}\t{name}s\t{name}", f"[X][{i}]", "\t".join(headers) + " \n"[:1]] + ["\t".join(r) for r in rows]
    return "\r\n".join(lines).encode("utf-16")


def test_export_sections_and_utf16():
    data = _exp([("DmConnection", ["Name", "Communication driver", "Channel unit", "Connection parameter "],
                  [["AS12_SRV", "SIMATIC S7", "Named Connections", "NC,AS12_SRV,WinCC Appl."]]),
                 ("DmTag", ["Name", "Connection", "Data type", "Address"], [["T1", "AS12_SRV", "Bool", "DB1"]] * 3),
                 ("DmStructtag", ["Name", "Structure type", "Connection"], [["S1", "@SFC_RTS", "AS12_SRV"]])])
    assert looks_like_export(data[:4000])
    e = parse_export(data, "x.txt", "SRV1")
    assert set(e.sections) == {"DmConnection", "DmTag", "DmStructtag"}
    assert e.sections["DmConnection"].headers[-1] == "Connection parameter"      # sondaki boşluk strip
    assert tag_totals(e) == {"DmTag": 3, "DmStructtag": 1, "total": 4}
    c = connections(e)["AS12_SRV"]
    assert (c.kind, c.as_label, c.tags, c.struct_tags) == ("named", "AS12", 3, 1)


def test_alarm_only_numeric_rows():
    data = _exp([("ALG_Alarm", ["Number", "Message tag", "Message class", "Message Type", "Message Group",
                                "Source (ENU)", "Area (ENU)", "Event (ENU)"],
                  [["1", "A/B", "Alarm", "High", "", "S", "Area1", "text part"], ["continued", "", "", "", "", "", "", ""],
                   ["2", "A/C", "Warning", "Low", "", "S", "", "t2"]])])
    al = alarms(parse_export(data))
    assert sorted(al) == [1, 2] and al[1].area == "Area1"


@pytest.mark.parametrize("param, kind, vendor, ip", [
    ("NC,AS2_SRV,WinCC Appl.", "named", "", ""),
    ("192.168.0.70,,02,03", "tcpip", "", "192.168.0.70"),
    ("OPC.DeltaV.1;192.168.4.130;\x01\x7f", "opc", "Emerson DeltaV", "192.168.4.130"),
    ("SaabTankRadar.TankServer.1;10.0.0.5;", "opc", "Saab / Rosemount TankRadar", "10.0.0.5"),
    ("Daniel.DanOPCHub;x", "opc", "Emerson Daniel", ""),
])
def test_classify_connection(param, kind, vendor, ip):
    c = classify_connection("X", "", "", param)
    assert (c.kind, c.opc_vendor, c.ip) == (kind, vendor, ip)
    assert "\x01" not in c.parameter


# --- roller / düzeltmeler ---------------------------------------------------------

@pytest.mark.parametrize("name, role", [("SRV1", "server"), ("SRV1_StBy", "standby"), ("OSC90_Ref(1)", "reference"),
                                        ("ENG", "es"), ("OSC10", "client"), ("OS(17)", "client"), ("OS1000", "client"), ("TANKPC", "?")])
def test_os_role(name, role):
    assert os_role(name) == role


def test_eng_srv1_is_not_master_copy(an):
    pair = [d for d in an.os_diffs if d.kind == "os_pair"]
    assert pair and (pair[0].a_label, pair[0].b_label) == ("ENG", "OS_SRV1")
    f = [x for x in an.findings if x.check_id == "CONS_ES_SERVER" and "iki OS projesi ayrışmış" in x.detail]
    assert f and "online" not in f[0].detail and "master" not in f[0].detail


def test_roles_reference_standby_os1000(an):
    r = {o.info.name: o for o in an.os_projects if o.in_es}
    assert r["OSC90_Ref(1)"].role == "reference" and r["OS_SRV1_StBy"].role == "standby"
    assert r["OS1000"].role == "client" and "rolü teyit" in r["OS1000"].role_note
    assert not any(m.endswith("OSC90_Ref(1)") for g in an.client_groups for m in g.members)


def test_pc_station_vs_wincproj(an):
    assert an.missing_os_projects == ["OSC99"]
    assert "OS1000" in an.extra_os_projects and "OSC03" in an.extra_os_projects


# --- WinCC ENG <-> SRV1 ------------------------------------------------------------

def test_wincc_totals_and_connections(an):
    eng, srv = an.wincc["ENG"], an.wincc["OS_SRV1"]
    assert (eng.dm_tag, eng.dm_structtag, eng.total_tags, eng.alarms) == (64, 0, 64, 17)
    assert (srv.dm_tag, srv.dm_structtag, srv.total_tags, srv.alarms) == (63, 6, 69, 11)
    assert srv.sfc_struct_tags == 6
    v = {c.name: c for c in srv.connections}
    assert v["DELTAV_WS"].opc_vendor == "Emerson DeltaV" and v["TANK"].kind == "tcpip"


def test_export_diff(an):
    (d,) = an.export_diffs
    assert [p[0] for p in d.conn_pairs] == ["AS01", "AS02"]              # AS01_ES <-> AS01_SRV beklenen
    assert d.conn_only_a == ["DANIEL_1"] and d.conn_only_b == ["DELTAV_WS"]
    assert not d.tags_changed                                            # connection adı farkı değişiklik sayılmaz
    assert d.n_tags_only_a == 2 and d.n_tags_only_b == 1
    assert d.n_alarms_only_a == 7 and d.n_alarms_only_b == 1
    assert d.diag_only_a == {"AS01_1": 7}
    assert d.alarm_text_diff == [(1003, "Tank XX level high", "Tank 3 level high")]


def test_opc_and_redundancy_findings(an):
    ids = {f.check_id: f for f in an.findings}
    assert "Emerson Daniel" in ids["OPC_3RD_PARTY"].detail and "DANIEL_1 sadece ENG" in ids["OPC_3RD_PARTY"].detail
    assert "192.168.0.70" in ids["OS_CONN_REDUNDANCY"].detail and "redundant değildir" in ids["OS_CONN_REDUNDANCY"].detail


# --- SFC / LM / arşiv --------------------------------------------------------------

def test_chartlst_parse_and_groups():
    rows = parse_chartlst("V701.TK01_OP1_FILL_CYCLE.1481000000.TK01_OP1_FILL_CYCLE.0.0.Fill.0\r\nbozuk satır\r\n")
    assert rows == [("TK01_OP1_FILL_CYCLE", 1481000000, "Fill")]
    assert chart_group("TK01_OP1") == "TK01" and chart_group("MN_SEL_X") == "MN_SEL" and chart_group("GO_T") == "GO_T"


def test_sfc_visualization(an):
    s = {o.info.name: o.sfc for o in an.os_projects if o.in_es}
    assert s["OS_SRV1"]["filled"] and s["OS_SRV1"]["charts"] == 6 and len(s["OS_SRV1"]["groups"]) == 4
    assert s["ENG"]["present"] and not s["ENG"]["filled"]                # boş şablon = kullanım kanıtı değil
    f = next(x for x in an.findings if x.check_id == "SFC_VISU")
    assert "6 chart" in f.detail and "2016-12 → 2018-07" in f.detail


def test_logic_matrix_installed_not_used(an):
    assert an.lm_status["AS01"]["status"] == "kurulu, kullanılmıyor"
    f = next(x for x in an.findings if x.check_id == "LIB_LOGIC_MATRIX")
    assert f.severity.value == "Düşük"


def test_archives_and_ldf_ratio(an):
    fs = [x.detail for x in an.findings if x.check_id == "ARCHIVES"]
    assert any("ALG 2 / TLG 3" in x for x in fs) and any("oran 5.0" in x for x in fs)


# --- HW / çıktı ---------------------------------------------------------------------

def test_hw_fw_columns(an):
    m = {x.order: x for x in an.hw_matches}
    assert m["6ES7 414-5HM06-0AB0"].fw_status == "uyumlu" and m["6ES7 414-5HM06-0AB0"].listed_fw == "V6.x"
    assert m["6ES7 960-1AA06-0XA0"].fw_status == "listede yok"
    assert any(x.kind == "GSD / 3rd party" for x in an.hw_matches)


def test_prep_list_and_manual(an):
    p = "\n".join(prep_list(an))
    for s in ("S7 F Systems", "V7.1 SP3 Upd4", "GSD", "FB245", "OB_DIAG", "SFC visualization", "@PCS7TypicalsAPC"):
        assert s in p, s
    m = dict((k, v) for k, v in manual_items(an) if k != "Müşteri sorusu")
    assert m["AS RT PO (PCS 7 License Information)"] == "250" and m["OS PO"] == "eksik"
    md = render_markdown(an)
    assert "AS RT PO 250" in md and "OS PO: eksik" in md and "PDM:** kullanılmıyor" in md


def test_no_star_import():
    """Ek prompt dersi: star import datetime'ı ezdi -> paket kodunda 'import *' yok."""
    import pathlib
    root = pathlib.Path(__file__).parents[1] / "pcs7_analyzer"
    offenders = [str(p) for p in root.rglob("*.py") if "_vendor" not in p.parts and "import *" in p.read_text(encoding="utf-8")]
    assert not offenders
