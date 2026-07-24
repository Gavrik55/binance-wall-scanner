"""
Лёгкий (без глубины стакана) сканер всего рынка сразу по нескольким биржам —
топ роста/падения за 24ч, импульс за короткое окно и поиск "ершей"/"лесенок"
(узкий боковой диапазон на низком объёме — типичный паттерн на неликвидных
монетах перед резким движением).

В отличие от сканера плотностей (ws_manager.py/gate_ws.py/okx_ws.py), тут НЕ
нужен REST-снапшот + WS-diff на каждый символ — у бирж есть один дешёвый
REST-эндпоинт, отдающий тикеры сразу по всему рынку одним запросом:

  BINANCE/ASTERDEX: GET /fapi/v1/ticker/24hr            (без параметра symbol)
  GATE:             GET /api/v4/futures/usdt/tickers
  OKX:              GET /api/v5/market/tickers?instType=SWAP
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
from concurrent.futures import ThreadPoolExecutor

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
    "ASTERDEX": "https://fapi.asterdex.com/fapi/v1/ticker/24hr",
    "GATE": "https://fx-api.gateio.ws/api/v4/futures/usdt/tickers",
    "OKX": "https://www.okx.com/api/v5/market/tickers",
    "BYBIT": "https://api.bybit.com/v5/market/tickers",
    "MEXC": "https://api.mexc.com/api/v3/ticker/24hr",
}

# --- "живая тишина": профиль монеты ЗА ЧАС ДО памп-выноса ---------------
# Пороги не выдуманы: посчитаны по 15 размеченным сигналам из телеграм-канала
# "splash 50% MEXC" (см. PROJECT_NOTES). У 7 из 9 пампов за час до старта цена
# ходила в узком, но ЖИВОМ диапазоне при низком объёме, который НЕ разгонялся.
# Дампы (-33%) выглядели ровно наоборот — диапазон 55-135%, разгон объёма
# 2-10x, — поэтому верхние границы тут не формальность, а именно то, что
# отсекает "похмелье" после уже случившегося выноса.
EARLY_WINDOW_SEC = 3600.0     # окно, на котором считаем профиль (1 час)
# Минимум точек в окне. Порог низкий сознательно: история может прийти как с
# живых опросов (раз в 15 сек -> 240 точек в час), так и из бутстрапа минутными
# свечами (60 точек в час). Настоящую защиту от вырожденных случаев даёт не это
# число, а проверка РЕАЛЬНОГО охвата окна по времени в _early_metrics.
EARLY_MIN_SAMPLES = 40
EARLY_RANGE_MIN_PCT = 3.0     # НИЖНЯЯ граница — важнее верхней: отсекает мёртвые
                              # монеты с плоской ценой (их 35% рынка, и они никогда
                              # не стреляют). Без этого порога кандидатов 453, с ним — 68.
EARLY_RANGE_MAX_PCT = 15.0    # выше — монету уже колбасит, мы опоздали
EARLY_VOL_MIN_USD = 2_500     # ниже — неликвид, из которого не выйти
EARLY_VOL_MAX_USD = 12_000    # выше — движение уже началось без нас
EARLY_ACCEL_MAX = 2.0         # объём НЕ должен разгоняться: у пампов было 0.4-1.7x

# "Эксклюзивность" листинга. Монета, которая уже торгуется на биржах первого
# эшелона, интересна нам гораздо меньше: её стакан толстый, и вынос на +50% с
# тонкой книги там не делается. Оставляем только те, что живут на MEXC и/или
# площадках второго эшелона (AsterDEX, Gate, Bitget и т.п.).
MAJOR_EXCHANGES = ("BINANCE", "OKX", "BYBIT")
# Binance в скринере подключён ФЬЮЧЕРСНЫМ эндпоинтом, поэтому монета, у которой
# есть спот, но нет фьючерса, из тикеров не видна и ошибочно сошла бы за
# эксклюзив MEXC. Список спота тянем отдельно — он меняется редко, поэтому
# запрашивается один раз при старте, а не каждый цикл.
BINANCE_SPOT_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"

# --- Открытый интерес (OI) фьючерсов MEXC ---------------------------------
# OI существует ТОЛЬКО для фьючерсов, а вотч-лист "Ранних" — спот. По факту
# фьючерс есть лишь у ~22% кандидатов, остальные чисто спотовые. Поэтому OI —
# НЕ фильтр-отсекатель (иначе выбросили бы 78% списка, включая спотовые пампы),
# а бонусный сигнал: спотовые монеты остаются в списке с прочерком.
#
# Величина OI сама по себе слабый сигнал (у реально выстреливших монет из
# канала OI был мизерный). Ценен именно РОСТ OI: если на затихшей монете растёт
# открытый интерес — трейдеры открывают позиции, готовятся к движению. Рост
# считаем по ЧИСЛУ КОНТРАКТОВ (holdVol), а не по OI в долларах: иначе скачок
# цены раздул бы "рост" даже при неизменных позициях.
MEXC_FUTURES_TICKER_URL = "https://contract.mexc.com/api/v1/contract/ticker"
MEXC_FUTURES_DETAIL_URL = "https://contract.mexc.com/api/v1/contract/detail"
OI_CHANGE_WINDOW_SEC = 3600.0     # окно для ΔOI (1 час, как у профиля "живой тишины")
OI_CHANGE_MIN_SPAN_SEC = 600.0    # без 10+ мин истории ΔOI шумный — показываем прочерк
OI_RISE_HIGHLIGHT_PCT = 20.0      # рост OI от этого — подсветка и подъём выше в списке
OI_RETENTION_SEC = OI_CHANGE_WINDOW_SEC + POLL_INTERVAL_SEC

# Бутстрап истории свечами при старте (см. bootstrap_mexc_history).
MEXC_KLINES_URL = "https://api.mexc.com/api/v3/klines"
BOOTSTRAP_WORKERS = 10        # /api/v3/klines имеет вес 1 при лимите 500/10с — 10 потоков это ~5% бюджета
BOOTSTRAP_V24_MIN = 20_000    # монеты вне этого коридора по 24ч-объёму физически не могут
BOOTSTRAP_V24_MAX = 3_000_000 # пройти фильтр EARLY_VOL_*, поэтому свечи по ним не тянем


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


def _fetch_okx() -> list:
    resp = requests.get(REST_URLS["OKX"], params={"instType": "SWAP"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    out = []
    for item in data.get("data", []):
        inst_id = item.get("instId", "")
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        try:
            last = float(item["last"])
            open24h = float(item["open24h"])
            change_pct = ((last - open24h) / open24h * 100) if open24h else 0.0
            symbol = inst_id.replace("-SWAP", "").replace("-", "").upper()
            out.append({
                "exchange": "OKX",
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


def _fetch_mexc() -> list:
    """MEXC spot. Формат почти как у Binance, но с одной ловушкой:
    priceChangePercent тут — ДОЛЯ, а не проценты ("-0.0245" = -2.45%), поэтому
    домножаем на 100. У Binance/AsterDEX то же поле уже в процентах."""
    resp = requests.get(REST_URLS["MEXC"], timeout=20)
    resp.raise_for_status()
    out = []
    for item in resp.json():
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue
        try:
            out.append({
                "exchange": "MEXC",
                "symbol": symbol,
                "last": float(item["lastPrice"]),
                "change_pct_24h": float(item["priceChangePercent"]) * 100,
                "quote_volume": float(item.get("quoteVolume", 0.0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fetch_binance_spot_symbols() -> set:
    """Все USDT-пары со СПОТА Binance (нормализованные, вида "BTCUSDT").
    Используется только для проверки "эксклюзивности" листинга, не для цен."""
    resp = requests.get(BINANCE_SPOT_INFO_URL, timeout=25)
    resp.raise_for_status()
    return {s.get("symbol", "") for s in resp.json().get("symbols", [])
            if s.get("symbol", "").endswith("USDT")}


def fetch_mexc_contract_sizes() -> dict:
    """Размер контракта на символ (contractSize) для перевода OI в USD.
    Ключ нормализуем в спот-форму ("HOODRAT_USDT" -> "HOODRATUSDT")."""
    resp = requests.get(MEXC_FUTURES_DETAIL_URL, timeout=20)
    resp.raise_for_status()
    out = {}
    for item in resp.json().get("data", []):
        sym = item.get("symbol", "")
        if not sym.endswith("_USDT"):
            continue
        try:
            out[sym.replace("_USDT", "") + "USDT"] = float(item["contractSize"])
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fetch_mexc_oi() -> dict:
    """Открытый интерес фьючерсов MEXC одним запросом по всему рынку.
    Возвращает {"BASEUSDT": (holdVol_контрактов, last_price)}. holdVol — это
    число открытых контрактов; в USD переводится через contractSize отдельно."""
    resp = requests.get(MEXC_FUTURES_TICKER_URL, timeout=15)
    resp.raise_for_status()
    out = {}
    for item in resp.json().get("data", []):
        sym = item.get("symbol", "")
        if not sym.endswith("_USDT"):
            continue
        hold = item.get("holdVol")
        if hold is None:
            continue
        try:
            price = float(item.get("lastPrice") or item.get("fairPrice") or 0)
            out[sym.replace("_USDT", "") + "USDT"] = (float(hold), price)
        except (ValueError, TypeError):
            continue
    return out


FETCHERS = {
    "BINANCE": lambda: _fetch_binance_style("BINANCE"),
    "ASTERDEX": lambda: _fetch_binance_style("ASTERDEX"),
    "GATE": _fetch_gate,
    "OKX": _fetch_okx,
    "BYBIT": _fetch_bybit,
    "MEXC": _fetch_mexc,
}


class MarketScanner:
    """Фоновый поток: раз в POLL_INTERVAL_SEC опрашивает опрашиваемые биржи
    целиком, хранит скользящую историю (цена + объём) на символ и зовёт
    on_update с готовыми тикерами (impulse_pct, hh_* метрики "ерша", vol_60m,
    vol_10m уже посчитаны). on_update вызывается из фонового потока — как и
    остальные колбэки в этом проекте, GUI должен сам передать результат в
    свою очередь, а не трогать Tk-виджеты напрямую отсюда.

    exchanges=None — опрашивать все зарегистрированные в FETCHERS биржи
    (используется вкладкой "Топ движений"). exchanges=["BINANCE","BYBIT"] —
    только перечисленные (используется вкладкой "Ерши" — по просьбе
    ограничиться этими двумя, без Mexc и без ASTERDEX/GATE/OKX)."""

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
        # заполняется в bootstrap_mexc_history; пустое множество безопасно —
        # фильтр эксклюзивности просто не увидит спот-листинги Binance
        self.binance_spot_symbols = set()
        # OI фьючерсов MEXC: размер контракта на символ (для OI в USD) и
        # скользящая история числа контрактов (для ΔOI). Заполняются на лету,
        # пустые значения безопасны — метрики просто будут "нет данных".
        self.mexc_contract_size = {}   # "BASEUSDT" -> contractSize
        self._oi_history = {}          # "BASEUSDT" -> deque[(ts, holdVol_контрактов, price)]

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
            # OI тянем только если MEXC вообще опрашивается (вкладка "Ерши" его
            # не опрашивает, ей OI не нужен). Отдельный эндпоинт, один запрос.
            if "MEXC" in self._fetchers:
                self._update_oi_history()
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
                t.update(self._early_metrics(dq, now, t))
                if t["exchange"] == "MEXC":
                    t.update(self._oi_metrics(t["symbol"], now))

    def _update_oi_history(self):
        """Опрос OI фьючерсов MEXC (один запрос) и обновление скользящей
        истории числа контрактов на символ. Сетевая ошибка не роняет цикл —
        просто в этот тик OI не обновится."""
        try:
            oi = fetch_mexc_oi()
        except Exception as e:
            self.on_status(f"[OI] ошибка опроса: {e}")
            return
        now = time.time()
        with self._lock:
            for base, (hold, price) in oi.items():
                dq = self._oi_history.setdefault(base, deque())
                dq.append((now, hold, price))
                while dq and now - dq[0][0] > OI_RETENTION_SEC:
                    dq.popleft()

    def _oi_metrics(self, symbol, now):
        """OI в USD (последний снимок) и рост ΔOI% по числу контрактов за окно.
        has_oi=False для чисто спотовых монет без фьючерса — GUI покажет им
        прочерк, из списка их это не выбрасывает."""
        result = {"has_oi": False, "oi_usd": 0.0, "oi_change_pct": 0.0}
        dq = self._oi_history.get(symbol)
        if not dq:
            return result
        _ts_now, hold_now, price_now = dq[-1]
        csize = self.mexc_contract_size.get(symbol, 0.0)
        result["has_oi"] = True
        result["oi_usd"] = hold_now * csize * price_now

        # ΔOI считаем от самого раннего замера В ОКНЕ, но только если история
        # покрывает хотя бы OI_CHANGE_MIN_SPAN_SEC — иначе процент шумный
        cutoff = now - OI_CHANGE_WINDOW_SEC
        base_ts, base_hold = None, None
        for ts, hold, _p in dq:
            if ts >= cutoff:
                base_ts, base_hold = ts, hold
                break
        if base_hold and now - base_ts >= OI_CHANGE_MIN_SPAN_SEC:
            result["oi_change_pct"] = (hold_now - base_hold) / base_hold * 100
        return result

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

    def _early_metrics(self, dq, now, ticker):
        """Профиль "живой тишины" за EARLY_WINDOW_SEC. Считается из той же
        скользящей истории, что импульс и "ерши" — дополнительных запросов к
        бирже не делает.

        vol_accel — во сколько раз средний объём последних 10 минут отличается
        от средних 50 минут до них. Именно ЭТО отличало памп от дампа: перед
        пампом объём затихал (0.4-1.7x), перед дампом взрывался (1.8-10x)."""
        result = {"early_ready": False, "range_60m": 0.0, "vol_accel": 0.0}
        cutoff = now - EARLY_WINDOW_SEC
        window = [(ts, price) for ts, price, _vol in dq if ts >= cutoff]
        if len(window) < EARLY_MIN_SAMPLES:
            return result
        # история должна РЕАЛЬНО покрывать окно, а не быть плотной пачкой
        # замеров за последние пару минут (иначе диапазон занижен и монета
        # ложно выглядит "затихшей")
        if now - window[0][0] < EARLY_WINDOW_SEC * 0.9:
            return result

        prices = [p for _ts, p in window]
        lo, hi = min(prices), max(prices)
        if not lo:
            return result
        result["range_60m"] = (hi - lo) / lo * 100

        vol_60m = ticker.get("vol_60m", 0.0)
        vol_10m = ticker.get("vol_10m", 0.0)
        prior_50m = vol_60m - vol_10m
        if prior_50m > 0:
            result["vol_accel"] = (vol_10m / 10.0) / (prior_50m / 50.0)
        result["early_ready"] = True
        return result

    def bootstrap_mexc_history(self, on_done=None):
        """Заполнить историю MEXC минутными свечами за последний час.

        Без этого вкладка "Ранние" мертва первый час после КАЖДОГО запуска
        (метрики считаются из скользящей истории, которой ещё нет) — то есть
        ни алертов, ни записи стаканов. Свечи дают ту же информацию сразу.

        Хитрость с объёмом: живые опросы кладут в историю КУМУЛЯТИВНЫЙ объём за
        24ч, а vol_60m считается как сумма его приростов. Свечи же дают объём
        поминутно. Поэтому синтезируем кумулятивный ряд так, чтобы он ЗАКАНЧИВАЛСЯ
        на текущем 24-часовом объёме монеты — тогда первый живой замер даст
        корректный прирост, а не гигантский скачок."""
        try:
            self.binance_spot_symbols = fetch_binance_spot_symbols()
            self.on_status(f"[Ранние] спот Binance: {len(self.binance_spot_symbols)} пар "
                            f"(для фильтра эксклюзивности)")
        except Exception as e:
            # не критично: без этого списка фильтр просто мягче, монеты со
            # спота Binance без фьючерса могут просочиться в вотч-лист
            self.on_status(f"[Ранние] не удалось получить спот Binance: {e}")

        try:
            self.mexc_contract_size = fetch_mexc_contract_sizes()
            self.on_status(f"[OI] размеры контрактов MEXC: {len(self.mexc_contract_size)}")
        except Exception as e:
            # не критично: без размеров контрактов OI не переведётся в USD,
            # но ΔOI (по числу контрактов) всё равно посчитается
            self.on_status(f"[OI] не удалось получить размеры контрактов: {e}")

        try:
            tickers = _fetch_mexc()
        except Exception as e:
            self.on_status(f"[Ранние] не удалось получить список MEXC: {e}")
            return

        targets = [t for t in tickers
                   if BOOTSTRAP_V24_MIN <= t["quote_volume"] <= BOOTSTRAP_V24_MAX]
        self.on_status(f"[Ранние] прогрев по свечам: {len(targets)} монет...")

        session = requests.Session()

        def seed(ticker):
            symbol = ticker["symbol"]
            try:
                r = session.get(MEXC_KLINES_URL,
                                params={"symbol": symbol, "interval": "1m", "limit": 60},
                                timeout=15)
                if r.status_code != 200:
                    return None
                candles = r.json()
            except Exception:
                return None
            if len(candles) < EARLY_MIN_SAMPLES:
                return None

            try:
                per_minute = [(int(c[6]) / 1000.0, float(c[4]), float(c[7])) for c in candles]
            except (IndexError, TypeError, ValueError):
                return None

            total = sum(v for _ts, _close, v in per_minute)
            cum_end = ticker["quote_volume"]
            entries, running = [], 0.0
            for ts, close, vol in per_minute:
                running += vol
                entries.append((ts, close, cum_end - (total - running)))
            return symbol, entries

        seeded = 0
        with ThreadPoolExecutor(max_workers=BOOTSTRAP_WORKERS) as pool:
            for result in pool.map(seed, targets):
                if self._stop:
                    return
                if not result:
                    continue
                symbol, entries = result
                key = f"MEXC:{symbol}"
                with self._lock:
                    existing = self._history.get(key, deque())
                    # живые замеры, успевшие прийти, обязаны остаться — свечи
                    # только достраивают историю СЛЕВА (более старую часть)
                    oldest_live = existing[0][0] if existing else float("inf")
                    merged = deque(e for e in entries if e[0] < oldest_live)
                    merged.extend(existing)
                    self._history[key] = merged
                seeded += 1

        self.on_status(f"[Ранние] прогрев завершён: {seeded} монет готовы")
        if on_done:
            on_done(seeded)

    @staticmethod
    def early_candidates(tickers, exchange=None, exclude_majors=True,
                          binance_spot_symbols=None):
        """Монеты в состоянии "живой тишины" — вотч-лист для наблюдения за
        стаканом. Это НЕ сигнал на вход: под профиль подходит ~5% рынка
        (68 из 1380 на момент калибровки), а стреляют единицы. Задача этого
        отбора — сузить рынок, чтобы дальше по кандидатам можно было физически
        успевать опрашивать стаканы.

        exclude_majors — выбросить монеты, торгующиеся на биржах первого
        эшелона (MAJOR_EXCHANGES + спот Binance). Списки берутся из ТОГО ЖЕ
        батча тикеров, который уже опрошен для всех бирж, поэтому фильтр не
        стоит ни одного дополнительного запроса. Площадки второго эшелона
        (AsterDEX, Gate) дисквалификацией не считаются — там такие монеты и
        живут; они лишь помечаются в поле also_on."""
        major = set()
        others = {}  # symbol -> список прочих бирж, где монета тоже есть
        for t in tickers:
            symbol, exch = t.get("symbol"), t.get("exchange")
            if exch in MAJOR_EXCHANGES:
                major.add(symbol)
            if exch != exchange:
                others.setdefault(symbol, []).append(exch)
        if binance_spot_symbols:
            major |= binance_spot_symbols

        out = []
        for t in tickers:
            if exchange and t.get("exchange") != exchange:
                continue
            if not t.get("early_ready"):
                continue
            if exclude_majors and t.get("symbol") in major:
                continue
            if not (EARLY_RANGE_MIN_PCT <= t.get("range_60m", 0.0) <= EARLY_RANGE_MAX_PCT):
                continue
            if not (EARLY_VOL_MIN_USD <= t.get("vol_60m", 0.0) <= EARLY_VOL_MAX_USD):
                continue
            if t.get("vol_accel", 0.0) >= EARLY_ACCEL_MAX:
                continue
            t["also_on"] = sorted(others.get(t.get("symbol"), []))
            out.append(t)
        # растущий OI — бонус: такие монеты всплывают в начало списка (трейдеры
        # уже открывают позиции), внутри группы — по сжатости диапазона.
        # Спотовые без OI не проигрывают ничего, кроме этого бонуса.
        return sorted(out, key=lambda x: (
            0 if x.get("oi_change_pct", 0.0) >= OI_RISE_HIGHLIGHT_PCT else 1,
            x["range_60m"]))

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
