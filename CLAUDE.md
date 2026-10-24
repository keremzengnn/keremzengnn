# PCS 7 Upgrade Analyzer

## Amaç
Bir SIMATIC PCS 7 proje backup'ını (STEP 7 V5.x tabanlı multiproject klasörü) **SIMATIC Manager açmadan**
offline okuyup upgrade ön değerlendirmesi için gereken bilgileri çıkaran bir CLI aracı.

Kullanıcının **kendi bilgisayarında** çalışır (backup 5+ GB, hiçbir yere yüklenmez). Girdi: klasör veya .zip.
```
python -m pcs7_analyzer                      # pencere (GUI)
python -m pcs7_analyzer <klasör|zip> [-o çıktı_klasörü] [--author ..] [--department ..] [--customer ..] [--discover] [--open]
python -m pcs7_analyzer --demo <klasör>      # sahte proje üret + analiz
```
Çıktı: rapor.docx (Word template'i ile) + rapor.html (Siemens renkleri) + rapor.md + rapor.json. Word template'i için aynı doküman modeli kullanılacak.
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
- `SUBBLKTYP` (gerçek proje MP_PDCS kayıt sayıları + açık kaynak STEP 7 V5 okuyucusu ile güncellendi, 2026-10-24):
  ana (MC7/header) kayıtlar = S7 block tipi kodu: 00008 OB, 00010 DB, **00012 FC**, 00013 SFC, **00014 FB**, 00015 SFB.
  00004 / 00005 = FB / FC'nin **plaintext interface** kaydı (sadece offline oluşturulan block'larda; PLC'den yüklenen /
  korumalı block'ta yok). Sayım ana + interface kaydının birleşimi; isim/author önce interface kaydından, yoksa ana kayıttan.
  Alt kayıtlar (sayılmaz): 1 UDT, 3/7/9 OB/SFC/SFB interface, 6 DB yapısı, 17-22 yorum, 27/38 VAT, 66.
  Ana kayıtta `PASSWORD = 3` -> know-how protection (ÇIKARIM); `LOCDATALEN` = block'un kendi local data'sı.
- Gerçek projede görülen yanlış pozitifler (test ile korunuyor): `F_TRIG` F-System değil (IEC edge trigger);
  `ELEM_400`/`ELEM_300` sürüm değil; `AdvLibIL` = PCS 7 Industry Library (APL değil); header'sız TCON/TSEND/TRCV/
  P_SND_RK/PUT… = Siemens standart (isimden), custom değil; `@@*.pdl` sistem dosyası; arşivi olan "OS1" = server.
- STEP 7 DBF'lerinde mantıksal alan `\x00` olabilir (YDBs/SYMLISTS.DBF): `blockmap._TolerantParser`.
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
- **Gerçek backup'ta çökme yok:** analiz (`analyze._stage`), envanter (`stage`) ve çıktı yazımı (`cli.run`) bölüm bölüm
  yalıtılmış; hata uyarı + `log.txt`'ye traceback. Keşifte okunamayan dosya uyarıdır. Windows'ta uzun path (`source.long_path`).
- BLKLANG kodu -> dil `parsers.subblk.lang_name` (1 STL, 2 LAD, 3 FBD, 4 SCL, 6 GRAPH; bilinmeyen "kod N").
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

## Manuel'den doğrulanan kurallar -> kontrol (yanlış bilgi vermemek için kaynaklı)
| Kural | Kaynak | Check |
|---|---|---|
| V7.1 SP4+ proje V10.0 SP2'ye update edilebilir; V9.1'den eski software doğrudan güncellenemez (PC sıfırdan kurulum) | [1] 4.3 | rapor: Proje migration notu |
| V9.0 SP3+ proje AS library update'siz (AS STOP'suz) update edilebilir | [1] dokümantasyon tablosu | rapor: version_note |
| V10.0 SP2 faceplate'leri sadece APL V9.0.x / V9.1.x ile mixed operation | [1] 9.10.4 | LIB_APL_V8 |
| Logic Matrix: upgrade without new functionality desteklenmez | [1] 9.9.4 | LIB_LOGIC_MATRIX |
| SFC system block'ları (FB245/246/300, FC240…250) elle kopyalanır, complete compile zorunlu | [1] 9.5 | LIB_SFC |
| PCS 7 Library V7.1 kullanılacaksa ES: Library V7.1 SP3 Upd4, ES+OS: Faceplates V7.1 SP3 Upd1 | [1] 8.5 | LIB_PCS7_V71, LIB_STD_LIB |
| Standard block -> APL dönüşümü yeni konfigürasyon gerektirir | [1] 9.11 | LIB_STD_LIB |
| OB_DIAG / OR_M_16 / OR_M_32 master data'dan silinmeli | [1] 4.3 | LIB_MASTERDATA_DELETE |
| OS RT PO sayısı artabilir; lisans upgrade paketleri kademeli | [1] 4.3 | OS_PO_INCREASE, LICENSES |
| CAS desteklenmiyor, arşivi PH'ye aktarılamaz, .PCK silinmeli | [1] 4.2, 9.8 | CAS_PH |
| IM_DRV block'ları update öncesi system chart'tan taşınmalı | [1] 6.1 | IM_DRV |
| PCS 7 BOX RTX update edilemez | [1] 4.1 | HW_BOX_RTX (blocking) |
| Basis TCiR sadece CPU 410-5H >= V8.2; APL TCiR ≤V9.1 SP2 -> ≥V10 sadece 410-5H | Basis Readme 5.2, APL Readme 4.4 | AS_STOP_NO_TCIR |
| V10.0/SP1/SP2'de interface'i değişen block listesi | APL Readme 5.x, Basis Readme 6.x | LIB_INTERFACE (data/block_changes_V10.0SP2.csv) |
| PCS 7 V8.1 = STEP 7 V5.5 SP4 + WinCC V7.3 | PCS 7 Readme V8.1 SP1, Bölüm 5 | versiyon tespiti (diğer eşlemeler confidence low) |

