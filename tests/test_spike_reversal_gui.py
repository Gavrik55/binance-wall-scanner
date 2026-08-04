import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

import gui as guimod


tmp = tempfile.gettempdir()
guimod.HEDGEHOG_BOOTSTRAP_ENABLED = False
guimod.CONFIG_FILE = os.path.join(tmp, "test_spike_reversal_config.json")
guimod.UI_SETTINGS_FILE = os.path.join(tmp, "test_spike_reversal_ui_settings.json")
guimod.SPIKE_REVERSAL_SETTINGS_FILE = os.path.join(tmp, "test_spike_reversal_settings.json")
for path in (guimod.CONFIG_FILE, guimod.UI_SETTINGS_FILE, guimod.SPIKE_REVERSAL_SETTINGS_FILE):
    if os.path.exists(path):
        os.remove(path)

root = tk.Tk()
app = guimod.App(root)

assert hasattr(app, "reversal_tree")
assert app.hedgehog_scanner.spike_reversal_return_pct == app.reversal_return_pct
print("OK: spike reversal tab exists and scanner received settings")

now = time.time()
fake = [{
    "exchange": "BINANCE",
    "symbol": "WICKUSDT",
    "last": 1.0,
    "rev_ready": True,
    "rev_samples": 50,
    "rev_count": 3,
    "rev_down_count": 3,
    "rev_up_count": 0,
    "rev_last_side": "down",
    "rev_last_ts": now - 20,
    "rev_last_price": 0.998,
    "rev_last_extreme": 0.970,
    "rev_last_move_pct": 3.0,
    "rev_last_return_pct": 93.0,
    "rev_last_duration_sec": 75.0,
    "rev_avg_move_pct": 2.7,
    "rev_best_move_pct": 3.0,
}]
stats = {"relevant": 2, "ready": 2, "with_events": 1, "candidates": 1, "max_samples": 50}
app._update_reversal_tree(fake, stats)
rows = app.reversal_tree.get_children()
print("reversal rows:", rows)
assert len(rows) == 1
values = app.reversal_tree.item(rows[0], "values")
assert values[0:4] == ("BINANCE", "WICKUSDT", "ПАДЕНИЕ+ОТКУП", "3"), values
assert "повторов 3+" in app.reversal_status_var.get()

app.reversal_filter_vars["down"].set(False)
app._on_reversal_filter_changed()
assert app.reversal_tree.get_children() == ()
app.reversal_filter_vars["down"].set(True)
app._on_reversal_filter_changed()
assert len(app.reversal_tree.get_children()) == 1
print("OK: spike reversal filter hides and restores rows")

app.reversal_return_entry.delete(0, "end")
app.reversal_return_entry.insert(0, "85")
app.reversal_min_move_entry.delete(0, "end")
app.reversal_min_move_entry.insert(0, "2")
app.reversal_history_entry.delete(0, "end")
app.reversal_history_entry.insert(0, "60")
app._apply_reversal_settings()
assert app.reversal_return_pct == 85.0
assert app.reversal_min_move_pct == 2.0
assert app.hedgehog_scanner.spike_reversal_return_pct == 85.0
assert app.hedgehog_scanner.spike_reversal_history_sec == 3600.0
print("OK: spike reversal settings apply to scanner")

app._on_close()
print("\nALL SPIKE REVERSAL GUI TESTS PASSED")
