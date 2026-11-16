# Açık işler (tek liste)

Güncelleme: 2026-11-16. Bakım: `pcs7-organizer` agent'ı. Yapılınca satır silinmez, "Kapandı" bölümüne taşınır.
Müşteri verisi, fiyat ve gerçek proje adı bu dosyaya yazılmaz.

## Senden bekleyen
- **FAZ 1B girdisi:** hOmSave7 rack/slot çözümü için gerçek backup'tan maskeli `yapi_tanisi.txt` (zaten üretiliyor, hangi klasörün gönderileceğini seç). Gerçek çıktılarda donanım "kesin" oranı 0 görünüyor; asıl neden bu.
- **FAZ 2 onayı:** teklif Excel'ini doldurma kodu yazılmadan önce açık onay (kapsam: fiyat/maliyet yok, şablon formülleri bozulmaz).
- **FAZ 4 listesi:** öneri maddelerinden seçim (kod yazılmaz).
- **Tag kararı:** `v1.0.0` tag'i (release yayını dış etkili, onayınla atılır).

## Bende bekleyen
- Gerçek rapor çıktılarında bulunan `rapor.md` yasak kalıp sızıntısı ("teyit edilmeli") düzeltmesi (devam ediyor).
- Düzeltme sonrası: test, commit, push, CI, exe'yi `PCS7Analyzer_exe` klasörüne kopyalama.
- Gerçek çıktılarda "kesin block klasörü eşleşmesi" oranı düşük (çok klasör "teyit"te): blockmap zincirinin gerçek veriyle neden KANIT'a ulaşamadığı incelenecek (1B ile birlikte).
- Sızıntı taraması gerçek rapor klasörlerinde de yapılmalı (yalnız sentetik demoda yapılmıştı).

## Riskli / bilinen sınır
- Destek paketi maskelemesi yalnız mutlak yolları kapsar; serbest metin (proje/station adı) maskelenmez, kullanıcıya yazılı uyarı var.
- "3 hane = V10.0" author sürüm çıkarımı gerçek veriyle teyitsiz.
- code.siemens.com taşıması şimdilik yok (FAZ 4 listesinde).

## Kapsam dışı kararlar (değişmez)
Fiyat/maliyet/kur/marj işlenmez · halef tahmini yok ("halef belirlenemedi") · FAT/SAT/eğitim kalemi yok · Kalkulasyon xlsm kapsam dışı.

## Kapandı
- FAZ 0 (gitignore + guard testi) · FAZ 1A (belirsizlik dili) · FAZ 3 (v1.0.0, destek paketi, release-check, veri kalitesi).