Veri dosyası yeniden üretimi: `python tools/extract_block_changes.py --apl <AdvLib-Readme.md> --basis <BasLib-Readme.md> -o pcs7_analyzer/data/block_changes_V10.0SP2.csv`

## Word raporu
`word.py`: gömülü `data/report_template.dotx` (kullanıcı public olduğunu belirtti; thumbnail çıkarıldı) doldurulur. Kapak (TitleTopline/Title/TitleSubline),
header "Ad | Departman | Tarih", footer "Restricted | © Siemens yıl". İçerik `build_document(full=False)`: ÖZET, PROJE ENVANTERİ,
RİSKLER, Referanslar (müşteri raporu). HTML/MD `full=True`: + teklif öncesi açık konular + ekler (çalışma raporu).
Ayarlar (ad, departman, template yolu) `%APPDATA%/pcs7_analyzer/settings.json`.

## Hedef versiyon
Program **PCS 7 V10.0 SP2'ye özel** (`cli.TARGET`). Hangi versiyondan gelinirse gelinsin hedef budur; mevcut versiyona göre
değişen kısımlar: kademeli yol (`staged_path_from`), `version_note`, APL V8/V9 kontrolü. `--target` seçeneği yok.

## Released Modules
`data/released_modules_V10.0SP2.csv` gömülü (Released Modules V10.0 SP2 List Manual, A5E52547920-AD, Markdown'dan
`released_extract.extract_rows_markdown`). FW: `V6.x` joker, FW'siz satır = her FW. Aksesuarlar (6ES7 960-1AA… H-Sync)
listede yok -> `ACCESSORIES` notu, Düşük etki.

