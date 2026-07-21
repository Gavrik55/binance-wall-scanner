import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig
from orderbook import OrderBook


def make_ob_usd(bids_usd, ask_price=1.02):
    """bids_usd: {price: желаемая сумма в $} -> qty подбирается так, чтобы price*qty == usd ровно."""
    ob = OrderBook("TESTUSDT")
    ob.bids = {p: usd / p for p, usd in bids_usd.items()}
    ob.asks = {ask_price: 1.0}
    ob.synced = True
    return ob


def new_detector(threshold=50_000, threshold_max=None, max_distance_pct=3.0):
    det = WallDetector()
    cfg = SymbolConfig("TESTUSDT", threshold, "LONG", exchange="BINANCE", mode="FIXED",
                        threshold_max_usd=threshold_max, max_distance_pct=max_distance_pct)
    det.set_config(cfg)
    return det


def prime(det, ask_price=1.02):
    """Прогревочный скан почти пустого стакана (крошечный бид ниже порога,
    чтобы было из чего считать mid()) — чтобы первый РЕАЛЬНЫЙ тик с
    плотностями не попал под baseline-подавление (см. detector.py:
    is_baseline_tick срабатывает на самом первом скане символа)."""
    det.scan("BINANCE", "TESTUSDT", make_ob_usd({ask_price - 0.02: 1.0}, ask_price=ask_price))


# --- 1) 3 равные (по $) плотности рядом по цене, появившиеся ОДНОВРЕМЕННО -> CASCADE ---
det = new_detector()
prime(det)
ob = make_ob_usd({1.00: 100_000, 1.005: 100_000, 1.01: 100_000})
events = det.scan("BINANCE", "TESTUSDT", ob)
cascades = [e for e in events if e.kind == "CASCADE"]
assert len(cascades) == 1, f"ожидался 1 CASCADE, получено {len(cascades)}"
print("OK: 3 равные соседние плотности одновременно -> 1 CASCADE:", cascades[0].extra)

# --- 2) разные объёмы рядом по цене, одновременно -> НЕ каскад ---
det2 = new_detector()
prime(det2)
ob2 = make_ob_usd({1.00: 100_000, 1.005: 120_000, 1.01: 100_000})  # средняя отличается
events2 = det2.scan("BINANCE", "TESTUSDT", ob2)
cascades2 = [e for e in events2 if e.kind == "CASCADE"]
assert len(cascades2) == 0, f"не должно быть каскада при разных объёмах, получено {len(cascades2)}"
# APPEARED теперь отложен до подтверждения (single_confirm_sec) — сразу не
# приходит ни для каскада, ни для отдельных плотностей; здесь просто
# проверяем, что все три всё равно начали отслеживаться как walls
assert len(det2.active_walls["BINANCE:TESTUSDT"]) == 3, "все три всё равно должны начать отслеживаться"
print("OK: разные объёмы рядом -> нет CASCADE, но все три плотности отслеживаются отдельно")

# --- 3) равные объёмы, но ДАЛЕКО друг от друга по цене -> НЕ каскад ---
det3 = new_detector(max_distance_pct=200.0)
prime(det3, ask_price=1.5)
ob3 = make_ob_usd({1.00: 100_000, 2.00: 100_000}, ask_price=1.5)
events3 = det3.scan("BINANCE", "TESTUSDT", ob3)
cascades3 = [e for e in events3 if e.kind == "CASCADE"]
assert len(cascades3) == 0, f"не должно быть каскада при удалённых ценах, получено {len(cascades3)}"
print("OK: равные объёмы, но далеко по цене -> нет CASCADE")

# --- 4) равные объёмы рядом, но появились НЕ одновременно (в разных тиках) -> НЕ каскад ---
det4 = new_detector()
ob4a = make_ob_usd({1.00: 100_000})
events4a = det4.scan("BINANCE", "TESTUSDT", ob4a)
assert not [e for e in events4a if e.kind == "CASCADE"]
ob4b = make_ob_usd({1.00: 100_000, 1.005: 100_000})  # первая уже была, добавилась вторая позже
events4b = det4.scan("BINANCE", "TESTUSDT", ob4b)
cascades4b = [e for e in events4b if e.kind == "CASCADE"]
assert len(cascades4b) == 0, f"появление в разных тиках не должно считаться каскадом, получено {len(cascades4b)}"
assert len(det4.active_walls["BINANCE:TESTUSDT"]) == 2, "обе плотности должны отслеживаться (просто не как каскад)"
print("OK: равные плотности, появившиеся В РАЗНЫХ тиках -> нет CASCADE (только обычный APPEARED)")

# --- 5) режим "от-до": плотность крупнее верхней границы не участвует в каскаде ---
det5 = new_detector(threshold=50_000, threshold_max=110_000)
prime(det5)
ob5 = make_ob_usd({1.00: 100_000, 1.005: 100_000, 1.01: 400_000})  # третья вне диапазона от-до
events5 = det5.scan("BINANCE", "TESTUSDT", ob5)
cascades5 = [e for e in events5 if e.kind == "CASCADE"]
assert len(cascades5) == 1, f"ожидался каскад из первых двух (третья отфильтрована режимом от-до), получено {len(cascades5)}"
assert "2 плотности" in cascades5[0].extra, cascades5[0].extra
print("OK: режим от-до корректно исключает плотность вне диапазона из каскада")

print("ALL CASCADE TESTS PASSED")
