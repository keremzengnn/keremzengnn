"""
Minimal .xlsx yazıcı (sadece standart kütüphane).

- `Workbook.add(ad, başlıklar, satırlar)`: tek tablolu sayfa (başlık, filtre, dondurulmuş ilk satır).
- `Workbook.add_sheet(ad, satırlar, header_rows=…, filter_row=…)`: aynı sayfada birden fazla tablo bloğu.
- Hücre: düz değer veya `Cell(v, style, f)`; `f` = formül (Excel açılışta hesaplar, `v` önbellek değeri).
- Stiller: header, num (#,##0), red, yellow, green, bold, section, wrap. Font Arial; header zemini `header_color`.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")

# stil adı -> cellXfs indeksi (styles.xml ile birlikte güncel tutulmalı)
STYLES = {"": 0, "header": 1, "num": 2, "red": 3, "yellow": 4, "green": 5, "bold": 6, "section": 7, "wrap": 8,
          "red_num": 9, "yellow_num": 10, "bold_num": 11}


@dataclass
class Cell:
    v: object = None
    style: str = ""
    f: str = ""          # formül (baştaki '=' olmadan)


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_letter(n: int) -> str:
    return _col(n)


def _cell(ref: str, v, style: str = "") -> str:
    f = ""
    if isinstance(v, Cell):
        style = v.style or style
        f, v = v.f, v.v
    if not style and isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1000:
        style = "num"
    st = f' s="{STYLES.get(style, 0)}"' if STYLES.get(style, 0) else ""
    if isinstance(v, bool):
        v = "Evet" if v else "Hayır"
    if f:
        val = f"<v>{v}</v>" if isinstance(v, (int, float)) else ""
        return f'<c r="{ref}"{st}><f>{escape(f)}</f>{val}</c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    if v is None or v == "":
        return f'<c r="{ref}"{st}/>' if st else ""
    t = _BAD_XML.sub("", str(v))[:32000]
    return f'<c r="{ref}"{st} t="inlineStr"><is><t xml:space="preserve">{escape(t)}</t></is></c>'


class Workbook:
    def __init__(self, header_color: str = "000028"):
        self.header_color = header_color.lstrip("#").upper()
        # (ad, satırlar, header satır indeksleri, filtre satırı, son filtre satırı, dondurulacak satır)
        self.sheets: list[dict] = []

    def _name(self, name: str) -> str:
        name = _SHEET_BAD.sub("_", name)[:31] or f"Sheet{len(self.sheets) + 1}"
        base, i = name, 2
        while any(s["name"] == name for s in self.sheets):
            name = f"{base[:28]}_{i}"
            i += 1
        return name

    def add(self, name: str, headers: list[str], rows: list[list]) -> None:
        self.add_sheet(name, [list(headers)] + [list(r) for r in rows], header_rows={0}, filter_row=0,
                       filter_last=len(rows), freeze=1)

    def add_sheet(self, name: str, rows: list[list], header_rows: set[int] | None = None, filter_row: int | None = None,
                  filter_last: int | None = None, freeze: int = 0, widths: list[int] | None = None) -> None:
        self.sheets.append({"name": self._name(name), "rows": rows, "headers": header_rows or set(),
                            "filter": filter_row, "filter_last": filter_last, "freeze": freeze, "widths": widths})

    @property
    def names(self) -> list[str]:
        return [s["name"] for s in self.sheets]

    def _sheet_xml(self, s: dict) -> str:
        rows = s["rows"]
        ncol = max([len(r) for r in rows] + [1])
        widths = s["widths"] or [0] * ncol
        if not s["widths"]:
            for r in rows[:3000]:
                for i, v in enumerate(r):
                    txt = str(v.v if isinstance(v, Cell) else v)
                    widths[i] = max(widths[i], min(max((len(x) for x in txt.split("\n")), default=0), 70))
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{max(8, w + 2)}" customWidth="1"/>'
                       for i, w in enumerate(widths))
        out = []
        for ri, r in enumerate(rows):
            style = "header" if ri in s["headers"] else ""
            out.append(f'<row r="{ri + 1}">' + "".join(_cell(f"{_col(i)}{ri + 1}", v, style) for i, v in enumerate(r))
                       + "</row>")
        view = ('<sheetViews><sheetView workbookViewId="0">'
                + (f'<pane ySplit="{s["freeze"]}" topLeftCell="A{s["freeze"] + 1}" activePane="bottomLeft" state="frozen"/>'
                   if s["freeze"] else "") + "</sheetView></sheetViews>")
        af = ""
        if s["filter"] is not None:
            last = s["filter"] + (s["filter_last"] if s["filter_last"] is not None else len(rows) - 1 - s["filter"])
            af = f'<autoFilter ref="A{s["filter"] + 1}:{_col(ncol - 1)}{max(s["filter"] + 1, last + 1)}"/>'
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"{view}<cols>{cols}</cols><sheetData>{''.join(out)}</sheetData>{af}</worksheet>")

    def _styles_xml(self) -> str:
        hc = self.header_color
        fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
        for color in (hc, "FFC7CE", "FFEB9C", "C6EFCE", "F3F3F0"):
            fills.append(f'<fill><patternFill patternType="solid"><fgColor rgb="FF{color}"/><bgColor indexed="64"/></patternFill></fill>')
        # fillId: 2 header, 3 red, 4 yellow, 5 green, 6 sand
        xfs = [(0, 0, 0, ""), (1, 2, 0, ' applyFont="1" applyFill="1"'), (0, 0, 3, ' applyNumberFormat="1"'),
               (0, 3, 0, ' applyFill="1"'), (0, 4, 0, ' applyFill="1"'), (0, 5, 0, ' applyFill="1"'),
               (2, 0, 0, ' applyFont="1"'), (2, 6, 0, ' applyFont="1" applyFill="1"'), (0, 0, 0, ""),
               (0, 3, 3, ' applyFill="1" applyNumberFormat="1"'), (0, 4, 3, ' applyFill="1" applyNumberFormat="1"'),
               (2, 0, 3, ' applyFont="1" applyNumberFormat="1"')]
        cellxfs = "".join(
            f'<xf numFmtId="{num}" fontId="{font}" fillId="{fill}" borderId="0" xfId="0"{extra}'
            + ('><alignment wrapText="1" vertical="top"/></xf>' if i == STYLES["wrap"] else
               '><alignment vertical="top"/></xf>' if i else "/>")
            for i, (font, fill, num, extra) in enumerate(xfs))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<fonts count="3"><font><sz val="10"/><name val="Arial"/></font>'
                '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>'
                '<font><b/><sz val="10"/><name val="Arial"/></font></fonts>'
                f'<fills count="{len(fills)}">{"".join(fills)}</fills>'
                '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(xfs)}">{cellxfs}</cellXfs>'
                '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')

    def save(self, path: Path) -> Path:
        path = Path(path)
        sheets = self.sheets or [{"name": "Boş", "rows": [], "headers": set(), "filter": None, "filter_last": None,
                                  "freeze": 0, "widths": None}]
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
        defined = []
        for i, s in enumerate(sheets):
            if s["filter"] is not None:
                ncol = max([len(r) for r in s["rows"]] + [1])
                last = s["filter"] + (s["filter_last"] if s["filter_last"] is not None else len(s["rows"]) - 1 - s["filter"])
                defined.append(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">\'{escape(s["name"])}\''
                               f'!$A${s["filter"] + 1}:${_col(ncol - 1)}${max(s["filter"] + 1, last + 1)}</definedName>')
        wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
              + "".join(f'<sheet name="{escape(s["name"])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, s in enumerate(sheets))
              + "</sheets>" + (f"<definedNames>{''.join(defined)}</definedNames>" if defined else "")
              + '<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
        wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                             f'relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                     'relationships/styles" Target="styles.xml"/></Relationships>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", rels)
            z.writestr("xl/workbook.xml", wb)
            z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
            z.writestr("xl/styles.xml", self._styles_xml())
            for i, s in enumerate(sheets):
                z.writestr(f"xl/worksheets/sheet{i + 1}.xml", self._sheet_xml(s))
        return path
