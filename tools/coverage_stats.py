"""Modül başına satır, test ve kontrol sayıları (COVERAGE.md için; tahmin değil, sayar)."""
import ast
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
pkg = root / "pcs7_analyzer"
rows = []
for p in sorted(pkg.rglob("*.py")):
    if "_vendor" in p.parts:
        continue
    rows.append((p.relative_to(root).as_posix(), sum(1 for _ in p.open(encoding="utf-8"))))
tests = {}
for p in sorted((root / "tests").glob("test_*.py")):
    tree = ast.parse(p.read_text(encoding="utf-8"))
    tests[p.name] = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"))
checks = (pkg / "checks.py").read_text(encoding="utf-8")
planned = len(re.findall(r"^\s*Check\(", checks, re.M))
impl = planned - len(re.findall(r"^\s*Check\(.*,\s*None\),?\s*$", checks, re.M))
print("| Dosya | Satır |\n|---|---|")
for f, n in rows:
    print(f"| {f} | {n} |")
print(f"\nToplam kod satırı: {sum(n for _, n in rows)}")
print("\n| Test dosyası | Test |\n|---|---|")
for f, n in tests.items():
    print(f"| {f} | {n} |")
print(f"\nToplam test fonksiyonu: {sum(tests.values())}")
print(f"Kontroller (CHECKS): planlanan {planned}, uygulanan {impl}")
