"""
Masaüstü penceresi. En kısa yol: backup seç (klasör veya .zip) -> "Analiz et" (analiz + envanter birlikte) ->
pencerede 5 satırlık özet + "Özeti aç" (index.html), "Word raporu", "Excel", "Klasör".
Diğer işler (sadece envanter, paketle, karşılaştır, doküman arşivi) "Diğer" bölümünde.
Hedef sabit: PCS 7 V10.0 SP2. Sadece standart kütüphane (tkinter). Renkler rapordaki Siemens token'larıyla aynı.
Hata penceresinde traceback gösterilmez; traceback log.txt'ye yazılır.
"""
from __future__ import annotations

import contextlib
import os
import queue
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

from . import __version__, settings
from .analyze import ManualInputs
from .cli import TARGET_LABEL, default_out_dir, index_path, run
from .report import SIEMENS_TOKENS as T


def _open_file(p: Path) -> None:
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]  # Windows: ilişkili programla aç
    except (AttributeError, OSError):
        webbrowser.open(Path(p).resolve().as_uri())


def _kb_status() -> str:
    p = settings.find_kb()
    if not p:
        return "Doküman arşivi: yok (Diğer → Doküman arşivi oluştur)"
    try:
        mb = p.stat().st_size / 1e6
    except OSError:
        mb = 0
    return f"Doküman arşivi: var ({mb:.0f} MB)"


def _write_error_log(out_dir: Path | None, tb: str) -> Path:
    """Traceback'i çıktı klasörünün log.txt'sine (yoksa ayar klasörüne) ekler; dosya yolunu döndürür."""
    for d in ([out_dir] if out_dir else []) + [settings.settings_path().parent]:
        try:
            d.mkdir(parents=True, exist_ok=True)
            p = d / "log.txt"
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"\n--- HATA {datetime.now():%Y-%m-%d %H:%M} (pcs7_analyzer {__version__}) ---\n{tb}\n")
            return p
        except OSError:
            continue
    return Path("log.txt")


def _friendly(e: Exception) -> str:
    if isinstance(e, PermissionError):
        return "Dosyaya erişilemedi (açık bir Excel / Word dosyası olabilir, kapatıp tekrar deneyin)."
    if isinstance(e, FileNotFoundError):
        return f"Dosya / klasör bulunamadı: {getattr(e, 'filename', '') or e}"
    if isinstance(e, MemoryError):
        return "Bellek yetmedi. Önce 'Paketle' ile küçük bir paket oluşturup onu analiz edin."
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return msg[:300]


class _QueueWriter:
    """stdout / stderr -> pencere günlüğü (kb build print'leri için)."""

    def __init__(self, put):
        self.put, self.buf = put, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.put(line)
        return len(s)

    def flush(self):
        if self.buf.strip():
            self.put(self.buf)
        self.buf = ""


