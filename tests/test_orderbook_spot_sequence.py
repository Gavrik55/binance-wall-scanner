import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orderbook import OrderBook


def make_book():
    ob = OrderBook("BTCUSDT")
    ob.apply_snapshot({
        "lastUpdateId": 100,
        "bids": [["99", "1"]],
        "asks": [["101", "1"]],
    })
    return ob


ob = make_book()
assert ob.apply_diff({
    "U": 99,
    "u": 101,
    "b": [["100", "2"]],
    "a": [],
})
assert ob.synced
assert ob.last_update_id == 101
print("OK: spot diff без pu находит старт по диапазону U/u")

assert ob.apply_diff({
    "U": 102,
    "u": 102,
    "b": [["100", "3"]],
    "a": [],
})
assert ob.synced
assert ob.last_update_id == 102
print("OK: следующий spot diff без pu применяется без ресинка")

ok = ob.apply_diff({
    "U": 104,
    "u": 104,
    "b": [["100", "4"]],
    "a": [],
})
assert not ok
assert not ob.synced
print("OK: пропуск update id в spot diff без pu вызывает ресинк")

print("\nALL ORDERBOOK SPOT SEQUENCE TESTS PASSED")
