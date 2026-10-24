"""
SUBBLK.DBF  (ombstx/offline/<id>/SUBBLK.DBF + SUBBLK.DBT) parser'ı.

Gerçek bir PCS 7 V8.1 projesiyle (6 adet S7-400H) test edilmiş referans implementasyondan taşındı.
"""
from __future__ import annotations

import collections
import os
from dataclasses import dataclass, field
from pathlib import Path

from .._vendor import dbfread
from .._vendor.dbfread.field_parser import FieldParser

# SUBBLKTYP kodları (doğrulananlar)
SUBBLK_FB = "00004"
SUBBLK_FC = "00005"
SUBBLK_OB = "00008"
SUBBLK_DB = "00010"
SUBBLK_SFB = "00015"
SUBBLK_SFC = "00013"

# Ana (MC7 / header) kayıtları: S7 block tipi kodu (0x08 OB, 0x0A DB, 0x0C FC, 0x0D SFC, 0x0E FB, 0x0F SFB).
# 00004 / 00005 = FB / FC'nin plaintext interface kaydı (sadece offline oluşturulmuş block'larda var; PLC'den yüklenen,
# bazı korumalı block'larda yok). Sayım iki kaydın birleşimiyle yapılır. Kaynak: gerçek proje kayıt sayıları +
# açık kaynak STEP 7 V5 okuyucusu (DotNetSiemensPLCToolBoxLibrary, BlocksOfflineFolder.cs).
SUBBLK_FB_MAIN = "00014"
SUBBLK_FC_MAIN = "00012"
MAIN_KIND = {SUBBLK_FB_MAIN: "FB", SUBBLK_FC_MAIN: "FC", SUBBLK_OB: "OB", SUBBLK_DB: "DB", SUBBLK_SFC: "SFC",
             SUBBLK_SFB: "SFB"}
# Bilinen alt kayıtlar (sayılmaz, Unknown'a da yazılmaz): plaintext interface / yorum / DB yapısı / VAT
KNOWN_SUBRECORDS = {"00001", "00003", "00006", "00007", "00009", "00017", "00018", "00019", "00020", "00021", "00022",
                    "00027", "00038", "00066",
                    # Gerçek projede block sayılarıyla birebir örtüşen ek alt kayıtlar (anlamı bilinmiyor, sayılmaz):
                    # 24/67 OB, 25/64 FB, 26/65 FC, 70 SFC, 71 SFB
                    "00024", "00025", "00026", "00064", "00065", "00067", "00070", "00071"}
KNOW_HOW_PASSWORD = 3        # ana kayıtta PASSWORD = 3 -> know-how protection (açık kaynak okuyucu; ÇIKARIM)

# SSBPART'tan okunan FB numarası bunun üstündeyse geçersiz kabul edilir.
MAX_VALID_FB_NUMBER = 8191

# DBF/DBT byte'larını 1:1 str'ye çevirir. dbfread language driver 0x00'da 'ascii' seçer;
# char_decode_errors='ignore' ile birlikte bu, SSBPART memo'sundaki >= 0x80 byte'ları
# sessizce siler ve FB numaralarını bozar (ör. FB1990 = C6 07 -> 07 ..).
DBF_ENCODING = "latin1"

# Block header USERNAME (author) -> library eşlemesi
AUTHOR_LIBRARY = {
    "AdvLib": "APL",            # AdvLib81 = APL V8.1, AdvLib82 = APL V8.2 ...
    "AdvLibLM": "Logic Matrix",
    "AdvLibIL": "PCS 7 Industry Library",   # IL_BS, IL_BR … (APL değil)
    "DRIVER": "Basis Library",  # DRIVER81 = Basis Library V8.1
    "ELEMENTA": "CFC ELEMENTA",
    "ELEM_300": "CFC ELEMENTA",
    "ELEM_400": "CFC ELEMENTA",
    "ES_MAP": "CFC generated",  # CFC'nin ürettiği FC/DB'ler
    "ES_SFC": "SFC system",
    "COMM71": "PCS 7 Library V7.1 COMM",
    "F_SAFE": "S7 F Systems Failsafe Blocks",  # F_SAFE13 = V1_3
    "SIMATIC": "SIMATIC system / Standard Library",
    "SIEMENS": "Siemens add-on (ör. Modbus TCP)",
}


