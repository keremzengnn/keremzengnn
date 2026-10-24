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
