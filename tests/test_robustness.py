"""
Bozuk / beklenmeyen girdide çökme yok (CLAUDE.md "Kurallar"): stress (fuzz) turunda bulunan hataların regresyonları.
Küçük sentetik fixture'lar; müşteri verisi yok.
"""
import zipfile

import pytest

from pcs7_analyzer.cli import main
from pcs7_analyzer.collect import MANIFEST, read_manifest
from pcs7_analyzer.discovery import discover
from pcs7_analyzer.parsers.hwconfig import parse_cfg
from pcs7_analyzer.parsers.wincc_export import decode_text, looks_like_export, parse_export
from pcs7_analyzer.qa import HATA, run_qa
from pcs7_analyzer.source import PackageSource, ZipSource, open_source

# UTF-16 BOM + tek başına high surrogate (D800) -> strict decode UnicodeDecodeError verirdi
BROKEN_UTF16 = b"\xff\xfe" + "DmTag\tx\r\n".encode("utf-16-le") + b"\x00\xd8A\x00" + "[DMTAG][1]".encode("utf-16-le")


def _proj(tmp_path):
    proj = tmp_path / "proj"
    (proj / "P").mkdir(parents=True)
    (proj / "P" / "P.s7p").write_bytes(b"")
    return proj


def test_decode_text_never_raises_on_broken_utf16():
    t = decode_text(BROKEN_UTF16)
    assert "DmTag" in t and "�" in t
    assert looks_like_export(BROKEN_UTF16[:17]) in (True, False)      # kesik baş (tek byte) da hata vermez
    parse_export(BROKEN_UTF16, "x.txt")


def test_export_control_chars_removed():
    raw = ("DmConnection\tx\r\n[DMCONNECTION][1]\r\nName\tParam \r\nC1\tA\x07B\x01\r\n").encode("utf-16")
    exp = parse_export(raw, "x.txt")
    assert exp.sections["DmConnection"].rows[0][1] == "AB"


def test_broken_utf16_txt_does_not_abort_analysis(tmp_path):
    """Önce: discovery'de UnicodeDecodeError (ValueError) -> cli 'usage error', hiçbir rapor yok."""
    proj = _proj(tmp_path)
    (proj / "exports").mkdir()
    (proj / "exports" / "Tags.txt").write_bytes(BROKEN_UTF16 + b"\x00" * 100)
    discover(proj)
    out = tmp_path / "out"
    assert main([str(proj), "-o", str(out)]) == 0
    assert (out / "rapor.html").exists() and (out / "rapor.json").exists()


def test_cfg_control_chars_stripped(tmp_path):
    p = tmp_path / "AS01.cfg"
    p.write_bytes(b'STATION S7400H , "AS\x0701"\r\nRACK 0, SLOT 3, "6ES7 414-5HM06-0AB0" "V6.\x010", "CPU\x1f"\r\n')
    cfg = parse_cfg(p)
    m = cfg["modules"][0]
    assert (m.firmware, m.name) == ("V6.0", "CPU")
    assert "\x07" not in cfg["station"]


def test_qa_corrupt_docx_is_hata_not_crash(tmp_path):
    with zipfile.ZipFile(tmp_path / "rapor.docx", "w") as z:
        z.writestr("word/document.xml", "<w:document xmlns:w='x'><w:body>\x07</w:body></w:document>")
    issues, q = run_qa(tmp_path)
    assert "rapor.docx" in q.unreadable
    assert any(i.level == HATA and i.check == "UNREADABLE" for i in issues)


def _zip_with_corrupt_member(tmp_path):
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("P/P.s7p", b"s7p")
        zf.writestr("P/ombstx/offline/00000001/SUBBLK.DBF", bytes(range(256)) * 40)
    b = bytearray(z.read_bytes())
    i = b.find(b"SUBBLK.DBF") + 10
    for k in range(i + 5, i + 120):
        b[k] ^= 0x55
    z.write_bytes(bytes(b))
    return z


def test_zip_corrupt_member_clean_error_no_partial_file(tmp_path):
    z = _zip_with_corrupt_member(tmp_path)
    with ZipSource(z, temp_dir=tmp_path) as src:
        rel = "P/ombstx/offline/00000001/SUBBLK.DBF"
        for _ in range(2):                       # ikinci çağrı yarım dosyayı "geçerli" sanmamalı
            with pytest.raises(OSError, match="zip üyesi okunamadı"):
                src.materialize(rel)
        with pytest.raises(OSError):
            src.read_head(rel, 4096)
        assert not any(p.is_file() and p.name.startswith("SUBBLK") for p in src._tmp.rglob("*"))


def test_zip_encrypted_member_clean_error(tmp_path):
    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("P/P.s7p", b"s7p")
    b = bytearray(z.read_bytes())
    for sig, off in ((b"PK\x01\x02", 8), (b"PK\x03\x04", 6)):
        b[b.find(sig) + off] |= 1                # "şifreli" bayrağı
    z.write_bytes(bytes(b))
    with ZipSource(z, temp_dir=tmp_path) as src:
        with pytest.raises(OSError, match="şifreli"):
            src.materialize("P/P.s7p")


def test_corrupt_zip_member_analysis_completes(tmp_path):
    out = tmp_path / "out"
    assert main([str(_zip_with_corrupt_member(tmp_path)), "-o", str(out), "--no-inventory"]) == 0
    assert (out / "rapor.html").exists()


def test_read_manifest_tolerates_bad_rows():
    bad = []
    data = b"#pcs7_manifest,1,orig\nrel,size,mtime,included\na.DBF,notint,1,1\nb.DBF,5,1.5,1\nshort\n\xff\xfe"
    orig, rows = read_manifest(data, bad)
    assert orig == "orig" and rows == [("b.DBF", 5, 1.5, True)] and len(bad) == 1


def test_bad_manifest_falls_back_to_plain_zip(tmp_path):
    """Önce: geçersiz manifest -> UnicodeDecodeError -> cli 'usage error', analiz / envanter / paket yok."""
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(MANIFEST, b"garbage\xff\n")
        zf.writestr("P/P.s7p", b"s7p")
    with open_source(z) as src:
        assert not isinstance(src, PackageSource)
        assert any("manifest" in w for w in src.warnings)
        assert [e.rel for e in src.entries if e.rel.endswith(".s7p")] == ["P/P.s7p"]
    out = tmp_path / "out"
    assert main([str(z), "-o", str(out), "--no-inventory"]) == 0
    assert (out / "rapor.html").exists()


def test_symbol_control_chars_stripped(tmp_path):
    from pcs7_analyzer._dbfwriter import write_dbf as wd
    from pcs7_analyzer.parsers.symbols import parse_symbol_asc, parse_symlist_dbf, read_symlist_all
    fields = [("_SKZ", "C", 24), ("_OPIEC", "C", 12), ("_DATATYP", "C", 10), ("_KOMMENTAR", "C", 80)]
    p = tmp_path / "SYMLIST.DBF"
    wd(p, fields, [{"_SKZ": "S\x07X", "_OPIEC": "FB  2600", "_DATATYP": "", "_KOMMENTAR": "c\x01"}], memo=None)
    assert parse_symlist_dbf(p) == [("FB", 2600, "SX", "c")]
    rows, _ = read_symlist_all(p)
    assert rows[0]["symbol"] == "SX" and rows[0]["comment"] == "c"
    asc = tmp_path / "s.asc"
    asc.write_bytes(b"126," + b"MOT\x07OR".ljust(24) + b"FB  1827    FB  1827    comment\r\n")
    assert parse_symbol_asc(asc)[0][:3] == ("FB", 1827, "MOT OR")