## Envanter modu (`inventory.py`, `--inventory`, PCS7Envanter.exe)
**Kullanıcının 1. önceliği: mevcut durum** (hardware, yazılım versiyonları, library'ler); analiz 2. aşama. Analiz modu da
aynı açık kaynaktan envanteri üretir (`--no-inventory` kapatır). İlk sayfa "Mevcut durum" (`_current_state`): diğer
sayfalardan özet, aynı isimli projenin eski kopyaları özet dışı (en yeni dosya tarihi). Değerlendirme yok; backup'taki her şey Excel'e (`xlsx.py`, bağımlılıksız yazıcı). Symbol table backup içinden
(`read_symlist_all`), HW backup içinden ham tarama (`.s7h` + `hOmSave7/*.DBF` içindeki MLFB/FW). hOmSave7 DBF formatı
(rack/slot/adres) henüz çözülmedi: kullanıcıdan `yapi_tanisi.txt` (sadece şema, `mask_path` ile müşteri adı maskeli) istenir.

## Readiness / güven / diagnostics
- `readiness.py`: `backup_coverage` (ne var / ne yok + analize etkisi; Var / Kısmen / Yok / VERİ YOK), `quote_inputs`
  (teklif girdileri, süre/fiyat yok), `findings_rows` (güven: high -> KANIT, low -> ÇIKARIM; ÇIKARIM sarı). HTML/MD full
  raporda + Excel `Backup_Yeterlilik`, `Teklif_Girdileri`, `Bulgular`. Word (müşteri raporu) Polisan yapısında kalır;
  full rapordaki ek tablolar numarasız (Tablo 1-6 numaralandırması bozulmasın).
- `parsers/diag.py` (DIAGNOSTICS: SQL ERRORLOG, WinCC diagnose, event log CSV, evtx listesi, segment sayısı) ->
  `analyze._analyze_diag` (sadece ERRORLOG / diagnose / evtx varsa) -> rapor "Diagnostics (server fail)" + Excel `Diagnostics`.
  WinCC diagnose formatları gerçek örnekle teyit edilmedi (keyword sınıflandırma, ÇIKARIM).
- `mlfb_info.describe`: MLFB -> model (Released Modules açıklaması = KANIT; yoksa MLFB ailesi = çıkarım; bilinmiyorsa boş).
- Block klasörü etiketi `BlockFolderInfo.label`: "Proje", "Proje · S7 program k/n", "Lib (library)" (.s7l); hex path'te.
  Library projeleri `an.as_folders`'tan hariç (AS kontrollerine girmez), `LIB_MASTERDATA_DELETE` dahil tüm klasörlere bakar
  (tam isim: OB_DIAG / OR_M_16 / OR_M_32; OB_DIAG1 / OR_M_16C silinmez).
- Manual'dan teyitli ek kurallar: proje ≥ V7.1 SP4 (`PROJ_MIN_VERSION`, 4.3), F-library ≥ V1.3 + F-@ chart silinmez (9.5.17),
  desteklenen OS / SQL 2019 / Maintenance functions (4.3), sadece WinCC 3D design (9.6.1).

## Master prompt (PROMPT_BACKUP_ANALYZER_TEK_PARCA) karşılıkları
- Kapsam: `docs/COVERAGE.md` (her madde YAPILDI / KISMİ / YAPILAMADI + neden), kararlar `docs/DECISIONS.md`.
- `blockmap.py`: ID zinciri hrs/S7RESOFF → linkhrs.lnk (01 60 11 00 + int16) → ombstx/offline/<ID:08X>; HRELATI1 RELID 16
  (CPU→program), TOBJTYP 1314972/1315656 (CPU→station); YDBs/YLNKLIST → SYMLISTS. Gerçek projede teyit edilmedi:
  KANIT sadece HW export station adı veya symbol table çapraz kontrolüyle. `blockmap_tanisi.txt` maskeli. Bkz. docs/blockmap_findings.md.
- `unknown.py` UnknownRecorder: `an.unknown` -> unknown.log, Excel `Analiz_Edilemeyenler`, HTML Ek D. Yeni okuma hatası = `_unk()`.
- `compare.py` (`cli compare A B`, pencerede "Karşılaştır"), `parsers/diag.py` (`cli diag`), `kb.py` (`cli kb build|search`,
  `settings.find_kb`, bulgu Kaynak sütununa "Doküman: …").
- `readiness.finding_status`: BLOCKER / RİSK / BİLGİ; kontrol edilemeyen = VERİ YOK; `findings.json`.
- Kurallar YAML değil `checks.py` (DECISIONS). Yeni: PROJ_MIN_VERSION, COMM_STD; symbol kontrolleri envanterde (`symbol_stats`).
- Gerçek müşteri backup'ı geliştirmede OKUNMAZ; sadece sentetik fixture (`_dbfwriter.write_project_links` vb.).

## Paketle (`collect.py`, `--collect`)
`needed(rel, size)` içeriği okunan dosyaları seçer; diğerleri `_pcs7_manifest.csv` (rel, size, mtime .3f, included).
Zip'te manifest varsa `open_source` -> `source.PackageSource` (entries manifest'ten) -> analiz/envanter orijinalle aynı
(`tests/test_collect.py`). Analiz yeni bir dosyanın İÇERİĞİNİ okumaya başlarsa `needed`'e eklenmeli, yoksa pakette eksik kalır.

