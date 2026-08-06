import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_scan
from collections import deque

scanner = market_scan.MarketScanner(lambda t: None, exchanges=["BINANCE"])

# симулируем окно "ерша": цена скачет между 1.00 (низ) и 1.012 (верх, диапазон ~1.2%,
# как в примере со скриншота), каждые 30 сек новая точка, кумулятивный объём растёт
now = time.time()
dq = deque()
n_points = int(market_scan.HEDGEHOG_WINDOW_SEC / 30) + 5  # с запасом
cum_vol = 100_000.0
for i in range(n_points):
    ts = now - (n_points - i) * 30
    # чередуем верх/низ диапазона (ёрш-паттерн)
    price = 1.012 if i % 2 == 0 else 1.000
    cum_vol += 50.0  # $50 за каждые 30 сек -> $100/мин -> $6000/60мин, $1000/10мин
    dq.append((ts, price, cum_vol))

metrics = scanner._hedgehog_metrics(dq, now)
print("metrics:", metrics)

assert metrics["hh_samples"] >= market_scan.HEDGEHOG_MIN_SAMPLES
assert metrics["hh_ready"] is True, "должно хватить точек для прогрева"
assert 1.0 < metrics["hh_range_pct"] < 1.3, f"диапазон должен быть ~1.2%, получили {metrics['hh_range_pct']}"
# чередование через раз -> касания и верха, и низа примерно у половины точек
assert metrics["hh_touch_top"] > 0.3, metrics
assert metrics["hh_touch_bot"] > 0.3, metrics
assert metrics["hh_low"] == 1.000, metrics
assert metrics["hh_high"] == 1.012, metrics
assert metrics["hh_needle_count"] >= 10, metrics
print("OK: диапазон и касания посчитаны корректно для чередующегося паттерна")

# объём: $100/мин * 60 = $6000 за 60 мин, $100/мин * 10 = $1000 за 10 мин (с точностью до дискретизации)
print(f"vol_60m={metrics['vol_60m']:.0f} (ожидаем ~6000), vol_10m={metrics['vol_10m']:.0f} (ожидаем ~1000)")
assert 5000 <= metrics["vol_60m"] <= 7000, metrics
assert 800 <= metrics["vol_10m"] <= 1200, metrics
print("OK: объём за 60м/10м в разумных пределах")

# --- сравнение: монотонный тренд (НЕ ёрш) должен иметь маленькое touch у одной из границ ---
dq2 = deque()
cum_vol2 = 100_000.0
for i in range(n_points):
    ts = now - (n_points - i) * 30
    price = 1.000 + (i / n_points) * 0.20  # монотонный рост на 20% - широкий диапазон, не ёрш
    cum_vol2 += 50.0
    dq2.append((ts, price, cum_vol2))
metrics2 = scanner._hedgehog_metrics(dq2, now)
print("\nmonotonic trend metrics:", {k: v for k, v in metrics2.items() if k.startswith('hh')})
assert metrics2["hh_range_pct"] > 15, "монотонный тренд должен иметь широкий диапазон, не узкий"
print("OK: монотонный тренд корректно НЕ выглядит как узкий ёрш (широкий range_pct)")

# --- hedgehog_candidates: сортировка по возрастанию range_pct ---
t_narrow = dict(exchange="BINANCE", symbol="NARROWUSDT", hh_ready=True, hh_range_pct=1.2)
t_wide = dict(exchange="BINANCE", symbol="WIDEUSDT", hh_ready=True, hh_range_pct=25.0)
t_not_ready = dict(exchange="BINANCE", symbol="WARMINGUPUSDT", hh_ready=False, hh_range_pct=0.5)
cands = market_scan.MarketScanner.hedgehog_candidates([t_wide, t_narrow, t_not_ready], n=10)
print("\ncandidates order:", [c["symbol"] for c in cands])
assert [c["symbol"] for c in cands] == ["NARROWUSDT", "WIDEUSDT"], "узкий диапазон должен быть первым, непрогретый исключён"
print("OK: hedgehog_candidates сортирует по возрастанию диапазона и фильтрует непрогретые")

# --- hedgehog_event_candidates: отдельная лента событий берёт только Binance futures/Bybit,
# узкий диапазон и минимум переходов верх/низ. Спот и широкий диапазон не должны попадать.
t_event = dict(exchange="BINANCE", symbol="EVENTUSDT", hh_ready=True, hh_range_pct=1.1,
               hh_needle_count=4, hh_low=1.0, hh_high=1.011, quote_volume=100000)
t_bybit = dict(exchange="BYBIT", symbol="BYBITUSDT", hh_ready=True, hh_range_pct=1.4,
               hh_needle_count=5, hh_low=2.0, hh_high=2.028, quote_volume=90000)
t_spot = dict(exchange="BINANCE SPOT", symbol="SPOTUSDT", hh_ready=True, hh_range_pct=1.0,
              hh_needle_count=10, hh_low=1.0, hh_high=1.01, quote_volume=100000)
t_quiet = dict(exchange="BINANCE", symbol="QUIETUSDT", hh_ready=True, hh_range_pct=1.0,
               hh_needle_count=1, hh_low=1.0, hh_high=1.01, quote_volume=100000)
t_wide_event = dict(exchange="BYBIT", symbol="WIDE2USDT", hh_ready=True, hh_range_pct=8.0,
                    hh_needle_count=8, hh_low=1.0, hh_high=1.08, quote_volume=100000)
events = market_scan.MarketScanner.hedgehog_event_candidates(
    [t_event, t_bybit, t_spot, t_quiet, t_wide_event], n=10)
event_symbols = [c["symbol"] for c in events]
print("\nevent candidates:", event_symbols)
assert event_symbols == ["BYBITUSDT", "EVENTUSDT"], event_symbols
print("OK: лента событий ершей фильтрует биржи, диапазон и иголки")

# --- bootstrap helper: минутная свеча должна сохранять high/low, иначе быстрые фитили пропадут ---
entries = market_scan._history_entries_from_klines([
    (now - 120, 1.0, 1.03, 0.99, 1.02, 100.0),
    (now - 60, 1.02, 1.04, 1.00, 1.01, 150.0),
], cumulative_quote_volume_end=1000.0)
prices = [p for _ts, p, _vol in entries]
volumes = [v for _ts, _p, v in entries]
assert 1.04 in prices and 0.99 in prices, prices
assert volumes == sorted(volumes), volumes
assert abs(volumes[-1] - 1000.0) < 1e-9, volumes[-1]
print("OK: bootstrap свечей сохраняет high/low и синтетический кумулятивный объём")

print("\nALL HEDGEHOG MATH TESTS PASSED")
