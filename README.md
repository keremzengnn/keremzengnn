# PCS 7 Upgrade Analyzer

SIMATIC PCS 7 (STEP 7 V5.x tabanlı) proje backup'ını **SIMATIC Manager açmadan**, kendi bilgisayarınızda
offline okuyup **PCS 7 V10.0 SP2'ye upgrade** ön değerlendirme raporu üretir (hedef sabit; mevcut versiyon backup'tan tespit edilir). Backup hiçbir yere yüklenmez ve **değiştirilmez**
(salt okunur).

Girdi: backup **klasörü** veya doğrudan **.zip** (açmaya gerek yok; sadece gereken dosyalar geçici klasöre çıkarılır).
Çıktı: `rapor.docx` (Word template'inizle; müşteri raporu), `rapor.html` (Siemens renkleri, detaylı çalışma raporu),
`rapor.md`, `rapor.json`.

## İki program
| Program | Ne yapar | Çıktı |
|---|---|---|
| **PCS7Analyzer.exe** | V10.0 SP2 upgrade değerlendirmesi + envanter (pencerede sadece "Envanter" modu da seçilebilir) | rapor.docx, rapor.xlsx (8 sayfa), rapor.html (+ md, json), envanter.xlsx |
| **PCS7Envanter.exe** | Sadece backup'taki her şeyi okur ve listeler, değerlendirme yapmaz | envanter.xlsx, envanter.html, yapi_tanisi.txt |

**Önce bakılacak yer: `envanter.xlsx` → "Mevcut durum" sayfası.** Tek tabloda: PCS 7 / STEP 7 / WinCC versiyonu
(proje dosyalarından), kullanılan library'ler ve versiyonları (APL, Basis, F, Logic Matrix, SFC, V7.1 …, karışık versiyon
uyarısıyla), custom / header'sız FB sayıları, AS bazında CPU + FW, CP'ler, saha cihaz sayıları, OS projeleri. Her satırın
kaynağı yazılıdır. Aynı proje backup'ta birden fazla yerde ise en yeni kopya kullanılır, diğerleri not edilir.

Envanter, export almadan backup içinden okur: symbol table'lar (`YDBs/.../SYMLIST.DBF`, tüm semboller),
HW (`.s7h` ve `hOmSave7` DBF'lerinden MLFB + FW; rack/slot yok), tüm FB/FC listesi ve instance sayıları, OS picture/script
listeleri. `.cfg` / `.asc` export'ları varsa onlar da okunur. `yapi_tanisi.txt` müşteri verisi içermez (sadece DBF alan
adları ve kayıt sayıları); formatı çözülmemiş dosyalar için geliştiriciyle paylaşılabilir.

## Kullanım (Windows)

**A) Exe (Python gerekmez):** GitHub → Actions → "Windows test + exe" → son çalışmanın *Artifacts* kısmından
`PCS7Analyzer-windows` indirin → `PCS7Analyzer.exe` veya `PCS7Envanter.exe`'yi çift tıklayın.

**B) Python ile (3.11+, ek paket gerekmez):** repo klasöründe `Baslat.bat`'a çift tıklayın.

Pencerede: **Backup klasörü seç…** veya **Backup .zip seç…** → (ilk seferde) adınızı ve departmanınızı girin
→ **Analizi başlat** → rapor tarayıcıda açılır, **Word'ü aç** ile .docx açılır. Ayarlar hatırlanır.
Raporlar varsayılan olarak `Belgeler\PCS7_Raporlar\<backup>_<tarih>` altına yazılır.
Her çalıştırmada aynı klasöre `log.txt` yazılır: bir şey ters giderse (uyarı, okunamayan dosya) bu dosyaya bakın.
Bir bölüm (ör. OS projeleri) okunamazsa program durmaz; diğer bölümler raporlanır, hata uyarılarda yazar.
Zip içindeki zip'ler (ör. farklı tarihli ikinci backup) de açılıp taranır.

Komut satırı:
```
python -m pcs7_analyzer D:\Backup\Proje.zip -o D:\Raporlar\Proje --author "Ad Soyad" --department "Departman" --open
python -m pcs7_analyzer D:\Backup\Proje.zip --inventory  # sadece envanter (Excel)
python -m pcs7_analyzer D:\Backup\Proje.zip --no-inventory  # analiz, envanter olmadan (daha hızlı)
python -m pcs7_analyzer D:\Backup\Proje --discover        # sadece klasör yapısı
python -m pcs7_analyzer --demo C:\Temp\demo               # sahte demo projesiyle dene
python -m pcs7_analyzer --list-checks                     # tanımlı kontroller
```

## Diğer komutlar
```
python -m pcs7_analyzer compare A.zip B.zip -o D:\Fark      # iki backup farkı (saha/ES, eski/yeni): fark.md/xlsx/json
python -m pcs7_analyzer diag D:\DIAGNOSTICS.zip             # server fail: SQL ERRORLOG, WinCC diagnose, event log CSV
python -m pcs7_analyzer kb build --root D:\Siemens_Dokumanlar --db kb\kb.sqlite   # offline doküman indeksi
python -m pcs7_analyzer kb search "Logic Matrix update"
```
`kb\kb.sqlite` (çalışma klasöründe) veya `%APPDATA%\pcs7_analyzer\kb.sqlite` varsa her bulguya doküman referansı eklenir
(PDF için `pdftotext` gerekir; Markdown dönüşümleri doğrudan indekslenir). Pencerede "Karşılaştır" modu da var.

