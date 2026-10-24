"""
Çıktı klasörünün giriş sayfası: index.html.

Her modda (analiz, envanter, keşif, paket, karşılaştırma) cli.run sonunda yazılır. Sadece klasördeki dosyalardan
beslenir (rapor.json, findings.json, report_ir.json, envanter_ozet.json): hangi mod çalışmış olursa olsun aynı kod.
İçerik: ne analiz edildi (kaynak, tarih, boyut), 5 satırlık proje özeti, üretilen dosyalar + ne işe yaradıkları,
geliştiriciye gönderilebilecek (maskeli) tanı dosyaları.
"""
from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import __version__

INDEX = "index.html"
INV_SUMMARY = "envanter_ozet.json"
STATUSES = ("BLOCKER", "RİSK", "BİLGİ", "VERİ YOK")

# (dosya / glob, grup, açıklama). Sıra = sayfadaki sıra.
FILES = [
    ("envanter.html", "Önce bakın", "Mevcut durum: versiyonlar, library'ler, hardware, OS projeleri (değerlendirme yok)"),
    ("yol_haritasi.html", "Önce bakın", "Yol haritası: upgrade için adım adım ne yapılmalı"),
    ("rapor.html", "Önce bakın", "Çalışma raporu (mühendis): tüm bulgular, kaynaklar, açık konular, ekler"),
    ("rapor.docx", "Müşteri / teklif", "Müşteri raporu (Word template'iyle): özet, envanter, riskler"),
    ("rapor.xlsx", "Müşteri / teklif", "Analiz Excel'i: AS envanteri, HW modüller, custom block'lar, OS/WinCC, farklar"),
    ("envanter.xlsx", "Detay", "Envanter Excel'i: backup'taki her şey sayfa sayfa (Mevcut durum ilk sayfa)"),
    ("semboller.xlsx", "Detay", "Symbol table'lar (tüm semboller) ve sembol kontrolleri"),
    ("fark.xlsx", "Detay", "Karşılaştırma: iki backup arasındaki farklar + hangisi baz alınmalı"),
    ("fark.md", "Detay", "Karşılaştırma özeti (metin)"),
    ("*_paket.zip", "Detay", "Paket: analiz için gereken dosyalar (müşteri verisi içerir; paylaşmadan önce kuralları teyit edin)"),
    ("kesif.md", "Detay", "Keşif: backup klasör yapısı (proje, block klasörü, HW, OS)"),
    ("qa_report.md", "Detay", "Rapor kalite kontrolü (HATA varsa raporu müşteriye göndermeden düzeltin)"),
    ("revizyon.md", "Detay", "Revizyon: önceki rapora göre yeni / kapanan / değişen bulgular"),
    ("rapor.md", "Detay", "Çalışma raporunun Markdown hali"),
    ("yol_haritasi.md", "Detay", "Yol haritasının Markdown hali"),
    ("findings.json", "Detay", "Bulgular (BLOCKER / RİSK / BİLGİ / VERİ YOK, KANIT / ÇIKARIM) — makine okunur"),
    ("rapor.json", "Detay", "Analiz verisinin tamamı — makine okunur"),
    ("report_ir.json", "Detay", "Rapor modeli (profil, bölümler, istatistik) — makine okunur"),
    ("log.txt", "Detay", "Çalışma günlüğü: uyarılar, hatalar (müşteri dosya yolları içerir)"),
    ("unknown.log", "Detay", "Okunamayan / analiz edilemeyen dosyalar (müşteri dosya yolları içerir)"),
    ("yapi_tanisi.txt", "Geliştiriciye gönder", "Yapı tanısı: DBF alan adları ve kayıt sayıları, isimler maskeli"),
    ("blockmap_tanisi.txt", "Geliştiriciye gönder", "Block klasörü ↔ AS zinciri tanısı, isimler maskeli"),
]
GROUPS = ("Önce bakın", "Müşteri / teklif", "Detay", "Geliştiriciye gönder")


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.2f} {unit}"
        n /= 1024
    return ""


def write_inventory_summary(inv, out_dir: Path) -> Path | None:
    """Envanterin 'Mevcut durum' satırlarını envanter_ozet.json'a yazar (index.html için; değerlendirme içermez)."""
    try:
        d = getattr(inv, "discovery", None)
        rows = []
        try:
            rows = [list(map(str, r[:4])) for r in inv.sheet("Mevcut durum").rows]
        except (StopIteration, AttributeError):
            pass
        data = {"source": str(getattr(inv, "source", "")), "created": str(getattr(inv, "created", "")),
                "n_files": getattr(d, "n_files", None), "total_bytes": getattr(d, "total_bytes", None),
                "current_state": rows, "warnings": len(getattr(inv, "warnings", []) or [])}
        p = Path(out_dir) / INV_SUMMARY
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return p
    except Exception:  # noqa: BLE001 - özet dosyası olmazsa index daha az bilgiyle yazılır
        return None


def _state_rows(inv: dict | None, section: str) -> list[list[str]]:
    return [r for r in (inv or {}).get("current_state", []) if r and r[0] == section]


