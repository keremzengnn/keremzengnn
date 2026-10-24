"""Tanımsız isim kontrolü (pyflakes F821 benzeri, bağımlılıksız): GUI gibi testte çalışmayan kodda
'name ... is not defined' hatasını CI'da yakalar."""
import builtins
import symtable
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "pcs7_analyzer"
FILES = sorted(p for p in PKG.rglob("*.py") if "_vendor" not in p.parts)


def _undefined(path: Path) -> list[str]:
    top = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
    module_names = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}
    known = module_names | set(dir(builtins)) | {"__file__", "__name__", "__spec__", "__builtins__"}
    out = []

    def walk(t):
        for s in t.get_symbols():
            if s.is_global() and not s.is_declared_global() and s.is_referenced() and s.get_name() not in known:
                out.append(f"{t.get_name()}:{s.get_name()}")
        for c in t.get_children():
            walk(c)
    walk(top)
    return out


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(PKG).as_posix())
def test_no_undefined_names(path):
    assert _undefined(path) == []
