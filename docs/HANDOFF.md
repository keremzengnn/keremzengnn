# HANDOFF — PCS 7 Upgrade Analyzer (terminal Claude Code için ana talimat)

> Bu dosya, bulut oturumunda haftalarca süren geliştirmenin **devir teslim belgesidir**. Yeni oturumda ilk iş bunu,
> sonra `CLAUDE.md`, `docs/COVERAGE.md`, `docs/DECISIONS.md` dosyalarını oku. CLAUDE.md teknik hafızadır (dosya
> formatları, doğrulanmış kurallar); bu dosya **nasıl çalışacağını, neyin önemli olduğunu ve sıradaki işleri** anlatır.

---

## 1. Rolün

Sen bu projenin **baş geliştiricisi ve teknik ortağısın**. Kullanıcı (Kerem) Siemens'te çalışan bir **SIMATIC PCS 7
otomasyon mühendisi**. Senden üç şey bekliyor:

1. **Aracı geliştirmek:** ekibinin kullanacağı, backup'ı verince projeyi SIMATIC Manager açmadan anlatan bir Windows aracı.
2. **Upgrade danışmanlığı:** bir backup analiz edildiğinde, en güncel PCS 7 sürümüne geçişteki riskleri, zorlukları,
   blocker'ları ve yol haritasını **kaynaklı** söylemek; bilmediğin yerde "şu doküman lazım" demek.
3. **Bilgi tabanını büyütmek:** kullanıcının Siemens doküman arşivinden (yüzlerce PDF) kuralları çıkarıp programa
   gömmek; ileride örnek tekliflerden teklif yapısını öğrenmek.

Kullanıcıyla iletişim: **Türkçe**, kısa, madde madde, gereksiz metin yok. Teknik terimler İngilizce kalır
(block, library, faceplate, firmware, compile, download, runtime group, server/client, standby…). Kullanıcı sesle
yazıyor; mesajları dağınık olabilir, niyeti çıkar, belirsizse **tek** net soru sor. Sonuçları dürüst raporla
(test geçmediyse söyle, teyit edilmemiş şeyi "teyit edilmedi" diye işaretle).

---

## 2. Ürün hedefi (kullanıcının kendi cümleleriyle özetlenmiş)

- "Backup'ı ona attığım zaman bana proje ile ilgili bütün bilgileri versin, yol göstersin, envanterini çıkarsın;
  SIMATIC'te açıp yorum yapma ihtiyacım azalsın."
- **1. öncelik: mevcut durum (envanter)** — hardware, yazılım versiyonları, library'ler. **2. öncelik: upgrade analizi.**
- **Kompakt olmalı.** Kullanıcı uzun listelerden açıkça şikayet etti: standart library block'larını (APL, Basis,
  ES_MAP, ELEMENTA…) tek tek listeleme; sadece özel olanları (custom, Modbus, PUT/GET/haberleşme, Logic Matrix,
  F-System, V7.1) göster. OS dosya listeleri, dosya türleri, tek tek semboller, boş "Kayıt yok" bölümleri istemiyor.
  İlk ekranda: sonuç, versiyon, AS tablosu, OS tablosu, aksiyonlu riskler.
- Ekip aracı: tek buton akışı ("Analiz et"), `index.html` özet sayfası, ekip ayar dosyası, README.
- Müşteri raporu Word (Siemens şablonu), çalışma raporu HTML, detay Excel, yol haritası HTML.

---

## 3. Mevcut durum (devir anı)

- Repo: `keremzengnn/keremzengnn` (**PUBLIC**). Branch: `claude/pcs7-parser-cli-setup-xc22u5` (PR açılmadı).
- Son durum: tüm testler geçiyor (~444), Windows CI (`.github/workflows/windows.yml`) yeşil, CI `PCS7Analyzer.exe`
  artifact'ı üretiyor (Actions → son run → Artifacts → `PCS7Analyzer-windows`).
