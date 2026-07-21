"""
OKX (v5) — свой протокол. Канал books: первое сообщение сразу после подписки
уже полный снапшот (action="snapshot"), дальше action="update" с точечными
изменениями. Отдельный REST-бутстрап не нужен вообще — всё приходит через WS.

OKX использует прикладной (не протокольный) ping — литеральный текст "ping",
на который сервер отвечает литеральным "pong". Библиотечный ping/pong тут не
подходит, поэтому шлём его сами по таймеру.

Тикеры у OKX через дефис + суффикс SWAP (LAB-USDT-SWAP), у нас внутри —
слитно (LABUSDT), конвертация на границе модуля.
"""

import asyncio
import json
import threading

import requests
import websockets

WS_BASE = "wss://ws.okx.com:8443/ws/v5/public"
REST_INSTRUMENTS = "https://www.okx.com/api/v5/public/instruments"
PING_INTERVAL_SEC = 20


def to_okx_symbol(symbol: str) -> str:
    """LABUSDT -> LAB-USDT-SWAP (предполагаем бессрочник в USDT)."""
    symbol = symbol.upper()
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}-USDT-SWAP"
    return symbol


def from_okx_symbol(inst_id: str) -> str:
    return inst_id.replace("-SWAP", "").replace("-", "").upper()


class OKXWSManager:
    def __init__(self, on_depth_update, on_status):
        self.exchange = "OKX"
        self.label = "OKX"
        self.on_depth_update = on_depth_update  # callback(exchange, symbol, {"b":[(p,q)],"a":[(p,q)],"snapshot":bool})
        self.on_status = on_status
        self.loop = None
        self.thread = None
        self.ws = None
        self._stop = False
        self._lock = threading.Lock()
        self._desired = set()  # inst_id (LAB-USDT-SWAP)

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
        inst_id = to_okx_symbol(symbol)
        with self._lock:
            self._desired.add(inst_id)
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._subscribe([inst_id]), self.loop)

    def unsubscribe_symbol(self, symbol: str):
        inst_id = to_okx_symbol(symbol)
        with self._lock:
            self._desired.discard(inst_id)
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._unsubscribe([inst_id]), self.loop)

    # ---------- внутреннее ----------

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.set_exception_handler(self._on_loop_exception)
        self.loop.run_until_complete(self._main())

    def _on_loop_exception(self, loop, context):
        detail = context.get("exception") or context.get("message", "неизвестная ошибка")
        self.on_status(f"[{self.label}] Внутренняя ошибка: {detail}")

    async def _main(self):
        backoff = 1
        while not self._stop:
            ping_task = None
            try:
                self.on_status(f"[{self.label}] Подключение...")
                async with websockets.connect(WS_BASE, ping_interval=None) as ws:
                    self.ws = ws
                    self.on_status(f"[{self.label}] Подключено")
                    backoff = 1
                    with self._lock:
                        insts = list(self._desired)
                    if insts:
                        await self._subscribe(insts)
                    ping_task = asyncio.ensure_future(self._ping_loop(ws))
                    await self._listen(ws)
            except Exception as e:
                if self._stop:
                    break
                self.on_status(f"[{self.label}] Обрыв связи ({e}). Реконнект через {backoff}с")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                if ping_task:
                    ping_task.cancel()
        self.on_status(f"[{self.label}] Отключено")

    async def _ping_loop(self, ws):
        try:
            while not self._stop:
                await asyncio.sleep(PING_INTERVAL_SEC)
                await ws.send("ping")
        except Exception:
            pass

    async def _listen(self, ws):
        async for raw in ws:
            if self._stop:
                break
            if raw in ("pong", "ping"):
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            arg = msg.get("arg") or {}
            if arg.get("channel") != "books":
                continue
            inst_id = arg.get("instId")
            action = msg.get("action")
            data_list = msg.get("data") or []
            if not inst_id or not data_list:
                continue
            symbol = from_okx_symbol(inst_id)
            d = data_list[0]
            event = {
                "snapshot": action == "snapshot",
                "b": [(lvl[0], lvl[1]) for lvl in d.get("bids", [])],
                "a": [(lvl[0], lvl[1]) for lvl in d.get("asks", [])],
            }
            self.on_depth_update(self.exchange, symbol, event)

    async def _subscribe(self, inst_ids):
        if self.ws and inst_ids:
            args = [{"channel": "books", "instId": i} for i in inst_ids]
            await self.ws.send(json.dumps({"op": "subscribe", "args": args}))

    async def _unsubscribe(self, inst_ids):
        if self.ws and inst_ids:
            args = [{"channel": "books", "instId": i} for i in inst_ids]
            await self.ws.send(json.dumps({"op": "unsubscribe", "args": args}))

    async def _close(self):
        self._stop = True
        if self.ws:
            await self.ws.close()


def validate_symbol(symbol: str) -> bool:
    inst_id = to_okx_symbol(symbol)
    try:
        resp = requests.get(REST_INSTRUMENTS, params={"instType": "SWAP", "instId": inst_id}, timeout=10)
        resp.raise_for_status()
        return bool(resp.json().get("data"))
    except Exception:
        return True
