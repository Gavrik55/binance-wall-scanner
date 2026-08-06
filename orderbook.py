"""
Локальный стакан для одного символа. Поддерживается в актуальном состоянии
через diff-обновления, синхронизация — по официальному алгоритму Binance Futures:
https://binance-docs.github.io/apidocs/futures/en/#how-to-manage-a-local-order-book-correctly

ВАЖНО (фикс бесконечного ресинка): REST-снапшот даёт lastUpdateId, который
почти НИКОГДА не совпадает ровно с "u" какого-то живого diff-события из WS —
это независимый счётчик от отдельного REST-сервиса, и на практике он попадает
СЕРЕДИНОЙ в диапазон [U;u] одного из последующих diff-событий. Официальный
алгоритм Binance учитывает это: синхронизированным стакан считается только
после того, как найдено событие с U <= lastUpdateId+1 <= u — вот его и надо
применить первым, а не сверять "pu == lastUpdateId" (там и близко может не
совпасть). Старая версия этого файла сразу после snapshot() выставляла
synced=True БЕЗ этой проверки, если ни одно уже отбуференное событие не
подошло — а следующее живое событие, естественно, не проходило pu-сверку с
"чужим" lastUpdateId, что рвало синхронизацию заново, по кругу, до
бесконечности (и до 429 от биржи, см. debug.log).

Также методы ниже вызываются из ДВУХ разных потоков — из WS-потока (apply_diff
на каждое сообщение) и из фонового потока REST-ресинка (apply_snapshot после
получения снапшота) — отсюда блокировка на все мутации общего состояния.

ВАЖНО (сторож зависшего поиска точки старта): пока идёт поиск точки старта
после снапшота (_pending_baseline не None), apply_diff всегда возвращал True —
то есть гуй никогда не узнавал, что пора переспросить снапшот заново. Если
ровно в этот момент в живом потоке WS случится пропуск сообщения (например
сразу после реконнекта), нужное событие с U <= lastUpdateId+1 <= u может
никогда не встретиться — стакан тогда навсегда виснет в "ожидании старта":
без единой ошибки, без ресинка, просто Best Bid/Ask остаются "-" бесконечно.
PENDING_TIMEOUT_SEC ограничивает это ожидание: если точка старта не находится
достаточно долго, apply_diff возвращает False и гуй запускает свежий ресинк.
"""

import threading
import time

PENDING_TIMEOUT_SEC = 5.0


class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids = {}   # price -> qty
        self.asks = {}
        self.last_update_id = None
        self.synced = False
        self._buffer = []  # diff-события, накопленные пока нет снапшота/точки старта
        self._pending_baseline = None  # lastUpdateId снапшота, для которого ещё не найдена точка старта
        self._pending_since = None     # когда начали ждать точку старта — для таймаута
        self._lock = threading.Lock()

    def apply_snapshot(self, snapshot: dict):
        with self._lock:
            self.bids = {float(p): float(q) for p, q in snapshot["bids"]}
            self.asks = {float(p): float(q) for p, q in snapshot["asks"]}
            self.last_update_id = None
            self.synced = False
            self._pending_baseline = snapshot["lastUpdateId"]
            self._pending_since = time.monotonic()

            events, self._buffer = self._buffer, []
            for ev in events:
                self._try_find_start(ev)

    def apply_diff(self, event: dict) -> bool:
        """Возвращает False, если обнаружен разрыв последовательности (нужен ресинк)."""
        with self._lock:
            if self._pending_baseline is not None:
                # ещё ищем точку старта относительно последнего снапшота —
                # эта же проверка "захватывает ли диапазон событие lastUpdateId+1"
                # применяется и к живым событиям, не только к уже отбуференным
                self._try_find_start(event)
                if self._pending_baseline is not None:
                    if time.monotonic() - self._pending_since > PENDING_TIMEOUT_SEC:
                        # точку старта не нашли за разумное время (скорее всего
                        # пропущено сообщение в потоке) — сдаёмся, просим ресинк
                        self._pending_baseline = None
                        self.synced = False
                        self._buffer = [event]
                        return False
                return True
            if not self.synced:
                self._buffer.append(event)
                return True
            if event["u"] <= self.last_update_id:
                return True  # устаревшее событие, игнор
            prev_u = event.get("pu")
            first_u = event.get("U")
            if prev_u is not None:
                if prev_u != self.last_update_id:
                    self.synced = False
                    self._buffer = [event]
                    return False
            elif first_u is not None and first_u > self.last_update_id + 1:
                self.synced = False
                self._buffer = [event]
                return False
            self._apply(event)
            return True

    def _try_find_start(self, ev):
        """Ищет точку старта локального стакана после снапшота: первое
        событие, чей диапазон [U;u] захватывает lastUpdateId+1 снапшота
        (см. коммент в начале файла). До этого момента синхронизации нет,
        события просто пропускаются/копятся. После — применяются подряд,
        без сверки pu (это те же события, что шли в буфере непрерывно)."""
        if self.last_update_id is not None:
            self._apply(ev)
            return
        if ev["u"] < self._pending_baseline:
            return  # устарело относительно снапшота
        if ev["U"] <= self._pending_baseline + 1 <= ev["u"]:
            self._apply(ev)
            self._pending_baseline = None
            self.synced = True

    def _apply(self, event: dict):
        for p, q in event["b"]:
            p, q = float(p), float(q)
            if q == 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = q
        for p, q in event["a"]:
            p, q = float(p), float(q)
            if q == 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = q
        self.last_update_id = event["u"]

    def best_bid(self):
        with self._lock:
            return max(self.bids) if self.bids else None

    def best_ask(self):
        with self._lock:
            return min(self.asks) if self.asks else None

    def mid(self):
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2

    # ---- generic-методы для бирж с собственной бухгалтерией последовательности
    # (Gate, OKX) — они сами решают когда данные готовы к применению, эти
    # методы просто кладут готовые bids/asks в стакан ----

    def set_snapshot(self, bids, asks):
        """Полная замена стакана — без Binance-style update_id учёта."""
        with self._lock:
            self.bids = {float(p): float(q) for p, q in bids if float(q) > 0}
            self.asks = {float(p): float(q) for p, q in asks if float(q) > 0}
            self.synced = True

    def apply_deltas(self, bids, asks):
        """Точечные изменения (0 = удалить уровень), без сверки update_id."""
        with self._lock:
            for p, q in bids:
                p, q = float(p), float(q)
                if q == 0:
                    self.bids.pop(p, None)
                else:
                    self.bids[p] = q
            for p, q in asks:
                p, q = float(p), float(q)
                if q == 0:
                    self.asks.pop(p, None)
                else:
                    self.asks[p] = q
