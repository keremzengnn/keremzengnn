# PCS 7 Upgrade Analyzer

PCS 7 proje backup'ını (klasör veya .zip) **SIMATIC Manager açmadan** okur; mevcut durumu (versiyonlar, library'ler,
hardware, OS projeleri) çıkarır ve **PCS 7 V10.0 SP2** upgrade'i için riskleri, yol haritasını ve müşteri raporunu üretir.

- Kendi bilgisayarınızda çalışır. Backup **sadece okunur**, değiştirilmez, hiçbir yere gönderilmez.
- Hedef sabit: PCS 7 V10.0 SP2. Mevcut versiyon proje dosyalarından tespit edilir (bu PC'nin yazılımından değil).

## Kurulum
- **Exe (önerilen, Python gerekmez):** GitHub → Actions → "Windows test + exe" → son çalışma → *Artifacts* →
  `PCS7Analyzer-windows` → `PCS7Analyzer.exe`'yi çift tıklayın.
- **Python ile:** Python 3.11+ kurun (ek paket gerekmez), repo klasöründe `Baslat.bat`'a çift tıklayın.

## Kullanım (3 adım)
1. **Backup klasörü…** veya **Backup .zip…** ile backup'ı seçin (zip'i açmaya gerek yok).
2. İlk seferde adınızı ve departmanınızı girin (hatırlanır). Müşteri adı opsiyonel (Word kapağı).
3. **Analiz et**. Bitince pencerede 5 satırlık özet görünür ve `index.html` (özet sayfası) tarayıcıda açılır.
   Butonlar: **Özeti aç**, **Word raporu**, **Excel**, **Klasör**.

Raporlar `Belgeler\PCS7_Raporlar\<backup>_<tarih>` altına yazılır (pencerede değiştirilebilir, hatırlanır).
Büyük backup'ta (5+ GB) analiz birkaç dakika sürebilir; pencerede hangi aşamada olduğu yazar.

**Diğer** bölümü:
| Buton | Ne için |
|---|---|
| Sadece envanter | Değerlendirme olmadan backup'taki her şeyi listeler (daha hızlı) |
| Paketle | Analiz için gereken dosyaları küçük bir zip'e toplar; paket orijinal backup gibi analiz edilir. **Müşteri verisi içerir** |
| Karşılaştır | İki backup'ı karşılaştırır (saha ↔ ES, eski ↔ yeni) ve hangisinin baz alınacağını önerir |
| Siemens doküman arşivi (KB) oluştur | Bir kez yapılır; bulgulara manual / readme referansı eklenir (aşağıda) |
| Gelişmiş | Backup dışındaki WinCC export klasörü, PO sayıları, PC station listesi, önceki rapor (revizyon) |

## Çıktılar (önce `index.html`'i açın)
| Dosya | Ne için |
|---|---|
| `index.html` | Giriş sayfası: ne analiz edildi, proje özeti, sonraki adımlar, tüm dosyaların linki |
| `envanter.html` / `envanter.xlsx` | **Mevcut durum**: PCS 7 / STEP 7 / WinCC versiyonu, library'ler, AS (CPU + FW, CP, slave), OS projeleri. Değerlendirme yok |
| `yol_haritasi.html` | Upgrade için adım adım yol |
| `rapor.html` | Çalışma raporu (mühendis): tüm bulgular, kaynakları, açık konular |
| `rapor.docx` | Müşteri raporu (Word template'iyle). Sarı = çıkarım, teyit edilmeli |
| `rapor.xlsx` | Analiz Excel'i (AS, HW modüller, custom block'lar, instance sayıları, OS/WinCC, farklar) |
| `semboller.xlsx` | Symbol table'lar ve sembol kontrolleri |
| `qa_report.md` | Rapor kalite kontrolü: HATA varsa müşteriye göndermeden düzeltin |
| `revizyon.md` | (Önceki rapor seçildiyse) yeni / kapanan / değişen bulgular |
| `log.txt`, `unknown.log` | Uyarılar ve okunamayan dosyalar (müşteri dosya yolları içerir) |
| `yapi_tanisi.txt`, `blockmap_tanisi.txt` | Geliştirici için tanı (isimler maskeli) |

Bulgu durumları: **BLOCKER** (upgrade'i engeller), **RİSK**, **BİLGİ**, **VERİ YOK** (backup'ta kontrol için veri yok).
Güven: **KANIT** (dosyadan okundu) / **ÇIKARIM** (teyit edilmeli).