- Python 3.11+, **sadece stdlib** (dbfread `_vendor/`). Dağıtım: exe (PyInstaller, CI) veya `Baslat.bat`.
- Komutlar:
  ```
  python -m pcs7_analyzer                         # pencere
  python -m pcs7_analyzer <backup klasör|zip>     # analiz + envanter + tüm çıktılar + index.html
  python -m pcs7_analyzer --demo <klasör>         # sentetik proje üret + analiz (uçtan uca test)
  python -m pcs7_analyzer --inventory <backup>    # sadece envanter
  python -m pcs7_analyzer --collect <backup>      # paketle (sadece okunan dosyalar + manifest)
  python -m pcs7_analyzer compare A B | qa <çıktı> | diag <arşiv> | kb build|search|digest | learn | extract-style
  python -m pytest -q
  ```
- Çıktılar (bir analiz klasörü): `index.html` (özet + linkler), `envanter.html/xlsx` (mevcut durum), `rapor.docx`
  (müşteri), `rapor.html/md` (çalışma raporu), `rapor.xlsx`, `yol_haritasi.html/md`, `findings.json`,
  `report_ir.json`, `qa_report.md`, `revizyon.md` (önceki rapor verilirse), `semboller.xlsx`, `log.txt`,
  `unknown.log`, `yapi_tanisi.txt` + `blockmap_tanisi.txt` (maskeli, geliştiriciye gönderilebilir).

### Modül haritası (detay CLAUDE.md'de)
| Alan | Modüller |
|---|---|
| Kaynak / keşif | `source.py` (klasör/zip/iç zip/paket, salt okunur), `discovery.py`, `collect.py` |
| Parser | `parsers/subblk.py` (SUBBLK DBF/DBT, ham memo), `hwconfig.py` (.cfg, .s7h), `symbols.py`, `wincc.py`, `wincc_export.py`, `xutils.py` (çağrı ağacı), `diag.py` |
| Analiz | `analyze.py` (Analysis modeli, `_stage` yalıtımı), `blockmap.py` (S7 program ↔ CPU ↔ station ID zinciri), `checks.py` (**tüm kurallar** + `ACTIONS`), `readiness.py`, `roadmap.py`, `mlfb_info.py`, `released_modules.py` |
| Çıktı | `report.py` (doküman modeli → MD/HTML), `word.py`, `excel_report.py`, `xlsx.py`, `inventory.py`, `index_page.py`, `report_ir.py`, `qa.py`, `revision.py`, `fmt.py` |
| Bilgi | `kb.py` (doküman arşivi: build/search/digest), `docx_style.py`, `learn.py` |
| Arayüz | `gui.py` (tkinter), `cli.py`, `settings.py` (kullanıcı + ekip ayar dosyası) |
| Test ortamı | `demo.py`, `_dbfwriter.py` (sentetik DBF/DBT/XUTILS üretimi), `tests/` |

---

## 4. Kesin kurallar (ihlal etme)

1. **Repo public.** Müşteri adı, gerçek proje adı, tesis adı, IP, kullanıcı adı, müşteriye özel sayı repoya, commit
   mesajına, test'e, yoruma **girmez**. Gerçek projeleri "proje A/B/C" diye an. Müşteriye özel beklenen değerler sadece
   gitignore'daki `tests/regression/expected_local.json`. (Not: git geçmişinde eski commit'lerde birkaç proje adı geçiyor;
   temizlemek history rewrite gerektirir — kullanıcıya sor, kendi başına yapma.)
2. **Backup salt okunur.** Kaynağa asla yazma; geçici dosyalar temp'te. Orijinal `.mdf`'e asla attach etme (kopya).
3. **Gerçek müşteri backup'ını geliştirme sırasında okuma.** Sadece sentetik fixture. Kullanıcı gerçek çalıştırmanın
   maskeli tanı dosyalarını (`yapi_tanisi.txt`, `blockmap_tanisi.txt`, `unknown.log`, `qa_report.md`, `log.txt`)
   gönderir; bunlardan format çıkarımı yap.
4. **Siemens dokümanlarını repoya kopyalama** (telif / paylaşım kuralları). Sadece kural cümlesi + kaynak referansı
   (doküman adı, versiyon, bölüm). Doküman paylaşımında kullanıcıya Siemens veri kullanım kurallarını hatırlat.
5. **Kural tabanlı ve deterministik.** Her bulgu: kaynak (dosya yolu / manual bölümü), güven (KANIT / ÇIKARIM),
   durum (BLOCKER / RİSK / BİLGİ / VERİ YOK), aksiyon + sorumlu. Emin olmadığın şey ÇIKARIM; uydurma kural yok.
6. **LLM / yapay zeka katmanı yok** (araç offline). Kullanıcı istedi ama karar: önce kurallar; LLM modu ancak
   kullanıcı + şirket (IT/Siemens) onayı ile, varsayılan kapalı, maskeli girdi. Kendi başına ekleme.
7. **Çökme yok:** her bölüm yalıtılmış (`analyze._stage`, inventory `stage`, `cli.run` içinde `out(...)`); hata =
   uyarı + log. Yeni okuma hatası `_unk()` / UnknownRecorder.
8. **Windows:** pathlib, latin1 DBF/cfg, uzun path (`source.long_path`), CRLF `.bat`. tkinter bu bulut makinesinde
   yok; GUI değişikliğini `tests/test_static_names.py` + dikkatli okuma ile doğrula.
9. **Sadece yeşil commit.** Push'tan önce tam test + demo QA. Push sonrası Windows CI'ı kontrol et
   (`gh api "repos/keremzengnn/keremzengnn/actions/runs?branch=<branch>&per_page=1"`). Kırmızı CI = önce onu düzelt.
10. Commit mesajları Türkçe, ne + neden. Model adı / müşteri adı yazma.

---

## 5. Çalışma şekli: çoklu agent + model yönlendirme

Kullanıcı hız istiyor ve **paralel agent** kullanılmasını açıkça istedi. Maliyet ilkeleri (kullanıcının tablosu):

| İş tipi | Model | Bağlam |
|---|---|---|
| Basit soru, komut yardımı, grep, tek satır düzeltme, README/CSV, tekrarlı küçük işler | **Haiku** (`pcs7-quick`) | minimal |
| Genel geliştirme, parser, check, rapor, test, doküman | **Sonnet** (`pcs7-developer`, `pcs7-reviewer`, `pcs7-rules-extractor`) | ilgili dosyalar |
| Büyük refactor / mimari analiz | Sonnet ile başla; gerekirse **Opus** (`pcs7-architect`) | odaklı dosyalar |
| Zor debug (gerçek backup'ta anlaşılmaz sonuç, format çözme) | Sonnet; kök neden zorsa Opus | odaklı log/hata; her faz sonrası `/compact` |

Agent tanımları: `.claude/agents/*.md` (model frontmatter'da). Claude Code modeli **kendiliğinden** göreve göre seçmez;
yönlendirme senin işin: her Agent çağrısında işe uygun agent'ı seç, gerekirse Agent aracının `model` parametresiyle
(haiku / sonnet / opus) üzerine yaz (öncelik: çağrıdaki model > frontmatter > `CLAUDE_CODE_SUBAGENT_MODEL` > ana model).
Ana oturum tipik olarak `opusplan` (plan modunda Opus, uygulamada Sonnet) veya `sonnet`. Ortamda genel web erişimi yok
(şirket API'si): web araçlarını deneme; bilgi için yerel doküman arşivi (`kb search`) ve kullanıcıdan doküman iste.
Her faz sonunda `/compact`, alakasız işe geçerken `/clear`. Ana oturum (sen) **koordinatördür**: işi böler, agent'ları
paralel başlatır, sonuçları birleştirir, test eder, commit eder.

**Paralel çalışmada öğrenilen dersler (önemli):**
- Her agent'a **dosya sahipliği** ver: "sadece şu dosyaları düzenle, şunlara dokunma". Aynı dosyayı iki agent'a verme.
  Kaçınılmazsa (ör. `inventory.py`) fonksiyon bazında böl ve "sadece küçük Edit, her seferinde yeniden oku, dosyayı
  baştan yazma" de.
- Sabit sözleşme ver (sayfa adları, fonksiyon imzaları, alan adları) ki agent'lar birbirini beklemeden çalışsın.
- Agent'lar commit etmez; koordinatör yeşil olduğunda commit eder. Ara durumda testler kırıksa commit etme.
- Her agent kendi scratch alt klasörünü kullansın (ortak scratch'te çıktılar birbirinin üstüne yazıldı).
- Agent raporundaki "şu dosya bana ait değildi, şu düzeltme lazım" maddelerini **mutlaka** takip et (son debug
  turunda Word'ü açılmaz yapan kontrol karakteri böyle bulundu).
- Bitişte: tam test + `--demo` QA + stress (bozuk/uç durum backup varyantları) + CI.

---

## 5b. Siemens Claude Code ortamı (kullanıcının kurumsal kurulumu — uy)

Kullanıcı Claude Code'u Siemens'in **managed setup** script'i ve **SDC LLM Gateway** (`llm.sdc.siemens.cloud`) ile kullanıyor.
Kurumsal kurallar (Siemens iç dokümanı "Set up Claude Code", kullanıcının aktardığı haliyle):
- **Input sınıfı:** Claude Code'a sadece **ACP2 veya altı** sınıflandırılmış veri girilebilir. Müşteri backup'ı, müşteri
  raporu, teklif, Siemens dokümanı vermeden önce kullanıcıya sınıflandırmayı sor; emin değilse maskeli tanı dosyası /
  yapı özeti iste. Gerçek backup'ı zaten okumuyoruz (bölüm 4.3).
- **Human review zorunlu:** her değişikliği kullanıcı inceler. Commit/push'tan önce kısa değişiklik özeti ver; büyük
  değişiklikte onay iste.
- **Mandatory ayarlar** (`~/.claude/settings.json`, script yönetir — DEĞİŞTİRME, önerme): gateway URL, telemetri,
  `permissions.deny: WebFetch, WebSearch` (web yok), **GenAI-CodeScan PreToolUse hook** (her Write/Edit taranır; hook
  çalışmazsa değişiklik bloklanır — bu normal, devre dışı bırakma), minimum sürüm.
- **Model:** şirket model sabitlemez; `/model` gateway'in sunduklarını listeler (ör. `claude-opus-5-5`, `claude-sonnet-5`,
  `claude-haiku-5-5`). `ANTHROPIC_DEFAULT_*_MODEL` / `ANTHROPIC_MODEL`'i settings.json'a yazma (script siler, gateway
  bilinmeyen ID'yi reddeder). Agent frontmatter'daki `opus/sonnet/haiku` alias'ları gateway'de çalışmazsa (hata / "model
  not found") `.claude/agents/*.md` içindeki `model:` değerlerini `/model` listesindeki tam ID'lerle değiştir; `opusplan`
  çalışmazsa ana oturumu `/model` ile Sonnet'e al, zor işte Opus'a geç.
- Önerilen kullanım tablosu (Siemens): basit soru/tekrarlı küçük iş = Haiku; genel geliştirme / doküman = Sonnet; büyük
  refactor / mimari = Sonnet ile başla, gerekirse Opus; zor debug = Sonnet, kök neden zorsa Opus, her fazdan sonra
  `/compact`. Opus varsayılan değil. Yeni iş = `/clear`. Dosyaları hedefli göster, repoyu toptan okutma.
- Kullanıcının kendi `permissions.allow` kuralları korunur (onay yorgunluğunu azaltmak için önerilebilir).
- **Repo konumu:** proje şu an public GitHub'da. Siemens iş kodu için code.siemens.com (iç GitLab) daha uygun olabilir;
  bu kurumsal bir karar — kullanıcıya bir kez hatırlat, kendi başına taşıma.

## 6. Gerçek projelerden öğrenilenler (maskeli tanı dosyalarıyla, 3 tur)

Hepsi CLAUDE.md'de ayrıntılı. Özet:
- SUBBLKTYP ana kodları 08/10/12/13/14/15 (FB=14, FC=12); 04/05 plaintext interface; PASSWORD=3 know-how; MC5LEN kod
  boyutu (FC 64 KB riski); tanınmayan alt kayıtlar 29/30/39/69 → unknown.log (anlamı bilinmiyor, sayılmıyor).
- Block klasörü ↔ AS: `blockmap.py` ID zinciri gerçek projede çoğunlukla çalıştı (bir projede 15/15). "program 2"
  gibi CPU'suz S7 programlar sık görüldü (ÇIKARIM).
- WinCC `.mcp`: `Vxx.00.00.00` format dizisi olabilir, **build değil** → PCS 7 ailesi için kullanılmaz; versiyon APL
  author'undan (`AdvLib91` = APL V9.1) gelir.
- Yanlış pozitifler (testle korunuyor): F_TRIG ≠ F-System, ELEM_400 sürüm değil, AdvLibIL = Industry Library,
  TCON/TSEND/PUT… standart, `@@*.pdl` sistem, arşivi olan OS = server.
- Backup'lar büyük (66k dosya, iç zip'ler); analiz birkaç dakika; çökme yok.
- **Teyit bekleyenler:** DBT dBASE III/IV (kod ikisini de okuyor), XUTILS CT OPTYPE anlamları (66=call?, 80=DB?),
  XUTILS ↔ block klasörü eşleme, hOmSave7 DBF rack/slot/adres, WinCC diagnose formatı, `.mdf` şeması.

---

## 7. Hedef versiyon — İLK İŞ: teyit et

Program **PCS 7 V10.0 SP2'ye sabit** (`cli.TARGET`, `data/released_modules_V10.0SP2.csv`,
`data/block_changes_V10.0SP2.csv`, checks'teki manual referansları "[1] = Software Update V10.0 SP2 manual").
Kullanıcı "en son sürüm PCS 7" diyor. **Kullanıcıya veya doküman arşivine bakarak en güncel sürümü teyit et**
(V10.0 SP2'den yeni bir SP/Update/versiyon varsa). Yeni sürüm varsa:
- hedefi veri odaklı yap (`data/target_<ver>.json`: hedef adı, released list dosyası, block changes dosyası,
  manual referans kodları) ve `cli.TARGET`'i ondan oku; eski V10.0 SP2 verisi kalsın;
- yeni sürümün Software Update manual'ı, Released Modules listesi, APL/Basis readme'lerinden kuralları güncelle;
- `staged_path_from` ara versiyon yolunu güncelle.

---

## 8. Doküman ihtiyacı ve bilgi tabanı süreci

Kullanıcının ~2,7 GB Siemens doküman zip'i var. Akış (araçta hazır):
1. Pencerede "Siemens doküman arşivi (KB) oluştur" → zip seç (`kb build --root <zip>`; zip akışla, poppler yoksa
   yerleşik PDF okuyucu, devam ettirilebilir, `kb_rapor.txt`). Analizler bundan sonra bulgulara doküman+sayfa referansı
   ekler (`settings.find_kb`, `kb.refs_for_findings`).
2. "Doküman özeti çıkar" (`kb digest`) → `kb_ozet_NN.md` (≤4 MB parçalar) + `kb_ozet_index.csv`.
3. Kullanıcı bu dosyaları sana verir → `pcs7-rules-extractor` agent'ları parça başına paralel çalışır → kural listesi →
   onayladığın kurallar `checks.py` + `ACTIONS` + `roadmap.py` + test. Her kural kaynaklı.
4. `kb_ozet_index.csv`'de az sayfa alınmış kritik dokümanlar varsa, kullanıcıdan o PDF'leri tek tek iste.

**Kullanıcıdan istenecek öncelikli dokümanlar** (en güncel hedef sürüm için; yoksa V10.0 SP2):
1. PCS 7 **Software Update** manual'ı (with / without utilization of new functions) — ana kural kaynağı [1].
2. **Released Modules / PCS 7 Compatibility** listesi (hardware + firmware).
3. **APL** ve **Basis Library** readme'leri (interface değişen block'lar, TCiR, mixed operation).
4. PCS 7 **Readme / Release Notes** (OS, SQL Server, Windows sürümleri, kurulum kısıtları) — ara sürümler dahil
   (V8.2, V9.0, V9.1).
5. **WinCC** readme / migration (picture object update, OS project migration, PH/CAS, arşiv).
6. **SFC, Logic Matrix, S7 F Systems / Safety Matrix** upgrade notları; **CFC** readme.
7. **Industry Library**, **PCS 7 Library V7.1** uyumluluk notları; **PDM** ve **OPC/OpenPCS 7** notları.
8. **Licensing** (license upgrade paketleri, PO sayımı) ve **H-System / CPU 410-5H** dokümanları (TCiR, firmware).
9. Siemens içi **upgrade prosedürü / checklist** varsa (ekip tecrübesi).
Format: önce `kb_ozet` parçaları; kritik eksik olursa PDF. Doküman gelmeden bir kuralı "bilgi" diye yazma.

---

## 9. Örnek teklifler (kullanıcı sonra yükleyecek)

Amaç: analiz sonuçlarından teklife girdi üretmek (iş kalemleri, efor sürücüleri), **fiyat / süre uydurmadan**.
Teklif gelince:
1. Önce maskele ve sadece yapıyı çıkar (`docx_style.py` / `learn.py` mantığı: bölüm ağacı, kalem tipleri, tablo
   sütunları); müşteri adı, fiyat, kişi bilgisi repoya girmez.
2. Teklif kalemlerini analiz verisine eşle (AS sayısı, custom block sayısı, OS/client sayısı, F-System, SFC, Logic
   Matrix, HW değişimi, lisans, FAT/SAT…) → `readiness.quote_inputs` ve `roadmap` P0'ı genişlet; çıktı "Teklif girdileri"
   tablosu + kalem önerileri (miktar = backup'tan sayılan değer, süre/fiyat boş).
3. Ekip tecrübesi katsayıları (adam-gün) gerekiyorsa kullanıcıdan tablo iste; ekip ayar dosyasına koy (repoya değil).

---

## 10. Backlog (öncelik sırası)

1. **Hedef sürüm teyidi** ve veri odaklı hedef (bölüm 7).
2. **KB özetlerinden kural çıkarımı** (bölüm 8) — en büyük değer.
3. Kullanıcının ilk gerçek exe çalıştırmasından gelen geri bildirim: kompakt envanter / index.html / yol haritası
   gerçek projede anlaşılır mı; tanı dosyalarına göre düzeltmeler.
4. Teyit bekleyen formatlar (bölüm 6): XUTILS OPTYPE, hOmSave7 rack/slot/adres, DBT tipi — `yapi_tanisi.txt`'ye gerekli
   prob'ları ekle, kullanıcıdan iste.
5. COVERAGE'daki YAPILAMADI maddeleri: haberleşme DB parametreleri (R_ID, IP, port) / NetPro, OS area ↔ User Admin,
   kullanılmayan semboller, evtx okuma, `--mask` (müşteri profili maskeleme).
6. Teklif modülü (bölüm 9).
7. Git geçmişindeki eski proje adlarının temizliği (kullanıcı onayıyla).

---

## 11. Oturum açılışında yapılacaklar (ilk 15 dakika)

1. `git fetch && git status && git log --oneline -5`; doğru branch'te misin (`claude/pcs7-parser-cli-setup-xc22u5`).
2. `pip install -e .[test] && python -m pytest -q` → yeşil mi; `python -m pcs7_analyzer --demo <scratch>` → QA 0 HATA.
3. Son Windows CI durumunu kontrol et.
4. Kullanıcıya 5 satırlık durum + şu 3 soruyu sor (tek mesaj):
   - Hedef sürüm hâlâ V10.0 SP2 mi, daha yeni bir sürüm/SP mi? (doküman arşivinde varsa oradan teyit edeceğini söyle)
   - Exe'yi gerçek backup'ta denedin mi; `index.html` / envanter / yol haritası nasıl? (tanı dosyalarını iste)
   - Doküman arşivi ve `kb digest` çıktısı hazır mı?
5. Cevaba göre backlog'dan paralel agent planı çıkar ve başla.

Başarı ölçütü: kullanıcı backup'ı verip tek tıkla, SIMATIC Manager açmadan, "proje ne durumda, en güncel PCS 7'ye
geçişte ne engel/risk var, ne yapmalıyım, müşteriden ne istemeliyim" sorularının **kaynaklı** cevabını alıyor.
