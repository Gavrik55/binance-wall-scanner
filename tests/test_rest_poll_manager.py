import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rest_poll_manager as rpm


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def fake_get(url, params=None, timeout=None):
    if "/contract/detail" in url:
        return FakeResponse({
            "success": True,
            "code": 0,
            "data": {"symbol": "BTC_USDT", "contractSize": 0.0001},
        })
    if "/contract/depth/" in url:
        return FakeResponse({
            "success": True,
            "code": 0,
            "data": {
                "bids": [[100.0, 5000, 2]],
                "asks": [[101.0, 3000, 1]],
            },
        })
    raise AssertionError(url)


orig_get = rpm.requests.get
rpm.requests.get = fake_get
rpm._MEXC_CONTRACT_SIZE.clear()
try:
    snap = rpm.fetch_rest_depth("MEXC", "BTCUSDT", 20)
finally:
    rpm.requests.get = orig_get
    rpm._MEXC_CONTRACT_SIZE.clear()

assert snap["b"] == [("100.0", "0.5")]
assert snap["a"] == [("101.0", "0.3")]
print("OK: MEXC futures nested data depth and contractSize conversion work")

print("\nALL REST POLL MANAGER TESTS PASSED")
