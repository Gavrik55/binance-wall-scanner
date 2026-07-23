"""
Подключение к Binance-style рынкам (combined stream WS + REST snapshot).
Binance/AsterDEX futures и spot обслуживаются тем же классом — просто с
разными базовыми адресами и REST-путями.

ВАЖНО (фикс race condition): желаемые стримы (_desired_streams) хранятся
независимо от состояния соединения. При (пере)подключении начальный набор
стримов передаётся сразу в URL через ?streams=... (задокументированный способ
у обеих бирж), а не только через SUBSCRIBE-сообщение после гола коннекта —
это исключает ситуацию, когда подписка формируется до того как соединение
реально поднялось, и просто теряется.
"""

import asyncio
import json
import threading

import requests
import websockets

from debug_log import log as dlog

EXCHANGES = {
    "BINANCE": {
        "label": "Binance",
        "ws_base": "wss://fstream.binance.com/stream",
        "rest_base": "https://fapi.binance.com",
        "depth_path": "/fapi/v1/depth",
        "exchange_info_path": "/fapi/v1/exchangeInfo",
    },
    "BINANCE SPOT": {
        "label": "Binance Spot",
        "ws_base": "wss://stream.binance.com:9443/stream",
        "rest_base": "https://api.binance.com",
        "depth_path": "/api/v3/depth",
        "exchange_info_path": "/api/v3/exchangeInfo",
    },
    "ASTERDEX": {
        "label": "AsterDEX",
        "ws_base": "wss://fstream.asterdex.com/stream",
        "rest_base": "https://fapi.asterdex.com",
        "depth_path": "/fapi/v1/depth",
        "exchange_info_path": "/fapi/v1/exchangeInfo",
    },
    "ASTERDEX SPOT": {
        "label": "AsterDEX Spot",
        "ws_base": "wss://sstream.asterdex.com/stream",
        "rest_base": "https://sapi.asterdex.com",
        "depth_path": "/api/v1/depth",
        "exchange_info_path": "/api/v1/exchangeInfo",
    },
}

DEPTH_SPEED = "100ms"


