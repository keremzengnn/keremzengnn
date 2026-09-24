# PCS 7 Upgrade Analyzer

SIMATIC PCS 7 (STEP 7 V5.x tabanlı) proje backup'ını **SIMATIC Manager açmadan**, kendi bilgisayarınızda
offline okuyup upgrade ön değerlendirme raporu üretir. Backup hiçbir yere yüklenmez ve **değiştirilmez**
(salt okunur).

Girdi: backup **klasörü** veya doğrudan **.zip** (açmaya gerek yok; sadece gereken dosyalar geçici klasöre çıkarılır).
Çıktı: `rapor.docx` (Word template'inizle; müşteri raporu), `rapor.html` (Siemens renkleri, detaylı çalışma raporu),
`rapor.md`, `rapor.json`.

## Kullanım (Windows)

**A) Exe (Python gerekmez):** GitHub → Actions → "Windows test + exe" → son çalışmanın *Artifacts* kısmından
`PCS7Analyzer-windows` indirin → `PCS7Analyzer.exe`'yi çift tıklayın.

**B) Python ile (3.11+, ek paket gerekmez):** repo klasöründe `Baslat.bat`'a çift tıklayın.

Pencerede: **Klasör…** veya **Zip…** ile backup'ı seçin → (ilk seferde) Word template'i, adınızı ve departmanınızı girin
→ **Analizi başlat** → rapor tarayıcıda açılır, **Word'ü aç** ile .docx açılır. Ayarlar hatırlanır.
Zip içindeki zip'ler (ör. farklı tarihli ikinci backup) de açılıp taranır.

Komut satırı:
```
python -m pcs7_analyzer D:\Backup\Proje.zip -o D:\Raporlar\Proje --template D:\sablon.dotx --author "Ad Soyad" --department "Departman" --open
python -m pcs7_analyzer D:\Backup\Proje --discover        # sadece klasör yapısı
python -m pcs7_analyzer --demo C:\Temp\demo               # sahte demo projesiyle dene
python -m pcs7_analyzer --list-checks                     # tanımlı kontroller
```

## Backup'ta olması iyi olanlar
- ES multiproject'in tamamı (ombstx, hOmSave7, YDBs, wincproj …)
- **HW Config export'ları** (`.cfg`, HW Config → Station → Export), S7 F Configuration Pack kurulu PC'den
- ES ↔ OS server karşılaştırması için: OS server / client PC'lerinden `wincproj\<OS projesi>` kopyaları
  (ES projesi dışında bir klasörde, ör. `PC_KOPYALARI\SRV1\wincproj\OS_SRV1`)

## Word template
Siemens Word template'i (.dotx) repoda yoktur. Pencerede bir kez seçin ya da exe'nin yanındaki `data/` klasörüne koyun.
Template yoksa HTML/MD/JSON yine üretilir.

## Manuel'lerden gelen veriler
`pcs7_analyzer/data/block_changes_V10.0SP2.csv`: APL ve Basis Library Readme V10.0 SP2'deki "List of changed blocks"
tablolarından çıkarıldı (`tools/extract_block_changes.py`). Projede kullanılan ve interface'i değişen block tipleri raporlanır.

## Released Modules listesi
Hardware uyumluluğu için `data/released_modules_V10.0SP2.csv` gerekir (exe'nin veya çalışma klasörünün
yanındaki `data/` klasörüne koyun ya da pencerede seçin). Manual'dan taslak çıkarmak için:
```
pip install pypdf
python -m pcs7_analyzer.released_extract ReleasedModules.pdf -o data/released_modules_V10.0SP2.csv
```
Taslağı **elle kontrol edin**. Listede olmayan modül "bulunamadı, teyit edilmeli" olarak raporlanır, asla "uyumlu" denmez.

## Geliştirme
```
pip install pytest && pytest
```
Kontroller tek yerde: `pcs7_analyzer/checks.py` (`CHECKS`). Renkler tek yerde: `pcs7_analyzer/report.py` (`SIEMENS_TOKENS`).
Ayrıntılar: `CLAUDE.md`. Müşteri verisi bu repoya **konmaz**.
