from pcs7_analyzer.parsers import hw_inventory, parse_cfg, scan_s7h

USED = "5.5.4.9_10.1.0.1"
USED_HEX = " ".join(f"{b:02X}" for b in USED.encode("latin1") + b"\x00")

CFG = "\r\n".join([
    "FILEVERSION \"3.2\"",
    "#STEP7_VERSION V5.5 SP4",
    f'STATION S7400H , "AS_TEST"',
    'SUBNET PROFIBUS , "PROFIBUS(1)"',
    'SUBNET INDUSTRIAL_ETHERNET , "Plant bus"',
    'RACK 0, "6ES7 400-2JA00-0AA0", "UR2-H"',
    'RACK 0, SLOT 3, "6ES7 414-5HM06-0AB0" "V6.0", "CPU 414-5H"',
    'RACK 0, SLOT 3, SUBSLOT 1, "_S7H_IF1", "IF1"',
    'RACK 0, SLOT 3, SUBSLOT 2, "_S7H_IF2", "IF2"',
    'RACK 0, SLOT 5, "6GK7 443-1EX30-0XE0" "V3.0", "CP 443-1"',
    'CPU_ATTRIBUTES',
    '  CAPABLE_F_SAFETY "1"',
    f'  USED_S7_VERSIONS "{USED_HEX}"',
    'DPSUBSYSTEM 1, DPADDRESS 5, "6ES7 152-1AA00-0AB0" "V1.0", "ET 200iSP"',
    'DPSUBSYSTEM 1, DPADDRESS 5, SLOT 4, "6ES7 131-7RF00-0AB0", "8DI NAMUR"',
    'DPSUBSYSTEM 1, DPADDRESS 5, SLOT 5, "6ES7 131-7RF00-0AB0", "8DI NAMUR"',
    'DPSUBSYSTEM 1, DPADDRESS 20, "CPX_059E.GSE", "Festo CPX"',
    'DPSUBSYSTEM 1, DPADDRESS 21, "PAYLINK:6ES7 153-2BA70", "Y-Link"',
    '  PDM_PARAM "0"',
    "",
])


def _write(tmp_path, text=CFG):
    p = tmp_path / "AS.cfg"
    p.write_bytes(text.encode("latin1"))
    return p


def test_parse_cfg_header(tmp_path):
    cfg = parse_cfg(_write(tmp_path))
    assert cfg["station"].startswith("STATION S7400H")
    assert len(cfg["subnets"]) == 2
    assert cfg["used_s7_versions"] == USED
    assert cfg["export_step7_version"] == "V5.5 SP4"
    assert cfg["f_capable"] is True
    assert cfg["pdm_used"] is False


def test_parse_cfg_modules(tmp_path):
    mods = parse_cfg(_write(tmp_path))["modules"]
    by_loc = {m.location: m for m in mods}
    cpu = by_loc["RACK 0, SLOT 3"]
    assert (cpu.order_no, cpu.firmware, cpu.name) == ("6ES7 414-5HM06-0AB0", "V6.0", "CPU 414-5H")
    assert by_loc["RACK 0, SLOT 3, SUBSLOT 1"].is_internal
    slave = by_loc["DPSUBSYSTEM 1, DPADDRESS 5"]
    assert slave.is_station_header and not slave.is_gsd
    assert not by_loc["DPSUBSYSTEM 1, DPADDRESS 5, SLOT 4"].is_station_header
    assert by_loc["DPSUBSYSTEM 1, DPADDRESS 20"].is_gsd
    assert by_loc["DPSUBSYSTEM 1, DPADDRESS 21"].is_gsd   # PAYLINK: ':' içerir


def test_hw_inventory_skips_internal(tmp_path):
    inv = hw_inventory(parse_cfg(_write(tmp_path)))
    assert inv[("6ES7 131-7RF00-0AB0", "", "mod")] == 2
    assert inv[("6ES7 152-1AA00-0AB0", "V1.0", "slave")] == 1
    assert inv[("6ES7 414-5HM06-0AB0", "V6.0", "mod")] == 1
    assert not any(k[0].startswith("_") for k in inv)


def test_parse_cfg_pdm_and_non_f(tmp_path):
    text = CFG.replace('CAPABLE_F_SAFETY "1"', 'CAPABLE_F_SAFETY "0"').replace('PDM_PARAM "0"', 'PDM_PARAM "1"')
    cfg = parse_cfg(_write(tmp_path, text))
    assert cfg["f_capable"] is False and cfg["pdm_used"] is True


def test_parse_cfg_bad_used_versions_does_not_crash(tmp_path):
    cfg = parse_cfg(_write(tmp_path, CFG.replace(USED_HEX, "ZZ ZZ")))
    assert cfg["used_s7_versions"] == ""


def test_parse_cfg_latin1_names(tmp_path):
    cfg = parse_cfg(_write(tmp_path, CFG.replace("ET 200iSP", "Pompa Çıkış".encode("cp1254").decode("latin1"))))
    assert any("Pompa" in m.name for m in cfg["modules"])


def test_scan_s7h(tmp_path):
    p = tmp_path / "x.s7h"
    p.write_bytes(
        b"\x00\x01junk\x00" + b"6ES7 414-5HM06-0AB0\x00\x02V6.0\x00"
        + b"6GK7 443-1EX30-0XE0\x00V3.0\x00"
        + b"6ES7 131-7RF00-0AB0\x00notfw\x00"
        + b"6ES7 414-5HM06-0AB0\x00V6.0\x00"
        + b"6ES7960-1AA06-0XA0\x00"          # MLFB boşluksuz, dosya sonu
    )
    c = scan_s7h(p)
    assert c[("6ES7 414-5HM06-0AB0", "V6.0")] == 2
    assert c[("6GK7 443-1EX30-0XE0", "V3.0")] == 1
    assert c[("6ES7 131-7RF00-0AB0", "")] == 1
    assert c[("6ES7960-1AA06-0XA0", "")] == 1