def _state_value(inv: dict | None, section: str, topic: str) -> str:
    return next((r[2] for r in _state_rows(inv, section) if len(r) > 2 and r[1] == topic), "")


def summary_lines(out_dir: Path) -> list[str]:
    """5 satır: PCS 7 versiyonu, AS + CPU, OS projeleri, özel / custom block, BLOCKER / RİSK sayıları."""
    out_dir = Path(out_dir)
    rep = _load(out_dir / "rapor.json")
    inv = _load(out_dir / INV_SUMMARY)
    fnd = _load(out_dir / "findings.json")
    ir = _load(out_dir / "report_ir.json")
    lines = []

    # 1) PCS 7 versiyonu
    ver = ""
    if isinstance(rep, dict) and rep.get("pcs7_family"):
        ver = str(rep["pcs7_family"])
        if rep.get("pcs7_family_confidence") != "high":
            ver += " (çıkarım, teyit edilmeli)"
    ver = ver or _state_value(inv, "Yazılım", "PCS 7")
    if ver or rep or inv:
        lines.append(f"PCS 7 versiyonu: {ver or 'tespit edilemedi'} (proje dosyalarından)")

    # 2) AS + CPU tipleri
    if isinstance(rep, dict) and rep.get("stations"):
        cpus = Counter()
        for st in rep["stations"]:
            for c in st.get("cpus") or []:
                c = list(c) + ["", "", ""]
                cpus[" ".join(x for x in (c[2] or c[0], c[1]) if x)] += 1
        cpu_txt = ", ".join(f"{k} ×{n}" if n > 1 else k for k, n in cpus.most_common()) or "CPU tespit edilemedi"
        lines.append(f"AS: {len(rep['stations'])} station — {cpu_txt}")
    elif _state_rows(inv, "Hardware"):
        hw = [r for r in _state_rows(inv, "Hardware") if r[1] != "-"]
        cpus = Counter(r[2].split(",")[0].split(";")[0].strip() for r in hw if "CPU" in r[2])
        cpu_txt = ", ".join(f"{k} ×{n}" if n > 1 else k for k, n in cpus.most_common()) or "CPU tespit edilemedi"
        lines.append(f"AS: {len(hw)} station / proje — {cpu_txt}" if hw else "AS: HW bilgisi bulunamadı")
    elif rep or inv:
        lines.append("AS: HW bilgisi bulunamadı (HW Config export yok)")

    # 3) OS projeleri
    roles = Counter()
    if isinstance(rep, dict) and rep.get("os_projects"):
        roles = Counter(str(o.get("role") or "?") for o in rep["os_projects"])
    elif _state_rows(inv, "OS"):
        roles = Counter(r[2].split(",")[0].strip() or "?" for r in _state_rows(inv, "OS"))
    if roles:
        lines.append(f"OS projeleri: {sum(roles.values())} ({', '.join(f'{k} {n}' for k, n in roles.most_common())})")
    elif rep or inv:
        lines.append("OS projeleri: bulunamadı")

    # 4) Özel / custom block
    special = _state_value(inv, "Library", "Özel block")
    if special:
        lines.append(f"Özel / custom block: {special.split(' -> ')[0]}")
    elif isinstance(rep, dict) and rep.get("block_folders") is not None:
        n = sum(len(b.get("custom_blocks") or []) for b in rep["block_folders"])
        lines.append(f"Custom block: {n} ({len(rep['block_folders'])} block klasörü)")

    # 5) Bulgular
    by = Counter()
    if isinstance(fnd, list):
        by = Counter(str(x.get("status")) for x in fnd if isinstance(x, dict) and x.get("status"))
    elif isinstance(ir, dict):
        by = Counter((ir.get("stats") or {}).get("by_status") or {})
    if fnd is not None or ir is not None:
        lines.append("Bulgular: " + " · ".join(f"{s} {by.get(s, 0)}" for s in STATUSES))
    elif inv:
        lines.append("Bulgular: değerlendirme yapılmadı (sadece envanter)")
    return lines


def _source_info(out_dir: Path, source) -> dict:
    rep = _load(out_dir / "rapor.json")
    inv = _load(out_dir / INV_SUMMARY)
    info = {"source": str(source or ""), "date": "", "size": ""}
    if isinstance(rep, dict):
        d = rep.get("discovery") or {}
        info["source"] = info["source"] or str(rep.get("source", ""))
        info["date"] = str(rep.get("created", ""))
        if d.get("n_files") is not None:
            info["size"] = f"{d['n_files']} dosya, {_size(d.get('total_bytes'))}"
    if isinstance(inv, dict):
        info["source"] = info["source"] or inv.get("source", "")
        info["date"] = info["date"] or inv.get("created", "")
        if not info["size"] and inv.get("n_files") is not None:
            info["size"] = f"{inv['n_files']} dosya, {_size(inv.get('total_bytes'))}"
    if not info["size"] and source and Path(source).is_file():
        try:
            info["size"] = _size(Path(source).stat().st_size)
        except OSError:
            pass
    info["date"] = info["date"].replace("T", " ") or f"{datetime.now():%Y-%m-%d %H:%M}"
    return info


