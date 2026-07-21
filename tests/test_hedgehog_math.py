import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_scan
from collections import deque

scanner = market_scan.MarketScanner(lambda t: None, exchanges=["BINANCE"])

# симулируем 90 минут "ерша": цена скачет между 1.00 (низ) и 1.012 (верх, диапазон ~1.2%,
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

assert metrics["hh_ready"] is True, "должно хватить точек за 90 минут прогрева"
assert 1.0 < metrics["hh_range_pct"] < 1.3, f"диапазон должен быть ~1.2%, получили {metrics['hh_range_pct']}"
# чередование через раз -> касания и верха, и низа примерно у половины точек
assert metrics["hh_touch_top"] > 0.3, metrics
assert metrics["hh_touch_bot"] > 0.3, metrics
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

print("\nALL HEDGEHOG MATH TESTS PASSED")
