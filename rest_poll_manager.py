import threading
import time

import requests


REST_EXCHANGES = {
    "MEXC": {
        "label": "MEXC",
        "kind": "mexc_contract",
    },
    "MEXC SPOT": {
        "label": "MEXC Spot",
        "kind": "mexc_spot",
    },
    "BINANCE ALPHA": {
        "label": "Binance Alpha",
        "kind": "binance_alpha",
    },
}

MEXC_CONTRACT_BASE = "https://contract.mexc.com"
MEXC_SPOT_BASE = "https://api.mexc.com"
BINANCE_ALPHA_BASE = "https://www.binance.com"
BINANCE_ALPHA_TOKEN_LIST = "/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"

DEFAULT_DEPTH_LIMIT = 1000
POLL_INTERVAL_SEC = 1.0

_SYMBOL_CACHE = {}
_ALPHA_ALIAS_CACHE = None
_ALPHA_LABEL_CACHE = {}
_MEXC_CONTRACT_SIZE = {}


def to_mexc_contract_symbol(symbol: str) -> str:
    symbol = (symbol or "").upper().replace("/", "").replace("-", "").replace("_", "")
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}_USDT"
    return symbol


def from_mexc_contract_symbol(symbol: str) -> str:
    return (symbol or "").replace("_", "").upper()


def _alpha_symbol_from_id(alpha_id: str) -> str:
    alpha_id = str(alpha_id or "").strip().upper()
    if not alpha_id:
        return ""
    return alpha_id if alpha_id.endswith("USDT") else f"{alpha_id}USDT"


def _alpha_lookup_key(value: str) -> str:
    value = str(value or "").upper().strip()
    out = []
    for ch in value:
        if ch.isalnum() or ch == "_":
            out.append(ch)
    return "".join(out)


def _alpha_lookup_keys(value: str) -> set:
    key = _alpha_lookup_key(value)
    if not key:
        return set()
    return {key, key.replace("_", "")}


