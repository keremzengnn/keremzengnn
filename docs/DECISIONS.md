# Kararlar (DECISIONS)

Master prompt'taki [DANIŞ] maddeleri ve diğer mimari kararlar. Her karar: tarih, karar, gerekçe, alternatif.

## 2026-10-24 — Mevcut mimari korunur (prompt'taki `modules/`, `io/`, `report/` klasör düzenine taşınmaz)
- **Karar:** Paket düzeni aynı kalır (`analyze.py` + `parsers/` + `checks.py` + `report.py` + yeni modüller kökte).
- **Gerekçe:** 190+ test, GUI, 2 exe ve paketleme bu düzene bağlı; taşıma davranış değiştirmeden risk getirir. Prompt'taki
  modüllerin karşılıkları: inventory → `inventory.py` + `readiness.backup_coverage`; project/blocks/hwconfig/symbols →
  `parsers/*` + `analyze.py`; blockmap → `blockmap.py`; os_wincc → `parsers/wincc*.py`; sfc_f_lm → `parsers/wincc.py`
  + `checks.py`; readiness → `readiness.py` + `checks.py`; compare → `compare.py`; diag → `parsers/diag.py`; kb → `kb.py`;
  findings → `model.py` (+ `readiness.finding_status/findings_json`); unknown → `unknown.py`.
- **Alternatif:** Tam yeniden düzenleme — yalnızca isim değişikliği getirir, kullanıcıya fayda yok.

## 2026-10-24 — Katman ayrımı (extract / assess / report): kısmi
- **Karar:** Tek yönlü akış korunur: `analyze_source` (extract + kurallar) → `rapor.json` (tüm Analysis, deterministik) →
  `findings.json` (durum, güven, assumption) → Excel / Word / HTML. `rapor.json` = extract çıktısı; ayrı `cli extract|assess`
  komutu yok.
- **Gerekçe:** Yanlış bulguda kaynağı ayırmak için `rapor.json` (ham değer + kaynak yol) ve `findings.json` yeterli; ayrı
  JSON şemaları ve yeniden yükleme katmanı bakım maliyeti getirir.
- **Alternatif:** `extract/*.json` + `schema_version` + `assess` komutu. İhtiyaç olursa `rapor.json`'dan türetilebilir.

## 2026-10-24 — Kural tabanı YAML yerine Python (`checks.py` CHECKS)
- **Karar:** Kurallar `checks.py` içinde tek listede (id, konu, severity, manual referansı, fonksiyon). YAML yok.
- **Gerekçe:** Dağıtım "Python + standart kütüphane" (Baslat.bat, ek paket yok); PyYAML gerekir. Kuralların çoğu sürüm
  karşılaştırması / koleksiyon taraması (predicate) — YAML'da zaten Python fonksiyonuna referans olurdu. Yeni kural = bir satır
  + bir fonksiyon. Manual'dan doğrulanmamış kural güven ÇIKARIM ile işaretlenir (raporda sarı).
- **Alternatif:** `rules/V10.0SP2.yaml` + predicate kütüphanesi. Yeni hedef sürüm gerektiğinde değerlendirilecek.

## 2026-10-24 — UnknownRecorder
- **Karar:** `unknown.py`; analiz edilemeyen her şey (okunamayan dosya, tanınmayan SUBBLKTYP, çözülemeyen instance, blockmap
  zincir boşluğu, okunmayan evtx, tamamlanamayan analiz bölümü) modül + tam yol + neden ile kaydedilir → `unknown.log`, Excel
  `Analiz_Edilemeyenler`, HTML Ek D. Uyarılar listesi de korunur.
- **Gerekçe:** "Sessiz except yok" kuralı; kullanıcı neyin analiz edilmediğini tek yerde görür.

## 2026-10-24 — blockmap: ID zinciri + çapraz kontrol
- **Karar:** Block klasörü ↔ AS eşlemesi önce STEP 7 V5 proje ID zinciriyle (bkz. `docs/blockmap_findings.md`), olmazsa
  eski heuristic (proje adı / symbol FB seti). Zincir tam ve HW export station adı veya symbol table ile tutarlıysa KANIT,
  aksi halde ÇIKARIM.
- **Gerekçe:** Zincir açık kaynak STEP 7 V5 proje okuyucusundaki yapıdan öğrenildi (kod kopyalanmadı, LGPL); gerçek müşteri
  projesiyle henüz teyit edilmedi. Kullanıcı `blockmap_tanisi.txt` (isimler maskeli) paylaşınca teyit edilecek.
- **Alternatif:** Sadece FB seti benzerliği (eski yöntem) — çok program'lı projelerde belirsiz.

## 2026-10-24 — KB: SQLite FTS5, pdftotext opsiyonel, model yok
- **Karar:** `kb.py`; `.md/.txt` doğrudan, `.pdf` pdftotext varsa. Sadece referans verir, risk kararı vermez.
- **Gerekçe:** Şirket PC'sinde poppler olmayabilir; kullanıcının manual'ların Markdown dönüşümleri var. FTS5 Python'un
  sqlite3'ünde mevcut.

## 2026-10-24 — Geliştirmede gerçek müşteri backup'ı okunmaz
- **Karar:** Sadece sentetik fixture (`demo.py`, `_dbfwriter.py`). Gerçek backup'ı kullanıcı çalıştırır; geliştiriciye yalnızca
  maskeli tanı dosyaları (`yapi_tanisi.txt`, `blockmap_tanisi.txt`) ve özet gelir.

