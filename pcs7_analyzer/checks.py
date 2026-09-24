"""
Risk / tutarlılık kontrollerinin TEK tanım yeri.

Yeni kontrol = CHECKS listesine bir satır. `func` None ise kontrol planlanmış ama henüz
implement edilmemiştir; raporda "kontrol edilmedi" olarak listelenir (sessizce atlanmaz).
`func(ctx) -> list[Finding]`; ctx analiz aşamasında tanımlanacak.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .model import Finding, Severity

SW_UPDATE = "Software update V10.0 SP2"   # [1] A5E52547272
RELEASED = "Released Modules V10.0 SP2"   # [2] A5E52547920
BASIS_README = "Basis Library Readme V10.0 SP2"  # [3] A5E55678980


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    severity: Severity
    manual_ref: str
    func: Callable[..., list[Finding]] | None = None

    @property
    def implemented(self) -> bool:
        return self.func is not None


H, M, L = Severity.HIGH, Severity.MEDIUM, Severity.LOW

CHECKS: list[Check] = [
    # --- Hardware ---
    Check("HW_RELEASED", "Released Modules listesinde bulunamayan MLFB/FW", H, f"{RELEASED}"),
    Check("HW_F_EXPORT_MISSING", "F-block/F-driver var ama HW export'ta F-I/O yok (F Configuration Pack?)", H, "-"),
    Check("HW_GSD_3RD_PARTY", "3rd party GSD cihazlar", M, "-"),
    Check("AS_STOP_NO_TCIR", "Basis Library update TCiR ile yapılamıyor (410-5H değil) -> AS STOP", L, f"{BASIS_README}"),
    # --- Block / library ---
    Check("LIB_APL_V8", "APL V8.x block'ları: V10.0 SP2 faceplate'leri ile mixed operation yok -> library update", H, f"{SW_UPDATE}, Bölüm 9.10.4"),
    Check("LIB_MIXED_VERSIONS", "Aynı library'nin karışık author versiyonları", M, "-"),
    Check("LIB_PCS7_V71", "PCS 7 Library V7.1 block'ları (COMM71 vb.)", M, f"{SW_UPDATE}, Bölüm 8.5"),
    Check("LIB_LOGIC_MATRIX", "Logic Matrix: upgrade without new functionality desteklenmez", H, f"{SW_UPDATE}, Bölüm 9.9.4"),
    Check("LIB_SFC", "SFC system block'ları elle güncellenmeli", M, f"{SW_UPDATE}, Bölüm 9.5"),
    Check("LIB_F_SYSTEM", "F-System (Failsafe Blocks versiyonu, F faceplate'leri)", H, "S7 F Systems Readme (eksik)"),
    Check("LIB_MODBUS_TCP", "Modbus TCP block'ları", M, "-"),
    Check("LIB_MASTERDATA_DELETE", "OB_DIAG / OR_M_16 / OR_M_32 master data library'den silinmeli", L, f"{SW_UPDATE}, Bölüm 4.3"),
    Check("BLK_CUSTOM", "Custom block'lar (CFC kontrolü gerekli), STL/SCL, header'sız", M, "-"),
    Check("BLK_UNUSED", "Instance'sız custom/library FB'ler", L, "-"),
    Check("BLK_SYMBOL_MISMATCH", "Symbol'de olup block'u olmayan (ve tersi) block'lar", M, "-"),
    Check("BLK_AS_MAPPING", "Block klasörü <-> AS eşlemesi (heuristic ise işaretle)", M, "-"),
    Check("COMM_AS_AS", "AS-AS / multiproject'ler arası haberleşme", M, "-"),
    # --- OS ---
    Check("OS_CUSTOM_TYPICALS", "Custom picture object template'leri", M, f"{SW_UPDATE}, Bölüm 9.6.4"),
    Check("OS_OPC", "OPC konfigürasyonu / harici OPC client", M, "-"),
    Check("OS_PO_INCREASE", "Update sonrası OS RT PO sayısı artabilir", L, f"{SW_UPDATE}, Bölüm 4.3"),
    Check("OS_MIGRATION_VOLUME", "OS migration hacmi (CCMigrator, custom picture/script sayısı)", L, f"{SW_UPDATE}, Bölüm 9.2.2"),
    # --- Tutarlılık (ayrı analiz maddesi) ---
    Check("CONS_ES_SERVER", "ES OS projesi <-> OS server: sadece birinde olan / daha yeni olan dosyalar", H, "-"),
    Check("CONS_CLIENTS", "Client'lar arası içerik farkları (gruplama)", M, "-"),
    Check("CONS_BACKUP_DATES", "Aynı projenin farklı tarihli backup'ları", M, "-"),
]


def get_check(check_id: str) -> Check:
    for c in CHECKS:
        if c.id == check_id:
            return c
    raise KeyError(check_id)
