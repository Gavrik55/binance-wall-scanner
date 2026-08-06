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

from ws_manager import ExchangeWSManager


def noop(*_args, **_kwargs):
    pass


binance = ExchangeWSManager("BINANCE", noop, noop, on_trade_update=noop)
streams = binance._streams_for_symbol("BTCUSDT")
assert "btcusdt@depth@100ms" in streams
assert "btcusdt@trade" in streams
print("OK: Binance subscribes to depth and raw trade streams")

spot = ExchangeWSManager("BINANCE SPOT", noop, noop, on_trade_update=noop)
spot_streams = spot._streams_for_symbol("ETHUSDT")
assert "ethusdt@depth@100ms" in spot_streams
assert "ethusdt@trade" in spot_streams
print("OK: Binance Spot subscribes to depth and raw trade streams")

aster = ExchangeWSManager("ASTERDEX", noop, noop, on_trade_update=noop)
aster_streams = aster._streams_for_symbol("BTCUSDT")
assert aster_streams == ["btcusdt@depth@100ms"]
print("OK: AsterDEX remains depth-only until its trade stream is verified")

print("\nALL WS MANAGER TRADE STREAM TESTS PASSED")
