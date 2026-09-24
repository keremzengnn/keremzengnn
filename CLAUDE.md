# PCS 7 Upgrade Analyzer

## Amaç
Bir SIMATIC PCS 7 proje backup'ını (STEP 7 V5.x tabanlı multiproject klasörü) **SIMATIC Manager açmadan**
offline okuyup upgrade ön değerlendirmesi için gereken bilgileri çıkaran bir CLI aracı.

Kullanıcının **kendi bilgisayarında** çalışır (backup 5+ GB, hiçbir yere yüklenmez). Girdi: klasör veya .zip.
```
python -m pcs7_analyzer                      # pencere (GUI)
python -m pcs7_analyzer <klasör|zip> [-o çıktı_klasörü] [--target V10.0SP2] [--released csv] [--discover] [--open]
python -m pcs7_analyzer --demo <klasör>      # sahte proje üret + analiz
```
Çıktı: rapor.html (Siemens renkleri) + rapor.md + rapor.json. Word template'i için aynı doküman modeli kullanılacak.
Dağıtım: `Baslat.bat` (Python 3.11+, ek paket yok: dbfread `_vendor/` altında) veya GitHub Actions'ın ürettiği
`PCS7Analyzer.exe` (`.github/workflows/windows.yml`, testler Windows'ta da koşar).

Kullanıcı: PCS 7 otomasyon mühendisi. Raporda Türkçe metin, İngilizce teknik terimler
(firewall, block, library, faceplate…) **çevrilmeden** kalır. Kısa, madde madde, gereksiz metin yok.

## Kod yapısı
```
pcs7_analyzer/
  source.py       klasör / zip kaynağı: dosya indeksi + gerektiğinde temp'e çıkarma (kaynağa yazmaz)
  discovery.py    indeksten keşif (proje, block klasörü, cfg/s7h, symbol, OS projesi)
  parsers/        subblk.py, hwconfig.py, symbols.py (ASC + SYMLIST.DBF), wincc.py
  analyze.py      Analysis modeli: versiyon, AS envanteri, released eşleşme, block klasörleri, OS, tutarlılık
  checks.py       TÜM kontrollerin tek tanım yeri (CHECKS)
  report.py       doküman modeli -> Markdown / HTML / JSON; SIEMENS_TOKENS renkleri
  gui.py, cli.py  pencere ve komut satırı
  demo.py         sahte ama gerçekçi PCS 7 backup üreticisi (test ortamı)
  released_extract.py  Released Modules manual -> CSV taslağı
  data/           released_modules_<ver>.csv (müşteriden bağımsız)
  _vendor/dbfread gömülü bağımlılık (MIT)
tests/            pytest; test_analyze.py demo projesiyle uçtan uca (klasör + zip)
```
Test: `pytest`
Test: `pip install -e .[test] && pytest`

## Proje klasör yapısı (STEP 7 V5.x)
```
<Multiproject>/                 -> *.s7f (multiproject), alt projeler
<Proje>/
  *.s7p                         -> proje dosyası
  ombstx/offline/<8 hex>/       -> her S7 program'ın block klasörü
      SUBBLK.DBF + SUBBLK.DBT   -> block header'ları + memo (kod/interface)
      BAUSTEIN.DBF              -> block listesi
  hOmSave7/s7hstatx/*.s7h       -> HW Config (binary)
  hOmSave7/*/HOBJECT1.DBF, HATTRIB1.DBF… -> HW objeleri
  YDBs/                         -> symbol table'lar (SYMLIST.DBF)
  s7asrcom/, s7cfc/ …           -> source'lar, CFC
  <OS adı>/wincproj/<OS proje>/ -> WinCC OS projesi (*.mcp, GraCS/, ScriptLib/, ScriptAct/…)
  global/, xutils/ …
```
Aynı isimli dosyalar (SUBBLK.DBF vb.) her block klasöründe tekrar eder: **her zaman tam path ile çalış.**

## Doğrulanmış dosya formatı bilgisi (değiştirme, test ile koru)
**SUBBLK.DBF** (dbfread ile okunur, `char_decode_errors='ignore'`)
- **`encoding='latin1'` zorunlu.** dbfread language driver 0x00'da 'ascii' seçer; `char_decode_errors='ignore'` ile
  SSBPART memo'sundaki ≥0x80 byte'lar silinir ve FB numaraları bozulur (FB1990 -> FB7). Test ile korunuyor.
- Alanlar: `SUBBLKTYP, BLKNUMBER, BLOCKFNAME (family), BLOCKNAME, VERSION, USERNAME (author), BLKLANG, MC5CODE, SSBPART, ADDINFO`
- `SUBBLKTYP`: 00004=FB, 00005=FC, 00008=OB, 00010=DB, 00013=SFC, 00015=SFB. Diğer kodlar aynı block'un alt kayıtları.
- `VERSION` tek byte: `0x30 -> 3.0` (high nibble major, low nibble minor).
- Author → library: `AdvLib81`=APL V8.1, `AdvLib82`=APL V8.2, `AdvLibLM`=Logic Matrix, `DRIVER81`=Basis Library V8.1,
  `ELEMENTA/ELEM_300/ELEM_400`=CFC ELEMENTA, `ES_MAP`=CFC'nin ürettiği FC/DB, `ES_SFC`=SFC system block,
  `COMM71`=eski PCS 7 Library V7.1, `F_SAFE13`=S7 F Failsafe Blocks V1_3, `SIEMENS`=Siemens add-on (Modbus TCP vb.).
  Diğer author'lar (ör. `BM`, `MANAR`, `UK`) = integratör/custom.
- F-block'ların header'ı boştur (korumalı) → numara aralığı ve symbol table ile tanınır.
- **Instance → FB eşlemesi:** DB kaydının `SSBPART` memo'su: byte0 `0x0A`=FB instance / `0x0B`=SFB instance,
  byte1-2 little-endian FB numarası. DBT gerektirir. Saçma numaralar (≥ 8192) filtrelenir ve `unresolved_instances`'ta sayılır.
  Önceki saçma numaraların muhtemel sebebi yukarıdaki encoding hatası. SSBPART artık özel FieldParser ile HAM byte
  okunur (decode yok); MC5CODE/ADDINFO memo'ları hiç okunmaz (büyük DBT'de hız). **Açık:** DBT'nin DB3 mü DB4 mü olduğu teyit edilmedi;
  DB3 memo 0x1A'da, dbfread'in DB4 okuyucusu 0x1F'de keser -> FB26 / FB31 instance'ları kaybolabilir.