def decode_block_version(v: int | None) -> str:
    """VERSION alanı tek byte: high nibble major, low nibble minor. 0x30 -> '3.0'."""
    if not v:
        return "-"
    return f"{v >> 4}.{v & 15}"


# Header'ı boş olsa da isminden tanınan Siemens standart block'ları (S7 Standard Library / Communication Blocks,
# CP PtP library, IEC). Kaynak: block adı (ÇIKARIM) -> custom sayılmaz.
STANDARD_BLOCK_NAMES = {"TCON", "TDISCON", "TSEND", "TRCV", "TUSEND", "TURCV", "TSEND_C", "TRCV_C", "P_SND_RK",
                        "P_RCV_RK", "P_PRINT_RK", "PUT", "GET", "BSEND", "BRCV", "USEND", "URCV", "AG_SEND",
                        "AG_RECV", "AG_LSEND", "AG_LRECV", "AG_CNTRL", "R_TRIG", "F_TRIG", "TP", "TON", "TOF",
                        "CTU", "CTD", "CTUD", "SFC_RTS"}
STANDARD_LIBRARY = "Siemens Standard Library (isimden)"


def classify_author(author: str, name: str = "") -> str:
    """Author string'inden library adını döndür. En uzun prefix kazanır. Author boşsa standart block adı denenir."""
    a = author.strip()
    if not a:
        if name.strip().upper() in STANDARD_BLOCK_NAMES:
            return STANDARD_LIBRARY
        return "custom/unknown"
    best = ""
    for prefix in AUTHOR_LIBRARY:
        if a.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return AUTHOR_LIBRARY[best] if best else "custom"


# BLKLANG kodu -> dil (S7 block header dil kodları; 4 = SCL, APL/Basis block'ları SCL ile yazılmıştır)
BLOCK_LANGUAGES = {1: "STL", 2: "LAD", 3: "FBD", 4: "SCL", 5: "DB", 6: "GRAPH"}


def lang_name(code: str) -> str:
    """'00001' -> 'STL'; bilinmeyen kod 'kod N' olarak döner, boş kod ''."""
    c = str(code or "").strip()
    if not c.isdigit():
        return c
    n = int(c)
    return BLOCK_LANGUAGES.get(n, f"kod {n}") if n else ""


@dataclass
class BlockHeader:
    kind: str          # FB / FC / ...
    number: int
    family: str
    name: str
    version: str
    author: str
    lang: str          # BLKLANG ham kodu ('00001'); okunur ad: lang_name / .language

    @property
    def language(self) -> str:
        return lang_name(self.lang)

    @property
    def library(self) -> str:
        return classify_author(self.author, self.name)


@dataclass
class BlockFolder:
    path: Path
    n_records: int = 0
    counts: dict = field(default_factory=dict)          # {'FB': 66, 'FC': ..., 'DB': ..., 'OB': ...}
    blocks: list = field(default_factory=list)          # [BlockHeader] (FB + isimli FC)
    db_families: collections.Counter = field(default_factory=collections.Counter)
    instances_per_fb: collections.Counter = field(default_factory=collections.Counter)  # {(kind, nr): count}
    memo_available: bool = False
    # SSBPART'ı instance gibi görünen ama FB numarası çözülemeyen / geçersiz DB sayısı.
    unresolved_instances: int = 0
    bad_records: int = 0          # BLKNUMBER okunamayan kayıt (atlandı)
    protected: set = field(default_factory=set)      # {(kind, nr)} know-how protected (PASSWORD = 3)
    local_data: dict = field(default_factory=dict)   # {(kind, nr): LOCDATALEN} (block'un kendi local data'sı)
    code_len: dict = field(default_factory=dict)     # {(kind, nr): MC5LEN} derlenmiş kod boyutu (byte), ana kayıttan
    other_types: collections.Counter = field(default_factory=collections.Counter)  # bilinen 6 tip dışı SUBBLKTYP
    # Instance çözümleme tanısı: {neden: DB sayısı} + ilk örnekler [(DB no, neden, SSBPART ilk byte'lar hex)].
    # Nedenler: INSTANCE_ISSUE_* sabitleri. Sadece EMPTY / SHORT / RANGE unresolved_instances'a sayılır.
    unresolved_reasons: collections.Counter = field(default_factory=collections.Counter)
    unresolved_examples: list = field(default_factory=list)
    ssb_kind: collections.Counter = field(default_factory=collections.Counter)   # {SSBPART byte0: DB sayısı}
    memo_format: str = ""                 # DBT header'ından: 'db3' / 'db4' ('' = DBT okunmadı)
    memo_block_size: int = 0
    memo_seen: dict = field(default_factory=dict)      # memo bazında tespit: {'db4': n, 'db3': n}
    memo_issues: dict = field(default_factory=dict)    # DBT okuma anomalileri {neden: n}

    @property
    def is_empty(self) -> bool:
        return self.n_records == 0


