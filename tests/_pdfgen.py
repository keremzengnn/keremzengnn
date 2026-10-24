"""Testler için minimal PDF üretici (stdlib zlib; gerçek manual yok)."""
from __future__ import annotations

import zlib


def _esc(s: str) -> bytes:
    return s.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(pages: list[list[str]], compress: bool = True, encrypt: bool = False, use_tj: bool = False,
             cid_font: bool = False) -> bytes:
    """Her sayfa = satır listesi (boş liste = taranmış/metinsiz sayfa). Helvetica (WinAnsi) veya
    `cid_font=True`: Type0 Identity-H + ToUnicode CMap (2 byte kod = Unicode)."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    def stream(data: bytes, extra: bytes = b"") -> bytes:
        if compress:
            data = zlib.compress(data)
            extra += b" /Filter /FlateDecode"
        return b"<< /Length %d%s >>\nstream\n" % (len(data), extra) + data + b"\nendstream"

    catalog = add(b"")            # yer tutucu
    pages_id = add(b"")
    if cid_font:
        cmap = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
                b"1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
                b"1 beginbfrange <0000> <FFFF> <0000> endbfrange\nendcmap end end")
        tu = add(stream(cmap))
        font = add(b"<< /Type /Font /Subtype /Type0 /BaseFont /Arial /Encoding /Identity-H"
                   b" /ToUnicode %d 0 R >>" % tu)
    else:
        font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kids = []
    for lines in pages:
        ops = [b"BT /F1 11 Tf 72 760 Td 14 TL"]
        for i, line in enumerate(lines):
            if cid_font:
                s = b"<" + line.encode("utf-16-be").hex().encode() + b">"
            else:
                s = b"(" + _esc(line) + b")"
            if use_tj and not cid_font:
                words = line.split(" ")
                arr = b" -300 ".join(b"(" + _esc(w) + b")" for w in words)
                ops.append(b"[" + arr + b"] TJ T*")
            else:
                ops.append(s + b" Tj T*")
        ops.append(b"ET")
        if not lines:
            ops = [b"q 100 0 0 100 0 0 cm 0.5 g 0 0 1 1 re f Q"]
        content = add(stream(b"\n".join(ops)))
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Contents %d 0 R"
                        b" /Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_id, content, font)))
    objs[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objs[pages_id - 1] = (b"<< /Type /Pages /Count %d /Kids [" % len(kids)
                          + b" ".join(b"%d 0 R" % k for k in kids) + b"] >>")
    enc = None
    if encrypt:
        enc = add(b"<< /Filter /Standard /V 1 /R 2 /O <00> /U <00> /P -4 >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R" % (len(objs) + 1, catalog)
    if enc:
        out += b" /Encrypt %d 0 R /ID [<00> <00>]" % enc
    out += b" >>\nstartxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)
