# Doküman bilgi tabanı (`pcs7_analyzer/kb.py`)

Amaç: kullanıcının kendi PC'sindeki Siemens manual arşivinden (ör. `C:\Users\...\Siemens_Dokumanlar`) her analyzer
bulgusuna 1–3 kısa sayfa referansı ("Kaynak": dosya adı, ürün versiyonu, sayfa/başlık) vermek.
**Risk kararı vermez**, sadece referans gösterir. Offline, stdlib (sqlite3 + FTS5); ML/embedding/ağ yok.

```
python -m pcs7_analyzer kb build --root <klasör|arşiv.zip> [--db <kb.sqlite>] [--all] [--rebuild] [--pdftotext <exe>] [--progress-every 25]
python -m pcs7_analyzer kb search "<metin>" [--db <kb.sqlite>] [--target V10.0SP2] [--limit 3] [--json]
python -m pcs7_analyzer kb digest [--db <kb.sqlite>] [-o kb_ozet.md] [--part-mb 4] [--tum]
```
(`python -m pcs7_analyzer.kb …` de aynı.)

**Varsayılan db:** `settings.settings_path().parent / "kb.sqlite"` (Windows: `%APPDATA%\pcs7_analyzer\kb.sqlite`).
`settings.find_kb` sırası: açık yol > ayar `kb_db` > `./kb/kb.sqlite` (çalışma klasörü) > ayar klasörü. Yani `--db`
verilmeden build edilen KB analizde otomatik kullanılır; **ancak** ayarda `kb_db` varsa veya çalışma klasöründe
`kb\kb.sqlite` duruyorsa o önce gelir — build sonunda bu durumda uyarı loglanır. `search` / `digest` `--db`
verilmezse `find_kb()` sonucunu, o da yoksa varsayılanı kullanır.

**Kaynağa asla yazılmaz:** db klasör kaynağın içindeyse veya kaynak zip'in kendisiyse build reddedilir. Zip'ten PDF /
iç zip'ler tek tek `tempfile.mkdtemp(prefix="pcs7kb_")` altına akışla (1 MB parçalar) çıkarılır, işlenince silinir;
temp klasör build sonunda (hata / Ctrl+C dahil) kaldırılır. Klasör kaynağında dosyalar yerinde okunur (kopya yok).