_KIND = {SUBBLK_FB: "FB", SUBBLK_FC: "FC", SUBBLK_OB: "OB", SUBBLK_DB: "DB"}

# SSBPART byte0 (açık kaynak okuyucu: 0x05 normal / global DB, 0x0A FB instance, 0x0B SFB instance)
SSB_GLOBAL_DB, SSB_FB_INSTANCE, SSB_SFB_INSTANCE = 0x05, 0x0A, 0x0B
INSTANCE_ISSUE_EMPTY = "SSBPART memo referansı var ama DBT'de veri yok (boş memo)"
INSTANCE_ISSUE_SHORT = "SSBPART instance işaretli (byte0 0x0A/0x0B) ama 3 byte'tan kısa"
INSTANCE_ISSUE_RANGE = f"SSBPART FB numarası geçersiz (> {MAX_VALID_FB_NUMBER})"
INSTANCE_ISSUE_KIND = "SSBPART byte0 bilinmiyor (0x05 global / 0x0A FB / 0x0B SFB değil) -> instance sayılmadı"
_COUNTED_ISSUES = (INSTANCE_ISSUE_EMPTY, INSTANCE_ISSUE_SHORT, INSTANCE_ISSUE_RANGE)
MAX_ISSUE_EXAMPLES = 20


def _instance_issue(bf: "BlockFolder", db_nr: int, reason: str, raw: bytes) -> None:
    bf.unresolved_reasons[reason] += 1
    if reason in _COUNTED_ISSUES:
        bf.unresolved_instances += 1
    if len(bf.unresolved_examples) < MAX_ISSUE_EXAMPLES:
        bf.unresolved_examples.append((db_nr, reason, raw[:8].hex(" ")))


def record_instance_issues(bf: "BlockFolder", recorder, path: str, module: str = "blocks") -> int:
    """Instance çözümleme nedenlerini UnknownRecorder'a neden başına bir satır yazar (ilk örnek DB'lerle). Satır sayısı."""
    n = 0
    for reason, cnt in sorted(bf.unresolved_reasons.items()):
        ex = [e for e in bf.unresolved_examples if e[1] == reason][:5]
        raw = "; ".join(f"DB{nr}: {h or '-'}" for nr, _, h in ex)
        recorder.add(module, path, f"{cnt} DB: {reason}", where="SSBPART", raw=raw)
        n += 1
    for reason, cnt in sorted(bf.memo_issues.items()):
        recorder.add(module, path, f"DBT ({bf.memo_format}, block {bf.memo_block_size}): {reason} ×{cnt}", where="DBT")
        n += 1
    return n


def _to_bytes(v) -> bytes:
    return v if isinstance(v, bytes) else v.encode(DBF_ENCODING, "ignore")