## 2026-10-24 — Rapor kalitesi: Report IR = mevcut doküman modeli (ayrı select/compose katmanı yok)
- **Karar:** İçerik kararları `report.build_document` içinde kalır (bölümler, tablolar, gruplama, Finding ID bağları
  `Table.row_ids`). Renderer'lar (HTML / MD / Word, Excel `findings_rows`) sadece biçimler. `report_ir.py` bu modeli
  `report_ir.json`'a serileştirir: `schema_version`, `profile`, `input_hash` (kaynak indeksinin rel + boyut sha256'sı, içerik
  okunmaz), `sections`, `finding_ids`, `stats`, `omitted` (rapora girmeyen her bulgu + neden). `generated_at` dışında
  deterministik (anahtarlar sıralı).
- **Gerekçe:** Doküman modeli zaten IR (renderer'dan bağımsız blok listesi); ayrı compose katmanı yeniden yazımı test edilmiş
  rapor yapısını (Word Tablo 1-6) bozar, fayda getirmez. İçerik / biçim hatası ayrımı IR ↔ çıktı karşılaştırmasıyla yapılır (QA).
- **Alternatif:** Prompt'taki select/compose → IR → render zinciri; IR'dan geri okuyan renderer'lar. Profil sayısı artarsa.

## 2026-10-24 — Profiller, kalıplar, sözlük: YAML yok (Python dict / JSON)
- **Karar:** Profiller `report_ir.PROFILES` (teklif / musteri -> Word müşteri raporu `full=False`, muhendis -> HTML tam rapor
  `full=True`). Aksiyon kalıpları `checks.ACTIONS` (check_id -> (aksiyon, sorumlu)) + `action_for`; `phrases.yaml` yok.
  Terim sözlüğü `data/glossary.json` (keep_english, forbidden_translations, abbreviations).
- **Gerekçe:** Kurallarla aynı (bkz. "Kural tabanı YAML yerine Python"): standart kütüphane, PyYAML yok. Aksiyon check'in
  yanında tanımlı -> aksiyonsuz BLOCKER/RİSK QA'da yakalanır.
- **Açık:** devreye_alma / troubleshoot profilleri tanımlanmadı (içerik kullanıcıyla netleşmeli). Profil şu an sadece doküman
  modunu seçer; bölüm sırası / limit / sütun seçimi profil verisi değil.

## 2026-10-24 — Sayı ve tarih biçimi
- **Karar:** Rapor metninde (Word / HTML / MD) binlik ayırıcı Türkçe nokta (`1.234`); Excel `#,##0` (görünüm Excel'in yerel
  ayarına göre, Türkçe Excel'de nokta). Tarih `GG.AA.YYYY`; makine çıktıları (JSON, log, IR `generated_at`) ISO kalır.
- **Durum:** Uygulama tutarlı DEĞİL (COVERAGE R4.3 KISMİ): Word Tablo 4 nokta kullanıyor, bulgu detay metinleri (`checks.py`
  `{:,}`) virgül; Word header / kapak tarihi `meta.date` ISO (YYYY-AA-GG). Birleştirme: tek `fmt_num` / `fmt_date` yardımcısı.
- **Gerekçe:** Okuyucu Türk mühendis / müşteri; Siemens TR dokümanları Türkçe biçimi kullanır.

## 2026-10-24 — Word: highlight, tablo düzeni, Finding ID
- **Karar:** VARSAYIM / ÇIKARIM metni run seviyesinde sarı highlight (`word.is_assumption` işaretleri), hücre gölgesi değil.
  Risk tablosunda Finding ID + "Aksiyon (sorumlu)" sütunu. Tablolarda başlık satırı tekrar (`tblHeader`), satır bölünmez
  (`cantSplit`). Excel `Bulgular` aynı ID'yi taşır (`readiness.FINDINGS_COLUMNS`): Word satırından Excel ayrıntısına ID ile gidilir.

## 2026-10-24 — QA kapısı ve sınırları
- **Karar:** `qa.py` `QA_CHECKS` (yeni kontrol = fonksiyon + satır), `python -m pcs7_analyzer qa <klasör>` -> `qa_report.md`,
  HATA varsa çıkış kodu 1. Sayılar tek kaynaktan: IR `stats` = `findings.json` = Excel `Bulgular` durum sayıları.
- **Yapılmayanlar:** "Finding ID'si olmayan rakam cümlesi" kontrolü yok (başlık, açıklama, envanter cümlelerinde gürültü);
  Excel formülleri yeniden hesaplanmaz (LibreOffice yok, xlsx yazıcı önbellek değeri yazar; QA önbelleğe bakar); görsel kontrol
  (R9, docx -> PDF) yok: pipeline'da Word / LibreOffice yok, sayfa düzenini kullanıcı Word'de kontrol eder.

## 2026-10-24 — Revizyon, learn, referans stil
- **Karar:** `--compare-to <önceki klasör>` -> `revision.py` önceki `findings.json` ile fark -> `revizyon.md` + IR `revision`.
  Anahtar `check_id + scope + title` (Finding ID sıralamaya bağlı, anahtar olamaz). `learn` (`learn.py`) elle düzeltilmiş
  Word ile üretileni yapısal karşılaştırır -> `style_suggestions.json`; hiçbir öneri otomatik uygulanmaz.
  Referans rapor: `extract-style` (`docx_style.py`) sadece yapı çıkarır (başlık ağacı, tablo sütunları, stiller, highlight,
  kelime sayıları), metin maskeli; müşteri içeriği geliştiriciye gelmez.

## 2026-10-24 — LLM anlatı katmanı (R11) yapılmadı
- **Karar:** `--narrative` yok; tüm metin kalıplardan üretilir.
- **Gerekçe:** Araç offline çalışır, backup verisi bilgisayardan çıkmaz; katman prompt'ta da varsayılan kapalı ve sadece "cila".
  Rapor bu katman olmadan eksiksiz. Gerekirse IT kararı ve maskelenmiş IR özetiyle ayrı modül olarak eklenir.