def fetch_alpha_aliases() -> dict:
    global _ALPHA_ALIAS_CACHE
    now = time.time()
    if _ALPHA_ALIAS_CACHE and now - _ALPHA_ALIAS_CACHE[0] < 900:
        return dict(_ALPHA_ALIAS_CACHE[1])

    aliases = {}
    labels = {}
    try:
        symbols = fetch_rest_symbols("BINANCE ALPHA")
    except Exception:
        symbols = set()
    for symbol in symbols:
        for key in _alpha_lookup_keys(symbol):
            aliases[key] = symbol
        labels.setdefault(symbol, symbol)

    resp = requests.get(f"{BINANCE_ALPHA_BASE}{BINANCE_ALPHA_TOKEN_LIST}", timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    for row in payload.get("data", []):
        actual = _alpha_symbol_from_id(row.get("alphaId"))
        if not actual:
            continue
        if symbols and actual not in symbols:
            continue
        token_symbol = str(row.get("symbol") or "").strip().upper()
        token_name = str(row.get("name") or "").strip()
        cex_name = str(row.get("cexCoinName") or "").strip().upper()
        for alias in (actual, actual[:-4], row.get("alphaId"), token_symbol, f"{token_symbol}USDT", cex_name):
            for key in _alpha_lookup_keys(alias):
                aliases.setdefault(key, actual)
        for name_key in _alpha_lookup_keys(token_name):
            aliases.setdefault(name_key, actual)
        if token_symbol:
            labels[actual] = token_symbol

    _ALPHA_LABEL_CACHE.clear()
    _ALPHA_LABEL_CACHE.update(labels)
    _ALPHA_ALIAS_CACHE = (now, aliases)
    return dict(aliases)


def resolve_alpha_symbol(symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return ""
    key = _alpha_lookup_key(symbol)
    try:
        aliases = fetch_alpha_aliases()
        return aliases.get(key) or aliases.get(key.replace("_", "")) or aliases.get(_alpha_lookup_key(f"{symbol}USDT")) or symbol
    except Exception:
        return symbol


def alpha_display_symbol(symbol: str) -> str:
    actual = _alpha_symbol_from_id(symbol)
    if not actual:
        return str(symbol or "").upper()
    try:
        if not _ALPHA_LABEL_CACHE:
            fetch_alpha_aliases()
    except Exception:
        pass
    return _ALPHA_LABEL_CACHE.get(actual, actual)


def fetch_alpha_search_symbols() -> set:
    aliases = fetch_alpha_aliases()
    out = set()
    for alias, actual in aliases.items():
        if alias == actual:
            continue
        if alias.endswith("USDT"):
            continue
        if alias.startswith("ALPHA_"):
            continue
        out.add(alias)
    return out


def _first_number(level, *names, default=None):
    if isinstance(level, dict):
        for name in names:
            if name in level:
                return level[name]
        return default
    try:
        return level[0] if not names else level[1]
    except (IndexError, TypeError):
        return default


def _levels_from_pairs(levels, qty_multiplier=1.0):
    out = []
    for level in levels or []:
        try:
            if isinstance(level, dict):
                price = level.get("price") or level.get("p")
                qty = level.get("quantity") or level.get("qty") or level.get("q") or level.get("vol") or level.get("v")
            else:
                price = level[0]
                qty = level[1]
            out.append((str(price), str(float(qty) * float(qty_multiplier))))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def _mexc_contract_size(contract: str) -> float:
    contract = contract.upper()
    if contract in _MEXC_CONTRACT_SIZE:
        return _MEXC_CONTRACT_SIZE[contract]
    try:
        resp = requests.get(
            f"{MEXC_CONTRACT_BASE}/api/v1/contract/detail",
            params={"symbol": contract},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if isinstance(data, dict):
            rows = [data]
        else:
            rows = data
        for row in rows:
            if str(row.get("symbol", "")).upper() == contract:
                size = float(row.get("contractSize") or 1.0)
                _MEXC_CONTRACT_SIZE[contract] = size
                return size
    except Exception:
        pass
    _MEXC_CONTRACT_SIZE[contract] = 1.0
    return 1.0


def _fetch_mexc_contract_depth(symbol: str, limit: int):
    contract = to_mexc_contract_symbol(symbol)
    resp = requests.get(
        f"{MEXC_CONTRACT_BASE}/api/v1/contract/depth/{contract}",
        params={"limit": limit},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else payload
    data = data or {}
    multiplier = _mexc_contract_size(contract)
    return {
        "b": _levels_from_pairs(data.get("bids", []), qty_multiplier=multiplier),
        "a": _levels_from_pairs(data.get("asks", []), qty_multiplier=multiplier),
    }


def _fetch_mexc_spot_depth(symbol: str, limit: int):
    resp = requests.get(
        f"{MEXC_SPOT_BASE}/api/v3/depth",
        params={"symbol": symbol.upper(), "limit": min(int(limit), 5000)},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "b": _levels_from_pairs(data.get("bids", [])),
        "a": _levels_from_pairs(data.get("asks", [])),
    }


def _fetch_binance_alpha_depth(symbol: str, limit: int):
    symbol = resolve_alpha_symbol(symbol)
    resp = requests.get(
        f"{BINANCE_ALPHA_BASE}/bapi/defi/v1/public/alpha-trade/fullDepth",
        params={"symbol": symbol.upper(), "limit": min(int(limit), 1000)},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") not in (None, "000000"):
        raise RuntimeError(payload.get("message") or payload.get("msg") or payload.get("code"))
    data = payload.get("data") or {}
    return {
        "b": _levels_from_pairs(data.get("bids", [])),
        "a": _levels_from_pairs(data.get("asks", [])),
    }


def fetch_rest_depth(exchange: str, symbol: str, limit: int = DEFAULT_DEPTH_LIMIT) -> dict:
    exchange = exchange.upper()
    kind = REST_EXCHANGES[exchange]["kind"]
    if kind == "mexc_contract":
        return _fetch_mexc_contract_depth(symbol, limit)
    if kind == "mexc_spot":
        return _fetch_mexc_spot_depth(symbol, limit)
    if kind == "binance_alpha":
        return _fetch_binance_alpha_depth(symbol, limit)
    raise KeyError(exchange)


def fetch_rest_symbols(exchange: str) -> set:
    exchange = exchange.upper()
    now = time.time()
    cached = _SYMBOL_CACHE.get(exchange)
    if cached and now - cached[0] < 900:
        return set(cached[1])

    symbols = set()
    kind = REST_EXCHANGES[exchange]["kind"]
    try:
        if kind == "mexc_contract":
            resp = requests.get(f"{MEXC_CONTRACT_BASE}/api/v1/contract/detail", timeout=10)
            resp.raise_for_status()
            for row in resp.json().get("data", []):
                if row.get("quoteCoin") == "USDT" and int(row.get("state", 0)) == 0:
                    symbol = str(row.get("symbol", "")).upper()
                    symbols.add(from_mexc_contract_symbol(symbol))
                    try:
                        _MEXC_CONTRACT_SIZE[symbol] = float(row.get("contractSize") or 1.0)
                    except (TypeError, ValueError):
                        pass
        elif kind == "mexc_spot":
            resp = requests.get(f"{MEXC_SPOT_BASE}/api/v3/exchangeInfo", timeout=10)
            resp.raise_for_status()
            for row in resp.json().get("symbols", []):
                if row.get("quoteAsset") == "USDT":
                    symbols.add(str(row.get("symbol", "")).upper())
        elif kind == "binance_alpha":
            resp = requests.get(
                f"{BINANCE_ALPHA_BASE}/bapi/defi/v1/public/alpha-trade/get-exchange-info",
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
            for row in (payload.get("data") or {}).get("symbols", []):
                if str(row.get("quoteAsset", "")).upper() == "USDT":
                    symbols.add(str(row.get("symbol", "")).upper())
    except Exception:
        if cached:
            return set(cached[1])
        raise

    _SYMBOL_CACHE[exchange] = (now, symbols)
    return set(symbols)


def validate_rest_symbol(exchange: str, symbol: str) -> bool:
    exchange = exchange.upper()
    symbol = symbol.upper()
    try:
        if exchange == "BINANCE ALPHA":
            symbol = resolve_alpha_symbol(symbol)
        symbols = fetch_rest_symbols(exchange)
        if symbol in symbols:
            return True
        if exchange == "MEXC" and to_mexc_contract_symbol(symbol) in {to_mexc_contract_symbol(s) for s in symbols}:
            return True
        return False
    except Exception:
        try:
            depth = fetch_rest_depth(exchange, symbol, limit=20)
            return bool(depth.get("b") or depth.get("a"))
        except Exception:
            return True


class RestPollingManager:
    """Simple snapshot poller for markets where WS support needs extra protocol work."""

    def __init__(self, exchange: str, on_depth_update, on_status, interval_sec=POLL_INTERVAL_SEC):
        self.exchange = exchange.upper()
        self.label = REST_EXCHANGES[self.exchange]["label"]
        self.on_depth_update = on_depth_update
        self.on_status = on_status
        self.interval_sec = float(interval_sec)
        self.loop = None
        self.thread = None
        self._stop = False
        self._lock = threading.Lock()
        self._desired = set()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop = True

    def subscribe_symbol(self, symbol: str):
        with self._lock:
            self._desired.add(symbol.upper())

    def unsubscribe_symbol(self, symbol: str):
        with self._lock:
            self._desired.discard(symbol.upper())

    def _run(self):
        self.loop = True
        self.on_status(f"[{self.label}] Подключение...")
        self.on_status(f"[{self.label}] Подключено")
        last_error = {}
        while not self._stop:
            with self._lock:
                symbols = list(self._desired)
            for symbol in symbols:
                if self._stop:
                    break
                try:
                    snap = fetch_rest_depth(self.exchange, symbol)
                    self.on_depth_update(self.exchange, symbol, {"snapshot": True, **snap})
                    last_error.pop(symbol, None)
                except Exception as e:
                    previous = last_error.get(symbol)
                    text = str(e)
                    if previous != text:
                        self.on_status(f"[{self.label}] Ошибка стакана {symbol}: {e}")
                        last_error[symbol] = text
            time.sleep(self.interval_sec)
        self.on_status(f"[{self.label}] Отключено")