## Bir şey ters giderse
- Program durmaz: okunamayan bölüm atlanır, diğerleri raporlanır; uyarılar `log.txt`'de.
- Geliştiriciye **sadece** `yapi_tanisi.txt` ve `blockmap_tanisi.txt` gönderin (isimler maskeli, müşteri verisi yok).
  `log.txt` gerekiyorsa önce içine bakın: müşteri dosya yolları / proje adları içerebilir.
- Backup'ın kendisini, paket zip'ini veya raporları müşteri onayı olmadan paylaşmayın.

## Veri kuralları
- Müşteri backup'ı ve raporlar **sizin PC'nizde kalır**; program internete bağlanmaz.
- Paket (`*_paket.zip`) ve raporlar müşteri verisi içerir: paylaşmadan önce veri kullanım kurallarını teyit edin.
- Müşteri verisi bu repoya **konmaz** (repo public).

## Ekip ayarları
`PCS7Analyzer.exe`'nin (veya `Baslat.bat`'ın) yanına `pcs7_analyzer_ayarlar.json` konursa önce o okunur;
kişisel ayarlar (`%APPDATA%\pcs7_analyzer\settings.json`) boş olmayan değerlerle onu ezer. Program ekip dosyasına yazmaz.
```json
{
  "department": "DI PA CS",
  "template": "sablonlar\\rapor_sablonu.dotx",
  "out_root": "D:\\PCS7_Raporlar",
  "kb_db": "\\\\sunucu\\ekip\\kb.sqlite"
}
```
Anahtarlar: `author`, `department`, `template`, `out_root`, `kb_db`, `released`. Göreli yollar dosyanın klasörüne göredir.

## Siemens doküman arşivi (KB, opsiyonel, bir kez)
Siemens manual / readme'lerini (PDF, Markdown) bir klasöre veya .zip'e koyun → **Diğer → Siemens doküman arşivi (KB)
oluştur…** → klasörü / zip'i seçin. Arşiv bu PC'de (`%APPDATA%\pcs7_analyzer\kb.sqlite`) kalır; sonraki analizlerde
bulgulara doküman referansı eklenir. Pencerede "Doküman arşivi: var / yok" yazar.
PDF metni için [poppler](https://poppler.freedesktop.org/) `pdftotext.exe` PATH'te olursa sonuç daha iyi olur
(Markdown dönüşümleri doğrudan okunur).
```
python -m pcs7_analyzer kb build --root D:\Siemens_Dokumanlar
python -m pcs7_analyzer kb search "Logic Matrix update"
```

## Backup'ta olması iyi olanlar
- ES multiproject'in tamamı (ombstx, hOmSave7, YDBs, wincproj …)
- HW Config export'ları (`.cfg`), S7 F Configuration Pack kurulu PC'den (yoksa F-I/O görünmez)
- OS server / client PC'lerinden `wincproj\<OS projesi>` kopyaları (ES ↔ OS karşılaştırması için)
- WinCC Configuration Studio export'ları (Tag Management, Alarm Logging; dosya adında OS proje adı, ör. `SRV1_Tags.txt`)

## Komut satırı
```
python -m pcs7_analyzer D:\Backup\Proje.zip                 # analiz + envanter; sonunda özet + index.html yolu
python -m pcs7_analyzer D:\Backup\Proje.zip --inventory     # sadece envanter
python -m pcs7_analyzer D:\Backup\Proje.zip --collect       # paket
python -m pcs7_analyzer compare A.zip B.zip                 # karşılaştırma
python -m pcs7_analyzer diag D:\DIAGNOSTICS.zip             # server fail: SQL ERRORLOG, WinCC diagnose, event log
python -m pcs7_analyzer --demo C:\Temp\demo                 # sahte demo projesiyle dene
```
Seçenekler: `-o <klasör>`, `--author`, `--department`, `--customer`, `--manual <json>`, `--exports <klasör>`,
`--compare-to <önceki rapor>`, `--no-inventory`, `--open`, `--list-checks`.

## Geliştirici
```
pip install -e .[test] && pytest
```
Kontroller tek yerde `pcs7_analyzer/checks.py` (`CHECKS`), renkler `report.py` (`SIEMENS_TOKENS`), giriş sayfası
`index_page.py`. Gömülü veriler `pcs7_analyzer/data/` (Released Modules V10.0 SP2, block değişiklikleri, Word template).
Ayrıntılar ve dosya formatı bilgisi: `CLAUDE.md`, `docs/COVERAGE.md`, `docs/DECISIONS.md`.
