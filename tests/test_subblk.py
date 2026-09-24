import pytest

from dbfwriter import SUBBLK_FIELDS, block, fb_instance, sfb_instance, write_dbf
from pcs7_analyzer.parsers import (
    classify_author, decode_block_version, library_summary, parse_subblk,
)
from pcs7_analyzer.parsers.subblk import (
    SUBBLK_DB, SUBBLK_FB, SUBBLK_FC, SUBBLK_OB,
)

FB, FC, DB, OB = SUBBLK_FB, SUBBLK_FC, SUBBLK_DB, SUBBLK_OB
SUB = "00001"  # aynı block'un alt kaydı (sayılmaz)


@pytest.mark.parametrize("v, expected", [(0x30, "3.0"), (0x12, "1.2"), (0x4F, "4.15"), (0, "-"), (None, "-")])
def test_decode_block_version(v, expected):
    assert decode_block_version(v) == expected


@pytest.mark.parametrize("author, lib", [
    ("AdvLib81", "APL"), ("AdvLib82", "APL"), ("AdvLib80", "APL"),
    ("AdvLibLM", "Logic Matrix"),          # en uzun prefix kazanır (AdvLib değil)
    ("DRIVER81", "Basis Library"), ("ELEMENTA", "CFC ELEMENTA"), ("ELEM_400", "CFC ELEMENTA"),
    ("ES_MAP", "CFC generated"), ("ES_SFC", "SFC system"), ("COMM71", "PCS 7 Library V7.1 COMM"),
    ("F_SAFE13", "S7 F Systems Failsafe Blocks"), ("SIMATIC", "SIMATIC system / Standard Library"),
    ("SIEMENS", "Siemens add-on (ör. Modbus TCP)"),
    ("BM", "custom"), ("MANAR", "custom"), ("UK", "custom"),
    ("", "custom/unknown"), ("   ", "custom/unknown"),
])
def test_classify_author(author, lib):
    assert classify_author(author) == lib


def _sample_records():
    return [
        block(FB, 1827, "AdvLib81", "Intlk16", 0x10, "AdvLib81"),
        block(FB, 1827, "", "", None, "", ssb=None) | {"SUBBLKTYP": SUB},  # alt kayıt
        block(FB, 1990, "DRIVE", "SINAMICS", 0x11, "BM", lang="00001"),
        block(FB, 1850, "AdvLib82", "PIDConL", 0x80, "AdvLib82"),
        block(FB, 300, "SFC", "SFC_FB", 0x71, "ES_SFC"),
        block(FC, 1, "", "", 0x10, "ES_MAP"),                   # isimsiz CFC FC -> blocks'ta yok
        block(FC, 256, "CONVERT", "SEL_R", 0x10, "DRIVER81"),
        block(OB, 1, "", "CYC_INT", None, ""),
        block(OB, 35, "", "", None, ""),
        block(DB, 100, "AdvLib81", "", ssb=fb_instance(1827)),
        block(DB, 101, "AdvLib81", "", ssb=fb_instance(1827)),
        block(DB, 102, "DRIVE", "", ssb=fb_instance(1990)),     # 0xC6 byte'ı -> latin1 gerekir
        block(DB, 103, "SFC", "", ssb=fb_instance(300)),
        block(DB, 104, "", "", ssb=sfb_instance(14)),
        block(DB, 105, "", "", ssb=b"\x01\x02\x03"),            # global DB
        block(DB, 106, "", "", ssb=bytes([0x0A, 0xFF, 0xFF])),  # saçma numara (>= 8192)
        block(DB, 107, "", ""),                                 # memo yok
    ]


@pytest.fixture(params=["db3", "db4"])
def sample_folder(tmp_path, request):
    folder = tmp_path / "ombstx" / "offline" / "0000000a"
    folder.mkdir(parents=True)
    write_dbf(folder / "SUBBLK.DBF", SUBBLK_FIELDS, _sample_records(), memo=request.param)
    return folder


def test_counts(sample_folder):
    bf = parse_subblk(sample_folder / "SUBBLK.DBF")
    assert bf.n_records == 17
    assert bf.counts == {"FB": 4, "FC": 2, "OB": 2, "DB": 8}
    assert not bf.is_empty
    assert bf.memo_available


def test_block_headers(sample_folder):
    bf = parse_subblk(sample_folder / "SUBBLK.DBF")
    got = {(b.kind, b.number): b for b in bf.blocks}
    assert set(got) == {("FB", 300), ("FB", 1827), ("FB", 1850), ("FB", 1990), ("FC", 256)}
    fb = got[("FB", 1827)]  # isimli kayıt, alt kaydı ezmemeli
    assert (fb.name, fb.family, fb.version, fb.author, fb.library) == ("Intlk16", "AdvLib81", "1.0", "AdvLib81", "APL")
    assert got[("FB", 1990)].lang == "00001"
    assert got[("FB", 1990)].library == "custom"
    assert [b.number for b in bf.blocks] == sorted(b.number for b in bf.blocks if b.kind == "FB") + [256]


def test_instances(sample_folder):
    bf = parse_subblk(sample_folder / "SUBBLK.DBF")
    assert bf.instances_per_fb == {("FB", 1827): 2, ("FB", 1990): 1, ("FB", 300): 1, ("SFB", 14): 1}
    assert bf.unresolved_instances == 1
    assert bf.db_families["AdvLib81"] == 2


def test_instances_high_byte_fb_number_with_ascii_language_driver(tmp_path):
    """Regression: language driver 0x00 -> dbfread 'ascii' seçer; >= 0x80 byte'lar kaybolmamalı."""
    f = tmp_path / "SUBBLK.DBF"
    fbs = [128, 200, 1990, 2500, 0x7FF]
    write_dbf(f, SUBBLK_FIELDS, [block(DB, i, ssb=fb_instance(n)) for i, n in enumerate(fbs, 1)],
              memo="db4", language_driver=0x00)
    bf = parse_subblk(f)
    assert bf.instances_per_fb == {("FB", n): 1 for n in fbs}
    assert bf.unresolved_instances == 0


def test_without_dbt(tmp_path):
    f = tmp_path / "SUBBLK.DBF"
    write_dbf(f, SUBBLK_FIELDS, _sample_records(), memo=None)
    bf = parse_subblk(f)
    assert not bf.memo_available
    assert not bf.instances_per_fb
    assert bf.counts["DB"] == 8
    assert bf.db_families["AdvLib81"] == 2   # DBT'siz family bazında sayım hâlâ mümkün


def test_with_instances_false_ignores_dbt(sample_folder):
    bf = parse_subblk(sample_folder / "SUBBLK.DBF", with_instances=False)
    assert not bf.memo_available and not bf.instances_per_fb


def test_empty_block_folder(tmp_path):
    f = tmp_path / "SUBBLK.DBF"
    write_dbf(f, SUBBLK_FIELDS, [], memo="db4")
    bf = parse_subblk(f)
    assert bf.is_empty and bf.counts == {} and bf.blocks == []


def test_library_summary_shows_mixed_versions(sample_folder):
    s = library_summary(parse_subblk(sample_folder / "SUBBLK.DBF"))
    assert s["APL"] == {"AdvLib81": 1, "AdvLib82": 1}
    assert s["Basis Library"] == {"DRIVER81": 1}
    assert "CFC generated" not in s
