import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_hedgehog_gui_config.json")
guimod.HEDGEHOG_EVENT_SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "test_hedgehog_event_settings.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)
if os.path.exists(guimod.HEDGEHOG_EVENT_SETTINGS_FILE):
    os.remove(guimod.HEDGEHOG_EVENT_SETTINGS_FILE)

root = tk.Tk()
app = guimod.App(root)
print("App created OK, tabs:", app.notebook.tabs())
hh_keys = set(app.hedgehog_scanner._fetchers.keys())
assert hh_keys == set(guimod.HEDGEHOG_EXCHANGES), hh_keys
assert "MEXC" not in hh_keys, "MEXC не должен попадать в Ерши"
print("OK: hedgehog_scanner = HEDGEHOG_EXCHANGES (futures+spot), без MEXC")

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

book = app._summarize_hedgehog_book(
    bids=[["1.001", "25000"]],
    asks=[["1.019", "5000"]],
    low=1.0,
    high=1.02,
)
print("book confirmation:", book)
assert book["confirmed"] is True
assert "низ" in book["text"]

event = {
    "ts": 1_700_000_000.0,
    "kind": "HEDGEHOG_BOOK",
    "exchange": "BINANCE",
    "symbol": "TIGHTUSDT",
    "last": 1.01,
    "range_pct": 2.0,
    "needles": 5,
    "low": 1.0,
    "high": 1.02,
    "touch_top": 0.4,
    "touch_bot": 0.5,
    "book": book,
    "notify": False,
}
app._render_hedgehog_event(event)
event_rows = app.hedgehog_events_tree.get_children()
print("hedgehog event rows:", event_rows)
assert len(event_rows) == 1
values = app.hedgehog_events_tree.item(event_rows[0], "values")
assert values[1:4] == ("BINANCE", "TIGHTUSDT", "СТАКАН"), values
app.hedgehog_event_filter_vars["HEDGEHOG_BOOK"].set(False)
app._apply_hedgehog_event_filters()
assert app.hedgehog_events_tree.get_children() == ()
app.hedgehog_event_filter_vars["HEDGEHOG_BOOK"].set(True)
app._apply_hedgehog_event_filters()
assert len(app.hedgehog_events_tree.get_children()) == 1
print("OK: новая лента событий ершей отрисовывается и фильтруется")

root.destroy()
print("ALL HEDGEHOG GUI TESTS PASSED")
