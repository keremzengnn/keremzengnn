# Kapsam matrisi (master prompt → kod)

Durum: **YAPILDI** / **KISMİ** / **YAPILAMADI** (neden). Test sütunu: ilgili test dosyası.

| # | Madde (prompt bölümü) | Modül | Test | Durum |
|---|---|---|---|---|
| 1 | Zip / klasör / iç içe zip, salt okuma, tam yol, duplicate-path | source.py | test_analyze, test_source | YAPILDI |
| 2 | Windows uzun path, streaming, büyük dosya | source.py, subblk.py | test_source | YAPILDI |
| 3 | 00 içerik özeti (uzantı, üst klasör, sayılar) | discovery.py (`markers`), inventory "Dosya türleri" | test_discovery, test_inventory | YAPILDI |
| 4 | Backup yeterlilik tablosu + analize etkisi (8.0, 10.A) | readiness.backup_coverage | test_readiness | YAPILDI |
| 5 | project: .s7p/.s7f/.s7l, multiproject, AS listesi, versiyon (cfg/WinCC/APL) | discovery, analyze._versions | test_analyze | YAPILDI |
| 6 | project: Step7Bas.ver / S7NONFGX.tab / LicenseLog.xml / PMStart.log | - | - | YAPILAMADI (formatlar bilinmiyor, fixture yok; tahminle parser yazılmadı) |
| 7 | En güncel backup (aynı proje birden fazla) | analyze._analyze_backups, inventory | test_analyze | YAPILDI (s7p/dosya mtime) |
| 8 | blockmap ID zinciri (8.2) | blockmap.py | test_blockmap | KISMİ (sentetik test; gerçek projede teyit bekliyor, bkz. blockmap_findings.md) |
| 9 | blocks: SUBBLKTYP, VERSION nibble, author→library, SSBPART instance, boş klasör | parsers/subblk.py | test_subblk | YAPILDI |
| 10 | Tanınmayan SUBBLKTYP → Unknown | subblk.other_types → unknown.py | test_cli (unknown.log) | YAPILDI |
| 11 | author→library eşleme tablosu dosyada (`data/author_library_map.yaml`) | subblk.AUTHOR_LIBRARY (Python dict) | test_subblk | KISMİ (YAML değil, bkz. DECISIONS) |
| 12 | Mixed-version, custom block listesi, instance sayıları, source var mı | analyze, checks BLK_*, readiness | test_analyze, test_readiness | YAPILDI (source: s7asrcom/AWL/SCL varlığı, block bazında değil) |
| 13 | Know-how protection / şifreli block sayısı | subblk (PASSWORD = 3), checks BLK_KNOW_HOW | test_subblk | KISMİ (alan anlamı açık kaynak okuyucudan; gerçek projede teyit bekliyor) |
| 14 | Runtime group / chart başına block (FC 64 KB riski) | subblk MC5LEN -> checks BLK_FC_SIZE, rapor "En büyük FC'ler" | test_subblk | KISMİ (FC kod boyutu KANIT; V10'da aşma riski ÇIKARIM; XUTILS çağrı ağacı henüz kullanılmıyor) |
| 15 | hwconfig: .cfg, USED_S7_VERSIONS, F-capable, PDM, modül/FW, GSD ayrı | parsers/hwconfig.py | test_hwconfig | YAPILDI |
| 16 | MLFB yanında model / açıklama | mlfb_info.py | test_source | YAPILDI |
| 17 | IP / MPI adresleri, slot listesi | inventory "HW modüller (export)" (Konum) | test_inventory | KISMİ (rack/slot var; IP/MPI ayrıştırılmıyor) |
| 18 | F-capable CPU'da F-I/O yoksa "export eksik olabilir" | checks HW_F_EXPORT_MISSING | test_checks | YAPILDI |
| 19 | CPU Local Data | subblk LOCDATALEN (block'un kendi değeri), rapor "Local data" | test_subblk | KISMİ (priority class toplamı ve CPU ayarı VERİ YOK) |
| 20 | symbols: SYMLIST + ASC, çift adres, çift isim, adres aralığı | parsers/symbols.symbol_stats, inventory | test_symbols | YAPILDI (bit/word çakışması yok) |
| 21 | Kullanılmayan semboller | - | - | YAPILAMADI (block kodu / chart bağlantısı okunmuyor) |
| 22 | os_wincc: mcp, PDL, script, SfcRtBase, arşiv, Config Studio export, rol, client grupları | parsers/wincc*.py, analyze._analyze_os | test_wincc, test_wincc_os | YAPILDI |
| 23 | OS area ↔ User Administrator, picture tree, dangling picture, .fct, .pck | - (.pck: CAS_PH) | - | YAPILAMADI (User Admin / picture tree .mdf'te; şema bilinmiyor) |
| 24 | Archive segment sayısı / DB boyutu | parsers/wincc.archive_files, diag | test_wincc_os, test_diag | YAPILDI |
| 25 | sfc_f_lm: SFC chart sayısı + visualization, F-System, Logic Matrix 3 kontrol | checks LIB_SFC/SFC_VISU/LIB_F_SYSTEM/LIB_LOGIC_MATRIX | test_wincc_os, test_checks | YAPILDI (LM: block + instance + WinCC; chart içi kullanım yok) |
| 26 | comm: TCON/TSEND/BSEND/PUT/GET/SEND_R/REC_R/Modbus kullanımı | checks COMM_STD, COMM_AS_AS | test_readiness | KISMİ (kullanım + instance; parametreler okunmuyor) |
| 27 | comm: DB parametreleri (Interface, Slot, CPUSlot, Port, R_ID), R_ID çakışması, unit ID, NetPro, CN 4100 | - | - | YAPILAMADI (DB başlangıç değerleri MC5CODE memo'sunda, format teyit edilmedi; NetPro / CN 4100 export örneği yok) |
| 28 | readiness kuralları 10.B 1–16 | checks.py | test_checks, test_readiness | KISMİ: 1,2,3,4,5,6,8,10(not),11,14,15 YAPILDI; 7 VERİ YOK; 9 (CAS) YAPILDI, Tag Logging / design izi YAPILAMADI; 12,13 müşteri sorusu; 16 IM_DRV kontrolü |
| 29 | 10.C zorluk göstergeleri | checks + readiness | test_* | KISMİ (FC 64 KB, EV_ID, şifreli block YAPILAMADI) |
| 30 | 10.D hazırlık listesi, 10.E sonuç + teklif girdileri | report.prep_list, readiness.quote_inputs | test_analyze, test_readiness | YAPILDI |
| 31 | compare (8.10) | compare.py, `cli compare`, pencere "Karşılaştır" | test_compare, test_cli | YAPILDI (CFC chart diff YAPILAMADI) |
| 32 | diag (8.11): ERRORLOG, WinCC diagnose, evtx, segment, zaman çizelgesi | parsers/diag.py, `cli diag` | test_diag, test_readiness | KISMİ (evtx okunmaz → CSV istenir; WinCC log formatı teyitsiz) |
| 33 | kb (9): FTS5, include/exclude, title_mismatch, dedupe, finding referansı | kb.py, `cli kb` | test_kb | YAPILDI (PDF için pdftotext gerekir; OCR yok) |
| 34 | Finding: durum / güven / kaynak / assumption | readiness.findings_json | test_cli | YAPILDI (doc_refs: KB kuruluysa) |
| 35 | UnknownRecorder + Analiz_Edilemeyenler | unknown.py | test_cli, test_source | YAPILDI |
| 36 | Excel sekmeleri (Özet, Backup_Yeterlilik, AS_HW, Bloklar, …, Bulgular, Eksik_Veri, Analiz_Edilemeyenler) | excel_report.py + inventory | test_excel_report | KISMİ (isimler farklı: AS_Envanter, HW_Moduller, Custom_Blocklar, Instance_Sayilari, OS_WinCC, Acik_Konular_Kaynak = Eksik_Veri; Library_Map/Lisans/Comm ayrı sekme yok, envanter.xlsx'te) |
| 37 | Word: Siemens şablonu, tek sayfa özet başta, "Upgrade yaklaşımı" yok | word.py | test_word | YAPILDI (VARSAYIM sarı highlight Word'de YOK; HTML/Excel'de var) |
| 38 | --mask (IP / kullanıcı adı maskeleme) | inventory.mask_path (tanı dosyaları) | test_inventory | KISMİ (raporlarda --mask seçeneği yok) |
| 39 | Golden test `expected.yaml` | tests/test_regression.py (expected_local.json) | test_regression | KISMİ (JSON; kullanıcı doldurur) |
| 40 | Performans testi (bellek tavanı) | - | - | YAPILAMADI |

Sayılar `python tools/coverage_stats.py` ile üretilir (tahmin değil).
