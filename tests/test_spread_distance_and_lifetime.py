import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detector import WallDetector, SymbolConfig, NEAR_SPREAD_PCT, format_age
from orderbook import OrderBook


def make_ob(bids, asks=None):
    ob = OrderBook("TESTUSDT")
    ob.bids = dict(bids)
    ob.asks = dict(asks or {1.02: 1.0})
    ob.synced = True
    return ob


def prime(det):
    det.scan("BINANCE", "TESTUSDT", make_ob({0.5: 0.0001}, {1.5: 1.0}))


assert format_age(10.9) == "10.9с", "age below a minute should keep tenths, not show a rounded 0:10"
assert format_age(61.2) == "1:01", "age above a minute can stay compact mm:ss"
print("OK: wall lifetime display keeps tenths below one minute")


# 0% now means distance from the spread edge: best bid for bid walls, best ask for ask walls.
det_dist = WallDetector()
det_dist.set_config(SymbolConfig(
    "TESTUSDT", 50_000, "LONG", exchange="BINANCE", mode="FIXED",
    max_distance_pct=0.0,
))
det_dist.scan("BINANCE", "TESTUSDT", make_ob({
    1.00: 100_000,
    0.99: 100_000,
}))
walls = det_dist.active_walls["BINANCE:TESTUSDT"]
assert 1.00 in walls, "0% should include the best bid level itself"
assert 0.99 not in walls, "0% should exclude deeper bid levels away from the spread"
snapshot = det_dist.snapshot("BINANCE", "TESTUSDT", make_ob({1.00: 100_000}, {1.02: 1.0}))
assert snapshot and snapshot[0]["dist_pct"] == 0.0
print("OK: 0% distance catches the level directly at the spread edge")


# A wall that stands right under the spread should be visible immediately as a pushing wall,
# even when normal APPEARED confirmation still waits for single_confirm_sec.
det_push = WallDetector()
det_push.set_config(SymbolConfig(
    "TESTUSDT", 50_000, "LONG", exchange="BINANCE", mode="FIXED",
    max_distance_pct=NEAR_SPREAD_PCT,
    single_confirm_sec=10.0,
))
prime(det_push)
events_push = det_push.scan("BINANCE", "TESTUSDT", make_ob({1.00: 100_000}, {1.02: 1.0}))
pushes = [e for e in events_push if e.kind == "PUSH"]
assert len(pushes) == 1, f"expected one PUSH event near spread, got {[e.kind for e in events_push]}"
assert not [e for e in events_push if e.kind == "APPEARED"], "PUSH should not wait for normal APPEARED confirmation"
events_push_repeat = det_push.scan("BINANCE", "TESTUSDT", make_ob({1.00: 100_000}, {1.02: 1.0}))
assert not [e for e in events_push_repeat if e.kind == "PUSH"], "same price should not spam PUSH every tick"
snapshot_push = det_push.snapshot("BINANCE", "TESTUSDT", make_ob({1.00: 100_000}, {1.02: 1.0}))
assert snapshot_push and snapshot_push[0]["near_spread"] is True
print("OK: near-spread pushing wall gets immediate PUSH event and active-table marker")


# 0 seconds means "alert as soon as the scanner sees a new eligible wall".
det_now = WallDetector()
det_now.set_config(SymbolConfig(
    "TESTUSDT", 50_000, "LONG", exchange="BINANCE", mode="FIXED",
    single_confirm_sec=0.0,
))
prime(det_now)
events_now = det_now.scan("BINANCE", "TESTUSDT", make_ob({1.00: 100_000}, {1.02: 1.0}))
appeared_now = [e for e in events_now if e.kind == "APPEARED"]
assert len(appeared_now) == 1
assert appeared_now[0].usd == 100_000
assert appeared_now[0].best_bid == 1.00
assert appeared_now[0].best_ask == 1.02
assert appeared_now[0].dist_pct == 0.0
print("OK: 0 seconds lifetime confirms a new wall immediately")


# Same practical combination as the GUI creates for user-entered "0 distance + 0 life":
# distance becomes the near-spread minimum, life remains exactly 0.
det_min_filters = WallDetector()
det_min_filters.set_config(SymbolConfig(
    "TESTUSDT", 50_000, "LONG", exchange="BINANCE", mode="FIXED",
    max_distance_pct=NEAR_SPREAD_PCT,
    single_confirm_sec=0.0,
))
prime(det_min_filters)
events_min_filters = det_min_filters.scan(
    "BINANCE", "TESTUSDT", make_ob({1.00: 100_000, 0.99: 100_000}, {1.02: 1.0})
)
event_kinds = [e.kind for e in events_min_filters]
assert "APPEARED" in event_kinds, f"0 life should confirm immediately, got {event_kinds}"
assert "PUSH" in event_kinds, f"near-spread minimum should catch pushing walls, got {event_kinds}"
assert 0.99 not in det_min_filters.active_walls["BINANCE:TESTUSDT"], "minimum distance should still exclude deeper levels"
print("OK: GUI-style 0 distance + 0 life catches near-spread density immediately")


# Fractional seconds are allowed too.
det_frac = WallDetector()
det_frac.set_config(SymbolConfig(
    "TESTUSDT", 50_000, "LONG", exchange="BINANCE", mode="FIXED",
    single_confirm_sec=0.3,
))
prime(det_frac)
events_frac_1 = det_frac.scan("BINANCE", "TESTUSDT", make_ob({1.00: 100_000}, {1.02: 1.0}))
assert not [e for e in events_frac_1 if e.kind == "APPEARED"]
wall = det_frac.active_walls["BINANCE:TESTUSDT"][1.00]
wall.first_seen -= 0.35
events_frac_2 = det_frac.scan("BINANCE", "TESTUSDT", make_ob({1.00: 100_000}, {1.02: 1.0}))
appeared_frac = [e for e in events_frac_2 if e.kind == "APPEARED"]
assert len(appeared_frac) == 1
assert "0." in appeared_frac[0].extra, appeared_frac[0].extra
print("OK: fractional lifetime below one second confirms after the requested delay")

print("\nALL SPREAD DISTANCE/LIFETIME TESTS PASSED")
