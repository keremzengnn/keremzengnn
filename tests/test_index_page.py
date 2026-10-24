"""index.html (çıktı giriş sayfası): her modda yazılır, sadece klasördeki dosyalardan beslenir."""
import json

from pcs7_analyzer import index_page
from pcs7_analyzer.cli import index_path, main, run
from pcs7_analyzer.demo import build_demo_project


def test_analysis_index_summary_and_links(tmp_path):
    out = tmp_path / "o"
    p = run(build_demo_project(tmp_path / "d"), out, log=lambda m: None)
    assert index_path(p) == out / "index.html"
    html = (out / "index.html").read_text(encoding="utf-8")
    lines = index_page.summary_lines(out)
    assert len(lines) == 5
    assert lines[0].startswith("PCS 7 versiyonu: V8.1")
    assert lines[1].startswith("AS: 2 station") and "414-5H" in lines[1]
    assert lines[2].startswith("OS projeleri: ") and "server" in lines[2]
    assert "block" in lines[3].lower()
    assert "BLOCKER" in lines[4] and "RİSK" in lines[4]
    for name in ("envanter.html", "rapor.html", "rapor.docx", "rapor.xlsx", "qa_report.md", "yapi_tanisi.txt"):
        assert f'href="{name}"' in html, name
    assert "Geliştiriciye gönder" in html and "Proje özeti" in html
    assert 'href="revizyon.md"' not in html          # üretilmeyen dosya listelenmez
    assert (out / "envanter_ozet.json").exists()


def test_inventory_index_without_findings(tmp_path):
    out = tmp_path / "inv"
    assert main([str(build_demo_project(tmp_path / "d")), "--inventory", "-o", str(out)]) == 0
    lines = index_page.summary_lines(out)
    assert lines[0].startswith("PCS 7 versiyonu: V8.1")
    assert lines[-1] == "Bulgular: değerlendirme yapılmadı (sadece envanter)"
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="envanter.xlsx"' in html and 'href="rapor.html"' not in html


def test_discover_and_collect_write_index(tmp_path):
    src = build_demo_project(tmp_path / "d")
    assert main([str(src), "--discover", "-o", str(tmp_path / "k")]) == 0
    assert 'href="kesif.md"' in (tmp_path / "k" / "index.html").read_text(encoding="utf-8")
    assert main([str(src), "--collect", "-o", str(tmp_path / "c")]) == 0
    assert "_paket.zip" in (tmp_path / "c" / "index.html").read_text(encoding="utf-8")


def test_summary_from_files_only(tmp_path):
    (tmp_path / "findings.json").write_text(json.dumps([{"status": "BLOCKER"}, {"status": "RİSK"}, {"status": "RİSK"}]),
                                            encoding="utf-8")
    (tmp_path / "rapor.json").write_text(json.dumps({
        "pcs7_family": "V9.0", "pcs7_family_confidence": "low", "created": "2026-01-01T10:00",
        "stations": [{"cpus": [["6ES7 410-5HX08-0AB0", "V8.2", "CPU 410-5H"]]}],
        "os_projects": [{"role": "server"}, {"role": "client"}], "block_folders": [{"custom_blocks": [{}, {}]}],
        "discovery": {"n_files": 10, "total_bytes": 2048}}), encoding="utf-8")
    lines = index_page.summary_lines(tmp_path)
    assert lines == ["PCS 7 versiyonu: V9.0 (çıkarım, teyit edilmeli) (proje dosyalarından)",
                     "AS: 1 station — CPU 410-5H V8.2", "OS projeleri: 2 (server 1, client 1)",
                     "Custom block: 2 (1 block klasörü)", "Bulgular: BLOCKER 1 · RİSK 2 · BİLGİ 0 · VERİ YOK 0"]
    p = index_page.write_index(tmp_path, "X.zip")
    assert "10 dosya, 2 KB" in p.read_text(encoding="utf-8")


def test_empty_folder_index(tmp_path):
    assert index_page.summary_lines(tmp_path) == []
    assert "Analiz özeti" in index_page.write_index(tmp_path).read_text(encoding="utf-8")


def test_corrupt_json_does_not_crash(tmp_path):
    (tmp_path / "rapor.json").write_text("{bozuk", encoding="utf-8")
    (tmp_path / "findings.json").write_text("[", encoding="utf-8")
    index_page.write_index(tmp_path)
