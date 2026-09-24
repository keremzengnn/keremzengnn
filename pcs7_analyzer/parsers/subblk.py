"""
SUBBLK.DBF  (ombstx/offline/<id>/SUBBLK.DBF + SUBBLK.DBT) parser'ı.

Gerçek bir PCS 7 V8.1 projesiyle (6 adet S7-400H) test edilmiş referans implementasyondan taşındı.
"""
from __future__ import annotations

import collections
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


def classify_author(author: str) -> str:
    """Author string'inden library adını döndür. En uzun prefix kazanır."""
    a = author.strip()
    if not a:
        return "custom/unknown"
    best = ""
    for prefix in AUTHOR_LIBRARY:
        if a.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return AUTHOR_LIBRARY[best] if best else "custom"


@dataclass
class BlockHeader:
    kind: str          # FB / FC / ...
    number: int
    family: str
    name: str
    version: str
    author: str
    lang: str          # BLKLANG: 00001=STL, 00004=CFC/SCL derlenmiş vb.

    @property
    def library(self) -> str:
        return classify_author(self.author)


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

    @property
    def is_empty(self) -> bool:
        return self.n_records == 0


_KIND = {SUBBLK_FB: "FB", SUBBLK_FC: "FC", SUBBLK_OB: "OB", SUBBLK_DB: "DB"}


def _to_bytes(v) -> bytes:
    return v if isinstance(v, bytes) else v.encode(DBF_ENCODING, "ignore")


class _SubblkFieldParser(FieldParser):
    """
    Sadece SSBPART memo'sunu okur ve HAM byte döndürür (decode yok -> encoding'den bağımsız).
    MC5CODE / ADDINFO (block kodu, DBT'nin büyük kısmı) hiç okunmaz: 400+ MB DBT'de ciddi hız farkı.
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


def parse_subblk(dbf_path: Path, with_instances: bool = True, progress=None) -> BlockFolder:
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
    table = dbfread.DBF(
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
    for rec in table:
        bf.n_records += 1
        if progress and bf.n_records % 20000 == 0:
            progress(bf.n_records, total)
        ty = rec["SUBBLKTYP"]
        nr = int(rec["BLKNUMBER"])
        if ty in _KIND:
            present.add((ty, nr))
        if ty in (SUBBLK_FB, SUBBLK_FC):
            key = (ty, nr)
            if rec["BLOCKNAME"].strip() or key not in headers:
                headers[key] = rec
        if ty == SUBBLK_DB:
            bf.db_families[rec["BLOCKFNAME"].strip()] += 1
            if memo:
                ssb = rec.get("SSBPART")
                if ssb:
                    b = _to_bytes(ssb)
                    if b[0] in (0x0A, 0x0B):
                        fb_nr = b[1] | (b[2] << 8) if len(b) >= 3 else -1
                        if 0 <= fb_nr <= MAX_VALID_FB_NUMBER:
                            kind = "FB" if b[0] == 0x0A else "SFB"
                            bf.instances_per_fb[(kind, fb_nr)] += 1
                        else:
                            bf.unresolved_instances += 1
    c = collections.Counter(_KIND[t] for t, _ in present)
    bf.counts = dict(c)
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


def library_summary(bf: BlockFolder) -> dict[str, collections.Counter]:
    """{library: Counter({author_version: n_blocks})} -> karışık versiyonları gösterir."""
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for b in bf.blocks:
        if b.kind == "FB" or b.library not in ("CFC generated",):
            out[b.library][b.author or "(no header)"] += 1
    return out