# ---------------------------------------------------------------- DBT (memo) okuyucu
# dbfread'in memo okuyucuları SSBPART için güvenilir değil: DB3 okuyucusu ilk 0x1A'da, DB4 okuyucusu ilk 0x1F'de keser
# (FB26 = 0A 1A 00, FB31 = 0A 1F 00 -> instance kaybolur) ve DB4'te block boyutunu 512 varsayar (header'daki değeri
# okumaz). Burada ham byte, akış halinde (dosya belleğe alınmaz) okunur:
#   DBT header (512 byte): 0-3 next free block, 16 sürüm (0x03 = dBASE III, 0x00 = dBASE IV), 20-21 block boyutu (DB4).
#   dBASE IV memo: FF FF + int16 start offset (8) + int32 uzunluk (header dahil) -> uzunluk kadar okunur.
#   dBASE III memo: 512 byte block'lar, 0x1A 0x1A ile biter -> tek 0x1A'da kesilmez.
# Memo bazında imza kontrol edilir (header'dan bağımsız): FF FF imzası varsa DB4, yoksa DB3 taraması.
# Kaynak: açık kaynak STEP 7 V5 okuyucusu (DotNetSiemensPLCToolBoxLibrary, DBF/ParseDBF.cs ReadMemoBlock: DB4 tarzı,
# block boyutu header ofset 20, uzunluk - start; BlocksOfflineFolder.cs: SSBPART SSBLEN'e kısaltılır).
MEMO_SCAN_LIMIT = 16 * 1024 * 1024      # DB3 sonlandırıcı aranırken en fazla okunacak byte
_DB4_SIG = b"\xff\xff"


class RawMemoFile:
    """SUBBLK.DBT ham memo okuyucu (DB3 / DB4). memo[index] -> bytes; index 0 -> None; veri yoksa b''."""

    def __init__(self, filename):
        self.filename = str(filename)
        self.file = open(self.filename, "rb")
        self.size = os.fstat(self.file.fileno()).st_size
        head = self.file.read(512)
        self.header_version = head[16] if len(head) > 16 else None
        bs = int.from_bytes(head[20:22], "little") if len(head) >= 22 else 0
        self.flavor = "db3" if self.header_version == 0x03 else "db4"
        # DB3'te block boyutu sabit 512; DB4'te header'dan (geçersizse 512)
        self.block_size = bs if self.flavor == "db4" and 64 <= bs <= 32768 and bs % 64 == 0 else 512
        self.seen = collections.Counter()      # {'db4': n, 'db3': n} memo bazında tespit edilen biçim
        self.issues = collections.Counter()    # {neden: n} okuma anomalileri

    def __getitem__(self, index):
        if not index or index <= 0:
            return None
        f = self.file
        pos = index * self.block_size
        if pos >= self.size:
            self.issues["memo index DBT dosya sonunun ötesinde"] += 1
            return b""
        f.seek(pos)
        head = f.read(8)
        if head[:2] == _DB4_SIG and len(head) == 8:
            self.seen["db4"] += 1
            start = int.from_bytes(head[2:4], "little")
            length = int.from_bytes(head[4:8], "little")
            if not 8 <= start < self.block_size:     # bazı yazıcılar FF FF 08 08 yazar -> standart 8
                start = 8
            n = length - start
            if n <= 0:
                return b""
            if pos + start + n > self.size:
                self.issues["DB4 memo uzunluğu dosya sonunu aşıyor (kısaltıldı)"] += 1
                n = self.size - pos - start
            f.seek(pos + start)
            return f.read(n)
        self.seen["db3"] += 1
        f.seek(pos)
        data = bytearray()
        bsz = self.block_size
        while len(data) < MEMO_SCAN_LIMIT:
            chunk = f.read(bsz)
            if not chunk:
                self.issues["DB3 memo sonlandırıcısı (1A 1A) yok, dosya sonu"] += 1
                return bytes(data)
            scan_from = max(0, len(data) - 1)
            data += chunk
            end = data.find(b"\x1a\x1a", scan_from)
            if end != -1:
                return bytes(data[:end])
            # Tek 0x1A'lı DB3 varyantında tarama sonraki memo'nun 1A 1A'sına kadar sürer: fazla byte gelir, baştaki
            # byte'lar (SSBPART byte0-2) doğru kalır; SSBLEN alanı varsa memo ona kısaltılır.
        self.issues["DB3 memo sonlandırıcısı tarama sınırında bulunamadı"] += 1
        return bytes(data)

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _SubblkDBF(dbfread.DBF):
    """dbfread.DBF, memo dosyası olarak RawMemoFile kullanır (dbfread'in DB3/DB4 okuyucuları yerine)."""

    raw_memo: RawMemoFile | None = None

    def _open_memofile(self):
        if self.memofilename and not self.raw:
            self.raw_memo = RawMemoFile(self.memofilename)
            return self.raw_memo
        return super()._open_memofile()