- **Boş block klasörü:** DBF 834 byte, 0 kayıt. Normaldir (kullanılmayan program), hata değil.

**HW Config export (.cfg)**: latin1, CRLF. `RACK/DPSUBSYSTEM/IOSUBSYSTEM` satırları: `"<MLFB veya GSD>" "<FW>", "<isim>"`.
`USED_S7_VERSIONS` hex-encoded string: `5.5.4.x` = STEP 7 V5.5 SP4 → PCS 7 V8.1.
`CAPABLE_F_SAFETY "1"` = F-capable CPU. `PDM_PARAM "1"` = PDM ile parametrelenmiş cihaz.
- **Tuzak:** S7 F Configuration Pack kurulu olmayan PC'den alınan export'ta **F-I/O modülleri hiç görünmez.**
  Symbol table'da F-block veya block klasöründe F driver instance'ı varken HW'de F-modül yoksa uyarı ver.
- .cfg yoksa `.s7h` binary'sinden fallback: MLFB regex + sonraki string firmware (`scan_s7h`).

**Symbol table (.ASC)**: `126,` ile başlayan satırlar, isim ilk 24 karakter.

**WinCC**: `.mcp` içinde WinCC build (`V07.03.20.04` = WinCC 7.3). `GraCS/*.pdl` içinde `@` ile başlamayanlar custom picture,
`@PG_<Tip>_*.pdl` faceplate'ler, `@PCS7Typicals*.pdl` picture object template'leri, `ScriptLib/*.bmo` VBS modülleri,
`ScriptAct/*.bac` VBS global action'lar, `<bilgisayar adı>/PAS/*.pas` C action'lar (bilgisayar adı klasörü karşılaştırmada ihmal edilir).

## Yapılacak analizler (her biri raporda ayrı bölüm)
1. **Proje kimliği:** multiproject/proje listesi, PCS 7 / STEP 7 / WinCC versiyonu (kaynak göster: hangi dosyadan).
2. **AS envanteri:** her H/non-H station: CPU + FW, CP'ler, DP/PN slave'ler, GSD cihazlar, F-capable, PDM kullanımı.
3. **Hardware uyumluluk:** Released Modules listesine karşı eşleştirme. Liste markdown/PDF'ten çıkarılmış tablo olarak
   `data/released_modules_<versiyon>.csv` dosyasına konacak (MLFB, FW, durum). **Listede olmayanı "bulunamadı" diye raporla**,
   "uyumlu" deme (ör. H-Sync modülü 960-1AA06 listede yok).
