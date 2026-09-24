"""
Girdi kaynağı: proje klasörü veya doğrudan backup .zip'i (açmadan).

Tüm analiz bir dosya indeksi (Entry listesi) üzerinden çalışır; sadece içeriği okunması gereken
dosyalar (DBF/DBT, cfg, s7h, mcp …) `materialize()` ile gerçek path'e çevrilir. Zip'te bu dosyalar
tam path'leri korunarak temp klasöre çıkarılır (düzleşme yok). Kaynağa asla yazılmaz.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Entry:
    rel: str        # kaynağa göre relatif, '/' ayraçlı, orijinal harf büyüklüğüyle
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]

    @property
    def parent(self) -> str:
        return self.rel.rsplit("/", 1)[0] if "/" in self.rel else ""


class Source:
    label: str
    entries: list[Entry]
    warnings: list[str]

    def materialize(self, rel: str) -> Path:
        raise NotImplementedError

    def read_head(self, rel: str, n: int) -> bytes:
        raise NotImplementedError

    def read_bytes(self, rel: str) -> bytes:
        return self.materialize(rel).read_bytes()

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FolderSource(Source):
    def __init__(self, root: Path, progress=None):
        self.root = Path(root).resolve()
        self.label = str(self.root)
        self.warnings = []
        self.entries = []
        n = 0
        for dirpath, dirnames, filenames in os.walk(self.root, onerror=self._onerror):
            dirnames.sort()
            d = Path(dirpath)
            for fn in sorted(filenames):
                p = d / fn
                try:
                    st = p.stat()
                except OSError as e:
                    self.warnings.append(f"Okunamadı: {p} ({e.strerror})")
                    continue
                self.entries.append(Entry(p.relative_to(self.root).as_posix(), st.st_size, st.st_mtime))
                n += 1
                if progress and n % 20000 == 0:
                    progress(f"{n} dosya indekslendi")

    def _onerror(self, err: OSError) -> None:
        self.warnings.append(f"Okunamadı: {err.filename} ({err.strerror})")

    def materialize(self, rel: str) -> Path:
        return self.root / PurePosixPath(rel)

    def read_head(self, rel: str, n: int) -> bytes:
        with open(self.materialize(rel), "rb") as f:
            return f.read(n)


class ZipSource(Source):
    def __init__(self, zip_path: Path, progress=None, temp_dir: Path | None = None):
        self.path = Path(zip_path).resolve()
        self.label = str(self.path)
        self.warnings = []
        self.zf = zipfile.ZipFile(self.path)
        self._tmp = Path(tempfile.mkdtemp(prefix="pcs7an_", dir=temp_dir))
        self._info: dict[str, zipfile.ZipInfo] = {}
        self.entries = []
        seen = set()
        for zi in self.zf.infolist():
            if zi.is_dir():
                continue
            rel = zi.filename.replace("\\", "/").lstrip("/")
            if rel in seen:
                self.warnings.append(f"Zip'te aynı path iki kez var (üstteki kullanıldı): {rel}")
                continue
            seen.add(rel)
            try:
                mtime = time.mktime(zi.date_time + (0, 0, -1))
            except (OverflowError, ValueError):
                mtime = 0.0
            self._info[rel] = zi
            self.entries.append(Entry(rel, zi.file_size, mtime))
        self.entries.sort(key=lambda e: e.rel)
        if progress:
            progress(f"Zip indekslendi: {len(self.entries)} dosya")

    def materialize(self, rel: str) -> Path:
        out = self._tmp / PurePosixPath(rel)
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            with self.zf.open(self._info[rel]) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            m = self._entry_mtime(rel)
            if m:
                os.utime(out, (m, m))
        return out

    def _entry_mtime(self, rel: str) -> float:
        dt = self._info[rel].date_time
        try:
            return time.mktime(dt + (0, 0, -1))
        except (OverflowError, ValueError):
            return 0.0

    def read_head(self, rel: str, n: int) -> bytes:
        with self.zf.open(self._info[rel]) as f:
            return f.read(n)

    def close(self) -> None:
        self.zf.close()
        shutil.rmtree(self._tmp, ignore_errors=True)


def open_source(path: Path, progress=None) -> Source:
    path = Path(path)
    if path.is_dir():
        return FolderSource(path, progress)
    if path.is_file() and zipfile.is_zipfile(path):
        return ZipSource(path, progress)
    if path.suffix.lower() in (".7z", ".rar"):
        raise ValueError(f"{path.suffix} desteklenmiyor: önce klasöre açın (path yapısını koruyarak) veya .zip verin")
    raise ValueError(f"Klasör veya .zip değil: {path}")
