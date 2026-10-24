"""
Analiz edilemeyenler (UnknownRecorder): okunamayan dosya, tanınmayan kod / yapı, uygulanamayan kontrol.

Her kayıt: modül, TAM dosya yolu (backup içi), alan / ofset, ham değer (kısa), neden. Raporda "Analiz edilemeyenler"
sayfası + özette toplam sayı; çıktı klasöründe unknown.log. Hiçbir hata sessizce yutulmaz: ya burada ya bulgu olarak görünür.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class UnknownEntry:
    module: str          # hwconfig / blocks / symbols / os_wincc / blockmap / diag / analiz …
    path: str            # backup içindeki tam yol ('-' = dosyaya bağlı değil)
    reason: str
    where: str = ""      # alan adı / ofset
    raw: str = ""        # ham değer (kısaltılmış)

    def line(self) -> str:
        extra = "".join(f" [{k}: {v}]" for k, v in (("alan", self.where), ("ham", self.raw)) if v)
        return f"{self.module} | {self.path} | {self.reason}{extra}"


@dataclass
class UnknownRecorder:
    entries: list[UnknownEntry] = field(default_factory=list)

    def add(self, module: str, path: str, reason: str, where: str = "", raw: object = "") -> UnknownEntry:
        r = repr(raw) if raw not in ("", None) and not isinstance(raw, str) else (raw or "")
        e = UnknownEntry(module, path or "-", reason, where, r[:80])
        self.entries.append(e)
        return e

    def __len__(self) -> int:
        return len(self.entries)

    def rows(self) -> list[list[str]]:
        return [[e.module, e.path, e.reason, e.where, e.raw] for e in self.entries]

    def to_log(self) -> str:
        head = f"Analiz edilemeyenler: {len(self.entries)}\n"
        return head + "".join(e.line() + "\n" for e in self.entries)

    def to_list(self) -> list[dict]:
        return [asdict(e) for e in self.entries]


__all__ = ["UnknownEntry", "UnknownRecorder"]
