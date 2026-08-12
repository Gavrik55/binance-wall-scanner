"""Монитор "аптиков" (limit up/down) по всему рынку свопов OKX + Bybit.

Что ловим: в момент зажатия у спреда стоит АНОМАЛЬНО КРУПНАЯ плотность
(одинокая стенка ≫ обычных уровней), и одна сторона рыночных сделок замолкает
(лента становится односторонней) — заявки в неё не проходят.

Пороги (R3) откалиброваны на реальной 4-часовой записи DOS-USDT-SWAP: чистое
событие 18:44 (плотность ×27, 0% покупок) прошло, а весь шум (было 6 срабатываний
на ×15 без ленты) отсеялся до 1. Ключевые уроки калибровки:
  - фильтр "движение ≥X%" как условие алерта ВРЕДЕН: настоящее зажатие бывает
    при стоящей цене (её и держит стенка), поэтому движение используем только
    как дешёвый ПРЕДФИЛЬТР (какие символы вообще смотреть в стакане);
  - настоящий сигнал = плотность у спреда + замолчавшая сторона ленты.

Только OKX + Bybit — Binance (и его терминал) не трогаем. Трафик: тикеры Bybit
тяжёлые (~586 КБ/опрос), поэтому фича ВЫКЛючена по умолчанию и опрос редкий.
"""

import gzip
import json
import os
import statistics
import threading
import time
from collections import deque, defaultdict

import requests

POLL_INTERVAL_SEC = 5.0        # редкий опрос: событие живёт секунды, а трафик экономим
MOVE_WINDOW_SEC = 45.0
MOVE_PREFILTER_PCT = 0.8       # ПРЕДфильтр (какие смотреть в стакане), НЕ условие алерта
NEAR_K = 5                     # "у спреда" = первые N уровней
DENSITY_RATIO = 20.0           # стенка крупнее типичного крупного уровня в N раз
TAPE_BLOCKED_PCT = 10.0        # сторона ленты ниже этого = рыночные заявки в неё отключены
TAPE_WINDOW_MS = 15000
MAX_CHECKS_PER_EXCH = 12       # лимит стакан-запросов на биржу за цикл
REALERT_SEC = 120              # не повторять алерт по той же монете чаще
RECORD_AFTER_SEC = 120.0       # сколько писать ситуацию после срабатывания
RECORD_INTERVAL = 1.0


def _okx_tickers():
    r = requests.get("https://www.okx.com/api/v5/market/tickers", params={"instType": "SWAP"}, timeout=15)
    r.raise_for_status()
    out = []
    for t in r.json().get("data", []):
        i = t.get("instId", "")
        if i.endswith("-USDT-SWAP"):
            try:
                out.append((i, float(t["last"])))
            except (KeyError, ValueError, TypeError):
                pass
    return out


def _bybit_tickers():
    r = requests.get("https://api.bybit.com/v5/market/tickers", params={"category": "linear"}, timeout=15)
    r.raise_for_status()
    out = []
    for t in r.json().get("result", {}).get("list", []):
        s = t.get("symbol", "")
        if s.endswith("USDT"):
            try:
                out.append((s, float(t["lastPrice"])))
            except (KeyError, ValueError, TypeError):
                pass
    return out


def _okx_depth(sym):
    d = requests.get("https://www.okx.com/api/v5/market/books", params={"instId": sym, "sz": 25}, timeout=10).json()["data"][0]
    return ([(float(x[0]), float(x[1])) for x in d["bids"]],
            [(float(x[0]), float(x[1])) for x in d["asks"]])


def _bybit_depth(sym):
    d = requests.get("https://api.bybit.com/v5/market/orderbook", params={"category": "linear", "symbol": sym, "limit": 25}, timeout=10).json()["result"]
    return ([(float(x[0]), float(x[1])) for x in d["b"]],
            [(float(x[0]), float(x[1])) for x in d["a"]])


def _okx_tape(sym):
    d = requests.get("https://www.okx.com/api/v5/market/trades", params={"instId": sym, "limit": 50}, timeout=10).json()["data"]
    return [(t["side"], float(t["sz"]), float(t["ts"])) for t in d]


def _bybit_tape(sym):
    d = requests.get("https://api.bybit.com/v5/market/recent-trade", params={"category": "linear", "symbol": sym, "limit": 60}, timeout=10).json()["result"]["list"]
    return [(t["side"].lower(), float(t["size"]), float(t["time"])) for t in d]


EXCHANGES = {
    "OKX":   {"tickers": _okx_tickers, "depth": _okx_depth, "tape": _okx_tape,
              "disp": lambda i: i.replace("-USDT-SWAP", "USDT")},
    "BYBIT": {"tickers": _bybit_tickers, "depth": _bybit_depth, "tape": _bybit_tape,
              "disp": lambda s: s},
}


def spread_anomaly(bids, asks):
    """Одинокая стенка у спреда: уровень крупнее ТИПИЧНОГО КРУПНОГО (медианы
    топ-10 по размеру) в DENSITY_RATIO раз. Сравнение с крупными, а не со всеми,
    иначе тонкие глубокие уровни занижают базу и ликвидный стакан ложно
    выглядит аномальным. Отношение безразмерно (контракты OKX / монета Bybit)."""
    allsz = sorted((s for _, s in bids[:25] + asks[:25] if s > 0), reverse=True)
    if len(allsz) < 12:
        return None
    ref = statistics.median(allsz[:10])
    if ref <= 0:
        return None
    best = None
    for side, book in (("BID", bids), ("ASK", asks)):
        near = [s for _, s in book[:NEAR_K] if s > 0]
        if near:
            ratio = max(near) / ref
            if ratio >= DENSITY_RATIO and (best is None or ratio > best[1]):
                best = (side, ratio)
    return best