def main(mode: str = "analysis", fixed: bool = False) -> int:
    """Pencere. mode / fixed eski çağrılarla uyum için (fixed=True + 'inventory' -> ana buton envanter çıkarır)."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"PCS 7 Upgrade Analyzer {__version__}")
    root.geometry("920x800")
    root.minsize(760, 600)
    root.configure(bg=T["light-sand"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", font=("Segoe UI", 10), background=T["light-sand"], foreground=T["deep-blue"])
    style.configure("TLabel", background=T["light-sand"], foreground=T["deep-blue"])
    style.configure("Hint.TLabel", foreground=T["deep-blue-500"])
    style.configure("Step.TLabel", font=("Segoe UI", 11, "bold"))
    style.configure("Stage.TLabel", foreground=T["petrol"], font=("Segoe UI", 10, "bold"))
    style.configure("Path.TLabel", background=T["white"], foreground=T["deep-blue"], padding=(10, 8), relief="flat")
    style.configure("Summary.TLabel", background=T["white"], foreground=T["deep-blue"], padding=(12, 10),
                    font=("Segoe UI", 10), justify="left")
    style.configure("TEntry", fieldbackground=T["white"])
    style.configure("TLabelframe", background=T["light-sand"])
    style.configure("TLabelframe.Label", background=T["light-sand"], foreground=T["deep-blue"],
                    font=("Segoe UI", 10, "bold"))
    style.configure("Primary.TButton", background=T["petrol"], foreground=T["white"], borderwidth=0, padding=(34, 14),
                    font=("Segoe UI", 13, "bold"))
    style.map("Primary.TButton", background=[("active", T["deep-blue-700"]), ("disabled", T["deep-blue-300"])])
    style.configure("Pick.TButton", background=T["deep-blue"], foreground=T["white"], borderwidth=0, padding=(16, 10),
                    font=("Segoe UI", 10, "bold"))
    style.map("Pick.TButton", background=[("active", T["petrol"])])
    style.configure("TButton", background=T["white"], foreground=T["deep-blue"], padding=(12, 6))
    style.configure("Horizontal.TProgressbar", background=T["petrol"], troughcolor=T["deep-blue-50"])

    header = tk.Frame(root, bg=T["deep-blue"])
    header.pack(fill="x")
    tk.Label(header, text="SIMATIC PCS 7 · UPGRADE ÖN DEĞERLENDİRME", bg=T["deep-blue"], fg=T["bold-green"],
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=22, pady=(14, 0))
    tk.Label(header, text=f"Proje backup analizi → {TARGET_LABEL}", bg=T["deep-blue"], fg=T["white"],
             font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=22, pady=(0, 2))
    tk.Label(header, text=f"Sürüm {__version__} · backup sadece okunur, hiçbir yere gönderilmez", bg=T["deep-blue"],
             fg=T["deep-blue-100"], font=("Segoe UI", 9)).pack(anchor="w", padx=22, pady=(0, 12))
    tk.Frame(root, bg=T["petrol"], height=4).pack(fill="x")

    body = ttk.Frame(root, padding=(22, 14))
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)

    st = settings.load()
    src_var = tk.StringVar()
    src_show = tk.StringVar(value="Henüz backup seçilmedi")
    out_root_var = tk.StringVar(value=st.get("out_root", "") or str(default_out_dir(Path("x")).parent))
    author_var = tk.StringVar(value=st.get("author", ""))
    dept_var = tk.StringVar(value=st.get("department", ""))
    cust_var = tk.StringVar()
    stage_var = tk.StringVar(value="")
    summary_var = tk.StringVar(value="")
    kb_var = tk.StringVar(value=_kb_status())
    last_dir = {"v": st.get("last_source_dir", "")}

    def init_dir() -> str | None:
        return last_dir["v"] if last_dir["v"] and Path(last_dir["v"]).is_dir() else None

    def remember_dir(p: str) -> None:
        last_dir["v"] = str(Path(p).parent)
        settings.save({"last_source_dir": last_dir["v"]})

    def set_source(p: str) -> None:
        src_var.set(p)
        src_show.set(p)
        remember_dir(p)

    def pick_dir():
        p = filedialog.askdirectory(title="Backup klasörünü seçin", initialdir=init_dir())
        if p:
            set_source(p)

    def pick_zip():
        p = filedialog.askopenfilename(title="Backup .zip dosyasını seçin", initialdir=init_dir(),
                                       filetypes=[("Zip", "*.zip"), ("Tümü", "*.*")])
        if p:
            set_source(p)

    def pick_out():
        p = filedialog.askdirectory(title="Raporların kaydedileceği ana klasör", initialdir=out_root_var.get() or None)
        if p:
            out_root_var.set(p)

    # 1) Backup
    r = 0
    ttk.Label(body, text="1  Backup'ı seçin (klasör veya .zip)", style="Step.TLabel").grid(row=r, column=0, columnspan=3,
                                                                                       sticky="w", pady=(0, 6))
    r += 1
    picks = ttk.Frame(body)
    picks.grid(row=r, column=0, columnspan=3, sticky="w")
    ttk.Button(picks, text="Backup klasörü…", style="Pick.TButton", command=pick_dir).pack(side="left")
    ttk.Button(picks, text="Backup .zip…", style="Pick.TButton", command=pick_zip).pack(side="left", padx=8)
    r += 1
    ttk.Label(body, textvariable=src_show, style="Path.TLabel").grid(row=r, column=0, columnspan=3, sticky="ew",
                                                                     pady=(8, 10))
    r += 1

    # 2) Rapor bilgileri (hatırlanır)
    ttk.Label(body, text="2  Rapor bilgileri (bir kez girilir, hatırlanır)", style="Step.TLabel") \
        .grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 4))
    r += 1
    for label, var in (("Hazırlayan", author_var), ("Departman", dept_var), ("Müşteri / proje (kapak, ops.)", cust_var)):
        ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=var).grid(row=r, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        r += 1
    ttk.Label(body, text="Raporlar şuraya").grid(row=r, column=0, sticky="w", pady=2)
    ttk.Entry(body, textvariable=out_root_var).grid(row=r, column=1, sticky="ew", padx=8)
    ttk.Button(body, text="Değiştir…", command=pick_out).grid(row=r, column=2, sticky="e")
    r += 1

    # 3) Analiz et
    actions = ttk.Frame(body)
    actions.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(12, 4))
    run_btn = ttk.Button(actions, text="3  Analiz et", style="Primary.TButton")
    run_btn.pack(side="left")
    prog = ttk.Frame(actions)
    prog.pack(side="left", fill="x", expand=True, padx=(16, 0))
    bar = ttk.Progressbar(prog, mode="indeterminate")
    bar.pack(fill="x")
    ttk.Label(prog, textvariable=stage_var, style="Stage.TLabel").pack(anchor="w", pady=(4, 0))
    r += 1
    ttk.Label(body, text=f"Analiz + envanter birlikte: Word (müşteri), Excel, HTML çalışma raporu, mevcut durum. "
                         f"Hedef: {TARGET_LABEL}.", style="Hint.TLabel").grid(row=r, column=0, columnspan=3, sticky="w")
    r += 1

    # Sonuç: özet + butonlar
    res_frame = ttk.Frame(body)
    res_frame.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(10, 4))
    res_frame.columnconfigure(0, weight=1)
    summary_lab = ttk.Label(res_frame, textvariable=summary_var, style="Summary.TLabel", wraplength=840)
    summary_lab.grid(row=0, column=0, sticky="ew")
    btns = ttk.Frame(res_frame)
    btns.grid(row=1, column=0, sticky="w", pady=(6, 0))
    index_btn = ttk.Button(btns, text="Özeti aç", state="disabled")
    index_btn.pack(side="left")
    word_btn = ttk.Button(btns, text="Word raporu", state="disabled")
    word_btn.pack(side="left", padx=6)
    excel_btn = ttk.Button(btns, text="Excel", state="disabled")
    excel_btn.pack(side="left")
    folder_btn = ttk.Button(btns, text="Klasör", state="disabled")
    folder_btn.pack(side="left", padx=6)
    res_frame.grid_remove()
    r += 1

    # Diğer
    other = ttk.LabelFrame(body, text="Diğer", padding=(10, 6))
    other.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(10, 6))
    obtn = ttk.Frame(other)
    obtn.pack(fill="x")
    inv_btn = ttk.Button(obtn, text="Sadece envanter")
    inv_btn.pack(side="left")
    col_btn = ttk.Button(obtn, text="Paketle (göndermek için)")
    col_btn.pack(side="left", padx=6)
    cmp_btn = ttk.Button(obtn, text="Karşılaştır (B seç)…")
    cmp_btn.pack(side="left")
    kb_btn = ttk.Button(obtn, text="Siemens doküman arşivi (KB) oluştur…")
    kb_btn.pack(side="left", padx=6)
    adv_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(obtn, text="Gelişmiş", variable=adv_var).pack(side="left", padx=(6, 0))
    info = ttk.Frame(other)
    info.pack(fill="x", pady=(4, 0))
    ttk.Label(info, textvariable=kb_var, style="Hint.TLabel").pack(side="left")
    team = settings.team_file()
    if team:
        ttk.Label(info, text=f"   Ekip ayarları: {team}", style="Hint.TLabel").pack(side="left")

    # Gelişmiş (opsiyonel): backup dışındaki WinCC export'u, PO, PC station listesi, önceki rapor
    adv = ttk.Frame(other)
    adv.columnconfigure(1, weight=1)
    exp_var, po_as, po_os, po_arc, pcs_var, prev_var = (tk.StringVar() for _ in range(6))

    def pick_into(var, title):
        def f():
            p = filedialog.askdirectory(title=title)
            if p:
                var.set(p)
        return f
    ar = 0
    for label, var, title in (("WinCC export klasörü (ops.)", exp_var, "WinCC Configuration Studio export klasörü"),
                              ("Önceki rapor klasörü (revizyon)", prev_var, "Önceki rapor klasörü (findings.json)")):
        ttk.Label(adv, text=label).grid(row=ar, column=0, sticky="w", pady=2)
        ttk.Entry(adv, textvariable=var).grid(row=ar, column=1, sticky="ew", padx=8)
        ttk.Button(adv, text="Seç…", command=pick_into(var, title)).grid(row=ar, column=2, sticky="e")
        ar += 1
    ttk.Label(adv, text="PO: AS RT / OS / archive").grid(row=ar, column=0, sticky="w", pady=2)
    pof = ttk.Frame(adv)
    pof.grid(row=ar, column=1, columnspan=2, sticky="w", padx=8)
    for v in (po_as, po_os, po_arc):
        ttk.Entry(pof, textvariable=v, width=12).pack(side="left", padx=(0, 6))
    ttk.Label(pof, text="(PCS 7 License Information)", style="Hint.TLabel").pack(side="left")
    ar += 1
    ttk.Label(adv, text="PC station listesi (virgülle)").grid(row=ar, column=0, sticky="w", pady=2)
    ttk.Entry(adv, textvariable=pcs_var).grid(row=ar, column=1, columnspan=2, sticky="ew", padx=(8, 0))

    def on_adv(*_):
        adv.pack(fill="x", pady=(6, 0)) if adv_var.get() else adv.pack_forget()
    adv_var.trace_add("write", on_adv)
    r += 1

    logbox = tk.Text(body, height=7, bg=T["deep-blue"], fg=T["deep-blue-50"], insertbackground=T["white"],
                     font=("Consolas", 9), relief="flat", padx=8, pady=6)
    logbox.grid(row=r, column=0, columnspan=3, sticky="nsew")
    body.rowconfigure(r, weight=1)

    q: queue.Queue = queue.Queue()
    result = {"path": None, "out": None}
    busy_btns = (run_btn, inv_btn, col_btn, cmp_btn, kb_btn)

    def log(msg):
        q.put(("log", str(msg)))

    def manual_inputs() -> ManualInputs:
        return ManualInputs(as_rt_po=po_as.get().strip(), os_po=po_os.get().strip(), archive_tags=po_arc.get().strip(),
                            pc_stations=[x.strip() for x in pcs_var.get().replace(";", ",").split(",") if x.strip()])

    def out_root() -> Path | None:
        v = out_root_var.get().strip()
        return Path(v) if v else None

    def worker(job: str, src: str, b: str = ""):
        out = None
        try:
            if job == "kb":
                from .kb import main as kb_main
                w = _QueueWriter(log)
                with contextlib.redirect_stdout(w), contextlib.redirect_stderr(w):
                    rc = kb_main(["build", "--root", src])
                w.flush()
                q.put(("kb_done", rc))
                return
            if job == "compare":
                from .cli import _index
                from .compare import compare, write_outputs
                out = default_out_dir(Path(f"{Path(src).stem}_vs_{Path(b).stem}"), out_root())
                q.put(("out", out))
                res = compare(Path(src), Path(b), log)
                p = write_outputs(res, out)
                log(f"{len(res.rows)} fark satırı; öneri: {res.recommendation}")
                _index(out, Path(f"{src} ↔ {b}"), "compare", log)
                q.put(("done", p))
                return
            out = default_out_dir(Path(src), out_root())
            q.put(("out", out))
            exports = [Path(exp_var.get().strip())] if exp_var.get().strip() else []
            p = run(Path(src), out, log=log, author=author_var.get().strip(), department=dept_var.get().strip(),
                    customer=cust_var.get().strip() or None, inventory=job == "inventory", manual=manual_inputs(),
                    exports=exports, collect=job == "collect",
                    compare_to=Path(prev_var.get().strip()) if prev_var.get().strip() else None)
            q.put(("done", p))
        except Exception as e:  # noqa: BLE001 - pencerede kısa mesaj, traceback log.txt'ye
            lp = _write_error_log(out, traceback.format_exc())
            q.put(("error", (_friendly(e), lp)))

    def set_busy(busy: bool):
        for b in busy_btns:
            b.configure(state="disabled" if busy else "normal")
        (bar.start(12) if busy else bar.stop())

    def show_result(p: Path):
        idx = index_path(p)
        folder = idx.parent
        result["path"], result["out"] = idx, folder
        lines = []
        try:
            from .index_page import summary_lines
            lines = summary_lines(folder)
        except Exception:  # noqa: BLE001
            pass
        summary_var.set("Proje özeti\n" + "\n".join(f"•  {x}" for x in lines) if lines else f"Tamamlandı: {p.name}")
        res_frame.grid()
        index_btn.configure(state="normal")
        folder_btn.configure(state="normal")
        word_btn.configure(state="normal" if (folder / "rapor.docx").exists() else "disabled")
        excel_btn.configure(state="normal" if excel_file() else "disabled")
        if idx.suffix.lower() == ".html":
            webbrowser.open(idx.resolve().as_uri())

    def excel_file() -> Path | None:
        f = result["out"]
        if not f:
            return None
        return next((f / n for n in ("rapor.xlsx", "envanter.xlsx", "fark.xlsx") if (f / n).exists()), None)

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log":
                    logbox.insert("end", val + "\n")
                    logbox.see("end")
                    first = val.strip().splitlines()[0] if val.strip() else ""
                    if first and not first.startswith(("Traceback", "  ", "UYARI")):
                        stage_var.set(first[:110])
                elif kind == "out":
                    result["out"] = Path(val)
                elif kind == "done":
                    set_busy(False)
                    stage_var.set("Tamamlandı.")
                    show_result(Path(val))
                elif kind == "kb_done":
                    set_busy(False)
                    kb_var.set(_kb_status())
                    if val == 0:
                        stage_var.set("Doküman arşivi hazır.")
                        messagebox.showinfo("Doküman arşivi",
                                            "Doküman arşivi oluşturuldu.\nDoküman referansları sonraki analizlerde "
                                            "rapora eklenecek.")
                    else:
                        stage_var.set("Doküman arşivi oluşturulamadı.")
                        messagebox.showerror("Doküman arşivi", "Doküman arşivi oluşturulamadı. Ayrıntı pencere "
                                                               "günlüğünde.")
                elif kind == "error":
                    msg, lp = val
                    set_busy(False)
                    stage_var.set("Hata: işlem tamamlanamadı.")
                    logbox.insert("end", f"\nHATA: {msg}\nAyrıntı: {lp}\n")
                    logbox.see("end")
                    messagebox.showerror("İşlem tamamlanamadı",
                                         f"{msg}\n\nAyrıntı: {lp}")
        except queue.Empty:
            pass
        root.after(150, poll)

    def start(job: str, b: str = "", src: str | None = None):
        src = src if src is not None else src_var.get().strip()
        if not src or not Path(src).exists():
            messagebox.showwarning("Backup", "Önce 'Backup klasörü…' veya 'Backup .zip…' ile backup'ı seçin.")
            return
        logbox.delete("1.0", "end")
        summary_var.set("")
        res_frame.grid_remove()
        settings.save({"author": author_var.get().strip(), "department": dept_var.get().strip(),
                       "out_root": out_root_var.get().strip()})
        set_busy(True)
        stage_var.set("Başlıyor…")
        threading.Thread(target=worker, daemon=True, args=(job, src, b)).start()

    def start_compare():
        if not src_var.get().strip():
            messagebox.showwarning("Backup", "Önce A backup'ını (yukarıda) seçin.")
            return
        if messagebox.askyesno("Backup B", "Karşılaştırılacak backup (B) bir .zip mi?\n(Hayır = klasör)"):
            b = filedialog.askopenfilename(title="Karşılaştırılacak backup (B)", initialdir=init_dir(),
                                           filetypes=[("Zip", "*.zip"), ("Tümü", "*.*")])
        else:
            b = filedialog.askdirectory(title="Karşılaştırılacak backup klasörü (B)", initialdir=init_dir())
        if b:
            start("compare", b)

    def start_kb():
        messagebox.showinfo("Doküman arşivi",
                            "Siemens dokümanlarının (manual, readme; PDF / Markdown) bulunduğu klasörü veya .zip'i "
                            "seçin. Arşiv bir kez oluşturulur ve bu PC'de kalır.")
        if messagebox.askyesno("Doküman arşivi", "Dokümanlar bir .zip içinde mi?\n(Hayır = klasör)"):
            p = filedialog.askopenfilename(title="Doküman arşivi (.zip)", filetypes=[("Zip", "*.zip"), ("Tümü", "*.*")])
        else:
            p = filedialog.askdirectory(title="Doküman arşivi klasörü")
        if p:
            start("kb", src=p)

    run_btn.configure(command=lambda: start("inventory" if fixed and mode == "inventory" else "analysis"))
    inv_btn.configure(command=lambda: start("inventory"))
    col_btn.configure(command=lambda: start("collect"))
    cmp_btn.configure(command=start_compare)
    kb_btn.configure(command=start_kb)
    index_btn.configure(command=lambda: result["path"] and webbrowser.open(result["path"].resolve().as_uri()))
    word_btn.configure(command=lambda: result["out"] and (result["out"] / "rapor.docx").exists()
                       and _open_file(result["out"] / "rapor.docx"))
    excel_btn.configure(command=lambda: excel_file() and _open_file(excel_file()))
    folder_btn.configure(command=lambda: result["out"] and _open_file(result["out"]))
    root.after(150, poll)
    root.mainloop()
    return 0
