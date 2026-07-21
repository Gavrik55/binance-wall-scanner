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


def prime(det):
    det.scan("BINANCE", "TESTUSDT", make_ob_usd({0.5: 100}))


def age_and_rescan(det, ob, seconds=11.0):
    """Первый скан заводит таймер устойчивости кандидатов в стенку,
    состариваем его на seconds (> single_confirm_sec) и сканируем ещё раз —
    имитирует, что плотности реально простояли это время."""
    det.scan("BINANCE", "TESTUSDT", ob)
    key = "BINANCE:TESTUSDT"
    for pk in det.wall_candidate_seen.get(key, {}):
        det.wall_candidate_seen[key][pk] -= seconds
    return det.scan("BINANCE", "TESTUSDT", ob)


# --- 1) сильно разные объёмы (10к+50к+90к, разброс 80к > допуска 30к) -> НЕ стенка.
# (10к/20к/15к из более ранней версии этого теста теперь ЗАКОНОМЕРНО проходит:
# разброс там всего 10к, что меньше допуска 20-30к, который сами же и попросили)
det = new_detector()
prime(det)
ob = make_ob_usd({1.00: 10_000, 1.01: 50_000, 1.02: 90_000})
events = age_and_rescan(det, ob)
walls = [e for e in events if e.kind == "WALL"]
assert not walls, f"сильно разные объёмы НЕ должны формировать стенку, получено {len(walls)}"
print("OK: 10к+50к+90к (разброс 80к) рядом по цене -> НЕ стенка (органический шум)")

# --- 2) 3 плотности РАВНОГО объёма (50к) на круглых числах, ~3% друг от друга -> СТЕНКА ---
det2 = new_detector()
prime(det2)
ob2 = make_ob_usd({1.00: 50_000, 1.03: 50_000, 1.06: 50_000})  # ~3% между соседними
events2 = age_and_rescan(det2, ob2)
walls2 = [e for e in events2 if e.kind == "WALL"]
assert len(walls2) == 1, f"3 плотности по 50к рядом -> должна быть 1 стенка, получено {len(walls2)}"
print("OK: 3 плотности по $50,000 рядом -> СТЕНКА:", walls2[0].extra)

# --- 3) подгруппа внутри одного price-кластера: 3×50к + 2×100к вперемешку по цене ---
# (100к-50к=50к > допуска 30к — реально разные группы, в отличие от 75к из
# более ранней версии теста, которая теперь закономерно сливается с 50к)
# ожидаем стенку из 3×50к (набрала кворум), а 2×100к - нет (не хватило до wall_min_components=3)
det3 = new_detector()
prime(det3)
ob3 = make_ob_usd({
    1.00: 50_000, 1.01: 100_000, 1.02: 50_000, 1.03: 100_000, 1.04: 50_000,
})
events3 = age_and_rescan(det3, ob3)
walls3 = [e for e in events3 if e.kind == "WALL"]
assert len(walls3) == 1, f"должна найтись ровно 1 стенка (3×50к), получено {len(walls3)}"
assert "3 плотности" in walls3[0].extra and "50,000" in walls3[0].extra, walls3[0].extra
print("OK: подгруппа 3×50к внутри смешанного price-кластера найдена корректно:", walls3[0].extra)

# --- 4) минимум участников по-прежнему настраиваемый (3 по умолчанию) ---
det4 = new_detector(wall_min_components=3)
prime(det4)
ob4 = make_ob_usd({1.00: 50_000, 1.03: 50_000})  # только 2 - не хватает до 3
events4 = age_and_rescan(det4, ob4)
walls4 = [e for e in events4 if e.kind == "WALL"]
assert not walls4, f"2 плотности при wall_min_components=3 -> не стенка, получено {len(walls4)}"
print("OK: 2 плотности при минимуме 3 -> не стенка")

print("\nALL WALL EQUAL-VOLUME TESTS PASSED")
