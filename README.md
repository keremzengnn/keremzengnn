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
| **PCS7Analyzer.exe** | V10.0 SP2 upgrade değerlendirmesi (pencerede "Envanter" modu da seçilebilir) | rapor.docx, rapor.html (+ md, json) |
| **PCS7Envanter.exe** | Sadece backup'taki her şeyi okur ve listeler, değerlendirme yapmaz | envanter.xlsx, envanter.html, yapi_tanisi.txt |

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
Zip içindeki zip'ler (ör. farklı tarihli ikinci backup) de açılıp taranır.

Komut satırı:
```
python -m pcs7_analyzer D:\Backup\Proje.zip -o D:\Raporlar\Proje --author "Ad Soyad" --department "Departman" --open
python -m pcs7_analyzer D:\Backup\Proje.zip --inventory  # sadece envanter (Excel)
python -m pcs7_analyzer D:\Backup\Proje --discover        # sadece klasör yapısı
python -m pcs7_analyzer --demo C:\Temp\demo               # sahte demo projesiyle dene
python -m pcs7_analyzer --list-checks                     # tanımlı kontroller
```

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
