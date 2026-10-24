# İki backup karşılaştırması (`pcs7_analyzer/compare.py`)

Kullanım senaryoları: saha backup'ı ↔ ES backup'ı, eski ↔ yeni backup, ES projesi ↔ OS server PC'sinden alınmış kopya.
Amaç: farkları **tek bir listede** (Kategori kolonu) göstermek ve "hangisi baz alınmalı" için **kanıt** toplamak.
Program karar vermez; öneri metni her zaman "Karar kullanıcıya aittir." ile biter.

## Girdi
- İki path: klasör veya .zip (iç içe zip 1 seviye açılır). `source.open_source` ile açılır, **sadece okunur**.
- Her taraf `analyze.analyze_source` ile analiz edilir (aynı .s7p'nin eski kopyaları analiz dışı: `stale_dirs`).
- Block detayı için `SUBBLK.DBF` (+ `.DBT`) `parsers.subblk.parse_subblk` ile tekrar okunur.

## API
```python
compare(path_a, path_b, log=None) -> CompareResult          # iki kaynağı açar/kapatır
compare_sources(src_a, src_b, log=None) -> CompareResult    # açık Source'lar
write_outputs(res, out_dir) -> Path                          # fark.md + fark.json + fark.xlsx; fark.md döner
```
`CompareResult`: `label_a`, `label_b`, `rows: list[DiffRow]`, `summary: list[(konu, değer)]`, `evidence: list[str]`,
`recommendation: str`, `warnings: list[str]`.

## DiffRow alanları
| Alan | Anlam |
|---|---|
| category | Proje, Block, Library, HW, HW geçmişi, OS dosyası, Tag, Alarm, Alarm metni, Connection |
| scope | proje / S7 program etiketi (`BlockFolderInfo.label`), station adı, OS adı |
| item | `FB1990 SINAMICS_G120`, `6ES7 321-1BL00-0AA0 V1.0`, `GraCS/Tank1.pdl` … |
| change | `sadece A`, `sadece B`, `farklı`, `A'da daha yeni`, `B'de daha yeni` |
| a / b | taraf değeri (isim, author, versiyon / adet / boyut + tarih) |
| source_a / source_b | taraf içindeki tam relatif path |
| confidence | `KANIT` (dosya içeriği/boyutu) / `ÇIKARIM` (tarih veya formatı teyit edilmemiş veri) |

## Eşleme
- **Proje:** proje klasör adı (büyük/küçük harf duyarsız, `owner_name`). Tek tarafta olan proje -> `Proje` satırı.
- **S7 program:** aynı projede program sayısı eşitse `program_no` sırasıyla; farklıysa `Proje` satırı
  ("S7 program sayısı") + uyarı ve block klasörü hex adıyla (path'in son parçası) eşleme; eşlenemeyen klasör `Proje` satırı.
  Boş block klasörleri (0 kayıt) karşılaştırılmaz.
- **HW station:** station adı (büyük/küçük harf duyarsız). Aynı ad iki kez -> ikincisi uyarı.
- **OS projesi:** OS proje adı (`info.name`); aynı ad bir tarafta birden fazlaysa ES içindeki (`in_es`) seçilir.
- **WinCC export:** OS adı (export dosya adından, `assign_os`).

## Kurallar (kontrol listesi)
| # | Kontrol | Kategori | Güven |
|---|---|---|---|
| 1 | Proje / S7 program / OS projesi sadece bir tarafta | Proje | KANIT |
| 2 | FB / isimli FC sadece bir tarafta | Block | KANIT |
| 3 | Aynı numara, farklı isim / author / VERSION | Block (`farklı`) | KANIT |
| 4 | FB/FC/DB/OB sayısı farklı (isimsiz CFC FC'leri ve DB'ler tek tek listelenmez) | Block | KANIT |
| 5 | FB başına instance DB sayısı farklı (CFC değişikliğinin dolaylı göstergesi) | Block | KANIT |
| 6 | Library author dağılımı değişti (ör. APL AdvLib81 -> AdvLib82); custom / CFC generated hariç | Library | KANIT |
| 7 | Station başına (MLFB, FW) multiset: sadece A/B veya adet farklı. FW değişikliği = eski FW `sadece A` + yeni FW `sadece B` | HW | cfg: KANIT, .s7h fallback: ÇIKARIM |
| 8 | Proje başına `hOmSave7/s7hstatx/*.s7h` sayısı ve tarih aralığı, son kayıt hangi tarafta | HW geçmişi | ÇIKARIM |
| 9 | `hOmSave7/**/HOBJECT1.DBF`, `HATTRIB1.DBF` tarihi (son değişiklik / yükleme göstergesi) | HW geçmişi | ÇIKARIM |
| 10 | OS picture/script (`.pdl .bmo .bac .pas .act`): sadece A/B, boyut farklı, daha yeni taraf (fark > 2 s). Bilgisayar adı klasörü (`<PC>/PAS`) ihmal edilir | OS dosyası | boyut farkı: KANIT, sadece tarih: ÇIKARIM |
| 11 | Connection sadece bir tarafta (aynı AS'e giden farklı adlı named connection eş sayılır) | Connection | KANIT |
| 12 | Tag sadece bir tarafta / connection-adres farklı | Tag | KANIT |
| 13 | Alarm numarası sadece bir tarafta, message class farklı | Alarm | KANIT |
| 14 | Aynı alarm numarası, farklı event metni | Alarm metni | KANIT |

Tarih karşılaştırmasında tolerans **2 s** (zip zaman damgası çözünürlüğü).

## Özet, kanıt, öneri
- **summary:** A/B etiketi, toplam ve kategori başına satır sayısı, program başına FB/FC/DB/OB sayıları,
  en yeni SUBBLK.DBF / OS dosyası tarihleri, station / .s7h / OS projesi / export sayıları.
  Bir tarafta hiç yoksa değer `A: OS projesi yok` biçimindedir ("fark yok" denmez).
- **evidence:** SUBBLK.DBF'i daha yeni olan programlar, sadece A/B block sayıları,
  "B tarafı X tarihinden sonra N HW kaydı almış; A'yı baz almak bu değişiklikleri kaybettirir (doğrudan download riski)",
  daha yeni OS dosyası sayıları.
- **recommendation:** göstergelerin çoğunluğu bir tarafı gösteriyorsa o taraf + diğer tarafa özgü kaç satırın kontrol
  edilmesi gerektiği; çelişkiliyse birleştirme uyarısı; fark yoksa karşılaştırılmayan içerik notu. Son cümle her zaman
  "Karar kullanıcıya aittir."

## Çıktı
- `fark.md`: özet tablosu, kanıtlar, öneri, kategori başına tablo (kategori başına en fazla 300 satır, tamamı xlsx'te), uyarılar.
- `fark.json`: `CompareResult` (asdict).
- `fark.xlsx`: `Farklar` (tek liste, Kategori kolonu, filtre, dondurulmuş başlık; değişiklik rengi: sadece A/B sarı,
  farklı kırmızı, daha yeni yeşil) + `Ozet` (özet, kanıtlar, öneri, uyarılar).

## Sağlamlık
- Her bölüm (block, HW, HW geçmişi, OS, WinCC export) ayrı `try/except`; hata `warnings`'e yazılır, diğer bölümler devam eder.
- Okunamayan SUBBLK.DBF: o program için block satırı üretilmez, uyarı `Block karşılaştırması yapılamadı: <program> (B: ...)`.
- Bir taraf hiç analiz edilemezse satır üretilmez, öneri bunu söyler.
- Kaynağa yazılmaz (zip'ten okunan dosyalar `Source` temp klasörüne çıkarılır).

## Kabul kriterleri (tests/test_compare.py, sadece sentetik demo verisi)
- Aynı girdi -> 0 satır, kanıt yok, öneri "Karar kullanıcıya aittir." ile biter.
- Demo kopyasında: FB VERSION değişikliği, APL author AdvLib81 -> AdvLib82, yeni FB, yeni .s7h (yeni mtime),
  picture ekle/sil/touch, script içerik değişikliği, .cfg'de CP FW değişikliği -> beklenen satırların **tamamı ve yalnızca onlar**.
- Kanıtlar daha yeni tarafı (B) ve "doğrudan download riski" cümlesini içerir.
- Zip girdi klasörle aynı satırları verir; klasör ↔ kendi zip'i 0 satır.
- OS projesi olmayan taraf çökme üretmez, özet `B: OS projesi yok` der.
- Bozuk SUBBLK.DBF -> uyarı; HW ve diğer kategoriler yine karşılaştırılır.
- WinCC alarm export'unda metin değişikliği / yeni alarm / silinen alarm satırları.

## Bilinen sınırlamalar
- **CFC chart farkı yok:** CFC chart saklama formatı (`s7cfc/`) çözülmedi; sadece instance DB sayısı dolaylı gösterge.
- SFC chart, NetPro bağlantıları, PC station konfigürasyonu, symbol table içerik farkı karşılaştırılmaz.
- Block kodu (MC5CODE) karşılaştırılmaz: aynı isim/author/VERSION'da kod değişikliği görünmez. DB/OB tek tek listelenmez (sadece sayı).
- `.s7h` geçmiş formatı teyit edilmedi; s7h sayısı/tarihi "son değişiklik / yükleme göstergesi" olarak ÇIKARIM.
  HOBJECT1/HATTRIB1 içeriği (rack/slot) çözülmediği için sadece tarih karşılaştırılır.
- mtime kopyalama araçlarıyla değişebilir; tarih tabanlı satırlar ÇIKARIM'dır.
- HW'de FW değişikliği tek satırda değil, eski/yeni (MLFB, FW) çifti olarak iki satırda görünür.
- WinCC tag/alarm farkı sadece Configuration Studio export'u her iki tarafta varsa yapılır (.mdf okunmaz).
- Block klasörü ↔ AS eşlemesi analizdeki heuristic'e dayanır; eşleme proje adı + program sırasıyla yapılır.