## Kaynak: klasör veya .zip
- `.zip` `zipfile` ile akışla okunur (2.7 GB arşiv belleğe alınmaz; zip64 desteklenir). `.md`/`.txt` doğrudan
  üyeden okunur (> 64 MB atlanır), `.pdf` temp'e çıkarılır. Dosya adı UTF-8 bayrağı yoksa cp437 -> utf-8 / cp857
  (Windows TR zip'leri) denenir. `__MACOSX/`, dizin kayıtları, `..` içeren adlar atlanır. Şifreli zip üyesi atlanır.
- **İç zip (1 seviye):** kaynaktaki (klasör veya zip) her `.zip` temp'e çıkarılır ve üyeleri aynı kurallarla işlenir;
  path `dış/yol/paket.zip/iç/yol.pdf`, üst klasör dış path'ten. 2. seviye zip `unknown`: "iç içe zip (2. seviye) atlandı".
- Path'ler her zaman `/` ayraçlı, kaynağa göre relatif.
- **Sarmalayıcı klasör:** tüm dosyalar tek bir klasörün altındaysa (ör. zip içinde `Siemens_Dokumanlar/…`) ve o klasör
  `INCLUDE_TOP_PATTERNS`'a uymuyorsa, dahil/hariç kararı için bir seviye inilir (tekrarlanır). `docs.path` tam kalır.

## Dahil / hariç (mod)
- **include modu:** (sarmalayıcıdan sonraki) kökte `INCLUDE_TOP_PATTERNS`'a uyan en az bir klasör varsa sadece onlar
  taranır (büyük/küçük harf duyarsız): `PCS7_*`, `OT_Network`, `OT_Cybersecurity`, `Safety`, `SCALANCE`, `Sanallastirma`.
- **all modu:** hiç uyan klasör yoksa veya `--all` verilmişse her şey taranır (kökteki dosyalar dahil, üst klasör
  `(kök)`). Hangi modun kullanıldığı ve nedeni loglanır ve `kb_rapor.txt`'ye yazılır.
- Her iki modda: path'in herhangi bir parçası `EXCLUDE_PATTERNS`'a uyarsa atlanır: `Projeler`, `CN4100`,
  `Kendi_Kilavuzlarim`, `Kurs_*`, `_tekrarlar`, `_tablolar`, `_diger`, `_md_donusumler`.

## Metin çıkarma
- `.pdf`, tercih **pdftotext**: doküman başına tek `pdftotext -layout -enc UTF-8 <pdf> -` çağrısı, sayfalar form feed
  (`\f`) ile ayrılır (`page_kind='page'`, sayfa no = PDF sayfa sırası). Arama sırası: `--pdftotext` ->
  `shutil.which("pdftotext")` -> Windows'ta `C:\Program Files\poppler*\Library\bin`, `C:\Program Files\poppler*\bin`,
  `C:\poppler*\Library\bin`, `C:\poppler*\bin`. pdftotext hata verirse ("password"/"encrypt" -> şifreli) yerleşik
  okuyucu denenir.
- **Yerleşik okuyucu** (`fallback_pdf_pages`, pdftotext yoksa; stdlib: `mmap` + `zlib`, best effort): nesneler
  (`endobj`'ye atlayarak, binary stream içi taranmaz), object stream (`/ObjStm`), `/Root` -> sayfa ağacı (yoksa
  `/Type /Page` nesneleri dosya sırasıyla), `FlateDecode` veya filtresiz content stream, `Tj` / `TJ` (`< -200` aralık =
  boşluk) / `'` / `"`, satır sonu `Td`/`TD`/`T*`/`Tm`/`ET`, `Tf` ile font: `ToUnicode` CMap (bfchar / bfrange,
  codespacerange'den kod genişliği); CMap'siz basit font cp1252, CMap'siz Type0 çözülemez. Desteklenmeyen: diğer
  filtreler (DCT/LZW/ASCII85), Form XObject, Type3, `/Differences`, OCR. Çözülen sayfa metni %85'ten az
  harf/rakam/boşluk/noktalama içeriyorsa boş sayılır. > 400 MB PDF atlanır. Bu dokümanlar `docs.method='fallback'`,
  `docs.quality='low'`, sayfa `pages.quality='low'`; `KbRef.quality='low'`, `ref_text` sonuna `[metin kalitesi düşük]`.
- **Atlanan PDF** (`pdf_skipped`, `skip_reasons`): `şifreli PDF` (`/Encrypt`), `metin yok (taranmış PDF?, OCR
  yapılmadı)` (hiçbir sayfada metin yok), `metin çözülemedi (font encoding / desteklenmeyen filtre)`,
  `PDF yapısı okunamadı`, `çok büyük`. Doküman eklenmez; `files` ledger'ında `skipped` + neden.
- Bazı sayfaları boş PDF indekslenir; doküman başına bir `unknown`: "metin yok, OCR yapılmadı (s. 2, 5 …)".
- `.md` / `.txt`: metinde `\f` varsa sayfalara bölünür (`page`); yoksa Markdown başlıklarına (`#`…`######`) göre
  chunk'lanır (`page_kind='chunk'`, "sayfa" = chunk sırası, 1'den; başlıktan önceki metin de bir chunk).
  Okuma: UTF-8 (BOM'lu da) -> cp1254 -> latin1.
- Tek dosyanın okuma hatası build'i durdurmaz (`errors` + `unknown`, ledger `error` -> sonraki build tekrar dener).

## Artımlı / devam eden build
- `files` ledger'ı: `path` -> `sig` (klasör: `boyut:mtime`, zip üyesi: `boyut:crc32`), `status` (`indexed` / `skipped` /
  `error` / `container`), `method`, `reason`, `top`. İmza aynıysa dosya **okunmaz** (`unchanged`). Değişmemiş iç zip
  hiç açılmaz. Yeniden okunur: imza farklı, `error`, veya önceki `method` `fallback`/`none` iken artık pdftotext var.
- Her dosya kendi transaction'ında commit edilir: build yarıda kalırsa (Ctrl+C, çökme) tekrar çalıştırınca kalan
  dosyalardan devam eder. db doğrudan yerinde güncellenir (`.tmp` yok).
- Tam tur sonunda kaynakta artık olmayan path'ler silinir (`pruned`). Değişen/silinen dokümanın tekrar sayfası başka
  kopyaya devredilir (`pages.doc_id` güncellenir), FTS metni kaybolmaz.
- `SCHEMA_VERSION` farklı (eski "1") db veya `--rebuild` -> db silinip baştan.
- İlerleme: her `--progress-every` dosyada (varsayılan 25) `i/N dosya, MB/MB, yeni, değişmemiş, sayfa, süre`.
  Bellek: kaynak listesinde sadece metadata, bir seferde tek doküman metni, tekil sayfa hash seti.

## Rapor (`kb_rapor.txt`, db'nin yanında)
Sadece dosya adları + sayılar (doküman içeriği yok): kaynak, mod, db yolu + boyutu, pdftotext durumu; bu turun
sayıları (görülen/seçilen, indekslenen, değişmemiş, silinen, PDF yöntemi pdftotext / yerleşik, atlanan + nedenler,
hata); tüm KB: üst klasör başına doküman / sayfa / düşük kalite, yöntem dağılımı, atlanan/okunamayan dosya listesi
(neden), düşük kaliteli doküman listesi. Aynı özet build sonunda loglanır; `stats["summary"]`.

## Şema (tek SQLite dosyası, `SCHEMA_VERSION = "2"`)
| Tablo | Alanlar |
|---|---|
| `docs` | `id, path` (köke göre relatif, `/`), `file_name, doc_title, product_version, doc_no, pages, title_mismatch, sha1, top` (üst klasör), `method` (pdftotext / fallback / text), `quality` ('low' = yerleşik okuyucu) |
| `pages` (FTS5, `unicode61 remove_diacritics 2`) | `text, heading`, UNINDEXED: `doc_id, page, page_kind, content_hash, quality` |
| `page_refs` | `content_hash, doc_id, page` — aynı içerikli sayfanın **tüm** referansları |
| `files` | ledger: `path, sig, status, method, reason, top` (artımlı build) |
| `meta` | `schema_version, built_at, root, pdftotext, mode, stats` (JSON) |

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
  matched_tokens, matched_keys, quality)`. `snippet` ≤ 160 karakter (kısa referans, uzun alıntı yok).
- `version_note = 'farklı sürüm'`: hedef verilmiş, doküman versiyonu biliniyor ve major.minor farklı.
- `ref_text(ref)`: `Software_Update.pdf (V10.0 SP2), s. 91 — 9.5.17 Compiling the CFC Charts` (chunk için `bölüm N`,
  farklı sürümde sonuna `[farklı sürüm]`).
- `refs_for_findings(db, findings, target_version=None) -> {check_id: [KbRef]}`: sorgu = detay/başlıktaki teknik
  terimler (APL, SFC, TCiR, `OB_DIAG`, Logic Matrix, MLFB `6ES7 …` …) + başlık kelimeleri + check_id parçaları.
  Zayıf eşleşme -> `[]` (çağıran "kaynak bulunamadı" yazar): anahtar terim varken sayfada hiçbiri yoksa; anahtar terim
  yokken < 2 token eşleşiyorsa; isteğe bağlı `min_score`. Aynı check_id'li bulgulardan ilki kullanılır.

## Digest (`kb digest`): geliştiriciye gönderilecek kural adayı özeti
Yüzlerce dokümanı göndermek yerine upgrade ile ilgili içeriği **yüksek recall** ile seçip parçalı Markdown'a yazar;
geliştirici bunlardan `checks.py` kuralları çıkarır. Toplam boyut sınırı yok (kayıp yok), sadece parça sınırı.
- Çıktı: `-o kb_ozet.md` (varsayılan, çalışma klasörü) -> `kb_ozet_01.md`, `kb_ozet_02.md` … her biri ≤ `--part-mb`
  (varsayılan 4 MB; min 16 KB) + aynı klasörde `kb_ozet_index.csv` (UTF-8 BOM). Önceki çalışmadan kalan fazla
  parçalar silinir. Doküman parçaya sığmazsa sonraki parçada başlığı `(devam)` ile sürer.
- Doküman sırası `docs.path`; içinde sayfa sırası. Başlık: `## <dosya adı> (<versiyon>[, metin kalitesi düşük])`,
  altında `_<başlık>_ — \`path\``. Pasaj: `- [s. N] …` (chunk: `[bölüm N]`), ≤ 600 karakter (uzunsa cümle
  sınırında bölünür, metin atılmaz).
