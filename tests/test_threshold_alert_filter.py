import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig
from orderbook import OrderBook


def make_ob_usd(bids_usd, ask_price=1.1):
    ob = OrderBook("TESTUSDT")
    ob.synced = True
    ob.bids = {p: usd / p for p, usd in bids_usd.items()}
    ob.asks = {ask_price: 1.0}
    return ob


def make_detector(threshold=20_000, threshold_max=None):
    det = WallDetector()
    det.set_config(SymbolConfig(
        "TESTUSDT",
        threshold,
        "LONG",
        exchange="BINANCE",
        mode="FIXED",
        threshold_max_usd=threshold_max,
        single_confirm_sec=10.0,
    ))
    det.scan("BINANCE", "TESTUSDT", make_ob_usd({0.5: 100}))  # baseline-тик
    return det


det = make_detector()
det.scan("BINANCE", "TESTUSDT", make_ob_usd({1.0: 25_000}))
w = det.active_walls["BINANCE:TESTUSDT"][1.0]
w.first_seen -= 11
events = det.scan("BINANCE", "TESTUSDT", make_ob_usd({1.0: 17_000}))
assert not [e for e in events if e.kind == "APPEARED"]
assert 1.0 not in det.active_walls["BINANCE:TESTUSDT"]
print("OK: неподтверждённая плотность, похудевшая ниже 'от $', не даёт APPEARED")

det2 = make_detector(threshold=20_000, threshold_max=30_000)
det2.scan("BINANCE", "TESTUSDT", make_ob_usd({1.0: 25_000}))
w2 = det2.active_walls["BINANCE:TESTUSDT"][1.0]
w2.first_seen -= 11
events2 = det2.scan("BINANCE", "TESTUSDT", make_ob_usd({1.0: 35_000}))
assert not [e for e in events2 if e.kind == "APPEARED"]
assert 1.0 not in det2.active_walls["BINANCE:TESTUSDT"]
print("OK: неподтверждённая плотность, выросшая выше 'до $', не даёт APPEARED")

det3 = make_detector()
det3.scan("BINANCE", "TESTUSDT", make_ob_usd({1.0: 25_000}))
w3 = det3.active_walls["BINANCE:TESTUSDT"][1.0]
w3.first_seen -= 11
events3 = det3.scan("BINANCE", "TESTUSDT", make_ob_usd({1.0: 24_000}))
assert len([e for e in events3 if e.kind == "APPEARED"]) == 1
print("OK: плотность, оставшаяся в диапазоне, подтверждается как раньше")

print("\nALL THRESHOLD ALERT FILTER TESTS PASSED")
