import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig
from orderbook import OrderBook


def make_ob(bids, asks, mid_hint=None):
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
    """Прогревочный скан на почти пустом стакане — чтобы первый РЕАЛЬНЫЙ тик
    с плотностью не попал под baseline-подавление (is_baseline_tick
    срабатывает на самом первом скане символа, см. detector.py)."""
    det.scan("BINANCE", "TESTUSDT", make_ob({0.5: 0.0001}, {1.5: 1.0}))


# ============ ОДИНОЧНАЯ ПЛОТНОСТЬ: подтверждение через single_confirm_sec ============

# 1) плотность появилась -> НЕ должно быть немедленного APPEARED
det, cfg = new_detector(single_confirm_sec=10.0)
prime(det)
ob = make_ob({1.00: 100_000}, {1.02: 1.0})
events = det.scan("BINANCE", "TESTUSDT", ob)
appeared = [e for e in events if e.kind == "APPEARED"]
assert not appeared, f"APPEARED не должен приходить сразу, получено {len(appeared)}"
w = det.active_walls["BINANCE:TESTUSDT"][1.00]
assert w.confirmed is False
print("OK: плотность появилась -> APPEARED сразу не приходит (ждёт подтверждения)")

# 2) имитируем ход времени: подделываем first_seen, чтобы прошло >= 10 сек, скан снова
w.first_seen -= 11.0
events2 = det.scan("BINANCE", "TESTUSDT", ob)
appeared2 = [e for e in events2 if e.kind == "APPEARED"]
assert len(appeared2) == 1, f"после 10+ сек стабильности должен прийти APPEARED, получено {len(appeared2)}"
assert w.confirmed is True
print("OK: после single_confirm_sec (10с) стабильности -> приходит APPEARED, confirmed=True")

# 3) теперь плотность исчезает -> должен прийти EATEN/PULLED, т.к. уже confirmed
# (оставляем крошечный "прочий" бид, чтобы mid() было из чего считать — иначе
# скан целиком прерывается раньше времени просто из-за пустого стакана)
ob_gone = make_ob({1.005: 0.0001}, {1.02: 1.0})
events3 = det.scan("BINANCE", "TESTUSDT", ob_gone)
removal = [e for e in events3 if e.kind in ("EATEN", "PULLED")]
assert len(removal) == 1, f"после подтверждения снятие должно алертить, получено {len(removal)}"
print(f"OK: подтверждённая плотность исчезла -> {removal[0].kind}")

# 4) плотность появилась и исчезла ДО подтверждения (короткий спуф) -> вообще без алертов
det4, cfg4 = new_detector(single_confirm_sec=10.0)
prime(det4)
ob4a = make_ob({1.00: 100_000}, {1.02: 1.0})
det4.scan("BINANCE", "TESTUSDT", ob4a)
w4 = det4.active_walls["BINANCE:TESTUSDT"][1.00]
w4.first_seen -= 3.0  # прошло всего 3 сек, меньше 10
ob4b = make_ob({1.005: 0.0001}, {1.02: 1.0})  # исчезла раньше срока (mid считаем от прочего бида)
events4b = det4.scan("BINANCE", "TESTUSDT", ob4b)
any_single = [e for e in events4b if e.kind in ("APPEARED", "EATEN", "PULLED")]
assert not any_single, f"спуф до подтверждения не должен давать НИКАКИХ алертов, получено {[e.kind for e in any_single]}"
assert 1.00 not in det4.active_walls["BINANCE:TESTUSDT"], "запись должна быть тихо удалена"
print("OK: плотность исчезла ДО подтверждения (спуф) -> ни одного алерта, тихо забыта")

# ============ МАГНИТ: цена должна РЕАЛЬНО дойти до уровня в окне 2-10 сек ============

# 5) плотность появилась, цена БЛИЗКО но НЕ дошла -> магнит не должен сработать
det5, cfg5 = new_detector(magnet_window_min_sec=2.0, magnet_window_max_sec=10.0)
prime(det5)
ob5 = make_ob({1.00: 100_000}, {1.001: 1.0})  # best_bid будет max(bids)=1.00 (сама плотность же best bid)
# чтобы плотность НЕ была best_bid (иначе она автоматически "touched"), добавим более высокий бид
ob5.bids = {1.00: 100_000, 1.01: 0.001}  # 1.01 - крошечный уровень, но formально best_bid
events5 = det5.scan("BINANCE", "TESTUSDT", ob5)
w5 = det5.active_walls["BINANCE:TESTUSDT"][1.00]
w5.first_seen -= 3.0  # прошло 3 сек, входит в окно [2,10]
events5b = det5.scan("BINANCE", "TESTUSDT", ob5)  # цена всё ещё НЕ дошла (best_bid=1.01 > 1.00, не touched)
magnet5 = [e for e in events5b if e.kind == "MAGNET"]
assert not magnet5, f"цена не дошла до уровня -> магнита быть не должно, получено {len(magnet5)}"
print("OK: цена НЕ дошла до уровня плотности -> MAGNET не срабатывает")

# 6) теперь цена реально доходит до уровня (best_bid опускается до/ниже price плотности)
ob6 = make_ob({1.00: 100_000, 1.005: 0.001}, {1.02: 1.0})  # best_bid=1.005 -> ещё не тронула 1.00
# опустим best_bid до уровня плотности
ob6b = make_ob({1.00: 100_000}, {1.02: 1.0})  # best_bid == 1.00 == цена плотности -> touched=True
events6 = det5.scan("BINANCE", "TESTUSDT", ob6b)
magnet6 = [e for e in events6 if e.kind == "MAGNET"]
assert len(magnet6) == 1, f"цена дошла до уровня в пределах окна -> должен быть MAGNET, получено {len(magnet6)}"
print("OK: цена дошла/пересекла уровень плотности в окне 2-10с -> MAGNET срабатывает:", magnet6[0].extra)

# 7) окно раньше 2 сек: даже если цена дошла, МАГНИТ не должен сработать (проверим на новом стейте)
det7, cfg7 = new_detector(magnet_window_min_sec=2.0, magnet_window_max_sec=10.0)
prime(det7)
ob7 = make_ob({1.00: 100_000}, {1.02: 1.0})
det7.scan("BINANCE", "TESTUSDT", ob7)  # age=0, touched=True сразу (best_bid==price), но age < 2 сек
events7 = det7.scan("BINANCE", "TESTUSDT", ob7)
magnet7 = [e for e in events7 if e.kind == "MAGNET"]
assert not magnet7, f"age < magnet_window_min_sec -> магнита быть не должно, получено {len(magnet7)}"
print("OK: цена дошла слишком рано (< magnet_window_min_sec) -> MAGNET не срабатывает")

print("ALL MAGNET/CONFIRM TESTS PASSED")
