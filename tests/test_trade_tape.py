import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallEvent
from trade_tape import TradeTape


tape = TradeTape(retention_sec=30)

tape.add_binance_trade("BINANCE", {
    "s": "TESTUSDT",
    "t": 10,
    "p": "1.0000",
    "q": "700",
    "T": 100_500,
    "m": False,  # buyer is taker -> market buy hit ask
})

ask_event = WallEvent(
    "BINANCE", "TESTUSDT", "EATEN", 1.0, 0.0, "ask",
    extra="base",
    usd=0.0,
    max_usd=1000.0,
    age_sec=2.0,
    ts=101.0,
)
tape.annotate_wall_event(ask_event)
assert ask_event.trade_count == 1
assert ask_event.trade_side == "buy"
assert ask_event.trade_usd == 700.0
assert ask_event.trade_verdict == "70% исчезнувшего объёма"
assert "принты по уровню:" in ask_event.extra
assert "70% исчезнувшего объёма" in ask_event.extra
print("OK: ask wall disappearance is annotated with aggressive buys")

bid_event = WallEvent(
    "BINANCE", "TESTUSDT", "PULLED", 0.99, 0.0, "bid",
    extra="base",
    usd=0.0,
    max_usd=1000.0,
    age_sec=2.0,
    ts=101.0,
)
tape.annotate_wall_event(bid_event)
assert bid_event.trade_count == 0
assert bid_event.trade_side == "sell"
assert bid_event.trade_verdict == "no_level_trades"
assert bid_event.extra == "base"
print("OK: missing opposite trades do not add an unsupported text verdict")

print("\nALL TRADE TAPE TESTS PASSED")
