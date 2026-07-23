"""
Лёгкий (без глубины стакана) сканер всего рынка сразу по нескольким биржам —
топ роста/падения за 24ч, импульс за короткое окно и поиск "ершей"/"лесенок"
(узкий боковой диапазон на низком объёме — типичный паттерн на неликвидных
монетах перед резким движением).

В отличие от сканера плотностей (ws_manager.py/gate_ws.py/okx_ws.py), тут НЕ
нужен REST-снапшот + WS-diff на каждый символ — у бирж есть один дешёвый
REST-эндпоинт, отдающий тикеры сразу по всему рынку одним запросом:

  BINANCE/ASTERDEX: GET /fapi/v1/ticker/24hr            (без параметра symbol)
  SPOT-клоны:       GET /api/v3|v1/ticker/24hr
  GATE:             GET /api/v4/futures/usdt/tickers
  GATE SPOT:        GET /api/v4/spot/tickers
  OKX:              GET /api/v5/market/tickers?instType=SWAP
  OKX SPOT:         GET /api/v5/market/tickers?instType=SPOT
  BYBIT:            GET /v5/market/tickers?category=linear

Поэтому rate-лимиты тут не проблема (по одному запросу на биржу раз в
POLL_INTERVAL_SEC), в отличие от сканера плотностей, где именно REST-снапшоты
по каждому символу были источником шторма/429 (см. ws_manager.py, gui.py).

"Ёрш"/"лесенка" (см. HEDGEHOG_*) считается из той же самой скользящей истории
цены, что и импульс — просто окно длиннее (HEDGEHOG_WINDOW_SEC). Отдельных
REST-запросов под это не заводим: диапазон/объём/касания границ — производные
величины от уже опрашиваемых раз в POLL_INTERVAL_SEC тикеров. За счёт этого
частота выборки (раз в 15 сек) грубее, чем у специализированных ботов на
1-минутных свечах — метрики приблизительные, но кандидатов на неликвиде
находят без единого лишнего запроса к биржам.
"""

import threading
import time
from collections import deque

import requests

POLL_INTERVAL_SEC = 15.0
IMPULSE_WINDOW_SEC = 180.0   # 3 минуты — окно для расчёта "импульса"
IMPULSE_HIGHLIGHT_PCT = 2.0  # |impulse_pct| от этого значения — подсвечиваем в UI как "⚡"
TOP_N = 20

HEDGEHOG_WINDOW_SEC = 60 * 90       # 90 минут — окно для диапазона/касаний "ерша"
HEDGEHOG_MIN_SAMPLES = 30           # минимум точек в окне, чтобы вообще считать метрику (прогрев)
HEDGEHOG_TOUCH_TOLERANCE_PCT = 15.0 # "касанием" границы диапазона считаем попадание в ближайшие N% от его ширины
HEDGEHOG_VOL_60M_SEC = 60 * 60
HEDGEHOG_VOL_10M_SEC = 10 * 60

# самая долгая история, которую вообще нужно хранить — под неё считается retention в _update_history
HISTORY_RETENTION_SEC = max(IMPULSE_WINDOW_SEC, HEDGEHOG_WINDOW_SEC, HEDGEHOG_VOL_60M_SEC) + POLL_INTERVAL_SEC

REST_URLS = {
    "BINANCE": "https://fapi.binance.com/fapi/v1/ticker/24hr",
    "BINANCE SPOT": "https://api.binance.com/api/v3/ticker/24hr",
    "ASTERDEX": "https://fapi.asterdex.com/fapi/v1/ticker/24hr",
    "ASTERDEX SPOT": "https://sapi.asterdex.com/api/v1/ticker/24hr",
    "GATE": "https://fx-api.gateio.ws/api/v4/futures/usdt/tickers",
    "GATE SPOT": "https://api.gateio.ws/api/v4/spot/tickers",
    "OKX": "https://www.okx.com/api/v5/market/tickers",
    "BYBIT": "https://api.bybit.com/v5/market/tickers",
}


