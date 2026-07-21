import sys, os, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_movers_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)
print("App created OK, notebook tabs:", app.notebook.tabs())

# симулируем market update напрямую (без ожидания реального фонового потока)
fake_tickers = [
    {"exchange": "BINANCE", "symbol": "AAAUSDT", "last": 1.0, "change_pct_24h": 25.0, "quote_volume": 500000, "impulse_pct": 3.5},
    {"exchange": "GATE", "symbol": "BBBUSDT", "last": 2.0, "change_pct_24h": -18.0, "quote_volume": 300000, "impulse_pct": -1.0},
    {"exchange": "OKX", "symbol": "CCCUSDT", "last": 0.5, "change_pct_24h": 10.0, "quote_volume": 100000, "impulse_pct": 0.2},
]
app._update_movers_trees(fake_tickers)

gainers_rows = app.gainers_tree.get_children()
losers_rows = app.losers_tree.get_children()
print("gainers rows:", gainers_rows)
print("losers rows:", losers_rows)
assert "BINANCE:AAAUSDT" in gainers_rows
assert "BINANCE:AAAUSDT" in app.gainers_tree.get_children()  # с импульсом 3.5% > 2.0% highlight
tags = app.gainers_tree.item("BINANCE:AAAUSDT", "tags")
print("AAAUSDT tags (должен быть impulse, т.к. 3.5% >= 2.0%):", tags)
assert tags == ("impulse",)

vals = app.gainers_tree.item("BINANCE:AAAUSDT", "values")
print("AAAUSDT values:", vals)
assert "⚡" in vals[4]

# теперь эмулируем двойной клик -> должен добавить в сканер
class FakeEvent:
    widget = app.gainers_tree
app.gainers_tree.selection_set("BINANCE:AAAUSDT")
app._on_mover_double_click(FakeEvent())
assert "BINANCE:AAAUSDT" in app.orderbooks, "монета должна была добавиться в сканер"
cfg = app.detector.configs["BINANCE:AAAUSDT"]
assert cfg.mode == "AUTO", f"режим должен быть AUTO, получено {cfg.mode}"
assert cfg.threshold_usd == guimod.MOVER_ADD_DEFAULT_FLOOR
print("OK: двойной клик добавил монету в сканер с режимом AUTO, порог-пол =", cfg.threshold_usd)

root.destroy()
print("ALL MOVERS GUI TESTS PASSED")
