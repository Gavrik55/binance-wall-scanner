import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_tape import TradeTape


tape = TradeTape(retention_sec=60)

t1 = tape.add_trade("BINANCE", "BANKUSDT", 1.0, 4500, "buy", ts=100.0, trade_id="1")
assert tape.find_repeating_print_cluster(t1, min_count=3, window_sec=5, similarity_pct=15) is None

t2 = tape.add_trade("BINANCE", "BANKUSDT", 1.0, 4100, "buy", ts=101.0, trade_id="2")
assert tape.find_repeating_print_cluster(t2, min_count=3, window_sec=5, similarity_pct=15) is None

t3 = tape.add_trade("BINANCE", "BANKUSDT", 1.0, 4700, "buy", ts=102.0, trade_id="3")
cluster = tape.find_repeating_print_cluster(t3, min_count=3, window_sec=5, similarity_pct=15)
assert cluster is not None
assert cluster["count"] == 3
assert cluster["side"] == "buy"
assert cluster["total_usd"] == 13_300
assert cluster["span_sec"] == 2.0
assert cluster["print_usd"] == [4500, 4100, 4700]
print("OK: finds 3 similar buy prints inside a time window")

assert tape.find_repeating_print_cluster(
    t3, min_count=3, window_sec=5, similarity_pct=15, min_usd=4000
) is not None
assert tape.find_repeating_print_cluster(
    t3, min_count=3, window_sec=5, similarity_pct=15, min_usd=4400
) is None
assert tape.find_repeating_print_cluster(
    t3, min_count=3, window_sec=5, similarity_pct=15, max_usd=4600
) is None
assert tape.find_repeating_print_cluster(
    t3, min_count=3, window_sec=5, similarity_pct=15, min_usd=4000, max_usd=5000
) is not None
print("OK: repeating print volume filter applies to each print")

tape_zero = TradeTape(retention_sec=60)
z1 = tape_zero.add_trade("BINANCE", "BANKUSDT", 1.0, 4500, "sell", ts=100.0, trade_id="z1")
z2 = tape_zero.add_trade("BINANCE", "BANKUSDT", 1.0, 4100, "sell", ts=110.0, trade_id="z2")
z3 = tape_zero.add_trade("BINANCE", "BANKUSDT", 1.0, 4700, "sell", ts=120.0, trade_id="z3")
assert tape_zero.find_repeating_print_cluster(z3, min_count=3, window_sec=0, similarity_pct=15)["count"] == 3
print("OK: 0-second window means consecutive similar prints, regardless of elapsed seconds")

tape_break = TradeTape(retention_sec=60)
tape_break.add_trade("BINANCE", "BANKUSDT", 1.0, 4500, "sell", ts=100.0, trade_id="b1")
tape_break.add_trade("BINANCE", "BANKUSDT", 1.0, 9000, "sell", ts=101.0, trade_id="b2")
b3 = tape_break.add_trade("BINANCE", "BANKUSDT", 1.0, 4700, "sell", ts=102.0, trade_id="b3")
assert tape_break.find_repeating_print_cluster(b3, min_count=3, window_sec=0, similarity_pct=15) is None
print("OK: 0-second consecutive mode stops when a different-size print breaks the sequence")

print("\nALL REPEATING PRINT TESTS PASSED")