class _SubblkFieldParser(FieldParser):
    """
    Sadece SSBPART memo'sunu okur ve HAM byte döndürür (decode yok -> encoding'den bağımsız).
    MC5CODE / ADDINFO (block kodu, DBT'nin büyük kısmı) hiç okunmaz: 400+ MB DBT'de ciddi hız farkı.
    Dönüş: None = memo referansı yok; b'' = referans var ama DBT'de veri yok.
    """

    def parseM(self, field, data):
        if field.name != "SSBPART":
            return None
        memo = self.get_memo(self._parse_memo_index(data))
        return bytes(memo) if memo is not None else None


def dbf_record_count(dbf_path: Path) -> int:
    with open(dbf_path, "rb") as f:
        head = f.read(8)
    return int.from_bytes(head[4:8], "little") if len(head) == 8 else 0


_CACHE: dict = {}


def clear_cache() -> None:
    """Çalışma sonunda çağrılır (analiz + envanter aynı SUBBLK'yı iki kez okumasın diye önbellek)."""
    _CACHE.clear()


def parse_subblk(dbf_path: Path, with_instances: bool = True, progress=None) -> BlockFolder:
    dbf_path = Path(dbf_path)
    try:
        stt = dbf_path.stat()
        key = (str(dbf_path), stt.st_size, stt.st_mtime, with_instances)
    except OSError:
        key = None
    if key in _CACHE:
        return _CACHE[key]
    bf = _parse_subblk(dbf_path, with_instances, progress)
    if key is not None:
        _CACHE[key] = bf
    return bf