class ExchangeWSManager:
    """Один экземпляр = одно подключение к одной Binance-style бирже."""

    def __init__(self, exchange: str, on_depth_update, on_status):
        cfg = EXCHANGES[exchange]
        self.exchange = exchange
        self.label = cfg["label"]
        self.ws_base = cfg["ws_base"]
        self.rest_base = cfg["rest_base"]
        self.on_depth_update = on_depth_update  # callback(exchange, symbol, event_dict)
        self.on_status = on_status
        self.loop = None
        self.thread = None
        self.ws = None
        self._stop = False
        self._lock = threading.Lock()
        self._desired_streams = set()   # что должно быть подписано (живёт независимо от соединения)
        self._active_streams = set()    # что реально подтверждено в текущем соединении
        self._req_id = 1

    # ---------- публичное API ----------

    def start(self):
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop = True
        if self.loop:
            try:
                asyncio.run_coroutine_threadsafe(self._close(), self.loop)
            except RuntimeError:
                pass

    def subscribe_symbol(self, symbol: str):
        stream = f"{symbol.lower()}@depth@{DEPTH_SPEED}"
        with self._lock:
            self._desired_streams.add(stream)
        dlog(f"[{self.label}] subscribe_symbol({symbol}) loop_ready={self.loop is not None} ws_ready={self.ws is not None}")
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._subscribe([stream]), self.loop)
        # если loop ещё не поднят — стрим всё равно уйдёт в ?streams= при
        # первом коннекте (см. _main), запрос не теряется

    def unsubscribe_symbol(self, symbol: str):
        stream = f"{symbol.lower()}@depth@{DEPTH_SPEED}"
        with self._lock:
            self._desired_streams.discard(stream)
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._unsubscribe([stream]), self.loop)

    # ---------- внутреннее ----------

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.set_exception_handler(self._on_loop_exception)
        self.loop.run_until_complete(self._main())

    def _on_loop_exception(self, loop, context):
        # без этого необработанное исключение внутри event loop уходит в
        # стандартный logging, который в PyInstaller --windowed сборке может
        # сам упасть (sys.stderr = None) и пропасть бесследно
        detail = context.get("exception") or context.get("message", "неизвестная ошибка")
        self.on_status(f"[{self.label}] Внутренняя ошибка: {detail}")

    async def _main(self):
        backoff = 1
        while not self._stop:
            try:
                with self._lock:
                    initial_streams = list(self._desired_streams)
                url = self.ws_base
                if initial_streams:
                    url = f"{self.ws_base}?streams=" + "/".join(initial_streams)
                dlog(f"[{self.label}] connecting, initial_streams={initial_streams}")
                self.on_status(f"[{self.label}] Подключение...")
                async with websockets.connect(url, ping_interval=180, ping_timeout=600) as ws:
                    self.ws = ws
                    self._active_streams = set(initial_streams)
                    dlog(f"[{self.label}] connected ok, active_streams={self._active_streams}")
                    self.on_status(f"[{self.label}] Подключено")
                    backoff = 1

                    # ДОСОГЛАСОВАНИЕ: пока URL для этого подключения формировался,
                    # subscribe_symbol() мог быть вызван для других символов чуть
                    # позже и не попасть в initial_streams (гонка) — досылаем через
                    # обычный SUBSCRIBE всё, что осталось в _desired_streams, но не
                    # вошло в _active_streams. Без этого такие символы молча
                    # оставались бы без единой реальной подписки навсегда.
                    with self._lock:
                        missing = list(self._desired_streams - self._active_streams)
                    if missing:
                        dlog(f"[{self.label}] досогласование: досылаю пропущенные {missing}")
                        await self._subscribe(missing)

                    await self._listen(ws)
            except Exception as e:
                if self._stop:
                    break
                dlog(f"[{self.label}] connection error: {e!r}")
                self.on_status(f"[{self.label}] Обрыв связи ({e}). Реконнект через {backoff}с")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        self.on_status(f"[{self.label}] Отключено")

    async def _listen(self, ws):
        msg_count = 0
        async for raw in ws:
            if self._stop:
                break
            msg_count += 1
            if msg_count <= 5:
                dlog(f"[{self.label}] raw #{msg_count}: {raw[:300]}")
            elif msg_count == 50:
                dlog(f"[{self.label}] получено {msg_count} сообщений суммарно, поток идёт нормально")
            try:
                msg = json.loads(raw)
            except Exception as e:
                if msg_count <= 5:
                    dlog(f"[{self.label}] json.loads провалился: {e!r}")
                continue
            if "stream" in msg and "data" in msg:
                stream = msg["stream"]
                data = msg["data"]
                if "@depth" in stream:
                    symbol = stream.split("@")[0].upper()
                    self.on_depth_update(self.exchange, symbol, data)
            elif msg_count <= 5:
                dlog(f"[{self.label}] сообщение не depth-формата (например ack подписки): {msg}")

    async def _send_raw(self, obj):
        if self.ws:
            await self.ws.send(json.dumps(obj))

    async def _subscribe(self, streams):
        with self._lock:
            new = [s for s in streams if s not in self._active_streams]
        if not new or not self.ws:
            dlog(f"[{self.label}] _subscribe пропущен: new={new} ws_ready={self.ws is not None}")
            return
        with self._lock:
            self._active_streams.update(new)
        await self._send_raw({"method": "SUBSCRIBE", "params": new, "id": self._next_id()})
        dlog(f"[{self.label}] SUBSCRIBE реально отправлен: {new}")

    async def _unsubscribe(self, streams):
        with self._lock:
            present = [s for s in streams if s in self._active_streams]
        if not present or not self.ws:
            return
        with self._lock:
            for s in present:
                self._active_streams.discard(s)
        await self._send_raw({"method": "UNSUBSCRIBE", "params": present, "id": self._next_id()})

    async def _close(self):
        self._stop = True
        if self.ws:
            await self.ws.close()

    def _next_id(self):
        self._req_id += 1
        return self._req_id


def fetch_depth_snapshot(exchange: str, symbol: str, limit: int = 1000) -> dict:
    cfg = EXCHANGES[exchange]
    url = f"{cfg['rest_base']}{cfg['depth_path']}"
    resp = requests.get(url, params={"symbol": symbol.upper(), "limit": limit}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def validate_symbol(exchange: str, symbol: str) -> bool:
    cfg = EXCHANGES[exchange]
    url = f"{cfg['rest_base']}{cfg['exchange_info_path']}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        symbols = {s["symbol"] for s in resp.json().get("symbols", [])}
        return symbol.upper() in symbols
    except Exception:
        return True
