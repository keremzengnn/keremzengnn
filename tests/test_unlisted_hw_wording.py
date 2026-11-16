"""Released listesinde olmayan MLFB: kullanıcı çıktılarında 'bulunamadı' kalır, belirsizlik eki sızmaz."""
from pathlib import Path

from pcs7_analyzer.cli import main

MLFB = "6ES7 351-3AA23-0AB0"     # demo Released listesinde yok (sentetik)


def test_unlisted_module_no_forbidden_wording(tmp_path):
    out = tmp_path / "demo"
    assert main(["--demo", str(out)]) == 0
    texts = {}
    for p in out.rglob("*"):
        if p.suffix in (".md", ".html") and p.name != "qa_report.md":
            texts[p.name] = p.read_text(encoding="utf-8", errors="replace")
    md = texts["rapor.md"]
    assert MLFB in md and "bulunamadı" in md
    assert "bulunamadı, teyit edilmeli" not in md
    qa = (next(out.rglob("qa_report.md"))).read_text(encoding="utf-8")
    assert "FORBIDDEN_WORDS" not in qa and "HATA" not in qa.replace("0 HATA", "")
