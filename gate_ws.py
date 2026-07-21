"""
Gate.io Futures (USDT-margined) — свой протокол, отличный от Binance-style.

WS: канал futures.order_book_update, синхронизация через REST-снапшот с
with_id=true (алгоритм похож на Binance по духу, но другие имена полей и
нужен отдельный REST-запрос за базовым id, а не просто снапшот).

Тикеры у Gate через подчёркивание (LAB_USDT), у нас внутри приложения —
слитно (LABUSDT), конвертация на границе модуля.
"""

import asyncio
import json
import threading
import time

import requests
import websockets

WS_BASE = "wss://fx-ws.gateio.ws/v4/ws/usdt"
REST_BASE = "https://fx-api.gateio.ws/api/v4/futures/usdt"
DEPTH_FREQUENCY = "100ms"
DEPTH_LEVEL = "100"


def to_gate_symbol(symbol: str) -> str:
    """LABUSDT -> LAB_USDT (предполагаем котировку в USDT)."""
    symbol = symbol.upper()
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}_USDT"
    return symbol


def from_gate_symbol(contract: str) -> str:
    return contract.replace("_", "").upper()


class GateWSManager:
    def __init__(self, on_depth_update, on_status):
        self.exchange = "GATE"
        self.label = "Gate.io"
        self.on_depth_update = on_depth_update  # callback(exchange, symbol, {"b":[(p,q)],"a":[(p,q)],"snapshot":bool})
        self.on_status = on_status
        self.loop = None
        self.thread = None
        self.ws = None
        self._stop = False
        self._lock = threading.Lock()
        self._desired = set()    # contract-имена (LAB_USDT), которые должны быть подписаны
        self._book_state = {}    # contract -> {"synced":bool, "last_id":int, "buffer":[...]}

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
        contract = to_gate_symbol(symbol)
        with self._lock:
            self._desired.add(contract)
            self._book_state[contract] = {"synced": False, "last_id": 0, "buffer": [], "bootstrapping": False}
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._subscribe(contract), self.loop)

    def unsubscribe_symbol(self, symbol: str):
        contract = to_gate_symbol(symbol)
        with self._lock:
            self._desired.discard(contract)
            self._book_state.pop(contract, None)
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._unsubscribe(contract), self.loop)

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
            try:
                self.on_status(f"[{self.label}] Подключение...")
                async with websockets.connect(WS_BASE, ping_interval=None) as ws:
                    self.ws = ws
                    self.on_status(f"[{self.label}] Подключено")
                    backoff = 1
                    with self._lock:
                        contracts = list(self._desired)
                        for c in contracts:
                            self._book_state[c] = {"synced": False, "last_id": 0, "buffer": [], "bootstrapping": False}
                    for c in contracts:
                        await self._subscribe(c)
                    await self._listen(ws)
            except Exception as e:
                if self._stop:
                    break
                self.on_status(f"[{self.label}] Обрыв связи ({e}). Реконнект через {backoff}с")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        self.on_status(f"[{self.label}] Отключено")

    async def _listen(self, ws):
        async for raw in ws:
            if self._stop:
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("channel") != "futures.order_book_update" or msg.get("event") != "update":
                continue
            result = msg.get("result") or {}
            contract = result.get("s")
            if contract:
                self._handle_update(contract, result)

    def _handle_update(self, contract, result):
        state = self._book_state.get(contract)
        if state is None:
            return
        if not state["synced"]:
            state["buffer"].append(result)
            self._ensure_bootstrap(contract, state)
            return

        u = result.get("u")
        big_u = result.get("U")
        if u is not None and u <= state["last_id"]:
            return
        if big_u is not None and big_u != state["last_id"] + 1:
            state["synced"] = False
            state["buffer"] = [result]
            self._ensure_bootstrap(contract, state)
            return
        state["last_id"] = u
        symbol = from_gate_symbol(contract)
        self.on_depth_update(self.exchange, symbol, {
            "b": [(lvl["p"], lvl["s"]) for lvl in result.get("b", [])],
            "a": [(lvl["p"], lvl["s"]) for lvl in result.get("a", [])],
        })

    def _ensure_bootstrap(self, contract, state):
        """Запускает _bootstrap не более одного раза одновременно на contract.
        Раньше запуск триггерился только по len(buffer)==1 — если тот
        единственный REST-запрос падал (таймаут/429/сеть), контракт навсегда
        оставался несинхронизированным: buffer продолжал расти, но условие
        больше никогда не срабатывало заново, и стакан молча замирал (при
        этом статус подключения продолжал показывать "подключено")."""
        if state["bootstrapping"]:
            return
        state["bootstrapping"] = True
        threading.Thread(target=self._bootstrap, args=(contract,), daemon=True).start()

    def _bootstrap(self, contract):
        """REST-снапшот с with_id=true + поиск точки старта в буфере. Блокирующе,
        отдельный поток. При ошибке — повтор с бэкоффом, а не тихая сдача."""
        backoff = 1
        data = None
        while True:
            state = self._book_state.get(contract)
            if state is None or self._stop:
                return
            try:
                resp = requests.get(
                    f"{REST_BASE}/order_book",
                    params={"contract": contract, "limit": DEPTH_LEVEL, "with_id": "true"},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                self.on_status(f"[{self.label}] Ошибка снапшота {contract}: {e}. Повтор через {backoff}с")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

        base_id = data.get("id")
        state = self._book_state.get(contract)
        if state is None:
            return
        if base_id is None:
            state["bootstrapping"] = False
            return

        symbol = from_gate_symbol(contract)
        self.on_depth_update(self.exchange, symbol, {
            "snapshot": True,
            "b": [(lvl["p"], lvl["s"]) for lvl in data.get("bids", [])],
            "a": [(lvl["p"], lvl["s"]) for lvl in data.get("asks", [])],
        })

        buffer, state["buffer"] = state["buffer"], []
        applying = False
        for ev in buffer:
            u, big_u = ev.get("u"), ev.get("U")
            if u is None or u < base_id:
                continue
            if not applying:
                if big_u is not None and big_u <= base_id + 1 <= u:
                    applying = True
                else:
                    continue
            state["last_id"] = u
            self.on_depth_update(self.exchange, symbol, {
                "b": [(lvl["p"], lvl["s"]) for lvl in ev.get("b", [])],
                "a": [(lvl["p"], lvl["s"]) for lvl in ev.get("a", [])],
            })
        if not applying:
            state["last_id"] = base_id
        state["synced"] = True
        state["bootstrapping"] = False

    async def _subscribe(self, contract):
        if self.ws:
            payload = {"time": int(time.time()), "channel": "futures.order_book_update",
                       "event": "subscribe", "payload": [contract, DEPTH_FREQUENCY, DEPTH_LEVEL]}
            await self.ws.send(json.dumps(payload))

    async def _unsubscribe(self, contract):
        if self.ws:
            payload = {"time": int(time.time()), "channel": "futures.order_book_update",
                       "event": "unsubscribe", "payload": [contract, DEPTH_FREQUENCY]}
            await self.ws.send(json.dumps(payload))

    async def _close(self):
        self._stop = True
        if self.ws:
            await self.ws.close()


def validate_symbol(symbol: str) -> bool:
    contract = to_gate_symbol(symbol)
    try:
        resp = requests.get(f"{REST_BASE}/contracts/{contract}", timeout=10)
        return resp.status_code == 200
    except Exception:
        return True
