"""
Word (.docx) rapor: kullanıcının Word template'i (.dotx) doldurularak üretilir.

Template repoda DEĞİLDİR (kurum içi dosya); kullanıcı kendi bilgisayarındaki yolu verir.
Kullanılan template yapısı (Siemens one-column wide template ile uyumlu):
  - Kapak: TitleTopline / Title / TitleSubline paragrafları (kapak görseli first-page header'da)
  - header1: "Author | Department | YYYY-MM-DD", footer1: "Restricted | © Siemens 20XX" + sayfa no
  - Stiller isimle bulunur: Topline, heading 1/2, List Paragraph, Table Head, Table Text, caption; tablo stili "Siemens"
Kapaktan sonraki örnek içerik ve arka kapak bölümü atılır; ana bölümün sectPr'ı korunur.
Sadece standart kütüphane (zipfile + string XML); python-docx gerekmez.
"""
from __future__ import annotations

import re
import zipfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from .report import Bullets, Heading, Note, Para, ReportMeta, Table, Topline, badge_class, tr_upper

W_NS_DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
W_NS_TPL = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
TEXT_WIDTH_TWIPS = 9637        # A4 11906 - sol 1418 - sağ 851

_TAG = re.compile(r"<(/?)w:(p|tbl|sectPr)\b[^>]*?(/?)>")


class TemplateError(ValueError):
    pass


def split_body(body: str) -> list[str]:
    """document.xml body'sini üst seviye elemanlara (w:p / w:tbl / w:sectPr) böler; iç içe p'leri (textbox, tablo) korur."""
    out, depth, start = [], 0, None
    for m in _TAG.finditer(body):
        closing, _, selfclose = m.group(1), m.group(2), m.group(3)
        if not closing:
            if depth == 0:
                start = m.start()
            if selfclose:
                if depth == 0:
                    out.append(body[start:m.end()])
                continue
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                out.append(body[start:m.end()])
    return out


def style_ids(styles_xml: str) -> dict[str, str]:
    """{style adı (küçük harf): styleId}; aliases de eklenir."""
    out = {}
    for m in re.finditer(r'<w:style\b[^>]*w:styleId="([^"]+)"[^>]*>(.*?)</w:style>', styles_xml, re.S):
        sid, inner = m.group(1), m.group(2)
        n = re.search(r'<w:name w:val="([^"]+)"', inner)
        if n:
            out.setdefault(n.group(1).lower(), sid)
        a = re.search(r'<w:aliases w:val="([^"]+)"', inner)
        if a:
            for alias in a.group(1).split(","):
                out.setdefault(alias.strip().lower(), sid)
        out.setdefault(sid.lower(), sid)
    return out


def _t(text: str) -> str:
    return f'<w:t xml:space="preserve">{escape(text)}</w:t>'


def _runs(text: str, bold_all: bool = False, bold_style: str | None = None) -> str:
    """'**kalın**' işaretlemesini run'lara çevirir."""
    out = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        bold = bold_all or i % 2 == 1
        rpr = ""
        if bold:
            rpr = f'<w:rPr><w:rStyle w:val="{bold_style}"/></w:rPr>' if bold_style else "<w:rPr><w:b/><w:bCs/></w:rPr>"
        segs = part.split("\n")
        body = "<w:br/>".join(_t(s) for s in segs)
        out.append(f"<w:r>{rpr}{body}</w:r>")
    return "".join(out)


