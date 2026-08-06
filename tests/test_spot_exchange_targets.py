import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    fake_requests = types.ModuleType("requests")
    fake_requests.get = lambda *_args, **_kwargs: None
    sys.modules["requests"] = fake_requests

try:
    import websockets  # noqa: F401
except ModuleNotFoundError:
    fake_websockets = types.ModuleType("websockets")
    fake_websockets.connect = None
    sys.modules["websockets"] = fake_websockets

import gui


app = object.__new__(gui.App)

assert gui.BASE_EXCHANGE_CHOICES == ["BINANCE", "ASTERDEX", "GATE", "OKX", "MEXC"]
assert "BINANCE SPOT" in gui.EXCHANGE_CHOICES
assert "OKX SPOT" in gui.EXCHANGE_CHOICES
assert "MEXC SPOT" in gui.EXCHANGE_CHOICES
assert "BINANCE ALPHA" in gui.EXCHANGE_CHOICES
print("OK: concrete exchange list contains futures and spot markets")

targets, label = app._exchange_targets_for_selection("BINANCE")
assert targets == ["BINANCE"]
assert label == "BINANCE"
print("OK: selecting BINANCE targets only the futures market")

targets, label = app._exchange_targets_for_selection(gui.ALL_EXCHANGES_LABEL)
assert targets == gui.EXCHANGE_CHOICES
assert "GATE SPOT" in targets and "OKX SPOT" in targets
print("OK: all-exchanges selection targets all futures + spot markets")

assert app._base_exchange_for("ASTERDEX SPOT") == "ASTERDEX"
assert app._base_exchange_for("GATE") == "GATE"
print("OK: editing spot rows maps back to base exchange in UI")

assert app._config_targets_for_exchange("BINANCE") == ["BINANCE"]
assert app._config_targets_for_exchange("BINANCE SPOT") == ["BINANCE SPOT"]
print("OK: saved rows load as exact markets")

calls = []
app._add_symbol = lambda symbol, threshold, direction, **kwargs: calls.append(
    (symbol, threshold, direction, kwargs)
)
count = app._apply_config_data([{
    "exchange": "OKX",
    "symbol": "BTCUSDT",
    "threshold": 10000,
    "direction": "BOTH",
    "mode": "AUTO",
    "muted": True,
    "threshold_max": 50000,
    "max_distance_pct": 7,
    "single_confirm_sec": 0.2,
}])
assert count == 1
assert [call[3]["exchange"] for call in calls] == ["OKX"]
assert all(call[3]["exact_exchange"] for call in calls)
assert all(call[3]["single_confirm_sec"] == 0.2 for call in calls)
print("OK: config import/load applies exact markets")

print("\nALL SPOT EXCHANGE TARGET TESTS PASSED")
