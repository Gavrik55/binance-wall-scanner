import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_hedgehog_gui_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)
print("App created OK, tabs:", app.notebook.tabs())
assert app.hedgehog_scanner._fetchers.keys() == {"BINANCE", "BYBIT"}, app.hedgehog_scanner._fetchers.keys()
print("OK: hedgehog_scanner ограничен BINANCE+BYBIT")

fake_tickers = [
    {"exchange": "BINANCE", "symbol": "TIGHTUSDT", "last": 1.0, "hh_ready": True,
     "hh_range_pct": 1.2, "hh_touch_top": 0.5, "hh_touch_bot": 0.4, "vol_60m": 5000, "vol_10m": 700},
    {"exchange": "BYBIT", "symbol": "WIDEUSDT", "last": 2.0, "hh_ready": True,
     "hh_range_pct": 25.0, "hh_touch_top": 0.1, "hh_touch_bot": 0.1, "vol_60m": 500000, "vol_10m": 90000},
    {"exchange": "BINANCE", "symbol": "WARMUPUSDT", "last": 3.0, "hh_ready": False,
     "hh_range_pct": 0.0, "hh_touch_top": 0.0, "hh_touch_bot": 0.0, "vol_60m": 0, "vol_10m": 0},
]
app._update_hedgehog_tree(fake_tickers)
rows = app.hedgehog_tree.get_children()
print("rows:", rows)
assert rows == ("BINANCE:TIGHTUSDT", "BYBIT:WIDEUSDT"), rows
assert "BINANCE:WARMUPUSDT" not in rows, "непрогретые не должны показываться"
print("values TIGHTUSDT:", app.hedgehog_tree.item("BINANCE:TIGHTUSDT", "values"))

root.destroy()
print("ALL HEDGEHOG GUI TESTS PASSED")
