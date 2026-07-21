import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_clipboard_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)


def clip():
    root.update()
    try:
        return root.clipboard_get()
    except tk.TclError:
        return None


# --- 1) основная таблица сканера: двойной клик -> редактирует И копирует ---
app._add_symbol("BTCUSDT", 100000, "LONG", exchange="BINANCE", mode="FIXED", silent=True)
app.tree.selection_set("BINANCE:BTCUSDT")
app._edit_selected(None)
assert clip() == "BTCUSDT", f"должно скопироваться BTCUSDT, получено {clip()!r}"
assert app.symbol_entry.get() == "BTCUSDT", "редактирование по-прежнему должно работать"
print("OK: основная таблица - двойной клик и копирует, и подставляет в поля редактирования")

# --- 2) активные плотности ---
app._update_walls_tree("BINANCE", "EVAAUSDT", [
    {"price": 0.755, "side": "bid", "usd": 62716, "age": 6, "dist_pct": 1.27},
])
app.walls_tree.selection_set("BINANCE:EVAAUSDT|0.755")
app._copy_symbol_from_tree(app.walls_tree, 1)
assert clip() == "EVAAUSDT", f"получено {clip()!r}"
print("OK: 'Активные плотности' копирует тикер по двойному клику")

# --- 3) лента алертов ---
from detector import WallEvent
ev = WallEvent("BINANCE", "LABUSDT", "CASCADE", 0.82, 0, "bid", extra="тест")
app._render_event(ev)
first_row = app.log.get_children()[0]
app.log.selection_set(first_row)
app._copy_symbol_from_tree(app.log, 2)
assert clip() == "LABUSDT", f"получено {clip()!r}"
print("OK: 'Лента алертов' копирует тикер по двойному клику")

# --- 4) топ движений: двойной клик -> добавляет в сканер И копирует ---
fake_tickers = [
    {"exchange": "OKX", "symbol": "MOVERUSDT", "last": 1.0, "change_pct_24h": 15.0,
     "quote_volume": 100000, "impulse_pct": 0.5},
]
app._update_movers_trees(fake_tickers)
app.gainers_tree.selection_set("OKX:MOVERUSDT")
class FakeEvent:
    widget = app.gainers_tree
app._on_mover_double_click(FakeEvent())
assert clip() == "MOVERUSDT", f"получено {clip()!r}"
assert "OKX:MOVERUSDT" in app.orderbooks, "должно было ещё и добавиться в сканер, как раньше"
print("OK: 'Топ движений' копирует тикер И по-прежнему добавляет в сканер")

# --- 5) ерши ---
app._update_hedgehog_tree([
    {"exchange": "BYBIT", "symbol": "HHUSDT", "last": 2.0, "hh_ready": True,
     "hh_range_pct": 1.0, "hh_touch_top": 0.3, "hh_touch_bot": 0.3, "vol_60m": 1000, "vol_10m": 100},
])
app.hedgehog_tree.selection_set("BYBIT:HHUSDT")
app._copy_symbol_from_tree(app.hedgehog_tree, 1)
assert clip() == "HHUSDT", f"получено {clip()!r}"
print("OK: 'Ерши' копирует тикер по двойному клику")

root.destroy()
print("\nALL CLIPBOARD COPY TESTS PASSED")
