"""
Minimal .xlsx yazıcı (sadece standart kütüphane): çok sayfa, başlık satırı (kalın, deep-blue zemin),
autofilter, dondurulmuş ilk satır, sütun genişlikleri. Hücreler inline string / sayı.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v, style: int = 0) -> str:
    st = f' s="{style}"' if style else ""
    if isinstance(v, bool):
        v = "Evet" if v else "Hayır"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    t = _BAD_XML.sub("", "" if v is None else str(v))[:32000]
    return f'<c r="{ref}"{st} t="inlineStr"><is><t xml:space="preserve">{escape(t)}</t></is></c>'


class Workbook:
    def __init__(self):
        self.sheets: list[tuple[str, list[str], list[list]]] = []

    def add(self, name: str, headers: list[str], rows: list[list]) -> None:
        name = _SHEET_BAD.sub("_", name)[:31] or f"Sheet{len(self.sheets) + 1}"
        base, i = name, 2
        while any(n == name for n, _, _ in self.sheets):
            name = f"{base[:28]}_{i}"
            i += 1
        self.sheets.append((name, headers, rows))

    def _sheet_xml(self, headers: list[str], rows: list[list]) -> str:
        ncol = max([len(headers)] + [len(r) for r in rows]) if (headers or rows) else 1
        widths = [len(str(h)) for h in headers] + [0] * (ncol - len(headers))
        for r in rows[:2000]:
            for i, v in enumerate(r):
                widths[i] = max(widths[i], min(len(str(v)), 80))
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{max(8, w + 2)}" customWidth="1"/>' for i, w in enumerate(widths))
        out = ['<row r="1">' + "".join(_cell(f"{_col(i)}1", h, 1) for i, h in enumerate(headers)) + "</row>"]
        for ri, r in enumerate(rows, start=2):
            out.append(f'<row r="{ri}">' + "".join(_cell(f"{_col(i)}{ri}", v) for i, v in enumerate(r)) + "</row>")
        last = f"{_col(ncol - 1)}{max(1, len(rows) + 1)}"
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
                'state="frozen"/></sheetView></sheetViews>'
                f"<cols>{cols}</cols><sheetData>{''.join(out)}</sheetData>"
                f'<autoFilter ref="A1:{last}"/></worksheet>')

    def save(self, path: Path) -> Path:
        path = Path(path)
        sheets = self.sheets or [("Boş", [], [])]
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
              '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
              + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-'
                        f'officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets)))
              + "</Types>")
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
              + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (n, _, _) in enumerate(sheets))
              + "</sheets>" + "<definedNames>" + "".join(
                  f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">\'{escape(n)}\'!$A$1:$'
                  f'{_col(max(1, len(h)) - 1)}${max(1, len(r) + 1)}</definedName>' for i, (n, h, r) in enumerate(sheets))
              + "</definedNames></workbook>")
        wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                             f'relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                     'relationships/styles" Target="styles.xml"/></Relationships>')
        styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<fonts count="2"><font><sz val="10"/><name val="Arial"/></font>'
                  '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts>'
                  '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                  '<fill><patternFill patternType="solid"><fgColor rgb="FF000028"/><bgColor indexed="64"/></patternFill></fill></fills>'
                  '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                  '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                  '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                  '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
                  '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", rels)
            z.writestr("xl/workbook.xml", wb)
            z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
            z.writestr("xl/styles.xml", styles)
            for i, (_, h, r) in enumerate(sheets):
                z.writestr(f"xl/worksheets/sheet{i + 1}.xml", self._sheet_xml(h, r))
        return path