class DocxBuilder:
    def __init__(self, template: Path):
        self.template = Path(template)
        try:
            self.zf = zipfile.ZipFile(self.template)
        except (zipfile.BadZipFile, FileNotFoundError) as e:
            raise TemplateError(f"Word template okunamadı: {template} ({e})") from e
        self.files = {n: self.zf.read(n) for n in self.zf.namelist()}
        self.zf.close()
        if "word/document.xml" not in self.files:
            raise TemplateError("Geçerli bir Word template'i değil (word/document.xml yok)")
        self.styles = style_ids(self.files.get("word/styles.xml", b"").decode("utf-8"))
        doc = self.files["word/document.xml"].decode("utf-8")
        self.doc_head = doc[:doc.index("<w:body>") + len("<w:body>")]
        self.doc_tail = doc[doc.rindex("</w:body>"):]
        self.children = split_body(doc[len(self.doc_head):doc.rindex("</w:body>")])
        self.table_pr = self._sample_table_pr()

    # -- stil yardımcıları -------------------------------------------------
    def sid(self, *names: str) -> str | None:
        for n in names:
            s = self.styles.get(n.lower())
            if s:
                return s
        return None

    def p(self, text: str, style: str | None = None, *, bold: bool = False, align: str | None = None) -> str:
        ppr = ""
        if style or align:
            ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + \
                  (f'<w:jc w:val="{align}"/>' if align else "") + "</w:pPr>"
        return f"<w:p>{ppr}{_runs(text, bold_all=bold)}</w:p>"

    def _sample_table_pr(self) -> str:
        for c in self.children:
            if c.startswith("<w:tbl"):
                m = re.search(r"<w:tblPr>.*?</w:tblPr>", c, re.S)
                if m:
                    pr = m.group()
                    pr = re.sub(r"<w:tblLook [^>]*/>", '<w:tblLook w:val="0420" w:firstRow="1" w:lastRow="0" '
                                'w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/>', pr)
                    return pr
        tbl_style = self.sid("siemens", "table grid")
        return ("<w:tblPr>" + (f'<w:tblStyle w:val="{tbl_style}"/>' if tbl_style else "") +
                '<w:tblW w:w="5000" w:type="pct"/><w:tblLook w:val="0420" w:firstRow="1" w:lastRow="0" '
                'w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr>')

    def table(self, t: Table) -> str:
        n = len(t.headers)
        widths = t.widths if len(t.widths) == n else [100 // n] * n
        tw = [int(TEXT_WIDTH_TWIPS * w / sum(widths)) for w in widths]
        head_style = self.sid("table head")
        text_style = self.sid("table text")
        grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in tw) + "</w:tblGrid>"

        def cell(text: str, w: int, style: str | None, bold: bool) -> str:
            paras = "".join(self.p(line, style, bold=bold) for line in (str(text).split("\n") or [""]))
            return f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>{paras}</w:tc>'

        rows = ['<w:tr><w:trPr><w:tblHeader/><w:cnfStyle w:val="100000000000" w:firstRow="1" w:lastRow="0" '
                'w:firstColumn="0" w:lastColumn="0" w:oddVBand="0" w:evenVBand="0" w:oddHBand="0" w:evenHBand="0" '
                'w:firstRowFirstColumn="0" w:firstRowLastColumn="0" w:lastRowFirstColumn="0" w:lastRowLastColumn="0"/>'
                '</w:trPr>' + "".join(cell(h, w, head_style, False) for h, w in zip(t.headers, tw)) + "</w:tr>"]
        for r in t.rows:
            rows.append("<w:tr><w:trPr><w:cantSplit/></w:trPr>" + "".join(
                cell(c, w, text_style, i in t.badge_cols and badge_class(c) is not None)
                for i, (c, w) in enumerate(zip(r, tw))) + "</w:tr>")
        out = f"<w:tbl>{self.table_pr}{grid}{''.join(rows)}</w:tbl>"
        if t.caption:
            out += self.p(t.caption, self.sid("caption"), align="center")
        else:
            out += self.p("")
        return out

    # -- kapak / header / footer -------------------------------------------
    def _replace_para(self, xml: str, runs: str) -> str:
        ppr = re.search(r"<w:pPr>.*?</w:pPr>", xml, re.S)
        keep_break = "<w:r><w:br w:type=\"page\"/></w:r>" if 'w:type="page"' in xml else ""
        start = re.match(r"<w:p\b[^>]*>", xml).group()
        return f"{start}{ppr.group() if ppr else ''}{runs}{keep_break}</w:p>"

    def cover(self, topline: str, title_lines: list[str], bold_tail: str, subline: str) -> list[str]:
        ids = {k: self.sid(k) for k in ("title topline", "title", "title subline")}
        idx_sub = next((i for i, c in enumerate(self.children) if ids["title subline"] and
                        f'w:val="{ids["title subline"]}"' in c), None)
        if idx_sub is None:
            return [self.p(topline, ids["title topline"]), self.p("\n".join(title_lines), ids["title"]),
                    self.p(subline, ids["title subline"]), '<w:p><w:r><w:br w:type="page"/></w:r></w:p>']
        out = []
        for c in self.children[:idx_sub + 1]:
            if ids["title topline"] and f'w:pStyle w:val="{ids["title topline"]}"' in c:
                c = self._replace_para(c, _runs(topline))
            elif ids["title"] and re.search(rf'w:pStyle w:val="{re.escape(ids["title"])}"', c):
                fett = self.sid("strong")
                title = "<w:r>" + "<w:br/>".join(_t(x) for x in title_lines) + "</w:r>"
                title += _runs(f"**{bold_tail}**", bold_style=fett) if bold_tail else ""
                c = self._replace_para(c, title)
            elif f'w:val="{ids["title subline"]}"' in c:
                c = self._replace_para(c, _runs(subline))
            out.append(c)
        return out

    def main_sectpr(self) -> str:
        for c in self.children:
            if c.startswith("<w:p") and "<w:sectPr" in c:
                return re.search(r"<w:sectPr\b.*?</w:sectPr>", c, re.S).group()
        last = self.children[-1] if self.children and self.children[-1].startswith("<w:sectPr") else ""
        return last

    def _patch_part(self, name: str, repl: list[tuple[str, str]]) -> None:
        if name not in self.files:
            return
        x = self.files[name].decode("utf-8")
        for pat, new in repl:
            x = re.sub(pat, lambda m: new, x)
        self.files[name] = x.encode("utf-8")

    def header_footer(self, meta: ReportMeta) -> None:
        who = " | ".join(x for x in (meta.author or "", meta.department or "", meta.date) if x)
        year = (meta.date or date.today().isoformat())[:4]
        for n in [k for k in self.files if re.match(r"word/header\d+\.xml$", k)]:
            self._patch_part(n, [(r"Author \| Department \| YYYY-MM-DD", escape(who))])
        for n in [k for k in self.files if re.match(r"word/footer\d+\.xml$", k)]:
            self._patch_part(n, [(r"Restricted \| © Siemens 20XX", escape(f"{meta.classification} | © Siemens {year}"))])

    # -- çıktı ---------------------------------------------------------------
    def render(self, blocks: list, meta: ReportMeta, cover: tuple, out_path: Path) -> Path:
        body = self.cover(*cover)
        s_top = self.sid("topline")
        s_h1 = self.sid("heading 1")
        s_h2 = self.sid("heading 2")
        s_list = self.sid("list paragraph", "bullets")
        for i, b in enumerate(blocks):
            if isinstance(b, Topline):
                if i:
                    body.append(self.p(""))
                body.append(self.p(b.text, s_top))
            elif isinstance(b, Heading):
                body.append(self.p(b.text, s_h1 if b.level == 1 else s_h2))
            elif isinstance(b, Para):
                body.append(self.p(b.text))
            elif isinstance(b, Note):
                body.append(self.p(f"Not: {b.text}"))
            elif isinstance(b, Bullets):
                body.extend(self.p(i, s_list) for i in b.items)
            elif isinstance(b, Table):
                body.append(self.table(b))
        body.append(self.main_sectpr())
        self.files["word/document.xml"] = (self.doc_head + "".join(body) + self.doc_tail).encode("utf-8")
        ct = self.files["[Content_Types].xml"].decode("utf-8").replace(W_NS_TPL, W_NS_DOC)
        self.files["[Content_Types].xml"] = ct.encode("utf-8")
        self.header_footer(meta)
        out_path = Path(out_path)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in self.files.items():
                z.writestr(name, data)
        return out_path


def render_docx(an, blocks: list, meta: ReportMeta, template: Path, out_path: Path) -> Path:
    builder = DocxBuilder(template)          # önce template doğrulanır
    fam = an.pcs7_family
    tgt = an.target.replace("SP", " SP")
    customer = meta.customer or tr_upper(an.project_name)
    cover = (f"{customer}  |  SIMATIC PCS 7", ["Upgrade Ön", "Değerlendirmesi", f"{fam} → " if fam else "→ "], tgt,
             "Proje backup'ı üzerinden yapılan upgrade edilebilirlik analizi")
    return builder.render(blocks, meta, cover, out_path)
