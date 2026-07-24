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
    if "get-exchange-info" in url:
        return FakeResponse({
            "code": "000000",
            "data": {
                "symbols": [
                    {"symbol": "ALPHA_1005USDT", "quoteAsset": "USDT"},
                    {"symbol": "ALPHA_1011USDT", "quoteAsset": "USDT"},
                ],
            },
        })
    if "alpha/all/token/list" in url:
        return FakeResponse({
            "code": "000000",
            "data": [
                {"symbol": "CAP", "name": "Cap", "cexCoinName": "CAP", "alphaId": "ALPHA_1005"},
                {"symbol": "DATAIP", "name": "DATA Network", "cexCoinName": "DATAIP", "alphaId": "ALPHA_1011"},
            ],
        })
    if "fullDepth" in url:
        assert params["symbol"] == "ALPHA_1005USDT"
        return FakeResponse({
            "code": "000000",
            "data": {
                "bids": [["1.0", "10"]],
                "asks": [["1.1", "20"]],
            },
        })
    raise AssertionError(url)


orig_get = rpm.requests.get
rpm.requests.get = fake_get
rpm._SYMBOL_CACHE.clear()
rpm._ALPHA_ALIAS_CACHE = None
rpm._ALPHA_LABEL_CACHE.clear()
try:
    aliases = rpm.fetch_alpha_aliases()
    assert aliases["CAP"] == "ALPHA_1005USDT"
    assert aliases["CAPUSDT"] == "ALPHA_1005USDT"
    assert aliases["ALPHA1005USDT"] == "ALPHA_1005USDT"
    assert rpm.resolve_alpha_symbol("cap") == "ALPHA_1005USDT"
    assert rpm.resolve_alpha_symbol("CAPUSDT") == "ALPHA_1005USDT"
    assert rpm.resolve_alpha_symbol("ALPHA1005USDT") == "ALPHA_1005USDT"
    assert rpm.alpha_display_symbol("ALPHA_1005USDT") == "CAP"
    assert "CAP" in rpm.fetch_alpha_search_symbols()
    assert rpm.validate_rest_symbol("BINANCE ALPHA", "CAP")
    snap = rpm.fetch_rest_depth("BINANCE ALPHA", "CAP", 20)
finally:
    rpm.requests.get = orig_get
    rpm._SYMBOL_CACHE.clear()
    rpm._ALPHA_ALIAS_CACHE = None
    rpm._ALPHA_LABEL_CACHE.clear()

assert snap["b"] == [("1.0", "10.0")]
assert snap["a"] == [("1.1", "20.0")]
print("OK: Binance Alpha aliases resolve to technical symbols and display as familiar tickers")

print("\nALL ALPHA ALIAS TESTS PASSED")
