import csv
import os
import threading
import time
from datetime import datetime


AUDIT_FIELDS = [
    "source",
    "row_type",
    "local_time",
    "ts_epoch",
    "exchange",
    "market",
    "symbol",
    "side",
    "price",
    "qty",
    "usd",
    "best_bid",
    "best_ask",
    "mid",
    "spread",
    "dist_abs",
    "dist_pct",
    "age_sec",
    "event_kind",
    "event_extra",
    "threshold_usd",
    "threshold_max_usd",
    "max_distance_pct",
    "single_confirm_sec",
    "confirmed",
    "baseline",
    "near_spread",
    "trade_side",
    "trade_count",
    "trade_qty",
    "trade_usd",
    "trade_verdict",
    "trade_note",
]


def market_type(exchange):
    return "SPOT" if str(exchange).upper().endswith(" SPOT") else "FUTURES"


def local_time(ts):
    return datetime.fromtimestamp(float(ts)).isoformat(timespec="milliseconds")


def csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.12g}"
    return value


class AuditCsvWriter:
    def __init__(self, app_dir, dirname="audit_logs"):
        self.app_dir = app_dir
        self.dirname = dirname
        self.path = None
        self._file = None
        self._writer = None
        self._lock = threading.Lock()
        self._last_flush = 0.0

    @property
    def is_open(self):
        return self._writer is not None

    def start(self):
        with self._lock:
            if self._writer is not None:
                return self.path
            folder = os.path.join(self.app_dir, self.dirname)
            os.makedirs(folder, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path = os.path.join(folder, f"wall_audit_{stamp}.csv")
            self._file = open(self.path, "w", newline="", encoding="utf-8-sig")
            self._writer = csv.DictWriter(self._file, fieldnames=AUDIT_FIELDS, extrasaction="ignore")
            self._writer.writeheader()
            self._file.flush()
            self._last_flush = time.time()
            return self.path

    def stop(self):
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
            self._file = None
            self._writer = None

    def write_event(self, ev):
        if not self.is_open:
            return
        ts = getattr(ev, "ts", time.time())
        self._write({
            "source": "scanner",
            "row_type": "EVENT",
            "local_time": local_time(ts),
            "ts_epoch": ts,
            "exchange": ev.exchange,
            "market": market_type(ev.exchange),
            "symbol": ev.symbol,
            "side": ev.side,
            "price": ev.price,
            "qty": ev.qty,
            "usd": getattr(ev, "usd", None),
            "best_bid": getattr(ev, "best_bid", None),
            "best_ask": getattr(ev, "best_ask", None),
            "mid": getattr(ev, "mid", None),
            "spread": getattr(ev, "spread", None),
            "dist_abs": getattr(ev, "dist_abs", None),
            "dist_pct": getattr(ev, "dist_pct", None),
            "age_sec": getattr(ev, "age_sec", None),
            "event_kind": ev.kind,
            "event_extra": ev.extra,
            "threshold_usd": getattr(ev, "threshold_usd", None),
            "threshold_max_usd": getattr(ev, "threshold_max_usd", None),
            "max_distance_pct": getattr(ev, "max_distance_pct", None),
            "single_confirm_sec": getattr(ev, "single_confirm_sec", None),
            "confirmed": getattr(ev, "confirmed", None),
            "baseline": getattr(ev, "baseline", None),
            "near_spread": getattr(ev, "near_spread", None),
            "trade_side": getattr(ev, "trade_side", None),
            "trade_count": getattr(ev, "trade_count", None),
            "trade_qty": getattr(ev, "trade_qty", None),
            "trade_usd": getattr(ev, "trade_usd", None),
            "trade_verdict": getattr(ev, "trade_verdict", None),
            "trade_note": getattr(ev, "trade_note", None),
        })

    def write_trade(self, trade):
        if not self.is_open:
            return
        self._write({
            "source": "scanner",
            "row_type": "TRADE",
            "local_time": local_time(trade.ts),
            "ts_epoch": trade.ts,
            "exchange": trade.exchange,
            "market": market_type(trade.exchange),
            "symbol": trade.symbol,
            "side": trade.taker_side,
            "price": trade.price,
            "qty": trade.qty,
            "usd": trade.usd,
            "event_kind": "TRADE",
            "event_extra": trade.trade_id,
        })

    def write_snapshot(self, exchange, symbol, snapshot, ts=None):
        if not self.is_open:
            return
        ts = time.time() if ts is None else ts
        for wall in snapshot:
            self._write({
                "source": "scanner",
                "row_type": "ACTIVE",
                "local_time": local_time(ts),
                "ts_epoch": ts,
                "exchange": exchange,
                "market": market_type(exchange),
                "symbol": symbol,
                "side": wall.get("side"),
                "price": wall.get("price"),
                "qty": wall.get("qty"),
                "usd": wall.get("usd"),
                "best_bid": wall.get("best_bid"),
                "best_ask": wall.get("best_ask"),
                "mid": wall.get("mid"),
                "spread": wall.get("spread"),
                "dist_abs": wall.get("dist_abs"),
                "dist_pct": wall.get("dist_pct"),
                "age_sec": wall.get("age"),
                "event_kind": "",
                "event_extra": "",
                "threshold_usd": wall.get("threshold_usd"),
                "threshold_max_usd": wall.get("threshold_max_usd"),
                "max_distance_pct": wall.get("max_distance_pct"),
                "single_confirm_sec": wall.get("single_confirm_sec"),
                "confirmed": wall.get("confirmed"),
                "baseline": wall.get("baseline"),
                "near_spread": wall.get("near_spread"),
            })

    def _write(self, row):
        with self._lock:
            if self._writer is None:
                return
            self._writer.writerow({field: csv_value(row.get(field)) for field in AUDIT_FIELDS})
            now = time.time()
            if now - self._last_flush >= 1.0:
                self._file.flush()
                self._last_flush = now
