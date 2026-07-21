import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_all_exchanges_live_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)

app.symbol_entry.insert(0, "BTCUSDT")
app.threshold_entry.insert(0, "100000")
app.exchange_combo.set(guimod.ALL_EXCHANGES_LABEL)
app._add_symbol()


def check():
    print("orderbooks keys:", list(app.orderbooks.keys()))
    print("status_var:", app.status_var.get())
    assert len(app.orderbooks) == 4, f"BTCUSDT должен найтись на всех 4 биржах (реальная сеть), получено {len(app.orderbooks)}"
    for exch in guimod.EXCHANGE_CHOICES:
        assert f"{exch}:BTCUSDT" in app.orderbooks
    print("OK: BTCUSDT добавлен на все 4 реальные биржи через живую валидацию")
    root.destroy()


root.after(8000, check)
root.mainloop()
print("EXIT OK")
