import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig
from orderbook import OrderBook


def make_ob(bids, asks):
    ob = OrderBook("TESTUSDT")
    ob.bids = dict(bids)
    ob.asks = dict(asks)
    ob.synced = True
    return ob


def new_detector(**kwargs):
    det = WallDetector()
    cfg = SymbolConfig("TESTUSDT", 50_000, "LONG", exchange="BINANCE", mode="FIXED", **kwargs)
    det.set_config(cfg)
    return det, cfg


def prime(det):
    det.scan("BINANCE", "TESTUSDT", make_ob({0.5: 0.0001}, {1.5: 1.0}))


# плотность появляется большой (200к), потом её частично съедают (осталось 100к
# из price*qty), и цена как раз в этот момент доходит до уровня -> магнит должен
# показать текущий остаток и сколько съедено в $ и %
det, cfg = new_detector(magnet_window_min_sec=2.0, magnet_window_max_sec=10.0)
prime(det)
ob_big = make_ob({1.00: 200_000, 1.01: 0.001}, {1.02: 1.0})  # 200к плотность, best_bid=1.01 (не тронула ещё)
det.scan("BINANCE", "TESTUSDT", ob_big)
w = det.active_walls["BINANCE:TESTUSDT"][1.00]
w.first_seen -= 3.0  # прошло 3с, входит в окно [2,10]
assert w.max_qty == 200_000

# теперь съели половину (осталось 100к по qty) и цена дошла до уровня
ob_eaten = make_ob({1.00: 100_000}, {1.02: 1.0})  # best_bid == 1.00 -> touched
events = det.scan("BINANCE", "TESTUSDT", ob_eaten)
magnet = [e for e in events if e.kind == "MAGNET"]
assert len(magnet) == 1
print("MAGNET extra:", magnet[0].extra)
assert "$100,000" in magnet[0].extra, magnet[0].extra  # осталось
assert "$100,000" in magnet[0].extra.split("(")[1], magnet[0].extra  # съедено тоже 100к (200к-100к)
assert "50%" in magnet[0].extra, magnet[0].extra
print("ALL MAGNET VOLUME TESTS PASSED")
