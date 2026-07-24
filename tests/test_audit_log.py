import csv
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_log import AuditCsvWriter
from detector import WallEvent
from trade_tape import TradePrint


with tempfile.TemporaryDirectory() as tmp:
    writer = AuditCsvWriter(tmp)
    path = writer.start()

    ev = WallEvent(
        "BINANCE", "BTCUSDT", "APPEARED", 100.0, 12.5, "bid",
        extra="test density",
        usd=1250.0,
        best_bid=100.0,
        best_ask=100.1,
        mid=100.05,
        spread=0.1,
        dist_abs=0.0,
        dist_pct=0.0,
        age_sec=0.2,
        threshold_usd=1000.0,
        max_distance_pct=0.01,
        single_confirm_sec=0.0,
        confirmed=True,
        baseline=False,
        near_spread=True,
        trade_side="sell",
        trade_count=2,
        trade_qty=5.0,
        trade_usd=500.0,
        trade_verdict="частично били по уровню",
        trade_note="сделки: продажи $500 на уровне (2 шт.) -> частично били по уровню",
    )
    writer.write_event(ev)
    writer.write_trade(TradePrint(
        exchange="BINANCE",
        symbol="BTCUSDT",
        price=100.0,
        qty=1.5,
        usd=150.0,
        taker_side="buy",
        ts=1000.0,
        trade_id="42",
    ))
    writer.write_snapshot("BINANCE SPOT", "ETHUSDT", [{
        "side": "ask",
        "price": 200.0,
        "qty": 3.0,
        "usd": 600.0,
        "best_bid": 199.9,
        "best_ask": 200.0,
        "mid": 199.95,
        "spread": 0.1,
        "dist_abs": 0.0,
        "dist_pct": 0.0,
        "age": 0.4,
        "threshold_usd": 500.0,
        "threshold_max_usd": None,
        "max_distance_pct": 0.01,
        "single_confirm_sec": 0.0,
        "confirmed": False,
        "baseline": False,
        "near_spread": True,
    }])
    writer.stop()

    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

assert len(rows) == 3
assert rows[0]["row_type"] == "EVENT"
assert rows[0]["market"] == "FUTURES"
assert rows[0]["event_kind"] == "APPEARED"
assert rows[0]["usd"] == "1250"
assert rows[0]["confirmed"] == "1"
assert rows[0]["trade_count"] == "2"
assert rows[0]["trade_usd"] == "500"
assert rows[1]["row_type"] == "TRADE"
assert rows[1]["event_kind"] == "TRADE"
assert rows[1]["side"] == "buy"
assert rows[1]["event_extra"] == "42"
assert rows[2]["row_type"] == "ACTIVE"
assert rows[2]["market"] == "SPOT"
assert rows[2]["exchange"] == "BINANCE SPOT"
assert rows[2]["near_spread"] == "1"

print("OK: audit CSV writes EVENT and ACTIVE rows with structured scanner fields")