def _parse_subblk(dbf_path: Path, with_instances: bool = True, progress=None) -> BlockFolder:
    """
    SUBBLK.DBF okur.
    - Boş block klasöründe DBF 834 byte'tır (sadece header) -> n_records = 0.
    - Instance -> FB eşlemesi için DBT (memo) gerekir: DB kaydının SSBPART memo'sunun
      ilk byte'ı 0x0A (FB instance) / 0x0B (SFB instance), sonraki 2 byte little-endian
      FB numarası. DBT yoksa with_instances=False kullanılır.
    """
    dbf_path = Path(dbf_path)
    dbt = dbf_path.with_suffix(".DBT")
    memo = dbt.exists() and with_instances
    table = _SubblkDBF(
        str(dbf_path),
        encoding=DBF_ENCODING,
        ignore_missing_memofile=not memo,
        char_decode_errors="ignore",
        parserclass=_SubblkFieldParser,
    )
    total = dbf_record_count(dbf_path)
    bf = BlockFolder(path=dbf_path.parent, memo_available=memo)
    present = set()
    headers: dict[tuple, dict] = {}
    main_headers: dict[tuple, dict] = {}
    for rec in table:
        bf.n_records += 1
        if progress and bf.n_records % 20000 == 0:
            progress(bf.n_records, total)
        ty = rec["SUBBLKTYP"]
        try:
            nr = int(rec["BLKNUMBER"])
        except (TypeError, ValueError):      # bozuk / boş kayıt: atla, klasörün geri kalanı okunur
            bf.bad_records += 1
            continue
        if ty in _KIND:
            present.add((ty, nr))
        if ty in MAIN_KIND:
            kind = MAIN_KIND[ty]
            if ty not in _KIND:
                present.add(({"FB": SUBBLK_FB, "FC": SUBBLK_FC}.get(kind, ty), nr))
            if _int0(rec.get("PASSWORD")) == KNOW_HOW_PASSWORD:
                bf.protected.add((kind, nr))
            ld = _int0(rec.get("LOCDATALEN"))
            if ld:
                bf.local_data[(kind, nr)] = ld
            cl = _int0(rec.get("MC5LEN"))
            if cl and kind in ("FC", "FB", "OB"):
                bf.code_len[(kind, nr)] = cl
            if kind in ("FB", "FC"):
                main_headers.setdefault((kind, nr), rec)
        elif ty not in _KIND and str(ty).strip() not in KNOWN_SUBRECORDS:
            bf.other_types[str(ty).strip() or "(boş)"] += 1
        if ty in (SUBBLK_FB, SUBBLK_FC):
            key = (ty, nr)
            if rec["BLOCKNAME"].strip() or key not in headers:
                headers[key] = rec
        if ty == SUBBLK_DB:
            bf.db_families[rec["BLOCKFNAME"].strip()] += 1
            if memo:
                _resolve_instance(bf, nr, rec)
    if table.raw_memo is not None:
        rm = table.raw_memo
        bf.memo_format, bf.memo_block_size = rm.flavor, rm.block_size
        bf.memo_seen, bf.memo_issues = dict(rm.seen), dict(rm.issues)
    c = collections.Counter(_KIND.get(t) or MAIN_KIND[t] for t, _ in present)
    bf.counts = dict(c)
    # Interface kaydı olmayan FB/FC'ler: başlık ana kayıttan
    for (kind, nr), rec in main_headers.items():
        key = (SUBBLK_FB if kind == "FB" else SUBBLK_FC, nr)
        if key not in headers or (not headers[key]["BLOCKNAME"].strip() and str(rec.get("BLOCKNAME") or "").strip()):
            headers[key] = rec
    for (ty, nr), rec in sorted(headers.items()):
        name = rec["BLOCKNAME"].strip()
        if ty == SUBBLK_FC and not name:
            continue  # CFC'nin ürettiği isimsiz FC'ler
        bf.blocks.append(
            BlockHeader(
                kind=_KIND[ty], number=nr,
                family=rec["BLOCKFNAME"].strip(), name=name,
                version=decode_block_version(rec["VERSION"]),
                author=rec["USERNAME"].strip(), lang=str(rec["BLKLANG"]),
            )
        )
    return bf


def _resolve_instance(bf: BlockFolder, nr: int, rec) -> None:
    """DB kaydının SSBPART'ından instance -> FB eşlemesi; çözülemeyenin nedeni kaydedilir."""
    ssb = rec.get("SSBPART")
    if ssb is None:              # memo referansı yok (SSBPART'sız DB): instance değil, sorun değil
        return
    b = _to_bytes(ssb)
    ssblen = _int0(rec.get("SSBLEN"))
    if ssblen and len(b) > ssblen:   # açık kaynak okuyucu gibi: memo SSBLEN'e kısaltılır
        b = b[:ssblen]
    if not b:
        _instance_issue(bf, nr, INSTANCE_ISSUE_EMPTY, b)
        return
    bf.ssb_kind[b[0]] += 1
    if b[0] in (SSB_FB_INSTANCE, SSB_SFB_INSTANCE):
        if len(b) < 3:
            _instance_issue(bf, nr, INSTANCE_ISSUE_SHORT, b)
            return
        fb_nr = b[1] | (b[2] << 8)
        if fb_nr > MAX_VALID_FB_NUMBER:
            _instance_issue(bf, nr, INSTANCE_ISSUE_RANGE, b)
            return
        bf.instances_per_fb[("FB" if b[0] == SSB_FB_INSTANCE else "SFB", fb_nr)] += 1
    elif b[0] != SSB_GLOBAL_DB:
        _instance_issue(bf, nr, INSTANCE_ISSUE_KIND, b)


def _int0(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def library_summary(bf: BlockFolder) -> dict[str, collections.Counter]:
    """{library: Counter({author_version: n_blocks})} -> karışık versiyonları gösterir."""
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for b in bf.blocks:
        if b.kind == "FB" or b.library not in ("CFC generated",):
            out[b.library][b.author or "(no header)"] += 1
    return out
