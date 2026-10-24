# Rapor düzenlemesinden öğrenme (R7 "learn", `pcs7_analyzer/learn.py`)

Amaç: aracın **ürettiği** `rapor.docx` ile kullanıcının **elle düzenlediği** hali arasındaki farkı, müşteri içeriğini
göstermeden, yapısal olarak çıkarmak ve rapor üreticisi için öneri listesi hazırlamak.

```
python -m pcs7_analyzer.learn --generated rapor.docx --edited rapor_duzenlenmis.docx [-o çıktı_klasörü]
```
```python
from pcs7_analyzer.learn import compare, suggestions, write_suggestions
diff = compare(generated_docx, edited_docx)   # dict, schema_version "1"; okunamayan dosya -> ValueError
sug  = suggestions(diff)                      # list[str], Türkçe, deterministik sıra
write_suggestions(diff, out_dir)              # -> out_dir/style_suggestions.json
```
CLI: başarı 0, okunamayan / bozuk dosya 2 (`HATA: …` stderr). `main(argv) -> int` (ileride `cli.py learn` alt komutu).

## Gizlilik
- Gövde paragrafı ve hücre metni çıktıya **girmez**; sadece kelime / paragraf / satır sayıları.
- Başlıklar ve tablo başlık satırı `docx_style.mask_text` ile maskeli (rakam -> `#`, müşteri kısaltması -> `X`; kural
  `docs/spec/docx_style.md`).
- Terim değişimi sadece `data/glossary.json` terimlerinin (`keep_english`, `forbidden_translations` anahtarları) **sayısı**;
  serbest metin yok.
- Dosya adı / path, docProps (author, company) çıktıya yazılmaz.

## Onay
Çıktı **öneridir**: hiçbir config'e, sözlüğe, template'e yazılmaz, otomatik uygulanmaz (`"applied": false`).
JSON'un `_header` alanı ve konsol çıktısının ilk satırı bunu söyler; kullanıcı her öneriyi gözden geçirip onaylar.
**Format JSON** (YAML değil): proje sadece standart kütüphane kullanıyor, YAML yazıcı/okuyucu yok.

## Hizalama (deterministik)
- **Bölümler:** başlık listesi `(seviye, maskeli başlık)` anahtarıyla `difflib.SequenceMatcher` ile hizalanır.
  Başlık seviyesi `docx_style` ile aynı kural (Title 0, heading N, outlineLvl). İlk başlıktan önceki metin
  `(başlık öncesi)` bölümüdür. Eşleşmeyen `replace` bloklarında aynı seviyedeki çiftler sırayla = **yeniden adlandırma**;
  kalanlar kaldırılan / eklenen bölüm.
- **Bölüm metni:** eşleşen her bölüm için tablo dışı kelime ve paragraf sayısı (bir sonraki başlığa kadar). Azalanlar `shortened`.
- **Tablolar:** başlık satırı (maskeli) dizisiyle hizalanır; `equal`/`replace` bloklarında sırayla eşlenir. Eşleşen tablo için
  kaldırılan / eklenen sütun (başlık hücresi çoklu kümesi farkı), satır sayısı, hücre başına ortalama kelime, tablo stili;
  tablo hangi bölümde (`section`). Numara = üretilen belgedeki sıra (1'den).
- **Terimler:** tüm metin (`casefold`, kelime sınırı) içinde glossary terim sayıları. `replaced`: sayısı artan
  `forbidden_translations` anahtarı + karşılığı olan İngilizce terimin değişimi.
- **Vurgu / stil:** `docx_style.extract_style` sayaçlarının farkı (`highlight`, `paragraph_styles`, `direct_formatting`, `stats`).

## Çıktı (`style_suggestions.json`, `sort_keys`)
| Anahtar | İçerik |
|---|---|
| `_header`, `applied` | onay notu, her zaman `false` |
| `suggestions` | Türkçe öneri listesi |
| `diff.sections` | `generated`, `edited` (başlık sayısı), `removed` / `added` (`level, heading, words`), `renamed` (`level, from, to`), `word_changes`, `shortened` (`heading, level, words{generated,edited,delta,pct}, paragraphs{…}`) |
| `diff.tables` | `generated`, `edited`, `matched` (`table, edited_table, section, header, removed_columns, added_columns, n_cols, n_rows, avg_words_per_cell, style, changed`), `removed`, `added` |
| `diff.terms` | `english_terms`, `turkish_terms` (sayı farkı), `replaced`, `english_disappeared`, `turkish_appeared` |
| `diff.highlight`, `styles`, `direct_formatting`, `stats` | `{anahtar: {generated, edited, delta}}`, sadece değişenler |

## Öneri kuralları
| Fark | Öneri |
|---|---|
| kaldırılan bölüm | `'X' bölümünü kaldır (seviye N, k kelime)` |
| eklenen bölüm | `'X' bölümünü ekle (…, kullanıcı eklemiş)` |
| yeniden adlandırma | `'A' başlığını 'B' olarak değiştir` |
| bölüm metni ≥ %20 ve ≥ 5 kelime azaldı | `'X' bölüm metnini kısalt (a -> b kelime, %p)` |
| tablo / sütun kaldırıldı / eklendi | `Tablo N tablosunu kaldır`, `Tablo N 'Aksiyon' sütununu çıkar`, `Tablo N'e 'C' sütununu ekle` |
| satır azaldı / arttı | `Tablo N satır sayısını azalt / filtrele`, `… eksik bilgi var mı kontrol et` |
| hücre ortalaması ≥ %20 azaldı | `Tablo N hücre metnini kısalt` |
| keep_english terimi Türkçeleştirilmiş | sözlük kuralı hatırlatılır; sözlük değiştirilmez, kullanıcıyla teyit |
| vurgu / stil sayısı değişti | `Vurgu (…) kullanımını azalt/artır`, `'S' stil kullanımı değişmiş` |

Test: `tests/test_learn.py` (sentetik docx; gövdeye konan gizli metnin çıktıda olmadığı doğrulanır).
