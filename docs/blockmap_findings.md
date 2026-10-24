# Block klasörü ↔ AS eşlemesi (blockmap) — bulgular

## Sorun
`<Proje>/ombstx/offline/<8 hex>/SUBBLK.DBF` klasör adından hangi S7 program / CPU / station'a ait olduğu görünmez.

## Hipotezler ve durum
| # | Hipotez | Durum |
|---|---|---|
| 1 | Klasör adı = block container nesne ID'si (hex); program → container bağı `hrs/linkhrs.lnk` içinde | **Uygulandı** (sentetik testle); gerçek projede teyit bekliyor |
| 2 | Program → CPU bağı `hOmSave7/<s7hk41ax/s7hk31ax/s7hkcomx>/HRELATI1.DBF` RELID = 16 | **Uygulandı**; teyit bekliyor |
| 3 | CPU → station: aynı HRELATI1, TOBJTYP 1314972 / 1315656 (H yedek CPU), TUNITID = station ID; station adı/tipi `hOmSave7/s7hstatx/HOBJECT1.DBF` (OBJTYP) | **Uygulandı**; teyit bekliyor |
| 4 | Symbol table: `YDBs/YLNKLIST.DBF` TOI = program ID → SOI; `YDBs/SYMLISTS.DBF` _ID → _DBPATH | **Uygulandı**; teyit bekliyor |
| 5 | Yedek sinyaller: proje adı, symbol table FB seti (Jaccard ≥ %50), symbol export dosya adı | Zincir yoksa kullanılıyor (ÇIKARIM) |

Kaynak: açık kaynak STEP 7 V5 proje okuyucusu (DotNetSiemensPLCToolBoxLibrary, `Step7ProjectV5.cs`, LGPL). Sadece dosya /
alan yapısı bilgisi alındı; kod kopyalanmadı.

## Zincir
```
hrs/S7RESOFF.DBF (ID, NAME, RSRVD4_L) --RSRVD4_L ofset--> hrs/linkhrs.lnk (512 byte kayıt)
   kayıtta 01 60 11 00 + int16 LE  = block container ID  -> ombstx/offline/<ID:08X>
hOmSave7/s7hk41ax/HRELATI1.DBF  RELID=16: SOBJID=CPU, TOBJID=program
                                TOBJTYP∈{1314972,1315656}: SOBJID=CPU, TUNITID=station
hOmSave7/s7hk41ax/HOBJECT1.DBF  ID=CPU -> NAME, SUBSTATN, MODULN
hOmSave7/s7hstatx/HOBJECT1.DBF  ID=station -> NAME, OBJTYP (1314969 S7-300, 1314970 S7-400, 1315650 S7-400H, 1315651 RTX)
hOmSave7/s7hstatx/<station ID hex>.s7h  -> station HW
YDBs/YLNKLIST.DBF TOI=program -> SOI ; YDBs/SYMLISTS.DBF _ID=SOI -> _DBPATH -> YDBs/<_DBPATH>/SYMLIST.DBF
```

## Güven
- Zincir tam + (HW export station adı aynı **veya** zincirin verdiği symbol table FB seti uyumu ≥ %50) → **KANIT**
- Zincir tam, çapraz kontrol yok → **ÇIKARIM**
- Zincir kırık → eski heuristic; kırık adım `unknown.log`'a (ör. "linkhrs.lnk yok", "imza yok", "klasör backup'ta yok").

## Doğrulama (kullanıcıdan)
1. Gerçek backup'ı programla çalıştır; çıktı klasöründeki `blockmap_tanisi.txt` (isimler maskeli: sadece ID'ler, dosya
   var/yok, çözüm durumu) paylaşılır.
2. Raporda "S7 program ↔ CPU ↔ station (ID zinciri)" tablosu SIMATIC Manager ağacıyla karşılaştırılır.
3. Tek AS'li projede tüm dolu klasörler o AS'e gitmeli; çok AS'li projede CPU tipi (HW) ile eşleşen station tutarlı olmalı.
4. Uyuşursa güven kuralı (KANIT eşiği) güncellenir; uyuşmazsa hangi adımın farklı olduğu tanı dosyasından görülür.

## Bilinen sınırlamalar
- Silinmiş kayıtlar (DBF deleted flag) okunmaz (dbfread atlar) — doğru davranış.
- S7-300 / ET 200 CPU klasörleri (`s7hk31ax`, `s7hkcomx`) zincire dahil; RTX / PC station dahil değil.
- `linkhrs.lnk` imzası (`01 60 11 00`) STEP 7 sürümüne göre değişebilir: değişirse "imza yok" olarak raporlanır.