- **Seçim** (sayfa satırları paragraflara bölünür; bölüm durumu sayfalar arası taşınır):
  1. Başlığı (numaralı `9.5.17 …` / Markdown `#`; içindekiler satırı `.....  34` değil) `DIGEST_SECTION_HEADING`'e
     uyan bölümün **tamamı**, aynı/üst seviye sonraki başlığa kadar: restriction, notes, important, compatib,
     what's new, new features, changes, upgrad, migrat, installation notes, known issues/problems, discontinued,
     Hinweis, Einschränkung, Kompatibilität, Neuerung, Änderung, Wichtig, kısıtlama, uyumluluk, önemli, yenilik,
     değişiklik. Etiket `bölüm: <başlık>`.
  2. Tek başına satır `Note` / `Notice` / `Important` / `Caution` / `Warning` / `Hinweis` / `Wichtig` / `Achtung` /
     `Not` / `Önemli` / `Uyarı` -> izleyen paragraf (etiket `uyarı: …`).
  3. Kural cümlesi içeren paragraf (`passage_score > 0`): `DIGEST_RULE_PATTERNS` (not supported, no longer
     supported, must (not) be, is/are required, requires, only with, compatib, upgrad, updat, migrat, discontinued,
     replaced by, restriction, note:, notice, caution, important, cannot be, nicht unterstützt, nicht mehr, muss,
     erforderlich, nur mit, desteklenmez, gerekir, zorunlu …) **ve** `DIGEST_TERM_PATTERNS` (APL, Basis Library,
     WinCC, SIMATIC Manager, CFC, SFC, Logic Matrix, F-System, TCiR, H-System, OS server, PH, CAS, SQL Server,
     Windows, firmware, PCS 7 …) veya versiyon. Skor = (3 × kural + 2 × terim + V10.x/V9.1 için 3, diğer V için 1)
     / (1 + uzunluk/300) — sadece seçim eşiği ve test için; çıktı sırası sayfa sırasıdır.
  4. Diğer paragraflarda tablo benzeri satırlar: MLFB (`6ES7 410-5HX08-0AB0`, 6GK7/6AV/6DL…), `V<x.y>`, firmware,
     `SP<n>`, `Upd<n>` (ardışık satırlar ` | ` ile birleşir, etiket `tablo`).
