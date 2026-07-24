"""Запись снимков стакана MEXC по вотч-листу "живой тишины".

Зачем это нужно отдельным модулем. Гипотезу "перед пампом кто-то заранее
расставляет плотности, которые не снимаются" проверить на истории НЕЛЬЗЯ:
биржи отдают только ТЕКУЩИЙ стакан, исторического стакана не существует ни у
MEXC, ни у кого-либо ещё. Ценовую часть мы откалибровали по выгрузке из
телеграм-канала, но для стакана такого источника нет — значит единственный
способ получить размеченные данные это писать их вперёд, начиная с сегодня.

Формат — gzip-JSONL по одному файлу на сутки (append-only, устойчиво к падению
приложения: недописанная последняя строка не портит предыдущие; gzip дописывается
отдельными member-ами, которые читаются прозрачно). Пишем не весь стакан, а
только уровни от MIN_LEVEL_USD — нас интересуют плотности, а не пыль по десять
долларов.

Размер имеет значение, потому что писать придётся неделями: на живых данных
сырой JSONL с порогом $10 давал 266 МБ/сутки, а порог $50 + gzip дают 49 МБ/сутки
при сохранении ~29 значимых уровней в снимке (все реальные плотности $300+ целы).

Нагрузка: /api/v3/depth имеет вес 1 при лимите 500 запросов / 10 сек на IP,
то есть 50 rps. При ~60 монетах раз в 30 сек это ~2 rps — 4% бюджета.
"""

import gzip
import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

DEPTH_URL = "https://api.mexc.com/api/v3/depth"
DEPTH_LIMIT = 50          # уровней с каждой стороны запрашиваем у биржи
MIN_LEVEL_USD = 50.0      # уровни мельче — не пишем (это шум, а не плотность)
POLL_INTERVAL_SEC = 30.0  # плотности живут минутами, чаще опрашивать смысла нет
REQUEST_GAP_SEC = 0.05    # пауза между запросами внутри цикла, чтобы не долбить биржу пачкой


class DepthRecorder:
    """Фоновый поток: раз в POLL_INTERVAL_SEC обходит текущий вотч-лист и
    дописывает снимки стаканов в JSONL. Вотч-лист меняется на лету через
    set_watchlist() — GUI зовёт его при каждом обновлении списка кандидатов."""

    def __init__(self, out_dir, on_status=None):
        self.out_dir = out_dir
        self.on_status = on_status or (lambda text: None)
        self._symbols = []
        self._lock = threading.Lock()
        self._stop = False
        self._thread = None
        self._session = requests.Session()
        self.snapshots_written = 0

    def set_watchlist(self, symbols):
        with self._lock:
            self._symbols = list(symbols)

    def watchlist_size(self):
        with self._lock:
            return len(self._symbols)

    def start(self):
        os.makedirs(self.out_dir, exist_ok=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    def _current_path(self):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.out_dir, f"depth_{day}.jsonl.gz")

    def _fetch_depth(self, symbol):
        r = self._session.get(DEPTH_URL, params={"symbol": symbol, "limit": DEPTH_LIMIT},
                              timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()

        def levels(side):
            out = []
            for price_str, qty_str in data.get(side, []):
                try:
                    price, qty = float(price_str), float(qty_str)
                except (TypeError, ValueError):
                    continue
                usd = price * qty
                if usd >= MIN_LEVEL_USD:
                    out.append([price, qty, round(usd, 2)])
            return out

        return {"bids": levels("bids"), "asks": levels("asks")}

    def _run(self):
        while not self._stop:
            started = time.monotonic()
            with self._lock:
                symbols = list(self._symbols)

            if symbols:
                rows = []
                for symbol in symbols:
                    if self._stop:
                        return
                    try:
                        book = self._fetch_depth(symbol)
                    except Exception:
                        book = None  # сеть моргнула — пропускаем символ, цикл не роняем
                    if book and (book["bids"] or book["asks"]):
                        rows.append({"ts": round(time.time(), 3), "symbol": symbol,
                                     "bids": book["bids"], "asks": book["asks"]})
                    time.sleep(REQUEST_GAP_SEC)

                if rows:
                    try:
                        # весь цикл пишем одним gzip-member: так компактнее, чем
                        # по строке, и файл остаётся дописываемым
                        with gzip.open(self._current_path(), "at", encoding="utf-8") as f:
                            for row in rows:
                                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        self.snapshots_written += len(rows)
                    except Exception as e:
                        self.on_status(f"[Запись стаканов] ошибка записи: {e}")

            elapsed = time.monotonic() - started
            sleep_left = max(1.0, POLL_INTERVAL_SEC - elapsed)
            for _ in range(int(sleep_left * 10)):
                if self._stop:
                    return
                time.sleep(0.1)
