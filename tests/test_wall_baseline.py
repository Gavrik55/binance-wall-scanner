import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig
from orderbook import OrderBook


def make_ob_usd(bids_usd, ask_price=1.5):
    ob = OrderBook("TESTUSDT")
    ob.bids = {p: usd / p for p, usd in bids_usd.items()}
    ob.asks = {ask_price: 1.0}
    ob.synced = True
    return ob


def new_detector(threshold=10_000, wall_min_components=3):
    det = WallDetector()
    cfg = SymbolConfig("TESTUSDT", threshold, "LONG", exchange="BINANCE", mode="FIXED",
                        max_distance_pct=200.0, wall_max_distance_pct=200.0,
                        wall_min_components=wall_min_components)
    det.set_config(cfg)
    return det


def age_candidates(det, key, seconds):
    for pk in det.wall_candidate_seen.get(key, {}):
        det.wall_candidate_seen[key][pk] -= seconds


key = "BINANCE:TESTUSDT"

# --- 1) 3 равные плотности УЖЕ СТОЯТ на первом (baseline) скане -> НИКОГДА не алертят WALL,
# даже после 10+ секунд многократного пересканирования ---
det = new_detector()
ob = make_ob_usd({1.00: 50_000, 1.03: 50_000, 1.06: 50_000})
events1 = det.scan("BINANCE", "TESTUSDT", ob)  # это и есть baseline-тик
assert not [e for e in events1 if e.kind == "WALL"], "на baseline-тике WALL не должен сработать"
age_candidates(det, key, 11.0)
events2 = det.scan("BINANCE", "TESTUSDT", ob)
assert not [e for e in events2 if e.kind == "WALL"], "стенка, стоявшая ДО запуска, не должна алертить даже после 10+ сек"
assert det.known_clusters[key][0]["baseline"] is True
print("OK: стенка, уже стоявшая на старте, никогда не даёт WALL")

# --- 2) та же baseline-стенка потом ИСЧЕЗАЕТ -> WALL_GONE тоже не должен сработать ---
ob_gone = make_ob_usd({0.5: 100})
events3 = det.scan("BINANCE", "TESTUSDT", ob_gone)
assert not [e for e in events3 if e.kind == "WALL_GONE"], "распад baseline-стенки не должен алертить WALL_GONE"
print("OK: распад стенки, о которой не объявляли (baseline), тоже не алертит")

# --- 3) РЕГРЕССИЯ: стенка, сформировавшаяся ПОСЛЕ baseline-тика -> алертит как обычно ---
det2 = new_detector()
det2.scan("BINANCE", "TESTUSDT", make_ob_usd({0.5: 100}))  # baseline-тик - пусто, ничего интересного
ob2 = make_ob_usd({1.00: 50_000, 1.03: 50_000, 1.06: 50_000})  # НОВАЯ стенка после baseline
events4 = det2.scan("BINANCE", "TESTUSDT", ob2)
assert not [e for e in events4 if e.kind == "WALL"], "сразу ещё рано, устойчивость не набрана"
age_candidates(det2, key, 11.0)
events5 = det2.scan("BINANCE", "TESTUSDT", ob2)
walls5 = [e for e in events5 if e.kind == "WALL"]
assert len(walls5) == 1, f"новая стенка (после baseline) должна сработать нормально, получено {len(walls5)}"
assert det2.known_clusters[key][0]["baseline"] is False
print("OK: стенка, сформировавшаяся ПОСЛЕ старта, алертит как обычно (регрессия не сломана)")

# --- 4) и её распад -> WALL_GONE тоже срабатывает нормально ---
events6 = det2.scan("BINANCE", "TESTUSDT", make_ob_usd({0.5: 100}))
walls_gone6 = [e for e in events6 if e.kind == "WALL_GONE"]
assert len(walls_gone6) == 1, f"распад НЕ-baseline стенки должен алертить WALL_GONE, получено {len(walls_gone6)}"
print("OK: распад настоящей (не baseline) стенки алертит WALL_GONE нормально")

print("\nALL WALL BASELINE TESTS PASSED")