- `--tum`: ilgili dokümanların **bütün** sayfa metni (`### [s. N]` + satırlar).
- **İlgisiz doküman** (dosya adı/başlık/metinde `PCS 7`, `WinCC`, `S7`, `S7-300/400`, `SIMATIC`, `STEP 7` yok;
  klasör adı sayılmaz) özete girmez, index'te `relevant=hayır`.
- **Tekrar:** build'de tekrar sayfa tek FTS satırıdır; `page_refs` ile her dokümana bağlanır. Aynı pasaj (normalize)
  bir kez, dosya yolu sırasında ilk dokümanda yazılır; sonrakilerde `duplicate_passages` sayılır.
- `kb_ozet_index.csv` **her** dokümanı listeler: `doc, path, version, relevant, pages_total, pages_kept, passages,
  section_passages, rule_passages, table_passages, full_pages, duplicate_passages, parts` (kapsama görünür; 0 pasajlı
  dokümanlar da).
- Deterministik: zaman damgası yok (sadece db `built_at`), sıralama path + sayfa + rowid.

## Limitler
- OCR yok: taranmış PDF'ler "metin yok" olarak atlanır ve listelenir.
- Yerleşik PDF okuyucu best effort: karmaşık PDF'lerde (Form XObject, özel encoding) eksik/bozuk metin olabilir;
  pdftotext (poppler) kurulup build tekrar çalıştırılınca bu PDF'ler otomatik yeniden okunur.
- Başlık / versiyon / heading tespiti heuristic; `title_mismatch` sadece uyarı amaçlı.
- Markdown chunk numarası PDF sayfa numarası değildir (`page_kind='chunk'`).
- Semantik arama yok (sadece kelime/bm25); Türkçe bulgu metni İngilizce manual'le ancak teknik terimlerle eşleşir.
- Değişiklik tespiti imza ile (boyut + mtime / CRC); sha1 sadece bilgi amaçlı saklanır.
- Digest seçimi kalıp tabanlı; bölüm başlığı tespiti numaralı / Markdown başlıklara dayanır (numarasız PDF başlıkları kaçabilir; `--tum` ile tam metin alınabilir).
