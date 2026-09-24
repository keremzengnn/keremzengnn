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
from .cli import TARGET_LABEL, default_out_dir, run
from .report import SIEMENS_TOKENS as T


def _open_file(p: Path) -> None:
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]  # Windows: ilişkili programla aç
    except (AttributeError, OSError):
        webbrowser.open(Path(p).resolve().as_uri())


def main() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"PCS 7 Upgrade Analyzer {__version__}")
    root.geometry("900x700")
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
    tk.Label(header, text="SIMATIC PCS 7 · UPGRADE ÖN DEĞERLENDİRME", bg=T["deep-blue"], fg=T["bold-green"],
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=22, pady=(14, 0))
    tk.Label(header, text=f"Proje backup analizi → {TARGET_LABEL}", bg=T["deep-blue"], fg=T["white"],
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

    # 2) Rapor bilgileri
    ttk.Label(body, text="2  Rapor bilgileri", font=("Segoe UI", 11, "bold")).grid(row=r, column=0, sticky="w", pady=(0, 6))
    r += 1
    for label, var in (("Hazırlayan", author_var), ("Departman", dept_var), ("Müşteri / proje (kapak)", cust_var)):
        ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=var).grid(row=r, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        r += 1
    ttk.Label(body, text="Rapor klasörü").grid(row=r, column=0, sticky="w", pady=3)
    ttk.Entry(body, textvariable=out_var).grid(row=r, column=1, sticky="ew", padx=8)
    ttk.Button(body, text="Değiştir…", command=pick_out).grid(row=r, column=2, sticky="e")
    r += 1
    ttk.Checkbutton(body, text="Sadece keşif (klasör yapısını raporla, analiz yapma)", variable=disc_var) \
        .grid(row=r, column=1, columnspan=2, sticky="w", padx=8, pady=(4, 0))
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
    ttk.Label(body, text=f"Backup sadece okunur; hiçbir dosyası değiştirilmez ve hiçbir yere gönderilmez. "
                         f"Hedef: {TARGET_LABEL}.", style="Hint.TLabel") \
        .grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    q: queue.Queue = queue.Queue()
    result = {"path": None}

    def log(msg):
        q.put(("log", str(msg)))

    def worker(src, out, disc, author, dept, cust):
        try:
            p = run(Path(src), Path(out) if out else None, discover_only=disc, log=log,
                    author=author, department=dept, customer=cust or None)
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
                    if (Path(val).parent / "rapor.docx").exists():
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
                               cust_var.get().strip())).start()

    run_btn.configure(command=start)
    open_btn.configure(command=lambda: result["path"] and webbrowser.open(result["path"].resolve().as_uri()))
    word_btn.configure(command=lambda: result["path"] and _open_file(result["path"].parent / "rapor.docx"))
    folder_btn.configure(command=lambda: result["path"] and _open_file(result["path"].parent))
    root.after(150, poll)
    root.mainloop()
    return 0