## Ek prompt: WinCC / OS / alarm / arşiv / SFC / Logic Matrix / lisans
**Düzeltmeler (uyulmalı):**
- ENG (Eng alt projesindeki OS) SRV1'in master kopyası DEĞİL; ES üzerinde çalışan ayrı, tam OS (connection'lar `ASn_ES` / `ASn_SRV`).
  ENG↔SRV1 farkı "iki OS projesi ayrışmış" (`OsDiff.kind == "os_pair"`), online değişiklik yorumu yok; "reconciliation şart" yok.
  ES projesi ↔ OS PC'den alınmış kopya (`kind == "copy"`) ayrı karşılaştırmadır.
- Client grupları dosya **isim setine** göre (boyut farkı ayrıca `size_diff`). `*_Ref*` referans (client sayılmaz), `*_StBy` standby.
- Analizi yapan PC'nin yazılımı tesis versiyonu değildir; versiyon proje dosyalarından.
- Star import yok (test ediliyor); parse hataları yutulmaz, uyarı olarak loglanır (`list_os_project_from_csv`).

**Modüller:** `parsers/wincc_export.py` (Configuration Studio export: UTF-16 bölümler, DmConnection/DmTag/DmStructtag/ALG_Alarm,
connection sınıflandırma named/tcpip/opc + ProgID->üretici, `compare_exports`: aynı AS'e giden farklı adlı named connection eş sayılır),
`parsers/wincc.py` (`sfc_visualization` SfcRtBase/ChartLst, `archive_files`), `excel_report.py` (8 sayfa), `wincc_db.py`
(DENEYSEL .mdf şema tarayıcı: kopya + attach + şema + detach; gerçek SQL Server ile test edilmedi).
**Checks:** WINCC_DIFF, OPC_3RD_PARTY, OS_CONN_REDUNDANCY, SFC_VISU, ARCHIVES; LIB_LOGIC_MATRIX "kurulu, kullanılmıyor" ayrımı
(LM_Matrix/Cause/Effect/Node instance + WinCC `(?<![A-Za-z])LM_(Matrix|Cause|Effect|Node)`; `@PG_LM_*` kanıt değil).
**Girdi:** export'lar backup içinde otomatik bulunur (`discovery.wincc_exports`) veya `--exports <klasör>`; OS'e atama dosya adındaki
OS proje adıyla. Manuel girişler `--manual <json>` (şablon `data/manuel_giris_ornek.json`) veya pencerede (PO, PC station listesi).
**Çıktı:** rapor.xlsx 8 sayfa (Ozet, AS_Envanter, HW_Moduller, Custom_Blocklar, Instance_Sayilari, OS_WinCC, ENG_SRV1_Farklar,
Acik_Konular_Kaynak); Word'e Tablo 4 WinCC yapısı; HTML'e upgrade hazırlık listesi + manuel girişler.
**Müşteriye özel regression değerleri** (tag/alarm sayıları, chart sayıları…) repoya girmez: `tests/regression/expected_local.json`.
**Açık:** .mdf doğrudan okuma (şema bilinmiyor), compile OS wizard ayarlarının (area→OS) proje dosyasındaki yeri, PO tahmini.
