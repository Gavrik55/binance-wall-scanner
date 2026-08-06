import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_scan

print("--- Bybit fetcher ---")
data = market_scan._fetch_bybit()
print(f"BYBIT: {len(data)} символов, пример: {data[0]}")
assert len(data) > 0
for d in data[:5]:
    assert d["symbol"].endswith("USDT")
    assert isinstance(d["last"], float)
    assert isinstance(d["change_pct_24h"], float)
    assert isinstance(d["quote_volume"], float)
print("OK: Bybit fetcher корректен")

print("\n--- MarketScanner(exchanges=['BINANCE','BYBIT']) ---")
market_scan.POLL_INTERVAL_SEC = 3.0
received = []
scanner = market_scan.MarketScanner(lambda t: received.append(t), exchanges=["BINANCE", "BYBIT"])
assert set(scanner._fetchers.keys()) == {"BINANCE", "BYBIT"}, scanner._fetchers.keys()
scanner.start()
time.sleep(7)
scanner.stop()

assert len(received) >= 2, f"ожидалось 2+ циклов, получено {len(received)}"
last_batch = received[-1]
exchanges_seen = {t["exchange"] for t in last_batch}
print("биржи в данных:", exchanges_seen)
assert exchanges_seen == {"BINANCE", "BYBIT"}, "не должно быть ничего кроме BINANCE/BYBIT"

sample = last_batch[0]
print("пример тикера:", sample)
for key in ("impulse_pct", "hh_samples", "hh_ready", "hh_low", "hh_high", "hh_range_pct",
            "hh_touch_top", "hh_touch_bot", "hh_needle_count", "vol_60m", "vol_10m"):
    assert key in sample, f"нет поля {key}"
print("OK: все hedgehog-поля присутствуют")

# hh_ready ожидаемо ещё False (не набралось HEDGEHOG_MIN_SAMPLES=30 точек за 2 цикла)
assert sample["hh_ready"] is False
print("OK: hh_ready=False при недостатке истории (прогрев), как и ожидалось")

# hedgehog_candidates не должен падать даже когда пока никто не 'ready'
candidates = market_scan.MarketScanner.hedgehog_candidates(last_batch, n=10)
print("кандидатов пока (должно быть 0, прогрев):", len(candidates))
assert candidates == []

print("\nALL HEDGEHOG TESTS PASSED")
