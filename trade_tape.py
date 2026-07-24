import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


TRADE_RETENTION_SEC = 30.0
TRADE_EVENT_PAD_SEC = 0.75
PRICE_EPS = 1e-12
DEFAULT_REPEATING_PRINT_MIN_COUNT = 3


def _format_usd_compact(value):
    value = float(value or 0.0)
    sign = "-" if value < 0 else ""
    value = abs(value)

    def trim(num):
        text = f"{num:.1f}"
        return text[:-2] if text.endswith(".0") else text

    if value >= 1_000_000:
        return f"{sign}${trim(value / 1_000_000)}м"
    if value >= 1_000:
        return f"{sign}${trim(value / 1_000)}к"
    return f"{sign}${value:.0f}"


@dataclass
class TradePrint:
    exchange: str
    symbol: str
    price: float
    qty: float
    usd: float
    taker_side: str  # "buy" = market buy hit ask, "sell" = market sell hit bid
    ts: float
    trade_id: str = ""


class TradeTape:
    """Small in-memory tape of recent Binance raw trade prints."""

    def __init__(self, retention_sec=TRADE_RETENTION_SEC):
        self.retention_sec = float(retention_sec)
        self._trades = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _key(exchange, symbol):
        return f"{exchange.upper()}:{symbol.upper()}"

    def add_trade(self, exchange, symbol, price, qty, taker_side, ts=None, trade_id=""):
        price = float(price)
        qty = float(qty)
        if price <= 0 or qty <= 0:
            return None
        ts = time.time() if ts is None else float(ts)
        trade = TradePrint(
            exchange=exchange.upper(),
            symbol=symbol.upper(),
            price=price,
            qty=qty,
            usd=price * qty,
            taker_side=str(taker_side).lower(),
            ts=ts,
            trade_id=str(trade_id or ""),
        )
        key = self._key(exchange, symbol)
        with self._lock:
            q = self._trades[key]
            q.append(trade)
            self._prune_locked(key, ts)
        return trade

    def add_binance_trade(self, exchange, data):
        """Parse Binance raw trade payload.

        Binance field m means "buyer is maker":
        m=False -> buyer is taker -> aggressive buy hit the ask.
        m=True  -> seller is taker -> aggressive sell hit the bid.
        """
        symbol = (data.get("s") or "").upper()
        if not symbol:
            return None
        ts_ms = data.get("T") or data.get("E")
        ts = float(ts_ms) / 1000.0 if ts_ms is not None else time.time()
        buyer_is_maker = data.get("m")
        if isinstance(buyer_is_maker, str):
            buyer_is_maker = buyer_is_maker.strip().lower() in {"1", "true", "yes"}
        taker_side = "sell" if bool(buyer_is_maker) else "buy"
        return self.add_trade(
            exchange,
            symbol,
            data.get("p"),
            data.get("q"),
            taker_side,
            ts=ts,
            trade_id=data.get("t") if data.get("t") is not None else data.get("a"),
        )

    def add_binance_agg_trade(self, exchange, data):
        return self.add_binance_trade(exchange, data)

    def find_repeating_print_cluster(self, trade, min_count=DEFAULT_REPEATING_PRINT_MIN_COUNT,
                                     window_sec=5.0, similarity_pct=15.0,
                                     min_usd=0.0, max_usd=None):
        """Find same-side prints with similar dollar size ending at the new trade.

        window_sec=0 means strictly consecutive similar prints in the tape.
        """
        if trade is None:
            return None
        min_count = max(1, int(min_count))
        window_sec = max(0.0, float(window_sec))
        similarity_pct = max(0.0, float(similarity_pct))
        min_usd = max(0.0, float(min_usd or 0.0))
        max_usd = float(max_usd) if max_usd is not None else None
        if max_usd is not None and max_usd <= 0:
            max_usd = None
        if not self._usd_in_range(trade.usd, min_usd, max_usd):
            return None
        key = self._key(trade.exchange, trade.symbol)
        with self._lock:
            self._prune_locked(key, trade.ts)
            trades = list(self._trades.get(key, ()))
        if not trades:
            return None

        if window_sec == 0:
            candidates = []
            for item in reversed(trades):
                if item.taker_side != trade.taker_side:
                    break
                if not self._usd_in_range(item.usd, min_usd, max_usd):
                    break
                if not self._similar_usd(item.usd, trade.usd, similarity_pct):
                    break
                candidates.append(item)
            matches = list(reversed(candidates))
        else:
            start_ts = trade.ts - window_sec
            matches = [
                item for item in trades
                if item.taker_side == trade.taker_side
                and item.ts >= start_ts
                and item.ts <= trade.ts
                and self._usd_in_range(item.usd, min_usd, max_usd)
                and self._similar_usd(item.usd, trade.usd, similarity_pct)
            ]

        if len(matches) < min_count:
            return None

        first = matches[0]
        last = matches[-1]
        total_usd = sum(item.usd for item in matches)
        total_qty = sum(item.qty for item in matches)
        prices = [item.price for item in matches]
        print_usd = [item.usd for item in matches]
        series_seed = first.trade_id or f"{first.ts:.6f}:{first.price:g}:{first.usd:.2f}"
        return {
            "series_id": f"{key}:{trade.taker_side}:{series_seed}",
            "exchange": trade.exchange,
            "symbol": trade.symbol,
            "side": trade.taker_side,
            "count": len(matches),
            "avg_usd": total_usd / len(matches),
            "total_usd": total_usd,
            "total_qty": total_qty,
            "min_price": min(prices),
            "max_price": max(prices),
            "first_ts": first.ts,
            "last_ts": last.ts,
            "span_sec": max(0.0, last.ts - first.ts),
            "window_sec": window_sec,
            "similarity_pct": similarity_pct,
            "min_usd_filter": min_usd,
            "max_usd_filter": max_usd,
            "print_usd": print_usd,
        }

    def summarize_wall_trades(self, exchange, symbol, wall_side, price, start_ts, end_ts,
                              price_tolerance=PRICE_EPS, pad_sec=TRADE_EVENT_PAD_SEC):
        """Return aggressive trades that could execute the wall price."""
        key = self._key(exchange, symbol)
        target_side = "sell" if str(wall_side).lower() == "bid" else "buy"
        price = float(price)
        start_ts = float(start_ts) - float(pad_sec)
        end_ts = float(end_ts) + float(pad_sec)
        matched = []
        with self._lock:
            self._prune_locked(key, end_ts)
            trades = list(self._trades.get(key, ()))
        for trade in trades:
            if trade.taker_side != target_side:
                continue
            if trade.ts < start_ts or trade.ts > end_ts:
                continue
            if abs(trade.price - price) <= price_tolerance:
                matched.append(trade)
        qty = sum(t.qty for t in matched)
        usd = sum(t.usd for t in matched)
        return {
            "trade_side": target_side,
            "trade_count": len(matched),
            "trade_qty": qty,
            "trade_usd": usd,
            "first_trade_ts": min((t.ts for t in matched), default=None),
            "last_trade_ts": max((t.ts for t in matched), default=None),
        }

    def annotate_wall_event(self, ev):
        """Attach a human-readable trade hint to EATEN/PULLED/MAGNET events."""
        if ev.kind not in {"EATEN", "PULLED", "MAGNET"}:
            return None
        price = getattr(ev, "price", None)
        age_sec = getattr(ev, "age_sec", None)
        event_ts = getattr(ev, "ts", None)
        if not price or age_sec is None or event_ts is None:
            return None

        start_ts = float(event_ts) - max(0.0, float(age_sec))
        summary = self.summarize_wall_trades(
            ev.exchange,
            ev.symbol,
            ev.side,
            price,
            start_ts,
            event_ts,
        )
        max_usd = getattr(ev, "max_usd", None)
        current_usd = getattr(ev, "usd", None)
        disappeared_usd = None
        if max_usd is not None and current_usd is not None:
            disappeared_usd = max(0.0, float(max_usd) - float(current_usd))

        note, verdict = self._build_note(ev.kind, ev.side, summary, disappeared_usd)
        for name, value in summary.items():
            setattr(ev, name, value)
        ev.trade_verdict = verdict
        ev.trade_note = note
        if note:
            ev.extra = f"{ev.extra}; {note}" if ev.extra else note
        return summary

    @staticmethod
    def _build_note(kind, wall_side, summary, disappeared_usd):
        side_word = "продажи" if str(wall_side).lower() == "bid" else "покупки"
        trade_usd = summary["trade_usd"]
        trade_count = summary["trade_count"]
        if trade_count <= 0:
            return "", "no_level_trades"

        if disappeared_usd and disappeared_usd > 0:
            coverage = min(999.0, trade_usd / disappeared_usd * 100)
            verdict = f"{coverage:.0f}% исчезнувшего объёма"
        else:
            verdict = "есть принты по уровню"
        note = f"принты по уровню: {side_word} {_format_usd_compact(trade_usd)} ({trade_count} шт.) -> {verdict}"
        return note, verdict

    @staticmethod
    def _similar_usd(left, right, similarity_pct):
        if right <= 0:
            return False
        return abs(left - right) / right * 100 <= similarity_pct

    @staticmethod
    def _usd_in_range(usd, min_usd, max_usd):
        usd = float(usd or 0.0)
        if usd < float(min_usd or 0.0):
            return False
        if max_usd is not None and usd > float(max_usd):
            return False
        return True

    def _prune_locked(self, key, now):
        q = self._trades.get(key)
        if not q:
            return
        cutoff = float(now) - self.retention_sec
        while q and q[0].ts < cutoff:
            q.popleft()
        if not q:
            self._trades.pop(key, None)
