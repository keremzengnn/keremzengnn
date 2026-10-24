# Referans rapor stil çıkarıcı (`pcs7_analyzer/docx_style.py`)

Amaç: kullanıcının elle düzenlediği referans Word raporu (müşteri verisi içerir) **geliştiriciye gösterilmeden**
rapor stilinin ayarlanabilmesi. Program referans dosyadan **sadece yapıyı** çıkarır; kullanıcı JSON'u paylaşır.

```
python -m pcs7_analyzer.docx_style <referans.docx|.dotx> [-o reference_style.json]
```
```python
from pcs7_analyzer.docx_style import extract_style, mask_text
extract_style(path) -> dict      # schema_version "1"
```
Sadece standart kütüphane (zipfile + xml.etree). Deterministik (sayaçlar anahtar sırasıyla, JSON `sort_keys`).
CLI: başarı 0, okunamayan / bozuk dosya 2 (`HATA: …` stderr).

## Çıktı (schema_version "1")
| Anahtar | İçerik |
|---|---|
| `paragraph_styles` | `w:pStyle` id -> paragraf sayısı (stilsiz: `(none)`); gövde + tablo + textbox paragrafları |
| `outline` | belge sırasıyla başlıklar: `level`, `style`, `words`, `text_masked` |
| `tables` | belge sırasıyla (iç içe dahil): `index, n_rows, n_cols, header` (ilk satır, maskeli), `style` (`w:tblStyle`), `col_widths` (`w:gridCol w:w`), `avg_words_per_cell, max_words_per_cell, rows_repeat_header` (`w:tblHeader`), `cant_split` (`w:cantSplit`), `nested`, `caption_masked` |
| `highlight` | `run_highlight` (`w:highlight` val), `run_shading`, `paragraph_shading`, `cell_shading` (`w:shd` fill) -> adet |
| `direct_formatting` | `runs_total` ve doğrudan `w:rPr` içinde `rFonts / color / sz / b / i` olan run sayısı |
| `sections` | `explicit_page_breaks` (`w:br type=page`), `last_rendered_page_breaks`, `section_breaks` (`w:sectPr`), `page_break_before`, `app_pages` (docProps/app.xml `<Pages>`, yoksa null) |
| `stats` | `paragraphs` (tablo dışı), `empty_paragraphs`, `total_words`, `avg_words_per_paragraph` (boş olmayanlar), `list_paragraphs` (`w:numPr`), `table_paragraphs`, `table_words` |
| `header_footer` | her `word/header*.xml` / `footer*.xml`: `part`, `kind`, `paragraphs`, `words` (metin yok) |

**Başlık seviyesi:** stil adı/id'si `Title` -> 0, `heading N` (ve `Überschrift N`, `Başlık N`) -> N, stilin (basedOn zinciri dahil)
`outlineLvl k` -> k+1; paragrafın kendi `w:outlineLvl`'i önceliklidir. Boş başlıklar atlanır.
Template'teki `Topline` (ÖZET / PROJE ENVANTERİ / RİSKLER etiketi) başlık stili değildir; `paragraph_styles`'ta görünür.

**Caption:** tablodan hemen sonraki kardeş paragraf, stil id'si/adı `caption`, `Beschriftung`, `Resim Yazısı`… içeriyorsa.

**Kelime:** harf veya rakam içeren boşlukla ayrılmış token (`|`, `→` sayılmaz).

## Maskeleme kuralı (`mask_text`)
Sadece başlık metinleri, tablo ilk satırı ve caption maskelenip çıktıya girer.
1. Metin boşluklardan token'lara bölünür; baştaki/sondaki noktalama korunur.
2. Rakam içeren token -> `#` (`Tablo 1:` -> `Tablo #:`, `V8.1`, `2024`, `SRV1`).
3. Token'ın harf gruplarından biri 3+ ardışık büyük harf içeriyor ve `GENERIC_WORDS`'te değilse -> `X`
   (`ACME_PLANT` -> `X`, `DEMO_MP` -> `X`). Whitelist: ÖZET, PROJE, ENVANTERİ, RİSKLER, REFERANSLAR, TABLO, EK, AS, OS,
   HW, PCS, SIMATIC, WINCC, APL, SFC, CPU, CP + genel teknik terimler (MLFB, GSD, PDM, SQL, OPC, CFC, SCL …).
4. Diğer token'lar (küçük harf, Title-case) olduğu gibi kalır.

## Asla çıktıya girmeyenler
Gövde paragraf metni, tablo hücre metni (ilk satır hariç, maskeli), sayılar (maskeli), `docProps/core.xml` (hiç okunmaz),
`docProps/app.xml`'den `<Pages>` dışındaki her şey (Company, Template…), header/footer metni.

## Sağlamlık
- `.dotx` aynı yapı. Ana part `_rels/.rels` officeDocument hedefinden (yoksa `word/document.xml`).
- Eksik part -> ilgili bölüm boş. Zip değil -> `ValueError("Word dosyası açılamadı …")`. Bozuk XML ->
  `ValueError("… XML'i bozuk …")`. DOCTYPE/ENTITY içeren part okunmaz (`ValueError`).

## Sınırlamalar
- Title-case veya küçük harfli özel isimler (ör. `Kimya Tesisi`) maskelenmez; 2 harfli kısaltmalar da (`MP`).
  Kullanıcı JSON'u paylaşmadan önce `outline` / `header` / `caption_masked` alanlarına göz atmalı.
- Stil id'leri ve renk değerleri olduğu gibi çıkar (yapısal; custom stil adı müşteri adı içeriyorsa görünür).
- Sayfa sayısı XML'den hesaplanamaz: sadece açık sayfa/bölüm kesmeleri ve Word'ün kaydettiği `<Pages>`.
- Stil kalıtımı ile gelen biçim (`styles.xml` rPr) `direct_formatting`'e girmez; numaralı stil (stilde `numPr`)
  `list_paragraphs`'a girmez. Textbox / drawing içindeki paragraflar sayılır, `w:sdt` içerikleri normal paragraf gibi.
