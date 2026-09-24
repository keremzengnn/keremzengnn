# data/

`released_modules_<versiyon>.csv` — Released Modules List Manual'dan çıkarılan tablo.

| kolon | açıklama |
|---|---|
| mlfb | Sipariş no (boşluklu/boşluksuz fark etmez, eşleştirmede normalize edilir) |
| fw | Listedeki firmware (boş = belirtilmemiş) |
| status | released / discontinued <tarih> vb. (discontinued olan hâlâ destekli olabilir) |
| note | serbest not |

Kurallar:
- Listede olmayan MLFB → **"bulunamadı, teyit edilmeli"**. Asla "uyumlu" denmez.
- Aksesuarlar (ör. H-Sync module 6ES7 960-1AA06) listede yok; yanlışlıkla eklenmemeli.
- CSV manual'dan çıkarıldıktan sonra **elle kontrol edilmeli** (satır sayısı, kaçan tablo sayfaları).

`block_changes_<versiyon>.csv` — APL / Basis Library Readme'lerindeki "List of changed blocks" tabloları
(`tools/extract_block_changes.py` ile üretilir). Kolonlar: library, section, name, kind, number, version,
interface_change (yes/no/new), sfc_contact, code_change.

`*.dotx` — Word template buraya konabilir (repoya eklenmez).
