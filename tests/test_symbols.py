from pcs7_analyzer.parsers import parse_symbol_asc


def line(name, typ, nr, comment=""):
    return f"126,{name:<24}{typ:<4}{nr:<5}  {typ:<4}{nr:<5} {comment}"


def test_parse_symbol_asc(tmp_path):
    p = tmp_path / "sym.asc"
    p.write_bytes("\r\n".join([
        line("Intlk16", "FB", 1827, "Interlock 16"),
        line("PIDConL", "FB", 1850, "PID controller"),
        line("E_AS_PUT", "FB", 1994),
        line("CYC_INT5", "OB", 35, "Cyclic 100ms"),
        line("Pompa_Çıkış", "DB", 12, "ü".encode("cp1254").decode("latin1")),
        "126,Motor_Run               I      0.0    BOOL      input",   # I/O sembolü -> alınmaz
        "garbage line",
    ]).encode("latin1", "replace"))
    rows = parse_symbol_asc(p)
    assert rows[0] == ("FB", 1827, "Intlk16", "Interlock 16")
    assert rows[1] == ("FB", 1850, "PIDConL", "PID controller")
    assert rows[2] == ("FB", 1994, "E_AS_PUT", "")
    assert rows[3] == ("OB", 35, "CYC_INT5", "Cyclic 100ms")
    assert rows[4][:2] == ("DB", 12)
    assert len(rows) == 5


def test_symbol_stats_duplicates_and_ranges():
    from pcs7_analyzer.parsers.symbols import symbol_stats
    rows = [{"symbol": "PUMP_RUN", "operand": "I 10.0"}, {"symbol": "PUMP_ON", "operand": "E 10.0"},   # aynı adres (DE)
            {"symbol": "LEVEL", "operand": "PIW 512"}, {"symbol": "LEVEL", "operand": "PIW 514"},     # aynı isim
            {"symbol": "MOT", "operand": "FB 1990"}, {"symbol": "X", "operand": "???"}]
    st = symbol_stats(rows)
    assert st["dup_operand"] == {"I 10.0": ["PUMP_RUN", "PUMP_ON"]}
    assert st["dup_symbol"] == {"LEVEL": 2}
    assert st["areas"]["PIW"] == (2, 512, 514) and st["areas"]["FB"] == (1, 1990, 1990)
    assert st["unparsed"] == 1 and st["total"] == 6
    assert symbol_stats([])["dup_operand"] == {}