Her analizde ayrıca: `findings.json` (durum BLOCKER/RİSK/BİLGİ/VERİ YOK, güven KANIT/ÇIKARIM), `unknown.log`
(analiz edilemeyenler), `blockmap_tanisi.txt` (block klasörü ↔ AS zinciri, isimler maskeli — geliştiriciyle paylaşılabilir).
Kapsam ve kararlar: `docs/COVERAGE.md`, `docs/DECISIONS.md`, `docs/blockmap_findings.md`.

## Paketle (backup'ı göndermek için)
5+ GB backup'ın çoğu (WinCC .mdf/.ldf, arşivler, picture'lar) analizde sadece adı/boyutu/tarihiyle kullanılır.
Pencerede **Paketle** (veya `--collect`) sadece içeriği okunan dosyaları (block klasörleri, HW, DBF'ler, symbol table,
.mcp, script'ler, export'lar) `<backup>_paket.zip` içine toplar; diğer tüm dosyalar manifest'te listelenir.
Paket bu programla orijinal backup gibi analiz edilir (aynı sonuç, test ile korunuyor).
Paket müşteri verisi içerir: paylaşmadan önce veri kullanım kurallarını teyit edin.
```
python -m pcs7_analyzer D:\Backup\Proje.zip --collect -o D:\Paket
```

## WinCC tag / alarm (Configuration Studio export)
Tag ve alarm konfigürasyonu OS projesinin `.mdf` veritabanındadır. Configuration Studio'da **Tag Management** ve **Alarm Logging**
export edilip (`.txt`, dosya adında OS projesinin adı geçsin: ör. `SRV1_Tags.txt`, `ENG_Alarms.txt`) backup klasörüne konur ya da
pencerede "WinCC export klasörü" seçilir. Program connection / tag / struct tag / alarm sayılarını, ENG↔SRV1 farklarını,
3rd party OPC server'ları ve H-system'e tek IP'li TCP/IP bağlantıları raporlar.

Deneysel: export'suz okumak için `.mdf` şema tarayıcı (WinCC/SQL Server kurulu PC'de, admin):
```
python -m pcs7_analyzer.wincc_db D:\Backup\...\wincproj\SRV1\SRV1.mdf
```
Orijinal dosyaya dokunmaz (kopya attach edilir, sonra detach + silinir); sadece tablo/kolon adı ve satır sayısı yazar.
Çıkan `*_sema.txt` paylaşılırsa export'suz okuma eklenebilir.

## Manuel girişler
PO / archive tag (SIMATIC Manager → Options → PCS 7 License Information), PC station listesi pencerede girilebilir ya da
`--manual manuel.json` (şablon: `pcs7_analyzer/data/manuel_giris_ornek.json`). Girilmeyenler raporda "eksik" yazar.

## Backup'ta olması iyi olanlar
- ES multiproject'in tamamı (ombstx, hOmSave7, YDBs, wincproj …)
- **HW Config export'ları** (`.cfg`, HW Config → Station → Export), S7 F Configuration Pack kurulu PC'den
- ES ↔ OS server karşılaştırması için: OS server / client PC'lerinden `wincproj\<OS projesi>` kopyaları
  (ES projesi dışında bir klasörde, ör. `PC_KOPYALARI\SRV1\wincproj\OS_SRV1`)

## Gömülü veriler
- `data/report_template.dotx`: Siemens Word template'i (one-column wide, A4). Başka template için `--template`.
- `data/released_modules_V10.0SP2.csv`: Released Modules (V10.0 SP2) List Manual'dan çıkarıldı (731 satır, manual'daki tüm
  MLFB'ler). FW eşleşmesi `V6.x` gibi jokerleri anlar. Aksesuarlar (H-Sync) listede yoktur, ayrıca not edilir.

## Manuel'lerden gelen veriler
`pcs7_analyzer/data/block_changes_V10.0SP2.csv`: APL ve Basis Library Readme V10.0 SP2'deki "List of changed blocks"
tablolarından çıkarıldı (`tools/extract_block_changes.py`). Projede kullanılan ve interface'i değişen block tipleri raporlanır.

## Released Modules listesini yenilemek
```
python -m pcs7_analyzer.released_extract S7pcshwb_en-US.md -o pcs7_analyzer/data/released_modules_V10.0SP2.csv
```
Listede olmayan modül "bulunamadı, teyit edilmeli" olarak raporlanır, asla "uyumlu" denmez.

## Geliştirme
```
pip install pytest && pytest
```
Kontroller tek yerde: `pcs7_analyzer/checks.py` (`CHECKS`). Renkler tek yerde: `pcs7_analyzer/report.py` (`SIEMENS_TOKENS`).
Ayrıntılar: `CLAUDE.md`. Müşteri verisi bu repoya **konmaz**.
