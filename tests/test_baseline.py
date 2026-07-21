import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig
from orderbook import OrderBook


def make_ob_usd(bids_usd, ask_price=1.02):
    ob = OrderBook("TESTUSDT")
    ob.bids = {p: usd / p for p, usd in bids_usd.items()}
    ob.asks = {ask_price: 1.0}
    ob.synced = True
    return ob


def new_detector(**kwargs):
    det = WallDetector()
    cfg = SymbolConfig("TESTUSDT", 50_000, "LONG", exchange="BINANCE", mode="FIXED", **kwargs)
    det.set_config(cfg)
    return det, cfg


# 1) плотности, которые УЖЕ БЫЛИ в стакане на первом скане -> is_baseline=True, без алертов
det, cfg = new_detector(single_confirm_sec=10.0)
ob = make_ob_usd({1.00: 100_000, 1.005: 100_000})  # уже стартуем с 2 равными плотностями рядом
events = det.scan("BINANCE", "TESTUSDT", ob)
assert not events, f"на стартовом скане не должно быть НИКАКИХ событий (даже CASCADE), получено {[e.kind for e in events]}"
key = "BINANCE:TESTUSDT"
w1 = det.active_walls[key][1.00]
w2 = det.active_walls[key][1.005]
assert w1.is_baseline and w2.is_baseline
print("OK: стартовые плотности помечены is_baseline, каскада/алертов на старте нет")

# 2) продвигаем время на 11 сек -> даже подтверждение не должно дать APPEARED (это baseline)
w1.first_seen -= 11.0
events2 = det.scan("BINANCE", "TESTUSDT", ob)
assert not [e for e in events2 if e.kind == "APPEARED"], "baseline-плотность НЕ должна алертить APPEARED даже после 10+ сек"
assert w1.confirmed is False, "baseline-плотность не должна становиться confirmed вообще"
print("OK: стартовая плотность не алертит APPEARED даже после длительной стабильности")

# 3) baseline-плотность исчезает -> НЕ должно быть EATEN/PULLED
ob_gone = make_ob_usd({1.02: 0.0001})  # обе плотности пропали, оставляем прочий бид для mid()
events3 = det.scan("BINANCE", "TESTUSDT", ob_gone)
removal = [e for e in events3 if e.kind in ("EATEN", "PULLED")]
assert not removal, f"снятие baseline-плотности не должно алертить, получено {[e.kind for e in removal]}"
assert 1.00 not in det.active_walls[key] and 1.005 not in det.active_walls[key]
print("OK: снятие стартовой плотности проходит тихо, без EATEN/PULLED")

# 4) НОВАЯ плотность, появившаяся ПОСЛЕ первого скана -> обычное поведение (алертит как всегда)
det4, cfg4 = new_detector(single_confirm_sec=10.0)
ob4a = make_ob_usd({1.02: 0.0001})  # первый скан - пусто (кроме прочего бида ниже порога)
det4.scan("BINANCE", "TESTUSDT", ob4a)  # это стартовый тик, first_scan_done помечен
ob4b = make_ob_usd({1.00: 100_000, 1.02: 0.0001})  # теперь появилась НОВАЯ плотность
det4.scan("BINANCE", "TESTUSDT", ob4b)
w4 = det4.active_walls["BINANCE:TESTUSDT"][1.00]
assert w4.is_baseline is False, "плотность, появившаяся ПОСЛЕ первого скана, не должна быть baseline"
w4.first_seen -= 11.0
events4 = det4.scan("BINANCE", "TESTUSDT", ob4b)
appeared4 = [e for e in events4 if e.kind == "APPEARED"]
assert len(appeared4) == 1, f"новая плотность (после старта) должна алертить как обычно, получено {len(appeared4)}"
print("OK: плотность, появившаяся ПОСЛЕ первого скана, алертит как обычно (APPEARED после подтверждения)")

# 5) каскад из плотностей, которые были в стакане на старте -> НЕ должен сработать
det5, cfg5 = new_detector()
ob5 = make_ob_usd({1.00: 100_000, 1.005: 100_000, 1.01: 100_000})
events5 = det5.scan("BINANCE", "TESTUSDT", ob5)
assert not [e for e in events5 if e.kind == "CASCADE"], "каскад на стартовом скане не должен алертить"
print("OK: стартовый каскад (уже был в стакане) не алертит")

print("ALL BASELINE TESTS PASSED")
