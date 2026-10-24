# Doküman bilgi tabanı (`pcs7_analyzer/kb.py`)

Amaç: kullanıcının kendi PC'sindeki Siemens manual arşivinden (ör. `C:\Users\...\Siemens_Dokumanlar`) her analyzer
bulgusuna 1–3 kısa sayfa referansı ("Kaynak": dosya adı, ürün versiyonu, sayfa/başlık) vermek.
**Risk kararı vermez**, sadece referans gösterir. Offline, stdlib (sqlite3 + FTS5); ML/embedding/ağ yok.

```
python -m pcs7_analyzer.kb build --root <arşiv> [--db kb/kb.sqlite] [--pdftotext <exe>]
python -m pcs7_analyzer.kb search "<metin>" [--db kb/kb.sqlite] [--target V10.0SP2] [--limit 3] [--json]
```
Varsayılan db: çalışma klasörüne göre `kb/kb.sqlite`. db arşiv klasörünün içindeyse build reddedilir
(**kaynağa asla yazılmaz**). Build her seferinde baştan yapılır (`<db>.tmp` -> sonunda yerine konur).

## Girdiler ve klasör kuralları
- Kökte sadece `INCLUDE_TOP_PATTERNS` taranır (büyük/küçük harf duyarsız): `PCS7_*`, `OT_Network`, `OT_Cybersecurity`,
  `Safety`, `SCALANCE`, `Sanallastirma`.
- Path'in herhangi bir parçası `EXCLUDE_PATTERNS`'a uyarsa atlanır: `Projeler`, `CN4100`, `Kendi_Kilavuzlarim`,
  `Kurs_*`, `_tekrarlar`, `_tablolar`, `_diger`, `_md_donusumler`.
- `.pdf`: doküman başına **tek** `pdftotext -layout -enc UTF-8 <pdf> -` çağrısı, sayfalar form feed (`\f`) ile
  ayrılır (`page_kind='page'`, sayfa no = PDF sayfa sırası, 1'den). pdftotext arama sırası: `--pdftotext` ->
  `shutil.which("pdftotext")` -> Windows'ta `C:\Program Files\poppler*\Library\bin`, `C:\Program Files\poppler*\bin`,
  `C:\poppler*\Library\bin`, `C:\poppler*\bin`. Yoksa PDF'ler atlanır, `unknown`: "pdftotext yok: PDF indekslenmedi".
- `.md` / `.txt`: metinde `\f` varsa sayfalara bölünür (`page`); yoksa Markdown başlıklarına (`#`…`######`) göre
  chunk'lanır (`page_kind='chunk'`, "sayfa" = chunk sırası, 1'den; başlıktan önceki metin de bir chunk).
  Okuma: UTF-8 (BOM'lu da) -> cp1254 -> latin1.
- Boş metinli PDF sayfası indekslenmez; doküman başına bir `unknown` kaydı: "metin yok, OCR yapılmadı (s. 2, 5 …)".
- Tek dosyanın okuma hatası build'i durdurmaz (`errors` + `unknown`).

## Şema (tek SQLite dosyası, `SCHEMA_VERSION = "1"`)
| Tablo | Alanlar |
|---|---|
| `docs` | `id, path` (köke göre relatif), `file_name, doc_title, product_version, doc_no, pages, title_mismatch, sha1` (dosya) |
| `pages` (FTS5, `unicode61 remove_diacritics 2`) | `text, heading`, UNINDEXED: `doc_id, page, page_kind, content_hash` |
| `page_refs` | `content_hash, doc_id, page` — aynı içerikli sayfanın **tüm** referansları |
| `meta` | `schema_version, built_at, root, pdftotext, stats` (JSON) |

Tekrar: `content_hash` = sha1(küçük harf + boşlukları sadeleştirilmiş sayfa metni). Metin `pages`'e bir kez girer,
her kopya `page_refs`'e yazılır. Aramada tekrar sayfa için hedef sürümle uyuşan kopya tercih edilir.

## Metadata heuristic'leri
- `doc_title` (dosya adından ayrı): Markdown'da ilk `#` başlığı; değilse ilk 25 satırda `SIMATIC` geçen satırdan
  itibaren ilk anlamlı satır (yoksa ilk anlamlı satır); < 3 kelimeyse sonraki anlamlı satır eklenir. Anlamlı satır:
  ≥ 4 harf, ≤ 150 karakter, sadece stopword (SIMATIC, Siemens, PCS, manual…)/sayı/doküman no değil.
- `title_mismatch=1`: dosya adı ve başlık ≥ 4 harfli, stopword olmayan ortak kelime paylaşmıyor (sondaki `s` atılır).
  Taraflardan birinde anlamlı kelime yoksa 0 (karar verilemez).
- `product_version`: önce dosya adı, sonra ilk sayfa: `V\d+(.\d+)*( SP\d+)?( Upd\d+)?`, `_` ayraçları kabul edilir,
  `V10.0 SP2 Upd1` biçimine normalize. Bulunmazsa NULL. **Tuzak:** dosya adında versiyon yoksa ilk sayfadaki başka bir
  versiyon (ör. library versiyonu) yakalanabilir.
- `doc_no`: `A5E\d{8}(-[A-Z]{2})?` (dosya adı, sonra ilk sayfa).
- `heading` (sayfa başına): ilk numaralı başlık satırı `^\d{1,2}(\.\d{1,3})*\s+<harf>` (Markdown `#` öneki atılır), yoksa ''.

## Arama
- `search(db, query, target_version=None, limit=3) -> list[KbRef]`: token'lar (`9.5.17`, `6ES7-410` tek parça) çift
  tırnaklı phrase olarak `OR` ile birleşir; FTS özel karakterleri atılır; stopword'ler (TR/EN) çıkarılır. Sıralama
  FTS5 `bm25` (`score = -bm25`, büyük = iyi). db yok / boş sorgu / sqlite hatası -> `[]`.
- `KbRef(file_name, doc_title, product_version, page, heading, snippet, score, version_note, page_kind, path,
  matched_tokens, matched_keys)`. `snippet` ≤ 160 karakter (kısa referans, uzun alıntı yok).
- `version_note = 'farklı sürüm'`: hedef verilmiş, doküman versiyonu biliniyor ve major.minor farklı.
- `ref_text(ref)`: `Software_Update.pdf (V10.0 SP2), s. 91 — 9.5.17 Compiling the CFC Charts` (chunk için `bölüm N`,
  farklı sürümde sonuna `[farklı sürüm]`).
- `refs_for_findings(db, findings, target_version=None) -> {check_id: [KbRef]}`: sorgu = detay/başlıktaki teknik
  terimler (APL, SFC, TCiR, `OB_DIAG`, Logic Matrix, MLFB `6ES7 …` …) + başlık kelimeleri + check_id parçaları.
  Zayıf eşleşme -> `[]` (çağıran "kaynak bulunamadı" yazar): anahtar terim varken sayfada hiçbiri yoksa; anahtar terim
  yokken < 2 token eşleşiyorsa; isteğe bağlı `min_score`. Aynı check_id'li bulgulardan ilki kullanılır.

## Limitler
- OCR yok: taranmış PDF'ler "metin yok" olarak listelenir.
- Başlık / versiyon / heading tespiti heuristic; `title_mismatch` sadece uyarı amaçlı.
- Markdown chunk numarası PDF sayfa numarası değildir (`page_kind='chunk'`).
- Semantik arama yok (sadece kelime/bm25); Türkçe bulgu metni İngilizce manual'le ancak teknik terimlerle eşleşir.
- Artımlı build yok; her build tüm arşivi yeniden okur.
