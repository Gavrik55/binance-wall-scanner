import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig
from orderbook import OrderBook

def make_ob(bids):
    ob = OrderBook("TESTUSDT")
    ob.bids = dict(bids)
    ob.asks = {1.02: 1.0}  # близко к bid, чтобы плотность попадала в пределы max_distance_pct
    ob.synced = True
    return ob

# APPEARED теперь отложен до single_confirm_sec — проверяем факт попадания/
# непопадания в отслеживаемые walls (active_walls), а не мгновенный алерт.

# --- режим "от-до" (threshold_max задан): плотность ВНЕ диапазона игнорируется ---
det = WallDetector()
cfg = SymbolConfig("TESTUSDT", 100_000, "LONG", exchange="BINANCE", mode="FIXED", threshold_max_usd=150_000)
det.set_config(cfg)

ob = make_ob({1.0: 400_000})  # $400k плотность, вне диапазона 100k-150k
det.scan("BINANCE", "TESTUSDT", ob)
assert not det.active_walls["BINANCE:TESTUSDT"], "режим от-до: 400k НЕ должен пройти при диапазоне 100k-150k"
print("OK: режим от-до отсеивает плотность вне верхней границы")

det_b = WallDetector()
det_b.set_config(cfg)
ob2 = make_ob({1.0: 120_000})  # $120k — внутри 100k-150k
det_b.scan("BINANCE", "TESTUSDT", ob2)
assert 1.0 in det_b.active_walls["BINANCE:TESTUSDT"], "режим от-до: 120k ДОЛЖЕН пройти при диапазоне 100k-150k"
print("OK: режим от-до пропускает плотность внутри диапазона")

# --- режим "от и выше" (threshold_max=None): любой размер >= threshold проходит ---
det2 = WallDetector()
cfg2 = SymbolConfig("TESTUSDT", 100_000, "LONG", exchange="BINANCE", mode="FIXED", threshold_max_usd=None)
det2.set_config(cfg2)
ob3 = make_ob({1.0: 400_000})
det2.scan("BINANCE", "TESTUSDT", ob3)
assert 1.0 in det2.active_walls["BINANCE:TESTUSDT"], "режим от-и-выше: 400k ДОЛЖЕН пройти при пороге 100k без верхней границы"
print("OK: режим от-и-выше пропускает 400k при пороге 100k (без разницы, насколько крупная)")

print("ALL DETECTOR TESTS PASSED")
