"""
Basit masaüstü penceresi: backup (klasör veya .zip) seç -> Çalıştır -> rapor tarayıcıda açılır.
Sadece standart kütüphane (tkinter). Renkler rapordaki Siemens token'larıyla aynı.
"""
from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from pathlib import Path

from . import __version__
from .cli import DEFAULT_TARGET, default_out_dir, run
from .report import SIEMENS_TOKENS as T


def main() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"PCS 7 Upgrade Analyzer {__version__}")
    root.geometry("860x620")
    root.minsize(700, 480)
    root.configure(bg=T["light-sand"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    font = ("Segoe UI", 10)
    style.configure(".", font=font, background=T["light-sand"], foreground=T["deep-blue"])
    style.configure("TLabel", background=T["light-sand"], foreground=T["deep-blue"])
    style.configure("TEntry", fieldbackground=T["white"])
    style.configure("Primary.TButton", background=T["petrol"], foreground=T["white"], borderwidth=0, padding=(18, 8),
                    font=("Segoe UI", 10, "bold"))
    style.map("Primary.TButton", background=[("active", T["deep-blue-700"]), ("disabled", T["deep-blue-300"])])
    style.configure("TButton", background=T["white"], foreground=T["deep-blue"], padding=(10, 5))
    style.configure("Horizontal.TProgressbar", background=T["petrol"], troughcolor=T["deep-blue-50"])

    header = tk.Frame(root, bg=T["deep-blue"])
    header.pack(fill="x")
    tk.Label(header, text="SIMATIC PCS 7 · UPGRADE ÖN DEĞERLENDİRME", bg=T["deep-blue"], fg=T["bold-green"],
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=20, pady=(14, 0))
    tk.Label(header, text="Proje backup analizi", bg=T["deep-blue"], fg=T["white"],
             font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=20, pady=(0, 12))
    tk.Frame(root, bg=T["petrol"], height=4).pack(fill="x")

    body = ttk.Frame(root, padding=20)
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)

    src_var = tk.StringVar()
    out_var = tk.StringVar()
    tgt_var = tk.StringVar(value=DEFAULT_TARGET)
    rel_var = tk.StringVar()
    disc_var = tk.BooleanVar(value=False)

    def pick_dir():
        p = filedialog.askdirectory(title="Backup klasörü")
        if p:
            src_var.set(p)
            if not out_var.get():
                out_var.set(str(default_out_dir(Path(p))))

    def pick_zip():
        p = filedialog.askopenfilename(title="Backup .zip", filetypes=[("Zip", "*.zip"), ("Tümü", "*.*")])
        if p:
            src_var.set(p)
            if not out_var.get():
                out_var.set(str(default_out_dir(Path(p))))

    def pick_out():
        p = filedialog.askdirectory(title="Rapor klasörü")
        if p:
            out_var.set(p)

    def pick_rel():
        p = filedialog.askopenfilename(title="Released Modules CSV", filetypes=[("CSV", "*.csv")])
        if p:
            rel_var.set(p)

    r = 0
    ttk.Label(body, text="Backup").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(body, textvariable=src_var).grid(row=r, column=1, sticky="ew", padx=8)
    bf = ttk.Frame(body)
    bf.grid(row=r, column=2, sticky="e")
    ttk.Button(bf, text="Klasör…", command=pick_dir).pack(side="left", padx=2)
    ttk.Button(bf, text="Zip…", command=pick_zip).pack(side="left", padx=2)
    r += 1
    ttk.Label(body, text="Rapor klasörü").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(body, textvariable=out_var).grid(row=r, column=1, sticky="ew", padx=8)
    ttk.Button(body, text="Seç…", command=pick_out).grid(row=r, column=2, sticky="e")
    r += 1
    ttk.Label(body, text="Hedef versiyon").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(body, textvariable=tgt_var, width=16).grid(row=r, column=1, sticky="w", padx=8)
    r += 1
    ttk.Label(body, text="Released Modules CSV").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(body, textvariable=rel_var).grid(row=r, column=1, sticky="ew", padx=8)
    ttk.Button(body, text="Seç…", command=pick_rel).grid(row=r, column=2, sticky="e")
    r += 1
    ttk.Checkbutton(body, text="Sadece keşif (klasör yapısı)", variable=disc_var).grid(row=r, column=1, sticky="w", padx=8)
    r += 1

    actions = ttk.Frame(body)
    actions.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(12, 8))
    run_btn = ttk.Button(actions, text="Analizi başlat", style="Primary.TButton")
    run_btn.pack(side="left")
    open_btn = ttk.Button(actions, text="Raporu aç", state="disabled")
    open_btn.pack(side="left", padx=8)
    bar = ttk.Progressbar(actions, mode="indeterminate", length=200)
    bar.pack(side="right")
    r += 1

    logbox = tk.Text(body, height=14, bg=T["deep-blue"], fg=T["deep-blue-50"], insertbackground=T["white"],
                     font=("Consolas", 9), relief="flat", padx=8, pady=6)
    logbox.grid(row=r, column=0, columnspan=3, sticky="nsew")
    body.rowconfigure(r, weight=1)
    ttk.Label(body, text="Backup sadece okunur; hiçbir dosyası değiştirilmez.", foreground=T["deep-blue-500"]) \
        .grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    q: queue.Queue = queue.Queue()
    result = {"path": None}

    def log(msg):
        q.put(("log", str(msg)))

    def worker(src, out, tgt, rel, disc):
        try:
            p = run(Path(src), Path(out) if out else None, tgt or DEFAULT_TARGET, Path(rel) if rel else None, disc, log)
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
                    result["path"] = val
                    open_btn.configure(state="normal")
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
            messagebox.showwarning("Backup", "Önce backup klasörünü veya .zip dosyasını seçin.")
            return
        logbox.delete("1.0", "end")
        run_btn.configure(state="disabled")
        open_btn.configure(state="disabled")
        bar.start(12)
        threading.Thread(target=worker, daemon=True,
                         args=(src, out_var.get().strip(), tgt_var.get().strip(), rel_var.get().strip(),
                               disc_var.get())).start()

    def open_report():
        if result["path"]:
            webbrowser.open(Path(result["path"]).resolve().as_uri())

    run_btn.configure(command=start)
    open_btn.configure(command=open_report)
    root.after(150, poll)
    root.mainloop()
    return 0