def produced_files(out_dir: Path) -> list[tuple[str, str, str]]:
    """[(grup, dosya adı, açıklama)] sadece klasörde var olanlar."""
    out_dir = Path(out_dir)
    res = []
    for pat, group, desc in FILES:
        for p in sorted(out_dir.glob(pat)) if "*" in pat else [out_dir / pat]:
            if p.is_file():
                res.append((group, p.name, desc))
    return res


def next_steps(files: set[str]) -> list[str]:
    s = []
    if "envanter.html" in files:
        s.append("Mevcut durumu kontrol edin: <a href=\"envanter.html\">envanter.html</a> (versiyon, library, hardware, OS).")
    if "yol_haritasi.html" in files:
        s.append("Upgrade yolunu okuyun: <a href=\"yol_haritasi.html\">yol_haritasi.html</a>.")
    if "rapor.html" in files:
        s.append("BLOCKER / RİSK bulgularını ve açık konuları inceleyin: <a href=\"rapor.html\">rapor.html</a>.")
    if "rapor.docx" in files:
        s.append("Müşteri raporunu gözden geçirin (sarı = çıkarım, teyit edilmeli): <a href=\"rapor.docx\">rapor.docx</a>.")
    if "qa_report.md" in files:
        s.append("Göndermeden önce <a href=\"qa_report.md\">qa_report.md</a>'de HATA olmadığından emin olun.")
    return s


def _css() -> str:
    try:
        from .report import _css as report_css
        return report_css()
    except Exception:  # noqa: BLE001
        return "body{font-family:Segoe UI,Arial,sans-serif;background:#F3F3F0;color:#000028;margin:0}"


def render(out_dir: Path, source=None, mode: str = "analysis") -> str:
    out_dir = Path(out_dir)
    e = html.escape
    info = _source_info(out_dir, source)
    lines = summary_lines(out_dir)
    files = produced_files(out_dir)
    names = {n for _g, n, _d in files}
    mode_txt = {"analysis": "Upgrade analizi (PCS 7 V10.0 SP2) + envanter", "inventory": "Envanter (mevcut durum)",
                "discover": "Keşif (klasör yapısı)", "collect": "Paket", "compare": "Karşılaştırma"}.get(mode, mode)
    parts = [f"<!doctype html><html lang=\"tr\"><head><meta charset=\"utf-8\">"
             f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>PCS 7 Analiz Özeti</title>"
             f"<style>{_css()}\n.files td:first-child{{white-space:nowrap}} .summary li{{font-size:15px}}</style></head><body>",
             "<header><div class=\"topline\">SIMATIC PCS 7 · Upgrade ön değerlendirme</div>"
             f"<h1><b>Analiz özeti</b></h1><div class=\"sub\">{e(mode_txt)} · pcs7_analyzer {e(__version__)}</div></header>",
             "<main>",
             "<section><h2>Ne analiz edildi</h2><table><tbody>",
             f"<tr><th>Kaynak</th><td>{e(info['source']) or '-'}</td></tr>",
             f"<tr><th>Tarih</th><td>{e(info['date'])}</td></tr>",
             f"<tr><th>Boyut</th><td>{e(info['size']) or '-'}</td></tr>",
             f"<tr><th>Çıktı klasörü</th><td>{e(str(out_dir.resolve()))}</td></tr>",
             "</tbody></table>",
             "<p class=\"note\">Backup sadece okundu; hiçbir dosyası değiştirilmedi ve hiçbir yere gönderilmedi. "
             "Bu klasördeki dosyalar müşteri verisi içerir (\"Geliştiriciye gönder\" grubu hariç).</p></section>"]
    if lines:
        parts.append("<section><h2>Proje özeti</h2><ul class=\"summary\">"
                     + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ul></section>")
    steps = next_steps(names)
    if steps:
        parts.append("<section><h2>Sonraki adımlar</h2><ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol></section>")
    for g in GROUPS:
        rows = [(n, d) for gg, n, d in files if gg == g]
        if not rows:
            continue
        intro = ("<p>Bir şey ters giderse sadece bu dosyaları geliştiriciye gönderin: isimler maskelidir, "
                 "müşteri verisi içermez. log.txt / unknown.log dosya yolu içerir, göndermeden önce bakın.</p>"
                 if g == "Geliştiriciye gönder" else "")
        parts.append(f"<section><h2>{e(g)}</h2>{intro}<table class=\"files\"><tbody>"
                     + "".join(f"<tr><td><a href=\"{e(n)}\">{e(n)}</a></td><td>{e(d)}</td></tr>" for n, d in rows)
                     + "</tbody></table></section>")
    parts.append(f"</main><footer>pcs7_analyzer {e(__version__)} · {datetime.now():%Y-%m-%d %H:%M}</footer></body></html>")
    return "\n".join(parts)


def write_index(out_dir: Path, source=None, mode: str = "analysis") -> Path:
    p = Path(out_dir) / INDEX
    p.write_text(render(out_dir, source, mode), encoding="utf-8")
    return p
