import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

import gui as guimod

guimod.HEDGEHOG_BOOTSTRAP_ENABLED = False
guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_movers_config.json")
guimod.UI_SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "test_movers_ui_settings.json")
guimod.HEDGEHOG_EVENT_SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "test_movers_hedgehog_event_settings.json")
guimod.SPIKE_REVERSAL_SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "test_movers_spike_reversal_settings.json")
for path in (
    guimod.CONFIG_FILE,
    guimod.UI_SETTINGS_FILE,
    guimod.HEDGEHOG_EVENT_SETTINGS_FILE,
    guimod.SPIKE_REVERSAL_SETTINGS_FILE,
):
    if os.path.exists(path):
        os.remove(path)

root = tk.Tk()
app = guimod.App(root)
print("App created OK, notebook tabs:", app.notebook.tabs())

fake_tickers = [
    {"exchange": "BINANCE", "symbol": "AAAUSDT", "last": 1.0,
     "change_pct_24h": 25.0, "quote_volume": 500000, "impulse_pct": 3.5},
    {"exchange": "OKX", "symbol": "AAAUSDT", "last": 1.01,
     "change_pct_24h": 21.0, "quote_volume": 1000000, "impulse_pct": 1.1},
    {"exchange": "BYBIT", "symbol": "AAAUSDT", "last": 0.99,
     "change_pct_24h": 30.0, "quote_volume": 700000, "impulse_pct": 0.7},
    {"exchange": "GATE", "symbol": "BBBUSDT", "last": 2.0,
     "change_pct_24h": -18.0, "quote_volume": 300000, "impulse_pct": -1.0},
    {"exchange": "OKX", "symbol": "CCCUSDT", "last": 0.5,
     "change_pct_24h": 10.0, "quote_volume": 100000, "impulse_pct": 0.2},
]
app._update_movers_trees(fake_tickers)

gainers_rows = app.gainers_tree.get_children()
losers_rows = app.losers_tree.get_children()
print("gainers rows:", gainers_rows)
print("losers rows:", losers_rows)
assert "BINANCE:AAAUSDT" in gainers_rows
assert "BYBIT:AAAUSDT" not in gainers_rows, "old exchange view must stay old and hide BYBIT"
tags = app.gainers_tree.item("BINANCE:AAAUSDT", "tags")
print("AAAUSDT tags:", tags)
assert tags == ("impulse",)

vals = app.gainers_tree.item("BINANCE:AAAUSDT", "values")
print("AAAUSDT values:", vals)
assert "⚡" in vals[4]
assert vals[2] == "1"


class FakeEvent:
    widget = app.gainers_tree


app.gainers_tree.selection_set("BINANCE:AAAUSDT")
orig_add_symbol = app._add_symbol


def add_symbol_sync(*args, **kwargs):
    kwargs["exact_exchange"] = True
    return orig_add_symbol(*args, **kwargs)


app._add_symbol = add_symbol_sync
app._on_mover_double_click(FakeEvent())
assert "BINANCE:AAAUSDT" in app.orderbooks, "old double click should add one selected exchange"
cfg = app.detector.configs["BINANCE:AAAUSDT"]
assert cfg.mode == "AUTO", cfg.mode
assert cfg.threshold_usd == guimod.MOVER_ADD_DEFAULT_FLOOR
print("OK: old double click adds the selected exchange only")

app._add_symbol = orig_add_symbol
added_all = []


def add_all_stub(symbol, threshold, threshold_max, direction, mode,
                 max_distance_pct, single_confirm_sec, exchanges=None, target_label=None):
    added_all.append({
        "symbol": symbol,
        "threshold": threshold,
        "mode": mode,
        "exchanges": list(exchanges or []),
        "target_label": target_label,
    })


app._add_symbol_all_exchanges = add_all_stub
app.movers_view_var.set(guimod.MOVERS_VIEW_SYMBOL)
app._on_movers_view_changed()
group_rows = app.gainers_tree.get_children()
print("grouped gainers rows:", group_rows)
aaa_group_rows = [row for row in group_rows if app.gainers_tree.item(row, "values")[1] == "AAAUSDT"]
assert len(aaa_group_rows) == 1, aaa_group_rows
group_vals = app.gainers_tree.item(aaa_group_rows[0], "values")
print("AAAUSDT grouped values:", group_vals)
assert "BYB" in group_vals[0], group_vals
assert app.gainers_tree["displaycolumns"] == ("symbol", "change", "impulse", "volume")
assert group_vals[2], "price data may exist internally but must be hidden by displaycolumns"
assert "Σ" not in group_vals[5], group_vals
assert "|" not in group_vals[5], group_vals
assert group_vals[3] == "+30.00%", group_vals
assert group_vals[4] == "⚡ +3.50%", group_vals

app.gainers_tree.selection_set(aaa_group_rows[0])
app._on_mover_double_click(FakeEvent())
assert added_all, "grouped double click should start all-exchange add"
assert added_all[0]["symbol"] == "AAAUSDT"
assert added_all[0]["mode"] == "AUTO"
assert added_all[0]["exchanges"] == guimod.EXCHANGE_CHOICES
print("OK: grouped double click starts all-exchange add for the symbol")

app._on_close()
print("ALL MOVERS GUI TESTS PASSED")
