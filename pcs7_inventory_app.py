"""PyInstaller giriş noktası: sadece envanter çıkaran sade pencere (PCS7Envanter.exe)."""
import sys

from pcs7_analyzer.cli import main

if __name__ == "__main__":
    if len(sys.argv) > 1:                      # komut satırından: her zaman envanter modu
        raise SystemExit(main(sys.argv[1:] + ["--inventory"]))
    from pcs7_analyzer.gui import main as gui_main
    raise SystemExit(gui_main(mode="inventory", fixed=True))