4. **Block klasörleri:** her klasör için FB/FC/DB/OB sayısı, library versiyon dağılımı, **karışık versiyonlar**
   (aynı library'nin farklı author sürümleri), custom block listesi (numara, isim, family, author, dil), instance sayıları.
5. **Riskli içerik tespiti:** SFC, Logic Matrix, Modbus TCP, PCS 7 Library V7.1 block'ları, F-System,
   STL/SCL custom block'lar, header'sız block'lar, symbol'ü olup block'u olmayan (ve tersi) block'lar.
6. **Block klasörü ↔ AS eşlemesi:** **Çözülmemiş problem.** (Şu an: proje adı + SYMLIST FB seti Jaccard ≥ %50, heuristic.) Şimdiye kadar symbol table'daki FB listesi ile
   block klasörünün FB setini karşılaştırarak elle eşledik. Proje dosyalarında (S7CONTAI.DBF, BSTCNTOF.DBF, HOBJECT1.DBF,
   S7RESOFF.DBF …) doğrudan eşlemeyi bul; bulamazsan FB seti benzerliğiyle eşle ve raporda "heuristic" diye işaretle.
7. **OS yapısı:** server / standby / client / ES projeleri, custom picture sayısı, script'ler, custom typicals,
   F faceplate'leri (`@PG_SWC_MOS*`, `@PCS7Typicals_S7F*`), OPC konfigürasyonu.
8. **Tutarlılık (en önemli, önceki analizde gözden kaçtı):**
   - ES OS projesi ↔ OS server projesi: sadece birinde olanlar, boyut farkı olanlar, **hangisinin daha yeni olduğu** (mtime).
     Özellikle custom picture ve script'ler. "Server'da daha yeni" = online yapılmış, ES'e alınmamış değişiklik.
   - Client'lar arası: client'ları içerik imzasına göre grupla, grupları referansa göre diff'le.
   - Aynı projenin farklı tarihli backup'ları varsa: hangisi güncel.
9. **Özet ve açık konular:** tespit edilemeyen / teyit gereken her şey listelensin (ör. NetPro bağlantıları,
   PC station config, arşiv yapısı, 3rd party yazılımlar).

## Kurallar
- **Okuma sadece.** Proje klasörüne asla yazma. Geçici dosyalar için temp klasör kullan.
- Büyük dosyalar olacak (SUBBLK.DBT 400+ MB, DBF 70 MB): streaming oku, hepsini belleğe alma; ilerleme göster.
- Her bulgu kaynağını taşısın (dosya yolu). Emin olunmayan çıkarım `confidence: low` ile işaretlensin.
- Encoding: DBF/cfg latin1; Türkçe karakterler bozulabilir, çökme değil uyarı.
- Windows'ta çalışacak (Python 3.11+). Path'ler için `pathlib`, `\\` hardcode etme.
- Kontrol listesi (checks) tek yerde tanımlı olsun ki yenileri kolayca eklenebilsin: her check = id, başlık,
  fonksiyon, severity (Yüksek/Orta/Düşük), manual referansı (ör. "Software update V10.0 SP2, Bölüm 9.9.4").
  → `pcs7_analyzer/checks.py` `CHECKS`. Yeni kontrol = bir satır. `func=None` = planlandı, raporda "kontrol edilmedi".

## Test verisi
Müşteri backup'ı ve müşteriye özel beklenen değerler **repoya girmez (repo public).** Regression testleri
`tests/test_regression.py`: `PCS7_TEST_PROJECT=<klasör>` ve gitignore'daki `tests/regression/expected_local.json`
(şablon: `expected_example.json`) ile çalışır. Müşteri projesi kullanmadan önce veri kullanım kuralları teyit edilmeli.

## Heuristic'ler (gerçek projeyle teyit edilecek)
- SYMLIST.DBF alan adları (`_SKZ`, `_OPIEC`, `_KOMMENTAR`) anahtar kelimeyle eşleniyor.
- OS rolü proje adından (SRV/STBY/OSC/CLIENT…). ES ↔ server çifti: aynı isimli OS projesi, biri .s7p içinde, diğeri dışında.
- Aynı .s7p adı birden fazla yerde -> en yeni mtime'lı kopya analiz edilir, diğerleri analiz dışı (raporda not).
- WinCC build -> PCS 7 ailesi eşlemesi (7.3 -> V8.1 …) `confidence: low`.
