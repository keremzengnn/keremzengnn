# Changelog

Biçim: [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/), sürümleme: [SemVer](https://semver.org/lang/tr/).
Sürüm tek kaynağı `pcs7_analyzer/__init__.py` (`__version__`).

## [1.0.0] - 2026-11-16

### Eklendi
- Backup (klasör veya .zip) SIMATIC Manager açmadan, salt okunur analiz: proje kimliği, PCS 7 / STEP 7 / WinCC versiyonu,
  AS envanteri (CPU + firmware, CP, slave), block klasörleri, library versiyonları, OS projeleri.
- Hedef PCS 7 V10.0 SP2 için kaynaklı kontroller (Released Modules, library, SFC, Logic Matrix, F-System, CAS/PH vb.),
  yol haritası ve müşteri / mühendis raporu (Word, HTML, Markdown, JSON, Excel).
- Envanter modu: değerlendirme yapmadan mevcut durumu Excel'e döker.
- Karşılaştırma (iki backup, ES ↔ OS), paketleme (`--collect`), doküman arşivi (KB), QA raporu.
- WinCC-only girdi desteği.

### Değişti
- Raporlarda belirsizlik dili kaldırıldı: doğrulanmış bulgular ana tabloda, diğerleri sonda
  "Teyit edilecek noktalar" bölümünde toplanır.
- Block kategorisi ve Siemens library author tanıma genel kalıplarla çalışır.

### Güvenlik
- Müşteri verisi, fiyat ve katalog dosyaları için `.gitignore` korumaları ve repo koruma testi.
