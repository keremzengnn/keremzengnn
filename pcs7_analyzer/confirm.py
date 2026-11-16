"""FAZ 1: kullanıcıya görünen çıktılarda belirsizlik dili yok.

Ana tablolar yalnız doğrulanmış bilgiyi taşır. Doğrulanamayan her şey çıktının sonunda tek "Teyit edilecek noktalar"
bölümünde, aksiyon cümlesi olarak durur. Dahili güven modeli (`Confidence`) ve geliştirici tanı dosyaları (yapi_tanisi,
blockmap_tanisi, unknown.log, log.txt, findings.json'daki `confidence`) bu kuraldan muaftır.

Sözleşme (render katmanları buna dayanır):
- `ConfirmItem`: konu + aksiyon cümlesi (+ nerede).
- `collect(an)`: Analysis'ten teyit maddeleri (analiz tarafı doldurur).
- `HEADING`: bölüm / sayfa başlığı. Yasak kalıp kontrolü (`qa`) bu bölümü hariç tutar.
- `FORBIDDEN`: teyit bölümü dışında kullanıcı çıktısında geçmeyecek kalıplar (tek tanım; qa bunu kullanır).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HEADING = "Teyit edilecek noktalar"      # HTML / MD / Word başlığı ve index.html bağlantı metni
SHEET_ANALYSIS = "Teyit_Edilecekler"     # rapor.xlsx sayfası
SHEET_INVENTORY = "Teyit edilecekler"    # envanter.xlsx sayfası

FORBIDDEN = re.compile(
    r"çıkarım|\baday\b|teyit edilmeli|teyit edilecek(?! noktalar)|heuristic|ham tarama|tahmini|"
    r"\(çıkarım\)|güven\s*:\s*(low|düşük)|\w\?(?=[\s,;)]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConfirmItem:
    topic: str          # kısa konu (ör. "OS projeleri", "AS 1 donanım")
    action: str         # aksiyon cümlesi: ne yapılacak / kimden istenecek
    where: str = ""     # isteğe bağlı: dosya / sayfa / varlık adı


def is_clean(text: str) -> bool:
    """Kullanıcıya görünen metinde yasak kalıp yok mu (teyit bölümü dışında)."""
    return FORBIDDEN.search(text or "") is None


def _fix(text: str) -> str:
    """Cümleyi temizle: çift boşluk, sondaki nokta eksikliği."""
    t = " ".join((text or "").split())
    return t if not t or t[-1] in ".!" else t + "."


def _finding_items(an) -> list[ConfirmItem]:
    """Doğrulanamayan (LOW) bulgular: aksiyon = confirm_action, yoksa check aksiyonu, yoksa genel kontrol cümlesi."""
    from .checks import action_for
    from .readiness import unverified_findings
    out = []
    for f in unverified_findings(an):
        topic = f.title + (f" · {f.scope}" if f.scope else "")
        act = f.confirm_action or action_for(f.check_id)[0] or f"{topic} için bulguyu kaynak dosyada kontrol et ve doğrula"
        where = f.sources[0] if f.sources else ""
        out.append(ConfirmItem(topic, _fix(act), where))
    return out


def _not_checked_items(an) -> list[ConfirmItem]:
    from .checks import get_check
    out = []
    for cid, why in an.not_checked:
        if why.startswith("hata:") or "implement edilmedi" in why:      # dahili durum: kullanıcıya aksiyon değil
            continue
        try:
            title = get_check(cid).title
        except KeyError:
            title = cid
        out.append(ConfirmItem(f"Kontrol edilemedi: {title}",
                               _fix(f"{why}; bu veriyi iste ve analizi tekrarla"), cid))
    return out


def _situation_items(an) -> list[ConfirmItem]:
    """Bulgu olmayan belirsizlikler: sürüm, eşleme, OS rolü / kopya, HW export."""
    from .model import Confidence
    out = []
    if an.pcs7_family is None and (an.discovery.projects or an.os_projects):
        out.append(ConfirmItem("PCS 7 sürümü", "Mevcut PCS 7 sürümünü SIMATIC Manager proje özelliklerinden teyit et.",
                               "proje dosyaları"))
    elif an.pcs7_family and an.pcs7_family_confidence != Confidence.HIGH.value:
        out.append(ConfirmItem("PCS 7 sürümü", f"PCS 7 sürümünü ({an.pcs7_family}) SIMATIC Manager proje özelliklerinden teyit et.",
                               "proje dosyaları"))
    weak = sorted({b.as_label for b in an.as_folders if b.counts and b.mapping_confidence != Confidence.HIGH.value})
    if weak:
        out.append(ConfirmItem("Block klasörü ↔ AS eşlemesi",
                               f"Block klasörlerinin AS'e ait olduğunu HW Config / NetPro'dan doğrula: {', '.join(weak[:8])}"
                               + (f" (+{len(weak) - 8})." if len(weak) > 8 else "."), "ombstx"))
    if an.unmatched_os_copies:
        names = sorted(an.unmatched_os_copies)
        out.append(ConfirmItem("OS projeleri",
                               "OS PC kopyalarının hangi ES OS projesine karşılık geldiğini müşteriden teyit et "
                               f"(ES↔OS karşılaştırması yapılmadı): {', '.join(names[:5])}"
                               + (f" (+{len(names) - 5})." if len(names) > 5 else "."), "wincproj"))
    noted = sorted({f"{o.info.name} ({o.role_note})" for o in an.os_projects if o.role_note})
    if noted:
        out.append(ConfirmItem("OS rolleri", f"Şu OS projelerinin rolünü müşteriden teyit et: {'; '.join(noted[:6])}.", "wincproj"))
    elif any(o.role != "library" for o in an.os_projects):
        out.append(ConfirmItem("OS rolleri", "OS projelerinin rollerini (server / standby / client / ES) müşteriden teyit et.", "wincproj"))
    if an.stations and not an.discovery.cfg_exports:
        out.append(ConfirmItem("HW Config", "HW Config export'unu (.cfg) iste: rack/slot, adres, F-capable ve F-I/O bilgisi export'ta görünür; "
                               "F-I/O için export S7 F Configuration Pack kurulu PC'den alınmalı.", "hOmSave7"))
    return out


def collect(an) -> list[ConfirmItem]:
    """Analysis'ten teyit maddeleri; deterministik sıra, (topic, action) tekrarsız. Boş liste = teyit edilecek nokta yok.

    Kaynaklar: doğrulanamayan (LOW) bulgular, kontrol edilemeyen check'ler, bulgu olmayan belirsizlikler
    (sürüm / eşleme / OS rolü / eşleşmeyen kopya / HW export) ve `an.open_items`.
    """
    items = (_finding_items(an) + _not_checked_items(an) + _situation_items(an)
             + [ConfirmItem("Açık konu", _fix(x), "") for x in an.open_items])
    seen, out = set(), []
    for it in items:
        key = (it.topic, it.action)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
