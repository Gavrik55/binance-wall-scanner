"""Простой файловый лог для диагностики. Пишет в debug.log рядом с exe
(или рядом со скриптом при обычном запуске). Временная штука для отладки —
не влияет на основную логику, любая ошибка записи просто проглатывается."""
import datetime
import os
import sys

if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_PATH = os.path.join(_APP_DIR, "debug.log")


def log(msg: str):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass
