# ROADMAP v1.0 — prototipten ürüne

Durum: onaylandı (2026-11-16). Kurallar `docs/HANDOFF.md` ile aynı: müşteri / fiyat verisi repoya girmez, gerçek backup
okunmaz, human review, her faz sonunda özet → test + demo QA + sızıntı taraması → commit + push → Windows CI.

## Kararlar
- Fiyat, maliyet, kur, marj hiçbir yerde işlenmez.
- Doğrulanmamış bilgi kullanıcı çıktısında ana tabloya girmez; çıktının sonunda tek "Teyit edilecek noktalar" listesinde,
  aksiyon cümlesi olarak durur. Dahili güven modeli (`Confidence`) ve geliştirici tanı dosyaları kalır.
- Halef (successor) ürün kaynağı yok: uyumsuz donanım için "halef belirlenemedi" yazılır, tahmin yapılmaz.
- Teklif Excel'i doldurma (FAZ 2) arka plan işidir; kod ayrıca onay alır. Öncelik FAZ 0 → 1 → 3.
- FAT/SAT/eğitim kalemi eklenmez.
- Kod barındırma şimdilik değişmez.

## FAZ 0 — Girdiler ve güvenlik
- `.gitignore`: fiyat / teklif / katalog / müşteri raporu desenleri (`*katalog*`, `*catalog*`, `*fiyat*`, `*price*`,
  `*.xlsm`, `work/`, rapor klasörleri). Kaynak dosya adlarında `catalog` / `price` / `fiyat` geçmez (desenle çakışır).
- `tests/test_private_guard.py`: izlenen dosyalarda yasak ad, klasör, uzantı ve beklenmeyen ofis / PDF dosyası taraması.
- Fiyat ve müşteri içeren dosyalar yalnız yerelde kalır; sohbette toplu dökülmez, yalnız yapı (sayfa, sütun, kalem tipi) çıkarılır.

## FAZ 1 — "Belirsizlik dili yok" (tüm program)
İlke: etiketi silmek değil, güvene göre filtrelemek.
- 1A: bulgu modelinde doğrulanmış / teyit ayrımı; envanter, Word, HTML / MD, Excel, `index.html`, yol haritası, pencere özeti
  aynı kuralı kullanır; Excel'de ayrı `Teyit_Edilecekler` sayfası; `qa.py` yasak kalıp kontrolü (teyit bölümü hariç).
- 1B: gerçek okumayla belirsizliği azaltma (hOmSave7 DBF'lerinden station / rack / slot / MLFB / FW, blockmap çapraz
  doğrulama, OS rolü için çoklu gösterge, WinCC build). Alan anlamı bilinmiyorsa maskeli prob eklenir ve kullanıcıdan istenir;
  tahminle anlam atanmaz.

## FAZ 2 — Teklif Excel'i doldurma (arka plan)
Backup analizinden teklif Excel şablonunun girdi hücrelerini (kalem, MLFB, adet, açıklama, mühendislik satırı, kapsam metni)
olabildiğince doldurmak. Şablon yolu ve katsayılar ekip ayar dosyasından gelir, repoda değildir. Fiyat / maliyet hücrelerine
ve formüllere dokunulmaz. Önce tasarım notu ve analiz verisini teklif girdilerine çeviren ara model; örnek teklifler üzerinde
kapsama ölçümü (yalnız kalem tipi ve yüzde, fiyatsız).

## FAZ 3 — Ürünleşme
Sürümleme (SemVer, `CHANGELOG.md`, çıktılarda ve pencere başlığında sürüm, tag ile CI release) · kullanım kılavuzu ·
"Sorun bildir" (maskeli tanı dosyaları tek zip, göndermeden önce içerik gösterilir) · yerel `release-check` regresyonu ·
veri kalitesi satırı (kesin okunan HW oranı, AS'e eşlenen block klasörü oranı, teyit madde sayısı) · performans
(60k+ dosya / 5 GB: ölçüm, çift okumayı giderme, kalan süre) · kullanıcıya traceback yok.

## FAZ 4 — Öneriler (kullanıcı seçer, kod yazılmaz)
Çıktılara sınıflandırma etiketi · revizyon takibi · çoklu kullanıcı çalışma düzeni · `report_ir` şema uyumluluğu · kurumsal
araç / güvenlik incelemesi · exe imzalama · kural kaynak kaydı (doküman, bölüm, inceleme tarihi) · hedef sürümün veri odaklı
yapılması · müşteri verisi saklama / silme politikası · gerçek veriyle doğruluk karnesi.
