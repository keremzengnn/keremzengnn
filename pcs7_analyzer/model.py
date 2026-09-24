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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["confidence"] = self.confidence.value
        return d