def tape_state(trades):
    """Доля buy/sell за окно + пометка, если сторона рыночных сделок замолчала."""
    now_ms = time.time() * 1000
    buy = sum(sz for sd, sz, ts in trades if sd == "buy" and now_ms - ts <= TAPE_WINDOW_MS)
    sell = sum(sz for sd, sz, ts in trades if sd == "sell" and now_ms - ts <= TAPE_WINDOW_MS)
    tot = buy + sell
    if tot <= 0:
        return None, 50.0
    bp = buy / tot * 100
    blocked = None
    if bp < TAPE_BLOCKED_PCT:
        blocked = "покупки"
    elif bp > 100 - TAPE_BLOCKED_PCT:
        blocked = "продажи"
    return blocked, bp


class UptickMonitor:
    """Фоновый поток. Пока enabled=False — спит (трафик не тратит). on_alert
    вызывается из фонового потока со словарём события — GUI сам перекладывает
    в свою очередь, не трогая Tk напрямую отсюда."""

    def __init__(self, on_alert, on_status=None, record_dir=None):
        self.on_alert = on_alert
        self.on_status = on_status or (lambda t: None)
        self.record_dir = record_dir
        self.enabled = False
        self._stop = False
        self._thread = None
        self._hist = defaultdict(deque)     # "EXCH:SYM" -> deque[(ts, last)]
        self._flagged = {}                  # "EXCH:SYM" -> last alert ts (антиповтор)
        self._recording = set()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def set_enabled(self, value):
        self.enabled = bool(value)

    def _run(self):
        while not self._stop:
            if not self.enabled:
                time.sleep(0.5)
                continue
            started = time.monotonic()
            for exch in EXCHANGES:
                if self._stop or not self.enabled:
                    break
                try:
                    self._scan(exch)
                except Exception as e:
                    self.on_status(f"[Аптики] ошибка {exch}: {e}")
            elapsed = time.monotonic() - started
            for _ in range(int(max(1.0, POLL_INTERVAL_SEC - elapsed) * 10)):
                if self._stop or not self.enabled:
                    break
                time.sleep(0.1)

    def _scan(self, exch):
        cfg = EXCHANGES[exch]
        now = time.time()
        movers = []
        for sym, last in cfg["tickers"]():
            if not last:
                continue
            key = f"{exch}:{sym}"
            dq = self._hist[key]
            dq.append((now, last))
            while dq and now - dq[0][0] > MOVE_WINDOW_SEC + 15:
                dq.popleft()
            base = next((p for ts, p in dq if now - ts <= MOVE_WINDOW_SEC), None)
            if base and now - dq[0][0] >= MOVE_WINDOW_SEC * 0.6:
                mv = (last - base) / base * 100
                if abs(mv) >= MOVE_PREFILTER_PCT:
                    movers.append((sym, last, mv))
        movers.sort(key=lambda x: -abs(x[2]))
        for sym, last, mv in movers[:MAX_CHECKS_PER_EXCH]:
            if self._stop or not self.enabled:
                return
            key = f"{exch}:{sym}"
            try:
                bids, asks = cfg["depth"](sym)
            except Exception:
                continue
            anom = spread_anomaly(bids, asks)
            if not anom:
                continue
            try:
                trades = cfg["tape"](sym)
            except Exception:
                trades = []
            blocked, bp = tape_state(trades)
            if blocked is None:      # R3: нужна замолчавшая сторона
                continue
            if now - self._flagged.get(key, 0) < REALERT_SEC:
                continue
            self._flagged[key] = now
            side, ratio = anom
            event = {
                "ts": now, "exchange": exch, "symbol": cfg["disp"](sym),
                "side": side, "ratio": ratio, "blocked": blocked,
                "buy_pct": bp, "move_pct": mv, "price": last,
            }
            self.on_alert(event)
            if self.record_dir:
                threading.Thread(target=self._record, args=(exch, sym, event), daemon=True).start()
            time.sleep(0.05)

    def _record(self, exch, sym, meta):
        key = f"{exch}:{sym}"
        if key in self._recording:
            return
        self._recording.add(key)
        cfg = EXCHANGES[exch]
        try:
            os.makedirs(self.record_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
            path = os.path.join(self.record_dir, f"{exch}_{cfg['disp'](sym)}_{stamp}.jsonl.gz")
            with gzip.open(path, "at", encoding="utf-8") as f:
                f.write(json.dumps({"t": "event", **meta}, ensure_ascii=False) + "\n")
                end = time.time() + RECORD_AFTER_SEC
                while time.time() < end and not self._stop:
                    t0 = time.time()
                    try:
                        bids, asks = cfg["depth"](sym)
                        trades = cfg["tape"](sym)
                        f.write(json.dumps({
                            "t": "snap", "ts": round(time.time(), 3),
                            "b": [[p, s] for p, s in bids[:25]],
                            "a": [[p, s] for p, s in asks[:25]],
                            "trades": [[sd, sz, tt] for sd, sz, tt in trades[:40]],
                        }) + "\n")
                    except Exception:
                        pass
                    time.sleep(max(0.0, RECORD_INTERVAL - (time.time() - t0)))
        except Exception as e:
            self.on_status(f"[Аптики] ошибка записи: {e}")
        finally:
            self._recording.discard(key)
