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


assert gui._normalize_symbol_input("bank", "BINANCE") == "BANKUSDT"
assert gui._normalize_symbol_input("bankusdt", "BINANCE SPOT") == "BANKUSDT"
assert gui._normalize_symbol_input("BTC/USDT", "MEXC SPOT") == "BTCUSDT"
orig_resolve_alpha_symbol = gui.resolve_alpha_symbol
gui.resolve_alpha_symbol = lambda value: "ALPHA_1005USDT" if str(value).upper() in {"CAP", "CAPUSDT"} else str(value).upper()
try:
    assert gui._normalize_symbol_input("ALPHA_175USDT", "BINANCE ALPHA") == "ALPHA_175USDT"
    assert gui._normalize_symbol_input("cap", "BINANCE ALPHA") == "ALPHA_1005USDT"
    assert gui._normalize_symbol_input("CAPUSDT", "BINANCE ALPHA") == "ALPHA_1005USDT"
finally:
    gui.resolve_alpha_symbol = orig_resolve_alpha_symbol
print("OK: symbol input normalization works")

assert gui._format_compact_usd(100_000) == "$100к"
assert gui._format_compact_usd(3_000_000) == "$3м"
assert gui._format_compact_usd(4_500) == "$4.5к"
assert gui._parse_compact_usd("100к") == 100_000
assert gui._parse_compact_usd("$3м") == 3_000_000
assert gui._parse_compact_usd("10,000") == 10_000
assert gui._parse_compact_usd("10,5к") == 10_500
print("OK: compact USD formatting/parsing works")

assert gui._format_price(63023) == "63,023"
assert gui._format_price(1.23456789) == "1.234568"
assert gui._format_price(0.00001234) == "0.00001234"
print("OK: price formatting avoids scientific notation")

print("\nALL SYMBOL NORMALIZE / COMPACT TESTS PASSED")
