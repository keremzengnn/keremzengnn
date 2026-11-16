# Kullanım kılavuzu

## 1. Kurulum
- **Exe:** GitHub Releases sayfasından `PCS7Analyzer-<sürüm>.exe` dosyasını indirip çift tıklayın (Python gerekmez).
- **Python:** Python 3.11+ kurun, repo klasöründe `Baslat.bat`'a çift tıklayın (ek paket yok).

## 2. Analiz
1. Pencerede **Backup klasörü…** veya **Backup .zip…** ile backup'ı seçin.
2. İlk seferde ad ve departman girin (hatırlanır).
3. **Analiz et**. Bitince `index.html` açılır; tüm çıktılara oradan gidilir.

## 3. Diğer işlemler
- **Sadece envanter:** değerlendirme yapmadan mevcut durumu (versiyon, library, hardware, OS) Excel'e döker.
- **Karşılaştır:** iki backup'ı karşılaştırır (saha ↔ ES, eski ↔ yeni).
- **Paketle:** analiz için gereken dosyaları küçük bir zip'e toplar.

## 4. Teyit edilecek noktalar
Raporda ana tablo yalnızca dosyadan doğrulanan bulguları içerir. Backup'tan kesin sonuç çıkarılamayan konular
raporun sonunda **Teyit edilecek noktalar** başlığı altında toplanır. Bunlar sahada / müşteriyle kontrol edilmelidir.

## 5. Sorun bildir
Pencerede **Sorun bildir** düğmesi veya komut satırında `--support-bundle <çıktı klasörü>` ile destek paketi (zip) oluşturulur.
- **Pakette ne var:** yalnızca çıktı klasöründeki tanı dosyaları: `log.txt`, `unknown.log`, `yapi_tanisi.txt`,
  `blockmap_tanisi.txt`, `qa_report.md`, `envanter_ozet.json` (hangileri varsa) ve `_destek_paketi.txt` (açıklama).
  Rapor dosyaları (docx, xlsx, html, md), `findings.json`, `report_ir.json` ve backup dosyaları pakete girmez.
- **Maskelemenin kapsamı:** yalnızca mutlak dosya yolları maskelenir (son 3 seviye kalır, diğer klasör adları `<klasör>` olur).
  Hata izlerindeki `pcs7_analyzer` kaynak dosya yolları ve satır numaraları hata ayıklama için açık bırakılır.
- **Maskelenmeyen:** log içindeki serbest metin (müşteri, proje, station, OS adı gibi) maskelenmez. Paket
  müşteri adı içermeyeceğini **garanti etmez**.
- **Ne gönderilir:** göndermeden önce zip'i açıp içeriği kontrol edin; müşteri adı veya gizli bilgi görürseniz
  metni silin ya da paketi göndermeyin. Paketi yalnızca kurumun onaylı kanalıyla iletin.

## 6. Uyarı: müşteri verisi
Müşteri backup'ı, rapor çıktıları ve destek paketleri müşteri verisi içerebilir. Bunları **repoya commit etmeyin,
e-postayla göndermeyin**; yalnızca kurumun onaylı kanallarıyla paylaşın.
