"""
Bitget (v2) — свой протокол, по устройству почти копия OKX. Канал books:
первое сообщение после подписки action="snapshot" (полный стакан), дальше
action="update" (точечные изменения; size "0" = уровень снят). Отдельный
REST-бутстрап не нужен — всё приходит через WS.

Ping прикладной: шлём текст "ping", сервер отвечает "pong". Библиотечный
ping/pong не годится (Bitget рвёт соединение без прикладного пинга за 30с),
поэтому шлём сами по таймеру — как в okx_ws.py.

Тикеры Bitget-спота слитные (BTCUSDT) — совпадают с нашим внутренним форматом,
конвертация не нужна. Пока подключаем только СПОТ (по просьбе); фьючерс Bitget
можно добавить сюда же новым конфигом с instType="USDT-FUTURES".
"""

import asyncio
import json
import threading

import requests
import websockets

WS_BASE = "wss://ws.bitget.com/v2/ws/public"
REST_SYMBOLS = "https://api.bitget.com/api/v2/spot/public/symbols"
PING_INTERVAL_SEC = 20


BITGET_CONFIGS = {
    "BITGET SPOT": {
        "label": "Bitget Spot",
        "inst_type": "SPOT",
    },
}


class BitgetWSManager:
    def __init__(self, on_depth_update, on_status, exchange="BITGET SPOT"):
        cfg = BITGET_CONFIGS[exchange]
        self.exchange = exchange
        self.label = cfg["label"]
        self.inst_type = cfg["inst_type"]
        self.on_depth_update = on_depth_update  # callback(exchange, symbol, {"b":[(p,q)],"a":[(p,q)],"snapshot":bool})
        self.on_status = on_status
        self.loop = None
        self.thread = None
        self.ws = None
        self._stop = False
        self._lock = threading.Lock()
        self._desired = set()  # instId (BTCUSDT)

    # ---------- публичное API (идентично GateWSManager/OKXWSManager) ----------

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
        inst_id = symbol.upper()
        with self._lock:
            self._desired.add(inst_id)
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._subscribe([inst_id]), self.loop)

    def unsubscribe_symbol(self, symbol: str):
        inst_id = symbol.upper()
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
            symbol = inst_id.upper()
            d = data_list[0]
            event = {
                "snapshot": action == "snapshot",
                "b": [(lvl[0], lvl[1]) for lvl in d.get("bids", [])],
                "a": [(lvl[0], lvl[1]) for lvl in d.get("asks", [])],
            }
            self.on_depth_update(self.exchange, symbol, event)

    async def _subscribe(self, inst_ids):
        if self.ws and inst_ids:
            args = [{"instType": self.inst_type, "channel": "books", "instId": i} for i in inst_ids]
            await self.ws.send(json.dumps({"op": "subscribe", "args": args}))

    async def _unsubscribe(self, inst_ids):
        if self.ws and inst_ids:
            args = [{"instType": self.inst_type, "channel": "books", "instId": i} for i in inst_ids]
            await self.ws.send(json.dumps({"op": "unsubscribe", "args": args}))

    async def _close(self):
        self._stop = True
        if self.ws:
            await self.ws.close()


def validate_symbol(symbol: str, exchange="BITGET SPOT") -> bool:
    """Есть ли такая спот-пара на Bitget. Bitget на невалидный символ отдаёт
    HTTP 400 + пустой data (code 40034), поэтому raise_for_status тут НЕЛЬЗЯ —
    иначе валидный ответ "нет такой пары" превратился бы в исключение и
    ошибочно прошёл бы по fallback. Смотрим прямо на data. Fallback True —
    только на РЕАЛЬНЫЙ сетевой сбой, чтобы не блокировать из-за него."""
    try:
        resp = requests.get(REST_SYMBOLS, params={"symbol": symbol.upper()}, timeout=10)
        return bool(resp.json().get("data"))
    except Exception:
        return True
