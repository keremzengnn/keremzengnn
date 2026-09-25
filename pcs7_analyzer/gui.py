"""
Masaüstü penceresi: backup (klasör veya .zip) seç -> Analizi başlat -> HTML rapor açılır, Word raporu hazır.
Hedef sabit: PCS 7 V10.0 SP2. Word template ve Released Modules listesi program içinde gömülü.
Sadece standart kütüphane (tkinter). Renkler rapordaki Siemens token'larıyla aynı.
"""
from __future__ import annotations

import os
import queue
import threading
import traceback
import webbrowser
from pathlib import Path

from . import __version__, settings
from .analyze import ManualInputs
from .cli import TARGET_LABEL, default_out_dir, run
from .report import SIEMENS_TOKENS as T


def _open_file(p: Path) -> None:
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]  # Windows: ilişkili programla aç
    except (AttributeError, OSError):
        webbrowser.open(Path(p).resolve().as_uri())


def main(mode: str = "analysis", fixed: bool = False) -> int:
    """mode: 'analysis' | 'inventory'; fixed=True -> mod seçimi gizli (ayrı envanter exe'si)."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"PCS 7 Upgrade Analyzer {__version__}")
    root.geometry("900x780")
    root.minsize(720, 560)
    root.configure(bg=T["light-sand"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", font=("Segoe UI", 10), background=T["light-sand"], foreground=T["deep-blue"])
    style.configure("TLabel", background=T["light-sand"], foreground=T["deep-blue"])
    style.configure("Hint.TLabel", foreground=T["deep-blue-500"])
    style.configure("Path.TLabel", background=T["white"], foreground=T["deep-blue"], padding=(10, 8), relief="flat")
    style.configure("TEntry", fieldbackground=T["white"])
    style.configure("Primary.TButton", background=T["petrol"], foreground=T["white"], borderwidth=0, padding=(22, 10),
                    font=("Segoe UI", 11, "bold"))
    style.map("Primary.TButton", background=[("active", T["deep-blue-700"]), ("disabled", T["deep-blue-300"])])
    style.configure("Pick.TButton", background=T["deep-blue"], foreground=T["white"], borderwidth=0, padding=(16, 10),
                    font=("Segoe UI", 10, "bold"))
    style.map("Pick.TButton", background=[("active", T["petrol"])])
    style.configure("TButton", background=T["white"], foreground=T["deep-blue"], padding=(12, 6))
    style.configure("Horizontal.TProgressbar", background=T["petrol"], troughcolor=T["deep-blue-50"])

    header = tk.Frame(root, bg=T["deep-blue"])
    header.pack(fill="x")
    topline = "SIMATIC PCS 7 · PROJE ENVANTERİ" if fixed and mode == "inventory" else "SIMATIC PCS 7 · UPGRADE ÖN DEĞERLENDİRME"
    tk.Label(header, text=topline, bg=T["deep-blue"], fg=T["bold-green"],
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=22, pady=(14, 0))
    title = "Proje backup envanteri" if fixed and mode == "inventory" else f"Proje backup analizi → {TARGET_LABEL}"
    tk.Label(header, text=title, bg=T["deep-blue"], fg=T["white"],
             font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=22, pady=(0, 12))
    tk.Frame(root, bg=T["petrol"], height=4).pack(fill="x")

    body = ttk.Frame(root, padding=22)
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)

    st = settings.load()
    src_var = tk.StringVar()
    src_show = tk.StringVar(value="Henüz backup seçilmedi")
    out_var = tk.StringVar()
    author_var = tk.StringVar(value=st.get("author", ""))
    dept_var = tk.StringVar(value=st.get("department", ""))
    cust_var = tk.StringVar()
    disc_var = tk.BooleanVar(value=False)
    mode_var = tk.StringVar(value=mode)

    def set_source(p: str) -> None:
        src_var.set(p)
        src_show.set(p)
        out_var.set(str(default_out_dir(Path(p), Path(st.get("out_root")) if st.get("out_root") else None)))

    def pick_dir():
        p = filedialog.askdirectory(title="Backup klasörünü seçin")
        if p:
            set_source(p)

    def pick_zip():
        p = filedialog.askopenfilename(title="Backup .zip dosyasını seçin", filetypes=[("Zip", "*.zip"), ("Tümü", "*.*")])
        if p:
            set_source(p)

    def pick_out():
        p = filedialog.askdirectory(title="Raporların kaydedileceği klasör")
        if p:
            out_var.set(p)

    # 1) Backup seçimi
    r = 0
    ttk.Label(body, text="1  Backup", font=("Segoe UI", 11, "bold")).grid(row=r, column=0, sticky="w", pady=(0, 6))
    r += 1
    picks = ttk.Frame(body)
    picks.grid(row=r, column=0, columnspan=3, sticky="w")
    ttk.Button(picks, text="Backup klasörü seç…", style="Pick.TButton", command=pick_dir).pack(side="left")
    ttk.Button(picks, text="Backup .zip seç…", style="Pick.TButton", command=pick_zip).pack(side="left", padx=8)
    r += 1
    ttk.Label(body, textvariable=src_show, style="Path.TLabel").grid(row=r, column=0, columnspan=3, sticky="ew", pady=(8, 14))
    r += 1

    # 2) Mod ve rapor bilgileri
    ttk.Label(body, text="2  Ayarlar" if fixed else "2  Ne yapılsın?", font=("Segoe UI", 11, "bold")) \
        .grid(row=r, column=0, sticky="w", pady=(0, 6))
    r += 1
    info_rows = []
    if not fixed:
        mf = ttk.Frame(body)
        mf.grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Radiobutton(mf, text=f"Analiz: {TARGET_LABEL} upgrade değerlendirmesi (Word + Excel + HTML)", value="analysis",
                        variable=mode_var).pack(anchor="w")
        ttk.Radiobutton(mf, text="Envanter: backup'taki her şeyi listele, değerlendirme yapma (Excel + HTML)",
                        value="inventory", variable=mode_var).pack(anchor="w")
        r += 1
    for label, var in (("Hazırlayan", author_var), ("Departman", dept_var), ("Müşteri / proje (kapak)", cust_var)):
        lab = ttk.Label(body, text=label)
        lab.grid(row=r, column=0, sticky="w", pady=3)
        ent = ttk.Entry(body, textvariable=var)
        ent.grid(row=r, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        info_rows.append((lab, ent))
        r += 1

    # Opsiyonel (sadece analiz): backup dışındaki WinCC export'ları ve manuel girişler (boş = raporda "eksik")
    exp_var, po_as, po_os, po_arc, pcs_var = (tk.StringVar() for _ in range(5))

    def pick_exports():
        p = filedialog.askdirectory(title="WinCC Configuration Studio export klasörü (Tag / Alarm .txt)")
        if p:
            exp_var.set(p)

    lab = ttk.Label(body, text="WinCC export klasörü (ops.)")
    lab.grid(row=r, column=0, sticky="w", pady=3)
    ent = ttk.Entry(body, textvariable=exp_var)
    ent.grid(row=r, column=1, sticky="ew", padx=8)
    btn = ttk.Button(body, text="Seç…", command=pick_exports)
    btn.grid(row=r, column=2, sticky="e")
    info_rows.append((lab, ent, btn))
    r += 1
    lab = ttk.Label(body, text="PO (ops.): AS RT / OS / archive")
    lab.grid(row=r, column=0, sticky="w", pady=3)
    pof = ttk.Frame(body)
    pof.grid(row=r, column=1, columnspan=2, sticky="w", padx=8)
    for v in (po_as, po_os, po_arc):
        ttk.Entry(pof, textvariable=v, width=12).pack(side="left", padx=(0, 6))
    ttk.Label(pof, text="(PCS 7 License Information)", style="Hint.TLabel").pack(side="left")
    info_rows.append((lab, pof))
    r += 1
    lab = ttk.Label(body, text="PC station listesi (ops.)")
    lab.grid(row=r, column=0, sticky="w", pady=3)
    ent = ttk.Entry(body, textvariable=pcs_var)
    ent.grid(row=r, column=1, columnspan=2, sticky="ew", padx=(8, 0))
    info_rows.append((lab, ent))
    r += 1

    def on_mode(*_):
        for widgets in info_rows:
            for w in widgets:
                if mode_var.get() == "inventory":
                    w.grid_remove()
                else:
                    w.grid()
        inv = mode_var.get() == "inventory"
        word_btn.configure(text="Excel'i aç" if inv else "Word'ü aç")
        run_btn.configure(text="3  Envanteri çıkar" if inv else "3  Analizi başlat")
        if inv:
            disc_chk.grid_remove()
        else:
            disc_chk.grid()
        hint.configure(text="Backup sadece okunur; hiçbir dosyası değiştirilmez ve hiçbir yere gönderilmez. "
                            + ("Envanter değerlendirme içermez; yapi_tanisi.txt müşteri verisi içermez." if inv
                               else f"Hedef: {TARGET_LABEL}."))
    ttk.Label(body, text="Rapor klasörü").grid(row=r, column=0, sticky="w", pady=3)
    ttk.Entry(body, textvariable=out_var).grid(row=r, column=1, sticky="ew", padx=8)
    ttk.Button(body, text="Değiştir…", command=pick_out).grid(row=r, column=2, sticky="e")
    r += 1
    disc_chk = ttk.Checkbutton(body, text="Sadece keşif (klasör yapısını raporla, analiz yapma)", variable=disc_var)
    disc_chk.grid(row=r, column=1, columnspan=2, sticky="w", padx=8, pady=(4, 0))
    r += 1

    # 3) Çalıştır
    actions = ttk.Frame(body)
    actions.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(14, 8))
    run_btn = ttk.Button(actions, text="3  Analizi başlat", style="Primary.TButton")
    run_btn.pack(side="left")
    open_btn = ttk.Button(actions, text="Raporu aç (HTML)", state="disabled")
    open_btn.pack(side="left", padx=(12, 6))
    word_btn = ttk.Button(actions, text="Word'ü aç", state="disabled")
    word_btn.pack(side="left")
    folder_btn = ttk.Button(actions, text="Klasörü aç", state="disabled")
    folder_btn.pack(side="left", padx=6)
    bar = ttk.Progressbar(actions, mode="indeterminate", length=160)
    bar.pack(side="right")
    r += 1

    logbox = tk.Text(body, height=10, bg=T["deep-blue"], fg=T["deep-blue-50"], insertbackground=T["white"],
                     font=("Consolas", 9), relief="flat", padx=8, pady=6)
    logbox.grid(row=r, column=0, columnspan=3, sticky="nsew")
    body.rowconfigure(r, weight=1)
    hint = ttk.Label(body, style="Hint.TLabel")
    hint.grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    q: queue.Queue = queue.Queue()
    result = {"path": None}

    def log(msg):
        q.put(("log", str(msg)))

    def worker(src, out, disc, author, dept, cust, inv, manual, exports):
        try:
            p = run(Path(src), Path(out) if out else None, discover_only=disc, log=log,
                    author=author, department=dept, customer=cust or None, inventory=inv,
                    manual=manual, exports=exports)
            q.put(("done", p))
        except Exception as e:  # noqa: BLE001
            q.put(("log", traceback.format_exc()))
            q.put(("error", str(e)))

    def poll():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "log":
                    logbox.insert("end", val + "\n")
                    logbox.see("end")
                elif kind == "done":
                    bar.stop()
                    run_btn.configure(state="normal")
                    result["path"] = Path(val)
                    open_btn.configure(state="normal")
                    folder_btn.configure(state="normal")
                    if (Path(val).parent / "rapor.docx").exists() or (Path(val).parent / "envanter.xlsx").exists():
                        word_btn.configure(state="normal")
                    logbox.insert("end", f"\nTamamlandı: {val}\n")
                    logbox.see("end")
                    webbrowser.open(Path(val).resolve().as_uri())
                elif kind == "error":
                    bar.stop()
                    run_btn.configure(state="normal")
                    messagebox.showerror("Hata", val)
        except queue.Empty:
            pass
        root.after(150, poll)

    def start():
        src = src_var.get().strip()
        if not src or not Path(src).exists():
            messagebox.showwarning("Backup", "Önce 'Backup klasörü seç' veya 'Backup .zip seç' ile backup'ı seçin.")
            return
        logbox.delete("1.0", "end")
        for b in (run_btn, open_btn, word_btn, folder_btn):
            b.configure(state="disabled")
        out = out_var.get().strip()
        settings.save({"author": author_var.get().strip(), "department": dept_var.get().strip(),
                       "out_root": str(Path(out).parent) if out else ""})
        bar.start(12)
        threading.Thread(target=worker, daemon=True,
                         args=(src, out, disc_var.get(), author_var.get().strip(), dept_var.get().strip(),
                               cust_var.get().strip(), mode_var.get() == "inventory",
                               ManualInputs(as_rt_po=po_as.get().strip(), os_po=po_os.get().strip(),
                                            archive_tags=po_arc.get().strip(),
                                            pc_stations=[x.strip() for x in pcs_var.get().replace(";", ",").split(",")
                                                         if x.strip()]),
                               [Path(exp_var.get().strip())] if exp_var.get().strip() else [])).start()

    run_btn.configure(command=start)
    open_btn.configure(command=lambda: result["path"] and webbrowser.open(result["path"].resolve().as_uri()))
    def open_second():
        if not result["path"]:
            return
        for n in ("envanter.xlsx", "rapor.docx") if mode_var.get() == "inventory" else ("rapor.docx",):
            if (result["path"].parent / n).exists():
                _open_file(result["path"].parent / n)
                return

    word_btn.configure(command=open_second)
    mode_var.trace_add("write", on_mode)
    on_mode()
    folder_btn.configure(command=lambda: result["path"] and _open_file(result["path"].parent))
    root.after(150, poll)
    root.mainloop()
    return 0
