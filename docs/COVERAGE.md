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
| 37 | Word: Siemens şablonu, tek sayfa özet başta, "Upgrade yaklaşımı" yok | word.py | test_word | YAPILDI (VARSAYIM / ÇIKARIM run seviyesinde sarı highlight, bkz. R5) |
| 38 | --mask (IP / kullanıcı adı maskeleme) | inventory.mask_path (tanı dosyaları) | test_inventory | KISMİ (raporlarda --mask seçeneği yok) |
| 39 | Golden test `expected.yaml` | tests/test_regression.py (expected_local.json) | test_regression | KISMİ (JSON; kullanıcı doldurur) |
| 40 | Performans testi (bellek tavanı) | - | - | YAPILAMADI |


## Rapor kalitesi (EK_RAPOR_KALITESI)

Ek prompt `PROMPT_EK_RAPOR_KALITESI.md` (master prompt bölüm 11'in yerine). Kararlar: `docs/DECISIONS.md` "Rapor kalitesi".

| # | Madde | Modül | Test | Durum |
|---|---|---|---|---|
| R0 | İlkeler: önce karar, izlenebilirlik, kısa, deterministik, KANIT/ÇIKARIM/VARSAYIM, Türkçe + İngilizce terim | report.py, readiness.py | test_readiness, test_word | KISMİ (ilk sayfa ÖZET + Finding ID; R3/R4 eksikleri aşağıda) |
| R1 | Report IR (`report_ir.json`: schema_version, profile, input_hash, sections, finding_ids, stats, omitted) | report_ir.py, cli.py | - | YAPILDI (ayrı select/compose katmanı yok: `build_document` doküman modeli = IR, bkz. DECISIONS) |
| R2 | Okuyucu profilleri (`--profile`) | report_ir.PROFILES | - | KISMİ (teklif / musteri -> Word müşteri raporu `full=False`, muhendis -> HTML tam rapor; devreye_alma / troubleshoot YAPILAMADI: içerik tanımı yok; profil bölüm sırası / satır limiti / sütun seçimi belirlemiyor; musteri'de maskeleme uygulanmıyor, sadece QA `MASK` yakalar; YAML değil Python dict) |
| R3.1 | Önem sıralaması BLOCKER > RİSK > VERİ YOK > BİLGİ | report.group_findings, readiness.finding_status | test_readiness | KISMİ (severity sırası; etki alanı / güven ikincil sıralaması yok) |
| R3.2 | Gruplama: sayı + en fazla N örnek + "(+N)", tam liste Excel'de ID ile | report.group_findings, `_short` | test_readiness | KISMİ (grup = konu etiketi; kural başına `group_by` anahtarı yok) |
| R3.3 | Limitler (özet satır, hücre ~25 kelime, giriş ≤ 2 cümle, boş bölüm yok) | qa.py (CELL_WORDS, EMPTY_SECTION) | - | KISMİ (QA ile ölçülüyor; özet BLOCKER 5 / RİSK 10 kesmesi ve "ve N bulgu daha" yok; giriş cümle sayısı kontrol edilmiyor) |
| R3.4 | Her BLOCKER/RİSK'in aksiyonu + sorumlusu | checks.ACTIONS, action_for; Word risk tablosu "Aksiyon (sorumlu)" | test_readiness | YAPILDI (aksiyonsuz BLOCKER/RİSK = QA HATA `NO_ACTION`) |
| R3.5 | "Upgrade yaklaşımı" yok, kesinti / PC tek satır not, kademeli yol yan yana, süre/fiyat yok | report.py, readiness.quote_inputs | test_word, test_readiness | YAPILDI |
| R4.1 | Cümle kalıpları (`phrases.yaml`) | checks.ACTIONS (aksiyon, sorumlu) | - | KISMİ (sadece aksiyon kalıbı; title/effect kalıbı ve kalıpsız bulgu uyarısı yok; YAML değil Python dict) |
| R4.2 | Terim sözlüğü: keep_english, forbidden_translations, abbreviations | data/glossary.json, qa.qa_glossary | - | YAPILDI (JSON; yasak çeviri = QA HATA; abbreviations ilk geçiş açılımı uygulanmıyor) |
| R4.3 | Sayı binlik ayırıcı, tarih GG.AA.YYYY, Siemens versiyon yazımı | fmt.py (`fmt_num`, `fmt_date`, `fmt_month`) -> checks.py, report.py, readiness.py, word.py, excel_report.py metin hücreleri; excel sayısal hücre `#,##0` | test_fmt, test_word, test_wincc_os | YAPILDI (metinde Türkçe nokta "1.234", tarih GG.AA.YYYY / ay AA.YYYY; JSON / IR / findings.json / log ISO ve ham sayı; `ReportMeta.date` ISO veri, sadece görüntüde biçimlenir; ondalıklı değerler ("30.0 KB", versiyon) dokunulmaz) |
| R5 | Word: şablon stilleri, sarı highlight (run), başlık tekrar + cantSplit, Finding ID + Aksiyon sütunu, sayfa sırası | word.py | test_word | KISMİ (highlight `word.is_assumption` ile run seviyesinde; tablolar tblHeader + cantSplit; revizyon tablosu Word'de yok, `revizyon.md`; sütun genişliği / sayı sağa hizası içerik tipine göre değil) |
| R6 | Excel: Arial, #009999, freeze, filtre, `#,##0`, Finding ID, Güven, renkler, formül özet, boş sekme yok | excel_report.py, xlsx.py, readiness.FINDINGS_COLUMNS | test_excel_report | KISMİ (Bulgular'da ID + Aksiyon (sorumlu); BLOCKER kırmızı, RİSK turuncu, VERİ YOK gri, ÇIKARIM sarı = stil, Excel koşullu biçimi değil; Özet'te COUNTIFS sadece ENG↔SRV fark özetinde; LibreOffice recalc YAPILAMADI: kurulu değil, QA önbellek değerlerine bakar; koşullu sekmeler (Diagnostics) veri yoksa oluşturulmaz) |
| R7 | Revizyon farkı `--compare-to` + `learn` | revision.py -> revizyon.md; learn.py -> style_suggestions.json (`python -m pcs7_analyzer learn`) | test_revision, test_learn | KISMİ (anahtar check_id + scope + title; Yeni / Kapanan / Değişen; `out/<proje>_<tarih>_r<N>/` klasör adı yok, rev no IR'da; learn öneri üretir, hiçbir zaman otomatik uygulamaz) |
| R8 | QA kapısı (`qa <klasör>` -> qa_report.md, HATA -> çıkış 1) | qa.py QA_CHECKS | test_qa (her QA kontrolü için bozuk fixture) | KISMİ (placeholder, aksiyon, glossary, IR/findings/Excel sayıları, highlight, doğrudan biçim, Excel hata, boş bölüm, omitted BLOCKER, mask (musteri), hücre kelime, tablo düzeni, tekrar YAPILDI; "Finding ID'siz rakam cümlesi" YAPILAMADI: başlık / açıklama cümlelerinde çok yanlış pozitif; Excel formül hatası sadece önbellek değeri) |
| R9 | Görsel kontrol (docx -> PDF -> sayfa görüntüsü) | - | - | YAPILAMADI (pipeline'da Word / LibreOffice yok; kullanıcı Word'de kontrol eder) |
| R10 | Referans rapordan sadece yapı (`extract-style --reference`) | docx_style.py -> reference_style.json | test_docx_style | KISMİ (başlık ağacı, tablo sütun/satır, stil, highlight, kelime sayıları; metin maskeli; profil/stil dosyası otomatik üretilmiyor; sayfa sayısı yok — render yok) |
| R11 | Opsiyonel LLM anlatı katmanı (`--narrative`) | - | - | YAPILAMADI (bilinçli: araç offline, veri dışarı çıkmaz; kalıp metin tek yol, bkz. DECISIONS) |
| R12 | Testler: golden IR, MD snapshot, QA bozuk fixture, gruplama, profil, Türkçe liste, determinizm | tests/test_docx_style, test_word, test_qa, test_report_ir, test_revision, test_learn, test_fmt | test_qa, test_report_ir | KISMİ (QA bozuk fixture (her kontrol), IR şema + Finding ID bağları + profil + determinizm, revizyon, learn, sayı/tarih biçimi VAR; IR "golden-ish" (şema/anahtar), tam golden dosya ve MD snapshot yok) |
| R13 | Uygulama sırası | - | - | KISMİ (1–4, 6 kısmen; 5 ve 7 yapılmadı, yukarıda) |

Sayılar `python tools/coverage_stats.py` ile üretilir (tahmin değil).