def _fetch_binance_style(exchange: str) -> list:
    resp = requests.get(REST_URLS[exchange], timeout=10)
    resp.raise_for_status()
    out = []
    for item in resp.json():
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        try:
            out.append({
                "exchange": exchange,
                "symbol": symbol,
                "last": float(item["lastPrice"]),
                "change_pct_24h": float(item["priceChangePercent"]),
                "quote_volume": float(item.get("quoteVolume", 0.0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _fetch_gate() -> list:
    resp = requests.get(REST_URLS["GATE"], timeout=10)
    resp.raise_for_status()
    out = []
    for item in resp.json():
        contract = item.get("contract", "")
        if not contract.endswith("_USDT"):
            continue
        try:
            symbol = contract.replace("_", "").upper()
            out.append({
                "exchange": "GATE",
                "symbol": symbol,
                "last": float(item["last"]),
                "change_pct_24h": float(item["change_percentage"]),
                "quote_volume": float(item.get("volume_24h_quote", 0.0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _fetch_gate_spot() -> list:
    resp = requests.get(REST_URLS["GATE SPOT"], timeout=10)
    resp.raise_for_status()
    out = []
    for item in resp.json():
        pair = item.get("currency_pair", "")
        if not pair.endswith("_USDT"):
            continue
        try:
            symbol = pair.replace("_", "").upper()
            out.append({
                "exchange": "GATE SPOT",
                "symbol": symbol,
                "last": float(item["last"]),
                "change_pct_24h": float(item.get("change_percentage", 0.0)),
                "quote_volume": float(item.get("quote_volume", item.get("base_volume", 0.0))),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _fetch_okx(inst_type="SWAP", exchange="OKX") -> list:
    resp = requests.get(REST_URLS["OKX"], params={"instType": inst_type}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    out = []
    suffix = "-USDT-SWAP" if inst_type == "SWAP" else "-USDT"
    for item in data.get("data", []):
        inst_id = item.get("instId", "")
        if not inst_id.endswith(suffix):
            continue
        try:
            last = float(item["last"])
            open24h = float(item["open24h"])
            change_pct = ((last - open24h) / open24h * 100) if open24h else 0.0
            symbol = inst_id.replace("-SWAP", "").replace("-", "").upper()
            out.append({
                "exchange": exchange,
                "symbol": symbol,
                "last": last,
                "change_pct_24h": change_pct,
                "quote_volume": float(item.get("volCcy24h", 0.0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _fetch_bybit() -> list:
    resp = requests.get(REST_URLS["BYBIT"], params={"category": "linear"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit retCode={data.get('retCode')} {data.get('retMsg')}")
    out = []
    for item in data.get("result", {}).get("list", []):
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        try:
            out.append({
                "exchange": "BYBIT",
                "symbol": symbol,
                "last": float(item["lastPrice"]),
                "change_pct_24h": float(item["price24hPcnt"]) * 100,
                "quote_volume": float(item.get("turnover24h", 0.0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


FETCHERS = {
    "BINANCE": lambda: _fetch_binance_style("BINANCE"),
    "BINANCE SPOT": lambda: _fetch_binance_style("BINANCE SPOT"),
    "ASTERDEX": lambda: _fetch_binance_style("ASTERDEX"),
    "ASTERDEX SPOT": lambda: _fetch_binance_style("ASTERDEX SPOT"),
    "GATE": _fetch_gate,
    "GATE SPOT": _fetch_gate_spot,
    "OKX": lambda: _fetch_okx("SWAP", "OKX"),
    "OKX SPOT": lambda: _fetch_okx("SPOT", "OKX SPOT"),
    "BYBIT": _fetch_bybit,
}


class MarketScanner:
    """Фоновый поток: раз в POLL_INTERVAL_SEC опрашивает опрашиваемые биржи
    целиком, хранит скользящую историю (цена + объём) на символ и зовёт
    on_update с готовыми тикерами (impulse_pct, hh_* метрики "ерша", vol_60m,
    vol_10m уже посчитаны). on_update вызывается из фонового потока — как и
    остальные колбэки в этом проекте, GUI должен сам передать результат в
    свою очередь, а не трогать Tk-виджеты напрямую отсюда.

    exchanges=None — опрашивать все зарегистрированные в FETCHERS биржи.
    В GUI список источников задаётся явно: "Топ движений" остаётся без spot,
    а "Ерши" получают spot-рынки дополнительно."""

    def __init__(self, on_update, on_status=None, exchanges=None):
        self.on_update = on_update
        self.on_status = on_status or (lambda text: None)
        self._fetchers = {k: v for k, v in FETCHERS.items() if exchanges is None or k in exchanges}
        self._stop = False
        self._thread = None
        # "EXCH:SYMBOL" -> deque[(ts, last, quote_volume)]
        self._history = {}
        self._lock = threading.Lock()
        # изменяемое поле (не модульная константа) — GUI может перенастроить
        # окно импульса в рантайме без пересоздания сканера. HISTORY_RETENTION_SEC
        # уже с большим запасом (задаётся окном "ершей", 90 мин) — под любое
        # разумное окно импульса истории хватит без досчёта retention.
        self.impulse_window_sec = IMPULSE_WINDOW_SEC

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        while not self._stop:
            started = time.monotonic()
            all_tickers = []
            for exchange, fetch in self._fetchers.items():
                try:
                    all_tickers.extend(fetch())
                except Exception as e:
                    self.on_status(f"[Топ рынка] ошибка {exchange}: {e}")
            if all_tickers:
                self._update_history(all_tickers)
                self.on_update(all_tickers)
            elapsed = time.monotonic() - started
            sleep_left = max(1.0, POLL_INTERVAL_SEC - elapsed)
            for _ in range(int(sleep_left * 10)):
                if self._stop:
                    return
                time.sleep(0.1)

    def _update_history(self, tickers):
        now = time.time()
        with self._lock:
            for t in tickers:
                key = f"{t['exchange']}:{t['symbol']}"
                dq = self._history.setdefault(key, deque())
                dq.append((now, t["last"], t["quote_volume"]))
                while dq and now - dq[0][0] > HISTORY_RETENTION_SEC:
                    dq.popleft()
                t["impulse_pct"] = self._impulse_pct(dq, now)
                t.update(self._hedgehog_metrics(dq, now))

    def _impulse_pct(self, dq, now):
        if len(dq) < 2:
            return 0.0
        cutoff = now - self.impulse_window_sec
        base_price = dq[0][1]
        for ts, price, _vol in dq:
            if ts >= cutoff:
                base_price = price
                break
        last_price = dq[-1][1]
        if not base_price:
            return 0.0
        return (last_price - base_price) / base_price * 100

    def _hedgehog_metrics(self, dq, now):
        """Диапазон и "касания" верхней/нижней границы за HEDGEHOG_WINDOW_SEC
        (узкий диапазон + частые касания обеих границ на низком объёме — и
        есть "ёрш"/"лесенка"), плюс объём за 60м/10м. hh_ready=False, пока не
        набралось HEDGEHOG_MIN_SAMPLES точек — GUI сам решает прятать
        непрогретые строки, как и с AUTO-порогом в детекторе плотностей."""
        window_cutoff = now - HEDGEHOG_WINDOW_SEC
        window_prices = [price for ts, price, _vol in dq if ts >= window_cutoff]
        result = {
            "hh_ready": len(window_prices) >= HEDGEHOG_MIN_SAMPLES,
            "hh_range_pct": 0.0,
            "hh_touch_top": 0.0,
            "hh_touch_bot": 0.0,
            "vol_60m": 0.0,
            "vol_10m": 0.0,
        }
        if window_prices:
            hi, lo = max(window_prices), min(window_prices)
            if lo:
                result["hh_range_pct"] = (hi - lo) / lo * 100
            span = hi - lo
            if span > 0:
                tol = span * HEDGEHOG_TOUCH_TOLERANCE_PCT / 100
                result["hh_touch_top"] = sum(1 for p in window_prices if p >= hi - tol) / len(window_prices)
                result["hh_touch_bot"] = sum(1 for p in window_prices if p <= lo + tol) / len(window_prices)

        # объём за 60м/10м — сумма положительных дельт кумулятивного 24ч
        # объёма между соседними замерами внутри окна. Приближение: 24ч-объём
        # сам скользящий, но на интервалах в минуты дельта практически равна
        # реально проторгованному объёму за этот интервал.
        for window_sec, out_key in ((HEDGEHOG_VOL_60M_SEC, "vol_60m"), (HEDGEHOG_VOL_10M_SEC, "vol_10m")):
            cutoff = now - window_sec
            vol_sum = 0.0
            prev_vol = None
            for ts, _price, vol in dq:
                if ts < cutoff:
                    prev_vol = vol
                    continue
                if prev_vol is not None:
                    delta = vol - prev_vol
                    if delta > 0:
                        vol_sum += delta
                prev_vol = vol
            result[out_key] = vol_sum
        return result

    @staticmethod
    def top_movers(tickers, n=TOP_N):
        """Возвращает (топ роста, топ падения) — n записей каждый, по change_pct_24h."""
        ranked = sorted(tickers, key=lambda t: t["change_pct_24h"], reverse=True)
        gainers = ranked[:n]
        losers = list(reversed(ranked[-n:])) if len(ranked) >= n else list(reversed(ranked))
        return gainers, losers

    @staticmethod
    def hedgehog_candidates(tickers, n=30):
        """Кандидаты в "ерши": самый узкий диапазон за HEDGEHOG_WINDOW_SEC —
        первые в списке. Только "прогретые" (набравшие HEDGEHOG_MIN_SAMPLES
        точек истории) записи."""
        ready = [t for t in tickers if t.get("hh_ready")]
        return sorted(ready, key=lambda t: t["hh_range_pct"])[:n]
