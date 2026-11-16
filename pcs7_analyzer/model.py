"""Rapordan bağımsız veri modeli (Markdown/JSON/Word renderer'ları bunu tüketir)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Severity(str, Enum):
    HIGH = "Yüksek"
    MEDIUM = "Orta"
    LOW = "Düşük"


class Confidence(str, Enum):
    HIGH = "high"
    LOW = "low"          # heuristic / teyit edilmeli


@dataclass
class Finding:
    check_id: str
    title: str
    severity: Severity
    detail: str
    sources: list[str] = field(default_factory=list)   # dosya yolları ve/veya manual bölümleri
    confidence: Confidence = Confidence.HIGH
    scope: str = ""          # AS etiketi (AS bazlı bulgu) veya "" (genel)
    blocking: bool = False   # upgrade'i engelleyen bulgu
    fid: str = ""            # deterministik Finding ID (F-001 …): rapordaki her satır buna bağlanır
    confirm_action: str = ""  # doğrulanamayan bulguda kullanıcının yapacağı iş (aksiyon cümlesi)

    @property
    def verified(self) -> bool:
        """Ana tablolara girer: yalnız dosyada doğrudan görülen (HIGH) bulgu."""
        return self.confidence == Confidence.HIGH

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["confidence"] = self.confidence.value
        return d
