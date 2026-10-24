"""SUBBLK.DBT ham memo okuma: dBASE III / IV, SSBPART içinde 0x1A / 0x1F, block boyutu, çözülemeyen instance nedenleri."""
import struct

import pytest

from dbfwriter import SUBBLK_FIELDS, block, fb_instance, sfb_instance, write_dbf
from pcs7_analyzer.parsers.subblk import (
    INSTANCE_ISSUE_EMPTY, INSTANCE_ISSUE_KIND, INSTANCE_ISSUE_RANGE, INSTANCE_ISSUE_SHORT, SUBBLK_DB, RawMemoFile,
    parse_subblk, record_instance_issues,
)
from pcs7_analyzer.unknown import UnknownRecorder

DB = SUBBLK_DB
# 0x1A / 0x1F byte'ı içeren FB numaraları: FB26 = 0A 1A 00, FB31 = 0A 1F 00, FB6682 = 0A 1A 1A (DB3'te kesilir),
# FB 0x1F1A, 0x1A1F; 0x1A ve 0x1F interface verisinin içinde de var.
TRICKY = [26, 31, 0x1F1A & 0x1FFF, 0x1A1F, 0x011A, 0x1A01, 0x1F00, 1990]


def _ssb(fb: int, prefix=0x0A) -> bytes:
    # Not: DB3'te ardışık 1A 1A memo sonudur (biçim gereği); payload'da tek 0x1A / 0x1F serbest.
    return bytes([prefix, fb & 0xFF, fb >> 8]) + b"\x00\x1a\x00\x1f\x1a\x00\x1f" + b"IDB" * 3


def _write(tmp_path, recs, memo, **kw):
    f = tmp_path / "SUBBLK.DBF"
    write_dbf(f, SUBBLK_FIELDS, recs, memo=memo, **kw)
    return f


@pytest.mark.parametrize("memo, bs", [("db4", 512), ("db4", 64), ("db4", 1024), ("db3", 512)])
def test_tricky_bytes_resolved(tmp_path, memo, bs):
    recs = [block(DB, i, ssb=_ssb(n)) for i, n in enumerate(TRICKY, 1)]
    recs.append(block(DB, 99, ssb=_ssb(26, prefix=0x0B)))
    bf = parse_subblk(_write(tmp_path, recs, memo, memo_block_size=bs))
    assert bf.instances_per_fb == {**{("FB", n): 1 for n in TRICKY}, ("SFB", 26): 1}
    assert bf.unresolved_instances == 0 and not bf.unresolved_reasons
    assert bf.memo_format == memo and bf.memo_block_size == bs
    assert bf.memo_seen == {memo: len(recs)} and not bf.memo_issues


def test_db3_double_terminator_inside_payload_truncates_but_db4_does_not(tmp_path):
    """FB6682 = 0A 1A 1A: DB3 biçimi gereği memo burada biter (3 byte'tan kısa -> SHORT nedeni); DB4 uzunlukla okunur."""
    recs = [block(DB, 1, ssb=_ssb(0x1A1A))]
    assert parse_subblk(_write(tmp_path, recs, "db4")).instances_per_fb == {("FB", 0x1A1A): 1}
    (tmp_path / "b").mkdir()
    bf = parse_subblk(_write(tmp_path / "b", recs, "db3"))
    assert bf.unresolved_reasons == {INSTANCE_ISSUE_SHORT: 1} and bf.unresolved_instances == 1


def test_raw_memo_reader_exact_bytes(tmp_path):
    payloads = [b"\x0a\x1a\x00" + bytes(range(256)) * 3, b"\x1f" * 700, b"\x0b\x1f\x00\x1a\x00"]
    for memo in ("db3", "db4"):
        d = tmp_path / memo
        d.mkdir()
        f = _write(d, [block(DB, i, ssb=p) for i, p in enumerate(payloads, 1)], memo)
        idx = [1, 3, 5]   # 1. ve 2. memo 512 byte'tan uzun -> 2 block
        with RawMemoFile(f.with_suffix(".DBT")) as rm:
            got = [rm[i] for i in idx]
            assert rm[0] is None
        assert got == payloads      # DB3: 1A 1A'ya kadar (payload'larda çift 1A yok), DB4: uzunlukla -> birebir


def test_ssblen_truncates_memo(tmp_path):
    fields = SUBBLK_FIELDS + [("SSBLEN", "N", 11)]
    f = tmp_path / "SUBBLK.DBF"
    write_dbf(f, fields, [dict(block(DB, 1, ssb=_ssb(31)), SSBLEN=2)], memo="db4")
    bf = parse_subblk(f)
    assert bf.unresolved_reasons == {INSTANCE_ISSUE_SHORT: 1}


def test_unresolved_reasons_and_unknown_recording(tmp_path):
    recs = [
        block(DB, 1, ssb=fb_instance(100)),
        block(DB, 2, ssb=bytes([0x0A, 0xFF, 0xFF])),          # >= 8192
        block(DB, 3, ssb=b"\x0a\x05"),                       # kısa
        block(DB, 4, ssb=b"\x05\x00\x00IDB"),                # global DB (0x05): sorun değil
        block(DB, 5, ssb=b"\x01\x02\x03"),                   # bilinmeyen byte0
        block(DB, 6, ssb=sfb_instance(14)),
        block(DB, 7),                                        # memo referansı yok: sorun değil
        block(DB, 8, ssb=fb_instance(200)),                  # aşağıda boş memo'ya çevrilir
    ]
    f = _write(tmp_path, recs, "db4")
    dbt = f.with_suffix(".DBT")
    raw = bytearray(dbt.read_bytes())
    pos = raw.rfind(b"\xff\xff\x08\x00")                     # son memo = DB8
    raw[pos + 4:pos + 8] = struct.pack("<I", 8)              # uzunluk = sadece header -> boş memo
    dbt.write_bytes(bytes(raw))
    bf = parse_subblk(f)
    assert bf.instances_per_fb == {("FB", 100): 1, ("SFB", 14): 1}
    assert bf.unresolved_reasons == {INSTANCE_ISSUE_RANGE: 1, INSTANCE_ISSUE_SHORT: 1, INSTANCE_ISSUE_KIND: 1,
                                     INSTANCE_ISSUE_EMPTY: 1}
    assert bf.unresolved_instances == 3                      # KIND sayılmaz (instance olduğu belli değil)
    assert bf.ssb_kind[0x05] == 1 and bf.ssb_kind[0x0A] == 3
    assert {e[0] for e in bf.unresolved_examples} == {2, 3, 5, 8}
    rec = UnknownRecorder()
    assert record_instance_issues(bf, rec, "p/SUBBLK.DBT") == 4
    lines = rec.to_log()
    assert "DB2: 0a ff ff" in lines and "boş memo" in lines and all(e.where == "SSBPART" for e in rec.entries)


def test_memo_index_beyond_eof_is_issue_not_crash(tmp_path):
    f = _write(tmp_path, [block(DB, 1, ssb=fb_instance(5))], "db4")
    dbt = f.with_suffix(".DBT")
    dbt.write_bytes(dbt.read_bytes()[:512])                  # memo block'ları kesik
    bf = parse_subblk(f)
    assert bf.unresolved_reasons == {INSTANCE_ISSUE_EMPTY: 1}
    assert bf.memo_issues
