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


def new_detector(threshold=10_000, wall_min_components=3, single_confirm_sec=10.0,
                  wall_volume_tolerance_usd=30_000.0):
    det = WallDetector()
    cfg = SymbolConfig("TESTUSDT", threshold, "LONG", exchange="BINANCE", mode="FIXED",
                        max_distance_pct=200.0, wall_max_distance_pct=200.0,
                        wall_min_components=wall_min_components,
                        single_confirm_sec=single_confirm_sec,
                        wall_volume_tolerance_usd=wall_volume_tolerance_usd)
    det.set_config(cfg)
    return det


def prime(det):
    det.scan("BINANCE", "TESTUSDT", make_ob_usd({0.5: 100}))


def age_all_wall_candidates(det, key, seconds):
    for pk in det.wall_candidate_seen.get(key, {}):
        det.wall_candidate_seen[key][pk] -= seconds


# --- 1) допуск по объёму (общий разброс, не по цепочке): 129к/155к/170к
# (разброс 41к > 30к) НЕ должны сложиться при дефолтном допуске 30к, а
# 135к/155к/160к (разброс 25к) — должны ---
det = new_detector()
prime(det)
ob = make_ob_usd({1.00: 135_000, 1.03: 155_000, 1.06: 160_000})
det.scan("BINANCE", "TESTUSDT", ob)  # первый тик - только начали отслеживать кандидатов
age_all_wall_candidates(det, "BINANCE:TESTUSDT", 11.0)  # состарили на 11 сек > single_confirm_sec
events = det.scan("BINANCE", "TESTUSDT", ob)
walls = [e for e in events if e.kind == "WALL"]
assert len(walls) == 1, f"135к/155к/160к (разброс 25к) должны сложиться в 1 стенку, получено {len(walls)}"
print("OK: 135к/155к/160к (разброс 25к, в пределах допуска 30к) -> СТЕНКА:", walls[0].extra)

# --- 2) органический шум: 10к/20к/50к (разброс 40к, больше допуска 30к) -> НЕ стенка ---
det2 = new_detector()
prime(det2)
ob2 = make_ob_usd({1.00: 10_000, 1.03: 20_000, 1.06: 50_000})
det2.scan("BINANCE", "TESTUSDT", ob2)
age_all_wall_candidates(det2, "BINANCE:TESTUSDT", 11.0)
events2 = det2.scan("BINANCE", "TESTUSDT", ob2)
walls2 = [e for e in events2 if e.kind == "WALL"]
assert not walls2, f"10к/20к/50к разбросаны шире допуска -> не стенка, получено {len(walls2)}"
print("OK: 10к/20к/50к (широкий разброс 40к) -> НЕ стенка")

# --- 3) устойчивость: 3 равные плотности мелькнули на 1 тик и ИСЧЕЗЛИ -> НЕ стенка (спуф) ---
det3 = new_detector()
prime(det3)
ob3 = make_ob_usd({1.00: 50_000, 1.03: 50_000, 1.06: 50_000})
events3a = det3.scan("BINANCE", "TESTUSDT", ob3)  # тик 1: появились
assert not [e for e in events3a if e.kind == "WALL"], "не должно сработать сразу, до устойчивости"
ob3_gone = make_ob_usd({0.5: 100})  # тик 2: исчезли (спуф - убрали раньше 10 сек)
events3b = det3.scan("BINANCE", "TESTUSDT", ob3_gone)
assert not [e for e in events3b if e.kind == "WALL"], "спуф (мелькнули и пропали) не должен дать стенку"
# candidate_seen должен был вычиститься для пропавших
assert not det3.wall_candidate_seen.get("BINANCE:TESTUSDT"), "таймеры пропавших кандидатов должны сброситься"
print("OK: 3 равные плотности мелькнули 1 тик и пропали -> НЕ стенка (устойчивость отсекла спуф)")

# --- 4) устойчивость: те же самые появляются заново и ПРОСТАИВАЮТ 10 сек -> стенка срабатывает ---
det4 = new_detector()
prime(det4)
ob4 = make_ob_usd({1.00: 50_000, 1.03: 50_000, 1.06: 50_000})
det4.scan("BINANCE", "TESTUSDT", ob4)  # тик 1: появились, candidate_seen = now
events4a = det4.scan("BINANCE", "TESTUSDT", ob4)  # тик 2: всё ещё < 10 сек
assert not [e for e in events4a if e.kind == "WALL"], "рано, ещё не простояли 10 сек"
age_all_wall_candidates(det4, "BINANCE:TESTUSDT", 11.0)
events4b = det4.scan("BINANCE", "TESTUSDT", ob4)  # тик 3: уже простояли 10+ сек
walls4b = [e for e in events4b if e.kind == "WALL"]
assert len(walls4b) == 1, f"после 10 сек устойчивости должна сработать СТЕНКА, получено {len(walls4b)}"
print("OK: 3 равные плотности простояли 10+ сек -> СТЕНКА сработала:", walls4b[0].extra)

print("\nALL WALL TOLERANCE/STABILITY TESTS PASSED")
