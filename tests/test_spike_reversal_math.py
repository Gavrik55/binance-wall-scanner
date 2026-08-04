import os
import sys
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_scan


scanner = market_scan.MarketScanner(lambda _t: None, exchanges=["BINANCE"])
scanner.spike_reversal_return_pct = 70.0
scanner.spike_reversal_min_move_pct = 1.0
scanner.spike_reversal_history_sec = 60 * 120
scanner.spike_reversal_max_duration_sec = 120.0

now = time.time()


def make_entry(ts, price, vol):
    return (now - (7200 - ts), price, vol)


pattern = deque()
volume = 100_000.0
ts = 0
for base, low in ((1.000, 0.970), (1.010, 0.980), (1.020, 0.985)):
    for offset, price in ((0, base), (30, low), (75, base - 0.002)):
        volume += 1000
        pattern.append(make_entry(ts + offset, price, volume))
    ts += 900

metrics = scanner._spike_reversal_metrics(pattern, now)
print("spike reversal metrics:", metrics)
assert metrics["rev_ready"] is True
assert metrics["rev_count"] >= 3, metrics
assert metrics["rev_down_count"] >= 3, metrics
assert metrics["rev_up_count"] == 0, metrics
assert metrics["rev_last_side"] == "down", metrics
assert metrics["rev_last_return_pct"] >= 70.0, metrics

ticker = {
    "exchange": "BINANCE",
    "symbol": "WICKUSDT",
    "last": 1.0,
    "quote_volume": 500_000,
    **metrics,
}
candidate_symbols = [
    t["symbol"] for t in market_scan.MarketScanner.spike_reversal_candidates([ticker], n=10)
]
assert candidate_symbols == ["WICKUSDT"], candidate_symbols
print("OK: three quick drop-and-buyback reversals produce a candidate")

trend = deque()
volume = 100_000.0
for i in range(30):
    volume += 1000
    trend.append(make_entry(i * 60, 1.0 + i * 0.003, volume))
trend_metrics = scanner._spike_reversal_metrics(trend, now)
print("trend metrics:", trend_metrics)
trend_ticker = {
    "exchange": "BINANCE",
    "symbol": "TRENDUSDT",
    "last": 1.09,
    "quote_volume": 500_000,
    **trend_metrics,
}
assert market_scan.MarketScanner.spike_reversal_candidates([trend_ticker], n=10) == []
print("OK: monotonic trend is not treated as repeated spike reversal")

up_points = [
    (now - 90, 1.0),
    (now - 50, 1.05),
    (now - 15, 1.01),
]
up_events = market_scan.MarketScanner._detect_spike_reversals(
    up_points, min_move_pct=1.0, min_return_pct=70.0, max_duration_sec=120.0
)
print("up events:", up_events)
assert any(ev["side"] == "up" for ev in up_events), up_events
print("OK: quick pop-and-sellback is detected too")

print("\nALL SPIKE REVERSAL MATH TESTS PASSED")
