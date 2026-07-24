import io
import json
import math
import os
import queue
import struct
import sys
import threading
import time
import wave
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

from audit_log import AuditCsvWriter
from orderbook import OrderBook
from debug_log import log as dlog
from detector import WallDetector, SymbolConfig, format_age, NEAR_SPREAD_PCT
from trade_tape import TradeTape
from ws_manager import (
    EXCHANGES as BINANCE_WS_CONFIGS,
    ExchangeWSManager,
    fetch_depth_snapshot,
    validate_symbol as binance_style_validate,
)
from gate_ws import GateWSManager, validate_symbol as gate_validate_symbol
from okx_ws import OKXWSManager, validate_symbol as okx_validate_symbol
from rest_poll_manager import (
    REST_EXCHANGES,
    RestPollingManager,
    alpha_display_symbol,
    fetch_alpha_search_symbols,
    fetch_rest_symbols,
    resolve_alpha_symbol,
    validate_rest_symbol,
)
from market_scan import (
    MarketScanner,
    POLL_INTERVAL_SEC as MARKET_POLL_INTERVAL_SEC,
    IMPULSE_WINDOW_SEC as MARKET_IMPULSE_WINDOW_SEC,
    IMPULSE_HIGHLIGHT_PCT as MARKET_IMPULSE_HIGHLIGHT_PCT,
    TOP_N as MARKET_TOP_N,
    HEDGEHOG_WINDOW_SEC,
    EARLY_RANGE_MIN_PCT,
    EARLY_RANGE_MAX_PCT,
    EARLY_VOL_MIN_USD,
    EARLY_VOL_MAX_USD,
    EARLY_ACCEL_MAX,
    OI_RISE_HIGHLIGHT_PCT,
)
from depth_recorder import DepthRecorder

# В обычном запуске (python main.py) конфиг лежит рядом со скриптом.
# В собранном PyInstaller-экзешнике __file__ указывает во временную папку
# распаковки (sys._MEIPASS), которая удаляется при выходе — поэтому в frozen-
# режиме берём папку рядом с самим .exe (sys.executable), иначе конфиг не
# сохранялся бы между запусками.
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_APP_DIR, "config.json")

# _RESOURCE_DIR — для ВШИТЫХ read-only файлов (звуки и т.п.), в отличие от
# _APP_DIR выше (для config.json/debug.log — то, что приложение само пишет
# рядом с exe). В frozen-сборке PyInstaller кладёт файлы, добавленные через
# --add-data, в sys._MEIPASS — это работает и для --onedir (папка _internal),
# и для --onefile (временная распаковка).
if getattr(sys, "frozen", False):
    _RESOURCE_DIR = getattr(sys, "_MEIPASS", _APP_DIR)
else:
    _RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
APPEARED_SOUND_PATH = os.path.join(_RESOURCE_DIR, "sounds", "Sound_07.wav")

BASE_EXCHANGE_CHOICES = ["BINANCE", "ASTERDEX", "GATE", "OKX", "MEXC"]
SPOT_EXCHANGE_BY_BASE = {
    "BINANCE": "BINANCE SPOT",
    "ASTERDEX": "ASTERDEX SPOT",
    "GATE": "GATE SPOT",
    "OKX": "OKX SPOT",
    "MEXC": "MEXC SPOT",
}
EXTRA_EXCHANGE_CHOICES = ["BINANCE ALPHA"]
EXCHANGE_CHOICES = BASE_EXCHANGE_CHOICES + list(SPOT_EXCHANGE_BY_BASE.values()) + EXTRA_EXCHANGE_CHOICES
BINANCE_STYLE = {"BINANCE", "ASTERDEX", "BINANCE SPOT", "ASTERDEX SPOT"}  # Binance-style diff (U/u/pu)
REST_POLLING_EXCHANGES = set(REST_EXCHANGES)
TRADE_TAPE_EXCHANGES = {"BINANCE", "BINANCE SPOT"}
ALL_EXCHANGES_LABEL = "🌐 ВСЕ БИРЖИ"  # спец-пункт в комбобоксе "Биржа" — добавить тикер сразу везде, где он есть
MARKET_TOP_EXCHANGES = ["BINANCE", "ASTERDEX", "GATE", "OKX"]  # что ПОКАЗЫВАЕМ в "Топ движений"
HEDGEHOG_EXCHANGES = ["BINANCE", "BYBIT", "BINANCE SPOT", "ASTERDEX SPOT", "GATE SPOT", "OKX SPOT"]
# Что market_scanner РЕАЛЬНО опрашивает: набор "Топ движений" + MEXC (нужен
# вкладке "Ранние") + BYBIT (нужен фильтру эксклюзивности "Ранних" — MAJOR_EXCHANGES).
# "Топ движений" всё равно показывает только MARKET_TOP_EXCHANGES (фильтр в
# _update_movers_trees), а MEXC уходит в "Ранние". Без MEXC здесь вкладка
# "Ранние" была бы мертва — это тихо ломалось при слиянии веток.
MARKET_SCAN_EXCHANGES = MARKET_TOP_EXCHANGES + ["BYBIT", "MEXC SPOT"]
EXCHANGE_SHORT_LABELS = {
    "BINANCE": "BIN",
    "BINANCE SPOT": "BIN S",
    "BINANCE ALPHA": "ALPHA",
    "ASTERDEX": "AST",
    "ASTERDEX SPOT": "AST S",
    "GATE": "GATE",
    "GATE SPOT": "GATE S",
    "OKX": "OKX",
    "OKX SPOT": "OKX S",
    "MEXC": "MEXC",
    "MEXC SPOT": "MEXC S",
}
CTRL_MASK = 0x0004
HOTKEY_KEYCODES = {
    "C": {67},
    "DELETE": {46, 110},
}
HOTKEY_KEYSYMS = {
    "C": {"c", "с", "cyrillic_es"},
    "DELETE": {"delete", "kp_delete"},
}

# пресеты диапазона объёма плотности для выпадающего списка: (подпись, от, до).
# "Вручную" ничего не подставляет — поля "от $"/"до $" заполняются самим
# пользователем. Пустое "до $" при добавлении = режим "от и выше" (без
# разницы, насколько крупная плотность), заполненное "до $" = режим "от-до".
VOLUME_PRESETS = [
    ("20к – 40к", 20_000, 40_000),
    ("40к – 50к", 40_000, 50_000),
    ("100к – 150к", 100_000, 150_000),
    ("150к – 250к", 150_000, 250_000),
    ("250к – 500к", 250_000, 500_000),
    ("500к – 1м", 500_000, 1_000_000),
    ("Вручную", None, None),
]

_UNSET = object()  # сентинел: отличить "параметр не передан" от "передан явный None"

# соответствие self.label каждого менеджера (человекочитаемое) -> наш внутренний ключ биржи
LABEL_TO_EXCHANGE = {
    "Binance": "BINANCE",
    "Binance Spot": "BINANCE SPOT",
    "AsterDEX": "ASTERDEX",
    "AsterDEX Spot": "ASTERDEX SPOT",
    "Gate.io": "GATE",
    "Gate.io Spot": "GATE SPOT",
    "OKX": "OKX",
    "OKX Spot": "OKX SPOT",
    "MEXC": "MEXC",
    "MEXC Spot": "MEXC SPOT",
    "Binance Alpha": "BINANCE ALPHA",
}

# состояние индикатора подключения -> (иконка, цвет, текст)
CONN_STATE_DISPLAY = {
    "connected":  ("🟢", "#22c55e", "подключено"),
    "connecting": ("🟡", "#eab308", "подключение..."),
    "error":      ("🔴", "#ef4444", "обрыв связи"),
    "idle":       ("⚪", "#6b7078", "—"),
}

SIDE_COLOR = {"bid": "#22c55e", "ask": "#ef4444"}  # зелёный/красный, как в heatmap-стакане

EVENT_COLORS = {
    "APPEARED":  "#fbbf24",
    "MAGNET":    "#f59e0b",
    "PUSH":      "#38bdf8",
    "EATEN":     "#34d399",
    "PULLED":    "#f87171",
    "WALL":      "#a78bfa",
    "WALL_GONE": "#9aa0a6",
    "CASCADE":   "#22d3ee",
}
EVENT_LABELS = {
    "APPEARED":  "🟨 ПЛОТНОСТЬ",
    "MAGNET":    "🟧 МАГНИТ",
    "PUSH":      "🟦 ПОД СПРЕДОМ",
    "EATEN":     "🟩 ПРОЕЛИ",
    "PULLED":    "🟥 СНЯЛИ",
    "WALL":      "🧱 СТЕНКА",
    "WALL_GONE": "🧱💨 РАССЕЯЛАСЬ",
    "CASCADE":   "🟦🟦 КАСКАД",
}
ALERT_FILTERS = [
    ("APPEARED", "Плотн."),
    ("PUSH", "Под спред"),
    ("MAGNET", "Магнит"),
    ("EATEN", "Проели"),
    ("PULLED", "Сняли"),
    ("WALL", "Стенка"),
    ("WALL_GONE", "Ст. ушла"),
    ("CASCADE", "Каскад"),
]
BEEP_FREQ = {
    "APPEARED": 700, "MAGNET": 1000, "PUSH": 1100, "EATEN": 500, "PULLED": 350,
    "WALL": 1200, "WALL_GONE": 400, "CASCADE": 1500, "IMPULSE": 850,
}

WALLS_PUSH_INTERVAL = 1.0
MOVER_ADD_DEFAULT_FLOOR = 20_000  # порог-пол при добавлении монеты из "Топ движений" (режим AUTO)
DEFAULT_MAX_DISTANCE_PCT = 10.0  # дефолт "Дистанция %" — совпадает с SymbolConfig.max_distance_pct
MIN_DISTANCE_PCT = NEAR_SPREAD_PCT  # если пользователь вводит 0, ищем в минимальном практическом радиусе от спреда
DEFAULT_SINGLE_CONFIRM_SEC = 10.0  # сколько секунд плотность должна прожить до алерта по умолчанию
MIN_SINGLE_CONFIRM_SEC = 0.0  # 0 = без ожидания: алерт сразу на первом подходящем скане


def _parse_decimal(value):
    return float(str(value).strip().replace(",", "."))


def _normalize_distance_pct(value):
    value = _parse_decimal(value)
    if 0 <= value < MIN_DISTANCE_PCT:
        return MIN_DISTANCE_PCT
    return value


def _normalize_single_confirm_sec(value):
    value = _parse_decimal(value)
    if 0 <= value < MIN_SINGLE_CONFIRM_SEC:
        return MIN_SINGLE_CONFIRM_SEC
    return value


def _format_compact_usd(value):
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    value = abs(value)
    def _trim(num):
        text = f"{num:.1f}"
        return text[:-2] if text.endswith(".0") else text
    if value >= 1_000_000:
        return f"{sign}${_trim(value / 1_000_000)}м"
    if value >= 1_000:
        return f"{sign}${_trim(value / 1_000)}к"
    return f"{sign}${value:.0f}"


def _parse_compact_usd(value):
    text = str(value or "").strip().lower()
    if not text or text == "-":
        return None
    multiplier = 1.0
    text = text.replace("$", "").replace(" ", "")
    if text.endswith(("к", "k")):
        multiplier = 1_000.0
        text = text[:-1]
    elif text.endswith(("м", "m")):
        multiplier = 1_000_000.0
        text = text[:-1]
    if "," in text and "." not in text:
        left, right = text.rsplit(",", 1)
        text = f"{left}.{right}" if len(right) <= 2 else f"{left}{right}"
    else:
        text = text.replace(",", "")
    return float(text) * multiplier


def _normalize_symbol_input(symbol, exchange=None):
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return ""
    symbol = symbol.replace("/", "").replace("-", "")
    exchange = (exchange or "").upper()
    if exchange == "BINANCE ALPHA":
        return resolve_alpha_symbol(symbol)
    symbol = symbol.replace("_", "")
    quote_assets = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB")
    if not any(symbol.endswith(q) for q in quote_assets):
        symbol = f"{symbol}USDT"
    return symbol


IMPULSE_THRESHOLD_MIN_PCT = 0.1
IMPULSE_THRESHOLD_MAX_PCT = 50.0
IMPULSE_WINDOW_MIN_SEC = 30.0
IMPULSE_WINDOW_MAX_SEC = 1800.0  # 30 мин — с запасом ниже HISTORY_RETENTION_SEC в market_scan.py (90 мин)
IMPULSE_TOAST_MS = 8000          # сколько всплывающее окно висит перед авто-закрытием
IMPULSE_TOAST_W, IMPULSE_TOAST_H = 280, 58
IMPULSE_SETTINGS_FILE = os.path.join(_APP_DIR, "impulse_settings.json")  # отдельный файл — config.json это список монет, а не dict настроек
PRINT_SETTINGS_FILE = os.path.join(_APP_DIR, "print_settings.json")
REPEATING_PRINT_MIN_COUNT = 3
DEFAULT_PRINT_WINDOW_SEC = 5.0
DEFAULT_PRINT_SIMILARITY_PCT = 15.0
DEFAULT_PRINT_MIN_USD = 0.0
DEFAULT_PRINT_MAX_USD = None
MAX_PRINT_ROWS = 200

# "Ранние" (вотч-лист живой тишины). Монета должна продержаться в профиле
# EARLY_CONFIRM_TICKS сканов подряд, прежде чем дать алерт — иначе те, кто
# болтается на границе порога (диапазон 2.9% / 3.1%), моргали бы алертом
# каждые 15 секунд. Та же логика подтверждения, что у плотностей в detector.py.
EARLY_CONFIRM_TICKS = 3
EARLY_REALERT_SEC = 3 * 3600     # повторный алерт по той же монете — не раньше чем через 3ч
EARLY_DEPTH_DIR = os.path.join(_APP_DIR, "depth_data")


_CHIME_CACHE = {}  # freq -> готовый WAV (bytes), чтобы не пересинтезировать на каждый алерт


def _generate_chime(freq: float, duration_sec: float = 0.24, sample_rate: int = 44100) -> bytes:
    """Мягкий колокольчик вместо резкого winsound.Beep (чистая прямоугольная
    волна пищит неприятно). Синус на основной частоте + тихая квинта сверху
    (для "колокольного" тембра) под плавной огибающей — быстрая атака,
    экспоненциальный спад к тишине, без резких щелчков в начале/конце."""
    n = int(sample_rate * duration_sec)
    attack = max(1, int(sample_rate * 0.008))
    samples = bytearray()
    for i in range(n):
        t = i / sample_rate
        env = (i / attack) if i < attack else math.exp(-4.0 * (i - attack) / max(1, n - attack))
        value = env * 0.6 * (
            math.sin(2 * math.pi * freq * t) +
            0.35 * math.sin(2 * math.pi * freq * 1.5 * t)  # тихая квинта сверху
        )
        sample = int(max(-1.0, min(1.0, value)) * 32767)
        samples += struct.pack("<h", sample)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(samples))
    return buf.getvalue()


def _chime_for(kind: str) -> bytes:
    freq = BEEP_FREQ.get(kind, 700)
    chime = _CHIME_CACHE.get(freq)
    if chime is None:
        chime = _generate_chime(freq)
        _CHIME_CACHE[freq] = chime
    return chime


def _play_beep(kind: str):
    try:
        if sys.platform == "win32":
            import winsound
            # для APPEARED ("🟨 ПЛОТНОСТЬ") — пользовательский звук из файла,
            # если он на месте; иначе (и для всех остальных типов событий) —
            # синтезированный колокольчик, как раньше
            if kind == "APPEARED" and os.path.isfile(APPEARED_SOUND_PATH):
                winsound.PlaySound(APPEARED_SOUND_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.PlaySound(_chime_for(kind), winsound.SND_MEMORY | winsound.SND_ASYNC)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Multi-Exchange Wall Scanner")
        self.root.geometry("1380x900")
        self.root.minsize(1100, 700)
        self.root.configure(bg="#0a0a0d")

        self.orderbooks = {}       # "EXCH:SYMBOL" -> OrderBook
        self.detector = WallDetector()
        self.ws_managers = {}      # exchange -> manager instance
        self.event_queue = queue.Queue()
        self.status_var = tk.StringVar(value="Отключено")
        self.sound_enabled = tk.BooleanVar(value=True)
        self._last_walls_push = {}
        self.muted_keys = set()    # "EXCH:SYMBOL" с выключенными алертами (детекция всё равно идёт)
        self._resyncing = set()    # "EXCH:SYMBOL", для которых сейчас уже идёт REST-ресинк (не дублировать)
        self._resync_lock = threading.Lock()
        # строки в "Активные плотности" держим в порядке ОБНАРУЖЕНИЯ (кто
        # раньше нашёлся — тот выше), а не порядке последнего обновления —
        # иначе строки "прыгают" по таблице каждый раз, когда обновляется
        # ЛЮБОЙ другой символ (см. _update_walls_tree)
        self._wall_row_seq = {}    # iid ("EXCH:SYMBOL|price") -> порядковый номер обнаружения
        self._next_wall_seq = 0
        self._log_comment_editor = None
        self._alert_rows = []
        self._alert_row_kinds = {}
        self._next_alert_seq = 0
        self._copy_notice_after_id = None
        self._symbol_suggestion_set = set()
        self._symbol_suggestion_lock = threading.Lock()
        self._symbol_suggestion_refreshing = False
        self.audit_writer = AuditCsvWriter(_APP_DIR)
        self.audit_enabled = tk.BooleanVar(value=False)
        self.trade_tape = TradeTape()
        self.print_window_sec = DEFAULT_PRINT_WINDOW_SEC
        self.print_similarity_pct = DEFAULT_PRINT_SIMILARITY_PCT
        self.print_min_usd = DEFAULT_PRINT_MIN_USD
        self.print_max_usd = DEFAULT_PRINT_MAX_USD
        self._load_print_settings()

        # "Импульс" (вкладка "Топ движений") — всплывающие уведомления,
        # видимые независимо от активной вкладки. Порог/окно настраиваются
        # вручную в UI (панель сверху вкладки), персистятся в отдельный файл
        # (не config.json — тот список монет, а не dict настроек).
        self.impulse_threshold_pct = MARKET_IMPULSE_HIGHLIGHT_PCT
        self.impulse_window_sec = MARKET_IMPULSE_WINDOW_SEC
        self.impulse_popup_enabled = tk.BooleanVar(value=True)
        self.impulse_sound_enabled = tk.BooleanVar(value=True)
        self._impulse_above = {}          # "EXCH:SYMBOL" -> был ли последний тик выше порога (для edge-триггера)
        self._active_impulse_toasts = []  # список открытых Toplevel-тостов, для стека/перепозиционирования
        self._load_impulse_settings()

        # "Ранние" — вотч-лист монет в "живой тишине" (профиль до памп-выноса)
        self.early_alerts_enabled = tk.BooleanVar(value=True)
        # по умолчанию включено: монеты, уже торгующиеся на Binance/OKX/Bybit,
        # имеют толстый стакан и на +50% с тонкой книги не выносятся
        self.early_exclusive_only = tk.BooleanVar(value=True)
        self._early_streak = {}     # symbol -> сколько сканов подряд держится в профиле
        self._early_alerted = {}    # symbol -> когда последний раз алертили (антиповтор)
        self.depth_recorder = DepthRecorder(EARLY_DEPTH_DIR, self._on_status)

        self._build_ui()
        self.root.bind_all("<KeyPress>", self._on_global_keypress, add="+")
        self._load_config()
        self._seed_symbol_suggestions_from_rows()
        self._refresh_symbol_suggestions_async()
        self.root.after(100, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # "Топ движений" — лёгкий REST-опрос всего рынка (не зависит от
        # Старт/Стоп сканера плотностей, работает всегда, пока открыто приложение)
        self.market_scanner = MarketScanner(self._on_market_update, self._on_status,
                                            exchanges=MARKET_SCAN_EXCHANGES)
        self.market_scanner.impulse_window_sec = self.impulse_window_sec
        self.market_scanner.start()

        # "Ерши" — узкий диапазон/частые касания границ на низком объёме.
        # Оставляем старые futures-источники и добавляем spot-рынки.
        self.hedgehog_scanner = MarketScanner(self._on_hedgehog_update, self._on_status,
                                               exchanges=HEDGEHOG_EXCHANGES)
        self.hedgehog_scanner.start()

        # запись стаканов по вотч-листу — единственный способ получить историю
        # стакана перед пампом, её нельзя добрать задним числом (см. depth_recorder.py)
        self.depth_recorder.start()

        # прогрев "Ранних" минутными свечами: без него вкладка пустая первый час
        # после каждого запуска, то есть ни алертов, ни записи стаканов
        threading.Thread(target=self.market_scanner.bootstrap_mexc_history,
                         daemon=True).start()

    # ---------------- UI ----------------

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#131316", foreground="white",
                         fieldbackground="#131316", rowheight=24, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#1f1f24", foreground="white",
                         font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#2563eb")])
        style.configure("TNotebook", background="#0a0a0d", borderwidth=0)
        style.configure("TNotebook.Tab", background="#1f1f24", foreground="white",
                         padding=(14, 6), font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", "#2563eb")])

        self.notebook = ttk.Notebook(self.root)
        tab_scanner = tk.Frame(self.notebook, bg="#0a0a0d")
        tab_movers = tk.Frame(self.notebook, bg="#0a0a0d")
        tab_hedgehog = tk.Frame(self.notebook, bg="#0a0a0d")
        tab_early = tk.Frame(self.notebook, bg="#0a0a0d")
        self.notebook.add(tab_scanner, text="Сканер плотностей")
        self.notebook.add(tab_movers, text="Топ движений")
        self.notebook.add(tab_hedgehog, text="🦔 Ерши")
        self.notebook.add(tab_early, text="🎯 Ранние")

        top = tk.Frame(tab_scanner, bg="#0a0a0d")
        top.pack(fill="x", padx=10, pady=(10, 4))

        tk.Label(top, text="Биржа:", bg="#0a0a0d", fg="white").grid(row=0, column=0, padx=4, sticky="w")
        self.exchange_combo = ttk.Combobox(top, values=EXCHANGE_CHOICES + [ALL_EXCHANGES_LABEL],
                                            width=16, state="readonly")
        self.exchange_combo.set("BINANCE")
        self.exchange_combo.grid(row=0, column=1, padx=4)
        self.exchange_combo.bind("<<ComboboxSelected>>", self._on_exchange_selected)

        tk.Label(top, text="Символ:", bg="#0a0a0d", fg="white").grid(row=0, column=2, padx=4, sticky="w")
        self.symbol_entry = tk.Entry(top, width=14)
        self.symbol_entry.grid(row=0, column=3, padx=4)
        self.symbol_entry.bind("<KeyRelease>", self._on_symbol_keyrelease)
        self.symbol_entry.bind("<Down>", self._focus_symbol_suggestions)
        self.symbol_entry.bind("<Return>", self._accept_symbol_entry_or_add)
        self.symbol_entry.bind("<Escape>", lambda _e: self._hide_symbol_suggestions())

        self.symbol_suggest_popup = tk.Toplevel(self.root)
        self.symbol_suggest_popup.withdraw()
        self.symbol_suggest_popup.overrideredirect(True)
        self.symbol_suggest_popup.configure(bg="#111827")
        self.symbol_suggest_frame = tk.Frame(self.symbol_suggest_popup, bg="#111827")
        self.symbol_suggest_frame.pack(fill="both", expand=True)
        self.symbol_suggest = tk.Listbox(self.symbol_suggest_frame, height=6, width=20, bg="#111827", fg="white",
                                         selectbackground="#e5e7eb", selectforeground="#111827",
                                         activestyle="none",
                                         highlightthickness=1, highlightbackground="#374151")
        self.symbol_suggest_scroll = tk.Scrollbar(self.symbol_suggest_frame, orient="vertical",
                                                  command=self.symbol_suggest.yview)
        self.symbol_suggest.configure(yscrollcommand=self.symbol_suggest_scroll.set)
        self.symbol_suggest.pack(side="left", fill="both", expand=True)
        self.symbol_suggest_scroll.pack(side="right", fill="y")
        self.symbol_suggest.bind("<ButtonRelease-1>", self._choose_symbol_suggestion)
        self.symbol_suggest.bind("<Return>", self._choose_symbol_suggestion)
        self.symbol_suggest.bind("<Escape>", lambda _e: self._hide_symbol_suggestions())
        self.symbol_suggest.bind("<Motion>", self._hover_symbol_suggestion)
        self.symbol_suggest.bind("<MouseWheel>", self._scroll_symbol_suggestions)
        self.symbol_suggest.bind("<Button-4>", self._scroll_symbol_suggestions)
        self.symbol_suggest.bind("<Button-5>", self._scroll_symbol_suggestions)

        tk.Label(top, text="Объём:", bg="#0a0a0d", fg="white").grid(row=0, column=4, padx=4, sticky="w")
        self.volume_preset_combo = ttk.Combobox(top, values=[p[0] for p in VOLUME_PRESETS],
                                                 width=11, state="readonly")
        self.volume_preset_combo.set("Вручную")
        self.volume_preset_combo.grid(row=0, column=5, padx=4)
        self.volume_preset_combo.bind("<<ComboboxSelected>>", self._on_volume_preset_selected)

        tk.Label(top, text="от $:", bg="#0a0a0d", fg="white").grid(row=0, column=6, padx=4, sticky="w")
        self.threshold_entry = tk.Entry(top, width=9)
        self.threshold_entry.grid(row=0, column=7, padx=4)

        tk.Label(top, text="до $:", bg="#0a0a0d", fg="white").grid(row=0, column=8, padx=4, sticky="w")
        self.threshold_max_entry = tk.Entry(top, width=9)
        self.threshold_max_entry.grid(row=0, column=9, padx=4)

        tk.Label(top, text="Режим:", bg="#0a0a0d", fg="white").grid(row=0, column=10, padx=4, sticky="w")
        self.mode_combo = ttk.Combobox(top, values=["FIXED", "AUTO"], width=8, state="readonly")
        self.mode_combo.set("FIXED")
        self.mode_combo.grid(row=0, column=11, padx=4)

        tk.Label(top, text="Дистанция % (от спреда до плотности):", bg="#0a0a0d", fg="white").grid(
            row=1, column=0, columnspan=3, padx=4, pady=(6, 0), sticky="w")
        self.max_distance_entry = tk.Entry(top, width=9)
        self.max_distance_entry.insert(0, str(DEFAULT_MAX_DISTANCE_PCT))
        self.max_distance_entry.grid(row=1, column=3, padx=4, pady=(6, 0), sticky="w")

        tk.Label(top, text="Жизнь, с:", bg="#0a0a0d", fg="white").grid(
            row=1, column=4, padx=(14, 4), pady=(6, 0), sticky="w")
        self.single_confirm_entry = tk.Entry(top, width=9)
        self.single_confirm_entry.insert(0, str(DEFAULT_SINGLE_CONFIRM_SEC))
        self.single_confirm_entry.grid(row=1, column=5, padx=4, pady=(6, 0), sticky="w")

        top2 = tk.Frame(tab_scanner, bg="#0a0a0d")
        top2.pack(fill="x", padx=10, pady=(0, 8))

        tk.Button(top2, text="➕ Добавить", command=self._add_symbol,
                  bg="#2563eb", fg="white", relief="flat", padx=8).grid(row=0, column=0, padx=(0, 8))
        tk.Button(top2, text="🗑 Удалить", command=self._remove_symbol,
                  bg="#1f1f24", fg="white", relief="flat", padx=8).grid(row=0, column=1, padx=4)
        tk.Button(top2, text="🔇 Вкл/выкл алерты", command=self._toggle_mute,
                  bg="#1f1f24", fg="white", relief="flat", padx=8).grid(row=0, column=2, padx=4)

        self.start_btn = tk.Button(top2, text="▶ Старт", command=self._toggle_start,
                                    bg="#16a34a", fg="white", width=10, relief="flat")
        self.start_btn.grid(row=0, column=3, padx=12)

        sound_chk = tk.Checkbutton(top2, text="🔔 Звук", variable=self.sound_enabled,
                                    bg="#0a0a0d", fg="white", selectcolor="#131316",
                                    activebackground="#0a0a0d", activeforeground="white")
        sound_chk.grid(row=0, column=4, padx=4)
        tk.Button(top2, text="💾 Экспорт конфига", command=self._export_config,
                  bg="#1f1f24", fg="white", relief="flat", padx=8).grid(row=0, column=5, padx=(12, 4))
        tk.Button(top2, text="📂 Импорт конфига", command=self._import_config,
                  bg="#1f1f24", fg="white", relief="flat", padx=8).grid(row=0, column=6, padx=4)
        self.audit_btn = tk.Button(top2, text="csv", command=self._toggle_audit,
                                    bg="#0a0a0d", fg="#343842", activebackground="#0a0a0d",
                                    activeforeground="#737883", relief="flat", bd=0,
                                    highlightthickness=0, padx=2, pady=0, width=4,
                                    font=("Segoe UI", 7), cursor="hand2")
        self.audit_btn.grid(row=0, column=7, padx=(4, 0))

        tk.Label(top2, text="🧱 Стенка = 3+ плотности рядом (отдельно от 🟨 одиночной). "
                             "Пустое «до $» = «от и выше» (без разницы, насколько крупная). "
                             "Двойной клик по строке — редактировать.",
                 bg="#0a0a0d", fg="#6b7078", font=("Segoe UI", 9)).grid(
            row=1, column=0, columnspan=9, padx=(0, 4), pady=(6, 0), sticky="w")

        mid = tk.Frame(tab_scanner, bg="#0a0a0d")
        mid.pack(fill="x", padx=10, pady=4)

        # ВАЖНО: threshold_max добавлен В КОНЕЦ кортежа columns, а не рядом с
        # threshold — по индексам vals[N] из этого кортежа завязано много кода
        # (_poll_queue, _toggle_mute, _save_config и т.д.), вставка новой
        # колонки в середину сдвинула бы все индексы после неё. Визуально же
        # колонка всё равно стоит рядом с "От $" — за это отвечает
        # displaycolumns ниже, который переставляет порядок ТОЛЬКО в отображении.
        cols = ("exchange", "symbol", "mode", "threshold", "live_threshold",
                "direction", "bid", "ask", "walls", "alerts", "threshold_max",
                "max_distance_pct", "single_confirm_sec")
        headers = {"exchange": "Биржа", "symbol": "Символ", "mode": "Режим",
                   "threshold": "От $", "live_threshold": "Тек. порог $",
                   "direction": "Напр.", "bid": "Best Bid", "ask": "Best Ask",
                   "walls": "Плотностей", "alerts": "Алерты", "threshold_max": "До $",
                   "max_distance_pct": "Дист. %", "single_confirm_sec": "Жизнь с"}
        widths = {"exchange": 120, "symbol": 120, "mode": 70, "threshold": 90,
                  "live_threshold": 110, "direction": 70, "bid": 100, "ask": 100,
                  "walls": 80, "alerts": 90, "threshold_max": 90, "max_distance_pct": 70,
                  "single_confirm_sec": 70}
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=6, selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="center")
        self.tree["displaycolumns"] = ("exchange", "symbol", "mode", "threshold", "threshold_max",
                                        "max_distance_pct", "single_confirm_sec", "live_threshold",
                                        "walls", "alerts")
        tree_scroll = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="x", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._edit_selected)
        self.tree.bind("<Button-3>", lambda e: self._copy_symbol_from_tree_event(self.tree, 1, e))

        details_notebook = ttk.Notebook(tab_scanner)
        details_notebook.pack(fill="x", padx=10, pady=(8, 4))

        prints_frame = tk.Frame(details_notebook, bg="#0a0a0d")
        walls_frame = tk.Frame(details_notebook, bg="#0a0a0d")
        details_notebook.add(prints_frame, text="Повторяющиеся принты")
        details_notebook.add(walls_frame, text="Активные плотности")

        prints_controls = tk.Frame(prints_frame, bg="#0a0a0d")
        prints_controls.pack(fill="x", pady=(2, 4))
        tk.Label(prints_controls, text="Мин. принтов: 3", bg="#0a0a0d", fg="#9aa0a6").pack(side="left", padx=(0, 12))
        tk.Label(prints_controls, text="От $:", bg="#0a0a0d", fg="white").pack(side="left", padx=(0, 4))
        self.print_min_usd_entry = tk.Entry(prints_controls, width=9)
        self.print_min_usd_entry.insert(0, f"{self.print_min_usd:g}")
        self.print_min_usd_entry.pack(side="left", padx=(0, 10))
        tk.Label(prints_controls, text="До $:", bg="#0a0a0d", fg="white").pack(side="left", padx=(0, 4))
        self.print_max_usd_entry = tk.Entry(prints_controls, width=9)
        self.print_max_usd_entry.insert(0, "" if self.print_max_usd is None else f"{self.print_max_usd:g}")
        self.print_max_usd_entry.pack(side="left", padx=(0, 12))
        tk.Label(prints_controls, text="Окно, с:", bg="#0a0a0d", fg="white").pack(side="left", padx=(0, 4))
        self.print_window_entry = tk.Entry(prints_controls, width=8)
        self.print_window_entry.insert(0, f"{self.print_window_sec:g}")
        self.print_window_entry.pack(side="left", padx=(0, 12))
        tk.Label(prints_controls, text="Похожесть, %:", bg="#0a0a0d", fg="white").pack(side="left", padx=(0, 4))
        self.print_similarity_entry = tk.Entry(prints_controls, width=8)
        self.print_similarity_entry.insert(0, f"{self.print_similarity_pct:g}")
        self.print_similarity_entry.pack(side="left", padx=(0, 12))
        tk.Button(prints_controls, text="Применить", command=self._apply_print_settings,
                  bg="#1f1f24", fg="white", relief="flat", padx=8).pack(side="left")
        self.print_min_usd_entry.bind("<Return>", lambda _e: self._apply_print_settings())
        self.print_max_usd_entry.bind("<Return>", lambda _e: self._apply_print_settings())
        self.print_window_entry.bind("<Return>", lambda _e: self._apply_print_settings())
        self.print_similarity_entry.bind("<Return>", lambda _e: self._apply_print_settings())

        pcols = ("time", "exchange", "symbol", "side", "count", "avg", "total", "span", "similarity", "prices", "prints")
        pheaders = {"time": "Время", "exchange": "Биржа", "symbol": "Символ", "side": "Сторона",
                    "count": "Принтов", "avg": "Средний $", "total": "Всего $", "span": "Окно",
                    "similarity": "Похожесть", "prices": "Цены", "prints": "Принты"}
        pwidths = {"time": 70, "exchange": 120, "symbol": 120, "side": 90, "count": 70,
                   "avg": 95, "total": 95, "span": 75, "similarity": 85, "prices": 140, "prints": 260}
        self.prints_tree = ttk.Treeview(prints_frame, columns=pcols, show="headings", height=5)
        for c in pcols:
            self.prints_tree.heading(c, text=pheaders[c])
            self.prints_tree.column(c, width=pwidths[c], anchor="center" if c != "prints" else "w")
        self.prints_tree.tag_configure("buy", foreground=SIDE_COLOR["bid"])
        self.prints_tree.tag_configure("sell", foreground=SIDE_COLOR["ask"])
        prints_scroll = ttk.Scrollbar(prints_frame, orient="vertical", command=self.prints_tree.yview)
        self.prints_tree.configure(yscrollcommand=prints_scroll.set)
        self.prints_tree.pack(side="left", fill="x", expand=True)
        prints_scroll.pack(side="right", fill="y")
        self.prints_tree.bind("<Double-1>", lambda e: self._copy_symbol_from_tree(self.prints_tree, 2))
        self.prints_tree.bind("<Button-3>", lambda e: self._copy_symbol_from_tree_event(self.prints_tree, 2, e))

        wcols = ("exchange", "symbol", "side", "price", "usd", "age", "dist")
        wheaders = {"exchange": "Биржа", "symbol": "Символ", "side": "Сторона", "price": "Цена",
                    "usd": "Размер $", "age": "Возраст", "dist": "Дистанция"}
        wwidths = {"exchange": 120, "symbol": 130, "side": 130, "price": 100,
                   "usd": 110, "age": 90, "dist": 100}
        self.walls_tree = ttk.Treeview(walls_frame, columns=wcols, show="headings", height=5)
        for c in wcols:
            self.walls_tree.heading(c, text=wheaders[c])
            self.walls_tree.column(c, width=wwidths[c], anchor="center")
        # BID/ASK — зелёный/красный, как на биржевых heatmap-стаканах
        self.walls_tree.tag_configure("bid", foreground=SIDE_COLOR["bid"])
        self.walls_tree.tag_configure("ask", foreground=SIDE_COLOR["ask"])
        self.walls_tree.pack(fill="x")
        self.walls_tree.bind("<Double-1>", lambda e: self._copy_symbol_from_tree(self.walls_tree, 1))
        self.walls_tree.bind("<Button-3>", lambda e: self._copy_symbol_from_tree_event(self.walls_tree, 1, e))

        bottom = tk.Frame(tab_scanner, bg="#0a0a0d")
        bottom.pack(fill="both", expand=True, padx=10, pady=8)
        log_header = tk.Frame(bottom, bg="#0a0a0d")
        log_header.pack(fill="x")
        tk.Label(log_header, text="Лента алертов", bg="#0a0a0d", fg="white",
                 font=("Segoe UI", 11, "bold")).pack(side="left", anchor="w")
        self.alert_filter_vars = {}
        for kind, label in ALERT_FILTERS:
            var = tk.BooleanVar(value=True)
            self.alert_filter_vars[kind] = var
            tk.Checkbutton(log_header, text=label, variable=var, command=self._apply_alert_filters,
                           bg="#0a0a0d", fg="#d1d5db", selectcolor="#131316",
                           activebackground="#0a0a0d", activeforeground="white",
                           font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))
        tk.Button(log_header, text="🧹 Очистить ленту", command=self._clear_alert_log,
                  bg="#1f1f24", fg="white", relief="flat", padx=8).pack(side="right")

        lcols = ("time", "exchange", "symbol", "side", "price", "event", "details", "comment")
        lheaders = {"time": "Время", "exchange": "Биржа", "symbol": "Символ", "side": "Сторона",
                    "price": "Цена", "event": "Событие", "details": "Детали", "comment": "Комментарий"}
        lwidths = {"time": 70, "exchange": 120, "symbol": 120, "side": 90,
                   "price": 90, "event": 130, "details": 300, "comment": 240}
        self.log = ttk.Treeview(bottom, columns=lcols, show="headings")
        for c in lcols:
            self.log.heading(c, text=lheaders[c])
            self.log.column(c, width=lwidths[c], anchor="center" if c not in ("details", "comment") else "w")
        for kind, color in EVENT_COLORS.items():
            self.log.tag_configure(kind, foreground=color)
        log_scroll = ttk.Scrollbar(bottom, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        self.log.bind("<Double-1>", self._on_log_double_click)
        self.log.bind("<Button-3>", lambda e: self._copy_symbol_from_tree_event(self.log, 2, e))

        self._build_movers_tab(tab_movers)
        self._build_hedgehog_tab(tab_hedgehog)
        self._build_early_tab(tab_early)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        status_bar = tk.Label(self.root, textvariable=self.status_var,
                               bg="#000000", fg="#9aa0a6", anchor="w", padx=8)
        status_bar.pack(fill="x", side="bottom")

        self.copy_notice_var = tk.StringVar(value="")
        self.copy_notice = tk.Label(self.root, textvariable=self.copy_notice_var,
                                    bg="#111827", fg="#a7f3d0", padx=8, pady=3,
                                    font=("Segoe UI", 8), relief="flat")

        conn_frame = tk.Frame(self.root, bg="#0a0a0d")
        conn_frame.pack(fill="x", side="bottom", padx=10, pady=(1, 1))
        tk.Label(conn_frame, text="Подключение:", bg="#0a0a0d", fg="#9aa0a6",
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        self.conn_labels = {}
        for exch in EXCHANGE_CHOICES:
            short = EXCHANGE_SHORT_LABELS.get(exch, exch)
            lbl = tk.Label(conn_frame, text=f"{short}: ⚪ —", bg="#0a0a0d", fg="#6b7078",
                           font=("Segoe UI", 8, "bold"), padx=3)
            lbl.pack(side="left", padx=(0, 5))
            self.conn_labels[exch] = lbl

    def _build_movers_tab(self, parent):
        """Вкладка «Топ движений»: топ-20 роста и топ-20 падения за 24ч по
        фьючерсным/линейным источникам без spot (лёгкий REST-опрос всего рынка, market_scan.py —
        никаких REST-снапшотов/WS per-символ, поэтому это не грузит биржи так,
        как подписка на стакан). Двойной клик по строке — сразу добавляет
        монету в сканер плотностей (режим AUTO)."""
        settings = tk.Frame(parent, bg="#0a0a0d")
        settings.pack(fill="x", padx=4, pady=(8, 0))

        tk.Label(settings, text="⚡ Настройка импульса:", bg="#0a0a0d", fg="white",
                 font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=(0, 10), sticky="w")

        tk.Label(settings, text="Порог %:", bg="#0a0a0d", fg="white").grid(row=0, column=1, sticky="w")
        self.impulse_threshold_entry = tk.Entry(settings, width=6)
        self.impulse_threshold_entry.insert(0, f"{self.impulse_threshold_pct:g}")
        self.impulse_threshold_entry.grid(row=0, column=2, padx=(4, 12))

        tk.Label(settings, text="Окно, сек:", bg="#0a0a0d", fg="white").grid(row=0, column=3, sticky="w")
        self.impulse_window_entry = tk.Entry(settings, width=6)
        self.impulse_window_entry.insert(0, f"{self.impulse_window_sec:g}")
        self.impulse_window_entry.grid(row=0, column=4, padx=(4, 12))

        tk.Checkbutton(settings, text="🔔 Всплывающее окно", variable=self.impulse_popup_enabled,
                        bg="#0a0a0d", fg="white", selectcolor="#131316",
                        activebackground="#0a0a0d", activeforeground="white").grid(row=0, column=5, padx=(0, 10))
        tk.Checkbutton(settings, text="🔊 Звук", variable=self.impulse_sound_enabled,
                        bg="#0a0a0d", fg="white", selectcolor="#131316",
                        activebackground="#0a0a0d", activeforeground="white").grid(row=0, column=6, padx=(0, 12))

        tk.Button(settings, text="Применить", command=self._apply_impulse_settings,
                  bg="#2563eb", fg="white", relief="flat", padx=8).grid(row=0, column=7)

        self.movers_hint_var = tk.StringVar()
        hint = tk.Label(parent, textvariable=self.movers_hint_var,
                         bg="#0a0a0d", fg="#6b7078", font=("Segoe UI", 9))
        hint.pack(anchor="w", padx=4, pady=(6, 4))
        self._update_movers_hint()

        split = tk.Frame(parent, bg="#0a0a0d")
        split.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        mcols = ("exchange", "symbol", "last", "change", "impulse", "volume")
        mheaders = {"exchange": "Биржа", "symbol": "Символ", "last": "Цена",
                    "change": "24ч %", "impulse": self._impulse_column_title(),
                    "volume": "Объём $"}
        mwidths = {"exchange": 120, "symbol": 130, "last": 100, "change": 90,
                   "impulse": 100, "volume": 110}

        def make_movers_tree(container, title):
            frame = tk.Frame(container, bg="#0a0a0d")
            tk.Label(frame, text=title, bg="#0a0a0d", fg="white",
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")
            inner = tk.Frame(frame, bg="#0a0a0d")
            inner.pack(fill="both", expand=True)
            tv = ttk.Treeview(inner, columns=mcols, show="headings")
            for c in mcols:
                tv.heading(c, text=mheaders[c])
                tv.column(c, width=mwidths[c], anchor="center")
            tv.tag_configure("up", foreground=SIDE_COLOR["bid"])
            tv.tag_configure("down", foreground=SIDE_COLOR["ask"])
            tv.tag_configure("impulse", foreground=EVENT_COLORS["MAGNET"])
            scroll = ttk.Scrollbar(inner, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=scroll.set)
            tv.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            tv.bind("<Double-1>", self._on_mover_double_click)
            tv.bind("<Button-3>", lambda e, tree=tv: self._copy_symbol_from_tree_event(tree, 1, e))
            frame.pack(side="left", fill="both", expand=True, padx=(0, 6))
            return tv

        self.gainers_tree = make_movers_tree(split, "🚀 Топ роста (24ч)")
        self.losers_tree = make_movers_tree(split, "📉 Топ падения (24ч)")

    def _build_hedgehog_tab(self, parent):
        """Вкладка «Ерши»: узкий боковой диапазон + частые касания обеих
        границ на низком объёме — типичный паттерн на неликвидных монетах
        перед резким движением. Считается
        из той же скользящей истории тикеров, что и «Топ движений» — никаких
        дополнительных REST-запросов, только окно шире (90 мин вместо 3)."""
        hint = tk.Label(parent,
                         text=f"Диапазон/касания за последние {int(HEDGEHOG_WINDOW_SEC / 60)} мин, "
                              f"Binance/Bybit + spot-рынки. Чем уже диапазон — тем выше в списке. "
                              f"Первые {int(HEDGEHOG_WINDOW_SEC / 60)} мин после запуска — прогрев "
                              "(строк не будет, копится история).",
                         bg="#0a0a0d", fg="#6b7078", font=("Segoe UI", 9))
        hint.pack(anchor="w", padx=4, pady=(8, 4))

        hcols = ("exchange", "symbol", "last", "range", "touch_top", "touch_bot", "vol60", "vol10")
        hheaders = {"exchange": "Биржа", "symbol": "Символ", "last": "Цена",
                    "range": "Диапазон %", "touch_top": "Touch верх", "touch_bot": "Touch низ",
                    "vol60": "Объём 60м $", "vol10": "Объём 10м $"}
        hwidths = {"exchange": 120, "symbol": 130, "last": 100, "range": 100,
                   "touch_top": 90, "touch_bot": 90, "vol60": 110, "vol10": 110}

        frame = tk.Frame(parent, bg="#0a0a0d")
        frame.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.hedgehog_tree = ttk.Treeview(frame, columns=hcols, show="headings")
        for c in hcols:
            self.hedgehog_tree.heading(c, text=hheaders[c])
            self.hedgehog_tree.column(c, width=hwidths[c], anchor="center")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.hedgehog_tree.yview)
        self.hedgehog_tree.configure(yscrollcommand=scroll.set)
        self.hedgehog_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.hedgehog_tree.bind("<Double-1>", lambda e: self._copy_symbol_from_tree(self.hedgehog_tree, 1))
        self.hedgehog_tree.bind("<Button-3>", lambda e: self._copy_symbol_from_tree_event(self.hedgehog_tree, 1, e))

    def _build_early_tab(self, parent):
        """Вкладка «🎯 Ранние»: монеты MEXC в состоянии "живой тишины" — тот
        профиль, который был у 7 из 9 размеченных пампов за час до старта
        (узкий, но не мёртвый диапазон + низкий объём, который не разгоняется).

        ВАЖНО понимать, что это вотч-лист, а не сигнал на вход: под профиль
        подходит ~5% рынка, а стреляют единицы. Смысл вкладки — сузить рынок
        с ~1800 пар до нескольких десятков, по которым параллельно пишутся
        стаканы (depth_recorder.py), чтобы потом проверить главную гипотезу:
        предсказывают ли памп неснимаемые плотности."""
        hint = tk.Label(parent,
                         text=f"MEXC. Профиль за час: диапазон {EARLY_RANGE_MIN_PCT:g}–{EARLY_RANGE_MAX_PCT:g}%, "
                              f"объём ${EARLY_VOL_MIN_USD:,}–${EARLY_VOL_MAX_USD:,}, "
                              f"без разгона (<{EARLY_ACCEL_MAX:g}x). "
                              "Это вотч-лист для наблюдения, а не сигнал на вход. "
                              "Первый час после запуска — прогрев. Двойной клик — копировать тикер.",
                         bg="#0a0a0d", fg="#6b7078", font=("Segoe UI", 9), justify="left")
        hint.pack(anchor="w", padx=4, pady=(8, 4))

        bar = tk.Frame(parent, bg="#0a0a0d")
        bar.pack(fill="x", padx=4, pady=(0, 4))
        tk.Checkbutton(bar, text="🔔 Алерт при появлении новой монеты", variable=self.early_alerts_enabled,
                        bg="#0a0a0d", fg="white", selectcolor="#131316",
                        activebackground="#0a0a0d", activeforeground="white").pack(side="left")
        tk.Checkbutton(bar, text="🚫 Только эксклюзивы (без Binance/OKX/Bybit)",
                        variable=self.early_exclusive_only,
                        bg="#0a0a0d", fg="white", selectcolor="#131316",
                        activebackground="#0a0a0d", activeforeground="white").pack(side="left", padx=(12, 0))
        self.early_status_var = tk.StringVar(value="прогрев...")
        tk.Label(bar, textvariable=self.early_status_var, bg="#0a0a0d", fg="#6b7078",
                 font=("Segoe UI", 9)).pack(side="left", padx=16)

        ecols = ("symbol", "last", "range", "vol60", "accel", "change24", "oi", "oi_chg", "also_on")
        eheaders = {"symbol": "Символ", "last": "Цена", "range": "Диапазон 60м",
                    "vol60": "Объём 60м $", "accel": "Разгон", "change24": "24ч %",
                    "oi": "OI $", "oi_chg": "OI Δ60м", "also_on": "Ещё на"}
        ewidths = {"symbol": 140, "last": 110, "range": 100, "vol60": 110,
                   "accel": 80, "change24": 80, "oi": 100, "oi_chg": 90, "also_on": 120}

        frame = tk.Frame(parent, bg="#0a0a0d")
        frame.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        self.early_tree = ttk.Treeview(frame, columns=ecols, show="headings")
        for c in ecols:
            self.early_tree.heading(c, text=eheaders[c])
            self.early_tree.column(c, width=ewidths[c], anchor="center")
        # чем уже диапазон, тем "сжатее" пружина — подсветим самых тихих
        self.early_tree.tag_configure("tight", foreground=EVENT_COLORS["CASCADE"])
        self.early_tree.tag_configure("normal", foreground="white")
        # растущий OI важнее сжатости — отдельный яркий цвет, перекрывает tight
        self.early_tree.tag_configure("oi_rising", foreground=EVENT_COLORS["MAGNET"])
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.early_tree.yview)
        self.early_tree.configure(yscrollcommand=scroll.set)
        self.early_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.early_tree.bind("<Double-1>", lambda e: self._copy_symbol_from_tree(self.early_tree, 0))

    # ---------------- управление монетами ----------------

    def _on_volume_preset_selected(self, _event=None):
        label = self.volume_preset_combo.get()
        for lbl, lo, hi in VOLUME_PRESETS:
            if lbl != label:
                continue
            self.threshold_entry.delete(0, "end")
            self.threshold_max_entry.delete(0, "end")
            if lo is not None:
                self.threshold_entry.insert(0, str(lo))
            if hi is not None:
                self.threshold_max_entry.insert(0, str(hi))
            return

    def _on_exchange_selected(self, _event=None):
        self._hide_symbol_suggestions()
        self._show_symbol_suggestions()

    def _seed_symbol_suggestions_from_rows(self):
        symbols = set()
        tree = getattr(self, "tree", None)
        if tree is not None:
            for key in tree.get_children():
                vals = tree.item(key, "values")
                if len(vals) > 1:
                    symbols.add(self._symbol_from_display(vals[1]))
        with self._symbol_suggestion_lock:
            self._symbol_suggestion_set.update(s for s in symbols if s)

    def _add_symbol_to_suggestions(self, symbol):
        symbol = str(symbol or "").upper()
        if not symbol:
            return
        with self._symbol_suggestion_lock:
            self._symbol_suggestion_set.add(symbol)

    def _refresh_symbol_suggestions_async(self):
        if self._symbol_suggestion_refreshing:
            return
        self._symbol_suggestion_refreshing = True
        threading.Thread(target=self._refresh_symbol_suggestions_worker, daemon=True).start()

    def _refresh_symbol_suggestions_worker(self):
        symbols = set()
        try:
            for exchange in EXCHANGE_CHOICES:
                try:
                    symbols.update(self._fetch_symbols_for_autocomplete(exchange))
                except Exception:
                    continue
        finally:
            with self._symbol_suggestion_lock:
                self._symbol_suggestion_set.update(s for s in symbols if s)
            self._symbol_suggestion_refreshing = False

    def _fetch_symbols_for_autocomplete(self, exchange):
        exchange = exchange.upper()
        if exchange == "BINANCE ALPHA":
            try:
                return fetch_alpha_search_symbols() | fetch_rest_symbols(exchange)
            except Exception:
                return fetch_rest_symbols(exchange)
        if exchange in BINANCE_STYLE:
            import requests
            cfg = BINANCE_WS_CONFIGS[exchange]
            resp = requests.get(f"{cfg['rest_base']}{cfg['exchange_info_path']}", timeout=10)
            resp.raise_for_status()
            return {
                str(item.get("symbol", "")).upper()
                for item in resp.json().get("symbols", [])
                if str(item.get("symbol", "")).upper().endswith("USDT")
            }
        if exchange in REST_POLLING_EXCHANGES:
            return fetch_rest_symbols(exchange)
        return set()

    def _on_symbol_keyrelease(self, event=None):
        keysym = str(getattr(event, "keysym", "") or "")
        if keysym in {"Up", "Down", "Return", "Escape"}:
            return
        self._show_symbol_suggestions()

    def _accept_symbol_entry_or_add(self, _event=None):
        if self._symbol_suggestions_visible():
            self._choose_symbol_suggestion()
            return "break"
        self._add_symbol()
        return "break"

    def _focus_symbol_suggestions(self, _event=None):
        if not self._show_symbol_suggestions():
            return None
        if self.symbol_suggest.size() > 0:
            self.symbol_suggest.focus_set()
            self.symbol_suggest.selection_clear(0, "end")
            self.symbol_suggest.selection_set(0)
            self.symbol_suggest.activate(0)
            return "break"
        return None

    def _choose_symbol_suggestion(self, _event=None):
        if not getattr(self, "symbol_suggest", None):
            return "break"
        selection = self.symbol_suggest.curselection()
        if not selection and self.symbol_suggest.size() > 0:
            selection = (0,)
        if selection:
            symbol = self.symbol_suggest.get(selection[0])
            self.symbol_entry.delete(0, "end")
            self.symbol_entry.insert(0, symbol)
            self.symbol_entry.icursor("end")
        self._hide_symbol_suggestions()
        self.symbol_entry.focus_set()
        return "break"

    def _hover_symbol_suggestion(self, event):
        if not getattr(self, "symbol_suggest", None) or self.symbol_suggest.size() <= 0:
            return None
        index = self.symbol_suggest.nearest(event.y)
        bbox = self.symbol_suggest.bbox(index)
        if not bbox:
            return None
        _x, y, _w, h = bbox
        if y <= event.y <= y + h:
            self.symbol_suggest.selection_clear(0, "end")
            self.symbol_suggest.selection_set(index)
            self.symbol_suggest.activate(index)
        return None

    def _scroll_symbol_suggestions(self, event):
        if not getattr(self, "symbol_suggest", None):
            return "break"
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            delta = getattr(event, "delta", 0)
            units = -1 * int(delta / 120) if delta else 0
            if units == 0 and delta:
                units = -1 if delta > 0 else 1
        if units:
            self.symbol_suggest.yview_scroll(units, "units")
        return "break"

    def _hide_symbol_suggestions(self):
        if hasattr(self, "symbol_suggest_popup"):
            self.symbol_suggest_popup.withdraw()

    def _symbol_suggestions_visible(self):
        popup = getattr(self, "symbol_suggest_popup", None)
        return bool(popup is not None and popup.state() != "withdrawn")

    def _show_symbol_suggestions(self):
        if not hasattr(self, "symbol_suggest"):
            return False
        raw = self.symbol_entry.get().strip().upper()
        exchange = self.exchange_combo.get().upper()
        normalized = raw.replace("_", "") if exchange == "BINANCE ALPHA" else (
            _normalize_symbol_input(raw, exchange) if raw else ""
        )
        if not raw:
            self._hide_symbol_suggestions()
            return False
        with self._symbol_suggestion_lock:
            all_symbols = list(self._symbol_suggestion_set)
        matches = []
        for symbol in all_symbols:
            plain = symbol.replace("_", "")
            if symbol.startswith(raw) or plain.startswith(raw) or symbol.startswith(normalized):
                matches.append(symbol)
        matches = sorted(matches)[:80]
        self.symbol_suggest.delete(0, "end")
        for symbol in matches:
            self.symbol_suggest.insert("end", symbol)
        if matches:
            visible_rows = min(8, len(matches))
            self.symbol_suggest.config(height=visible_rows)
            self.root.update_idletasks()
            x = self.symbol_entry.winfo_rootx()
            y = self.symbol_entry.winfo_rooty() + self.symbol_entry.winfo_height()
            width = max(self.symbol_entry.winfo_width(), 220)
            row_height = max(18, self.symbol_suggest.winfo_reqheight() // max(visible_rows, 1))
            height = (row_height * visible_rows) + 4
            self.symbol_suggest_popup.geometry(f"{width}x{height}+{x}+{y}")
            self.symbol_suggest_popup.deiconify()
            self.symbol_suggest_popup.lift()
            return True
        self._hide_symbol_suggestions()
        return False

    def _base_exchange_for(self, exchange):
        exchange = (exchange or "").upper()
        if exchange.endswith(" SPOT"):
            base = exchange[:-5]
            if base in BASE_EXCHANGE_CHOICES:
                return base
        return exchange

    @staticmethod
    def _symbol_display(exchange, symbol):
        symbol = (symbol or "").upper()
        exchange = (exchange or "").upper()
        if exchange == "BINANCE ALPHA":
            return alpha_display_symbol(symbol)
        return f"{symbol} SPOT" if exchange.endswith(" SPOT") else symbol

    @staticmethod
    def _symbol_from_display(symbol):
        symbol = (symbol or "").strip().upper()
        return symbol[:-5].strip() if symbol.endswith(" SPOT") else symbol

    @staticmethod
    def _side_display(side):
        return "низ" if side == "bid" else "верх"

    def _exchange_targets_for_selection(self, exchange):
        exchange = (exchange or "").upper()
        if exchange == ALL_EXCHANGES_LABEL.upper():
            return EXCHANGE_CHOICES, "всех биржах"
        return [exchange], exchange

    def _config_targets_for_exchange(self, exchange):
        """Load saved rows as the exact market that is stored in config.json."""
        exchange = (exchange or "BINANCE").upper()
        if exchange == ALL_EXCHANGES_LABEL.upper():
            return list(EXCHANGE_CHOICES)
        return [exchange]

    def _add_symbol(self, symbol=None, threshold=None, direction=None, exchange=None,
                     mode=None, muted=False, silent=False, threshold_max=_UNSET,
                     max_distance_pct=_UNSET, single_confirm_sec=_UNSET,
                     exact_exchange=False):
        exchange = (exchange or self.exchange_combo.get()).upper()
        symbol = _normalize_symbol_input(symbol or self.symbol_entry.get(), exchange)
        if not symbol:
            return
        try:
            threshold = _parse_compact_usd(threshold if threshold is not None else self.threshold_entry.get())
            if threshold is None:
                raise ValueError
        except (ValueError, TypeError):
            if not silent:
                messagebox.showerror("Ошибка", "Порог должен быть числом")
            return

        # _UNSET (параметр не передан вовсе) — читаем "до $" из поля ввода,
        # это интерактивный вызов по кнопке. Явный None (из _load_config,
        # сохранённый ранее режим "от и выше") — оставляем как есть, поле
        # ввода тут не при чём.
        if threshold_max is _UNSET:
            raw_max = self.threshold_max_entry.get().strip() if not silent else ""
            threshold_max = _parse_compact_usd(raw_max) if raw_max else None
        elif threshold_max is not None:
            try:
                threshold_max = _parse_compact_usd(threshold_max)
            except (ValueError, TypeError):
                threshold_max = None
        if threshold_max is not None and threshold_max <= threshold:
            if not silent:
                messagebox.showerror("Ошибка", "«до $» должно быть больше «от $»")
            return

        # то же самое для "Дистанция %" (от спреда до плотности) — пустое
        # поле или отсутствие в старом сохранённом конфиге = дефолт
        if max_distance_pct is _UNSET:
            raw_dist = self.max_distance_entry.get().strip() if not silent else ""
            raw_dist = raw_dist or str(DEFAULT_MAX_DISTANCE_PCT)
            try:
                max_distance_pct = _normalize_distance_pct(raw_dist)
            except (ValueError, TypeError):
                if not silent:
                    messagebox.showerror("Ошибка", "«Дистанция %» должна быть числом")
                return
        elif max_distance_pct is None:
            max_distance_pct = DEFAULT_MAX_DISTANCE_PCT
        else:
            try:
                max_distance_pct = _normalize_distance_pct(max_distance_pct)
            except (ValueError, TypeError):
                max_distance_pct = DEFAULT_MAX_DISTANCE_PCT
        if max_distance_pct < 0:
            if not silent:
                messagebox.showerror("Ошибка", "«Дистанция %» не может быть меньше нуля")
            return

        if single_confirm_sec is _UNSET:
            raw_life = self.single_confirm_entry.get().strip() if not silent else ""
            raw_life = raw_life or str(DEFAULT_SINGLE_CONFIRM_SEC)
            try:
                single_confirm_sec = _normalize_single_confirm_sec(raw_life)
            except (ValueError, TypeError):
                if not silent:
                    messagebox.showerror("Ошибка", "«Жизнь, с» должна быть числом")
                return
        elif single_confirm_sec is None:
            single_confirm_sec = DEFAULT_SINGLE_CONFIRM_SEC
        else:
            try:
                single_confirm_sec = _normalize_single_confirm_sec(single_confirm_sec)
            except (ValueError, TypeError):
                single_confirm_sec = DEFAULT_SINGLE_CONFIRM_SEC
        if single_confirm_sec < 0:
            if not silent:
                messagebox.showerror("Ошибка", "«Жизнь, с» не может быть меньше нуля")
            return

        direction = "BOTH"
        mode = (mode or self.mode_combo.get()).upper()
        if mode not in ("FIXED", "AUTO"):
            mode = "FIXED"

        if not exact_exchange and exchange == ALL_EXCHANGES_LABEL.upper():
            exchanges, target_label = self._exchange_targets_for_selection(exchange)
            self._add_symbol_all_exchanges(symbol, threshold, threshold_max, direction, mode,
                                            max_distance_pct, single_confirm_sec,
                                            exchanges, target_label)
            return

        if exchange not in EXCHANGE_CHOICES:
            if not silent:
                messagebox.showerror("Ошибка", f"Неизвестная биржа: {exchange}")
            return

        cfg = SymbolConfig(symbol, threshold, direction, exchange=exchange, mode=mode,
                            threshold_max_usd=threshold_max, max_distance_pct=max_distance_pct,
                            single_confirm_sec=single_confirm_sec)
        self.detector.set_config(cfg)

        key = f"{exchange}:{symbol}"
        if muted:
            self.muted_keys.add(key)
        alerts_display = "🔇 Выкл" if key in self.muted_keys else "🔔 Вкл"
        threshold_max_display = "-" if threshold_max is None else _format_compact_usd(threshold_max).replace("$", "")
        max_distance_display = f"{max_distance_pct:g}"
        single_confirm_display = f"{single_confirm_sec:g}"
        symbol_display = self._symbol_display(exchange, symbol)

        if key not in self.orderbooks:
            self.orderbooks[key] = OrderBook(symbol)
            self.tree.insert("", "end", iid=key,
                              values=(exchange, symbol_display, mode, _format_compact_usd(threshold).replace("$", ""), "-",
                                      direction, "-", "-", 0, alerts_display, threshold_max_display,
                                      max_distance_display, single_confirm_display))
            self._add_symbol_to_suggestions(symbol_display)
            if self.ws_managers:
                self._ensure_manager(exchange)
                threading.Thread(target=self._validate_and_subscribe,
                                  args=(exchange, symbol), daemon=True).start()
        else:
            self.tree.item(key, values=(exchange, symbol_display, mode, _format_compact_usd(threshold).replace("$", ""), "-",
                                         direction, "-", "-", 0, alerts_display, threshold_max_display,
                                         max_distance_display, single_confirm_display))
            self._add_symbol_to_suggestions(symbol_display)

        self._save_config()
        self.symbol_entry.delete(0, "end")
        self.threshold_entry.delete(0, "end")
        self.threshold_max_entry.delete(0, "end")
        self._hide_symbol_suggestions()
        symbol = symbol_display
        if not silent:
            self.status_var.set(f"{exchange}:{symbol} добавлен в сканер")
        # сбрасываем на дефолт (а не оставляем "липким", как режим/направление) —
        # иначе кастомная дистанция для одной монеты по забывчивости
        # перетекла бы на следующую добавленную по умолчанию
        self.max_distance_entry.delete(0, "end")
        self.max_distance_entry.insert(0, str(DEFAULT_MAX_DISTANCE_PCT))
        self.single_confirm_entry.delete(0, "end")
        self.single_confirm_entry.insert(0, str(DEFAULT_SINGLE_CONFIRM_SEC))

    def _add_symbol_all_exchanges(self, symbol, threshold, threshold_max, direction, mode,
                                   max_distance_pct, single_confirm_sec,
                                   exchanges=None, target_label=None):
        """Проверяет тикер на наборе конкретных рынков в фоне и добавляет
        только туда, где он реально торгуется."""
        exchanges = list(exchanges or EXCHANGE_CHOICES)
        target_label = target_label or "всех биржах"
        self.symbol_entry.delete(0, "end")
        self.threshold_entry.delete(0, "end")
        self.threshold_max_entry.delete(0, "end")
        self.max_distance_entry.delete(0, "end")
        self.max_distance_entry.insert(0, str(DEFAULT_MAX_DISTANCE_PCT))
        self.single_confirm_entry.delete(0, "end")
        self.single_confirm_entry.insert(0, str(DEFAULT_SINGLE_CONFIRM_SEC))
        self.status_var.set(f"Проверяю {symbol} на {target_label}...")
        threading.Thread(
            target=self._validate_all_exchanges_worker,
            args=(symbol, threshold, threshold_max, direction, mode, max_distance_pct,
                  single_confirm_sec, exchanges, target_label),
            daemon=True,
        ).start()

    def _validate_all_exchanges_worker(self, symbol, threshold, threshold_max, direction, mode,
                                        max_distance_pct, single_confirm_sec, exchanges, target_label):
        found = []
        for exchange in exchanges:
            try:
                ok = self._validator_for(exchange)(symbol)
            except Exception:
                ok = False
            if ok:
                found.append(exchange)
                self.root.after(0, lambda exch=exchange: self._add_symbol(
                    symbol, threshold, direction, exchange=exch, mode=mode,
                    silent=True, threshold_max=threshold_max, max_distance_pct=max_distance_pct,
                    single_confirm_sec=single_confirm_sec,
                    exact_exchange=True,
                ))
        if found:
            self.root.after(0, lambda: self.status_var.set(
                f"{symbol} добавлен на: {', '.join(found)}"))
        else:
            self.root.after(0, lambda: self.status_var.set(
                f"⚠ {symbol} не найден на {target_label}"))

    def _toggle_mute(self):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        if key in self.muted_keys:
            self.muted_keys.discard(key)
        else:
            self.muted_keys.add(key)
        vals = list(self.tree.item(key, "values"))
        vals[9] = "🔇 Выкл" if key in self.muted_keys else "🔔 Вкл"
        self.tree.item(key, values=vals)
        self._save_config()

    def _remove_symbol(self, _event=None):
        sel = list(self.tree.selection())
        if not sel:
            return "break" if _event is not None else None

        removed = []
        for key in sel:
            if not self.tree.exists(key):
                continue
            exchange, symbol = key.split(":", 1)
            mgr = self.ws_managers.get(exchange)
            if mgr:
                mgr.unsubscribe_symbol(symbol)
            self.orderbooks.pop(key, None)
            self.detector.remove_symbol(exchange, symbol)
            self.muted_keys.discard(key)
            self.tree.delete(key)
            for iid in list(self.walls_tree.get_children()):
                if iid.startswith(f"{key}|"):
                    self.walls_tree.delete(iid)
                    self._wall_row_seq.pop(iid, None)
            removed.append(key)

        self._save_config()
        if removed:
            self.status_var.set(f"Удалено из сканера: {len(removed)}")
        return "break" if _event is not None else None

    def _on_global_keypress(self, event=None):
        if event is None:
            return None
        if self._event_matches_hotkey(event, "DELETE"):
            return self._on_delete_key(event)
        if self._event_has_ctrl(event) and self._event_matches_hotkey(event, "C"):
            return self._copy_symbol_hotkey(event)
        return None

    def _event_has_ctrl(self, event):
        return bool(getattr(event, "state", 0) & CTRL_MASK)

    def _event_matches_hotkey(self, event, key_name):
        key_name = key_name.upper()
        keysym = str(getattr(event, "keysym", "") or "").lower()
        if keysym in HOTKEY_KEYSYMS.get(key_name, set()):
            return True
        try:
            keycode = int(getattr(event, "keycode", -1))
        except (TypeError, ValueError):
            keycode = -1
        return keycode in HOTKEY_KEYCODES.get(key_name, set())

    def _on_delete_key(self, event=None):
        focused = self.root.focus_get()
        if self._is_text_input_focused(focused):
            return None
        try:
            if focused is not None and focused.winfo_class() == "Treeview" and focused is not self.tree:
                return None
        except tk.TclError:
            return None
        if self.tree.selection():
            return self._remove_symbol(event)
        return None

    def _is_text_input_focused(self, widget):
        if widget is None:
            return False
        try:
            if self._log_comment_editor and widget == self._log_comment_editor.get("entry"):
                return True
            return widget.winfo_class() in {"Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox"}
        except tk.TclError:
            return False

    def _copy_symbol_hotkey(self, _event=None):
        focused = self.root.focus_get()
        if self._is_text_input_focused(focused):
            return None
        for tree, symbol_index in self._copyable_symbol_trees():
            if focused == tree:
                if tree.selection():
                    self._copy_symbol_from_tree(tree, symbol_index)
                    return "break"
                return None
        return None

    def _copyable_symbol_trees(self):
        for attr, symbol_index in (
            ("tree", 1),
            ("prints_tree", 2),
            ("walls_tree", 1),
            ("log", 2),
            ("gainers_tree", 1),
            ("losers_tree", 1),
            ("hedgehog_tree", 1),
        ):
            tree = getattr(self, attr, None)
            if tree is not None:
                yield tree, symbol_index

    def _edit_selected(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        vals = self.tree.item(key, "values")
        self.exchange_combo.set(vals[0])
        self.symbol_entry.delete(0, "end")
        self.symbol_entry.insert(0, vals[1])
        self.mode_combo.set(vals[2])
        self.threshold_entry.delete(0, "end")
        self.threshold_entry.insert(0, str(vals[3]).replace("$", ""))
        self.threshold_max_entry.delete(0, "end")
        tmax = vals[10] if len(vals) > 10 else "-"
        if tmax not in ("-", ""):
            self.threshold_max_entry.insert(0, str(tmax).replace("$", ""))
        self.volume_preset_combo.set("Вручную")
        dist = vals[11] if len(vals) > 11 else str(DEFAULT_MAX_DISTANCE_PCT)
        self.max_distance_entry.delete(0, "end")
        self.max_distance_entry.insert(0, dist or str(DEFAULT_MAX_DISTANCE_PCT))
        life = vals[12] if len(vals) > 12 else str(DEFAULT_SINGLE_CONFIRM_SEC)
        self.single_confirm_entry.delete(0, "end")
        self.single_confirm_entry.insert(0, life or str(DEFAULT_SINGLE_CONFIRM_SEC))
        self._copy_symbol_to_clipboard(vals[1])

    def _copy_symbol_to_clipboard(self, symbol):
        """Копирует тикер в буфер обмена — чтобы можно было сразу вставить в
        торговый терминал. Вызывается по двойному клику из любой таблицы,
        где показан символ."""
        self.root.clipboard_clear()
        self.root.clipboard_append(symbol)
        self.status_var.set(f"Скопировано в буфер: {symbol}")
        self._show_copy_notice(symbol)

    def _show_copy_notice(self, symbol):
        if not hasattr(self, "copy_notice"):
            return
        if self._copy_notice_after_id is not None:
            try:
                self.root.after_cancel(self._copy_notice_after_id)
            except tk.TclError:
                pass
        self.copy_notice_var.set(f"Скопировано: {symbol}")
        self.copy_notice.place(relx=1.0, rely=1.0, x=-18, y=-42, anchor="se")
        self.copy_notice.lift()
        self._copy_notice_after_id = self.root.after(1400, self._hide_copy_notice)

    def _hide_copy_notice(self):
        self._copy_notice_after_id = None
        if hasattr(self, "copy_notice"):
            self.copy_notice.place_forget()

    def _copy_symbol_from_tree(self, tree, symbol_index=1):
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0], "values")
        if len(vals) <= symbol_index:
            return
        self._copy_symbol_to_clipboard(self._symbol_from_display(vals[symbol_index]))

    def _copy_symbol_from_tree_event(self, tree, symbol_index=1, event=None):
        if event is not None:
            row = tree.identify_row(event.y)
            if not row:
                return "break"
            tree.selection_set(row)
            tree.focus(row)
        self._copy_symbol_from_tree(tree, symbol_index)
        return "break"

    def _clear_alert_log(self):
        rows = list(self._alert_rows) if self._alert_rows else list(self.log.get_children())
        if not rows:
            self.status_var.set("Лента алертов уже пустая")
            return
        if not messagebox.askyesno("Очистить ленту", f"Удалить {len(rows)} записей из ленты алертов?"):
            return
        self._close_log_comment_editor(save=False)
        for row in rows:
            if self.log.exists(row):
                self.log.delete(row)
        self._alert_rows.clear()
        self._alert_row_kinds.clear()
        self.status_var.set("Лента алертов очищена")

    def _passes_alert_filter(self, kind):
        var = getattr(self, "alert_filter_vars", {}).get(kind)
        return True if var is None else bool(var.get())

    def _apply_alert_filters(self):
        self._close_log_comment_editor(save=True)
        for row in list(self._alert_rows):
            if not self.log.exists(row):
                continue
            kind = self._alert_row_kinds.get(row)
            if self._passes_alert_filter(kind):
                self.log.move(row, "", 0)
            else:
                self.log.detach(row)
        visible = [row for row in reversed(self._alert_rows)
                   if self.log.exists(row) and self._passes_alert_filter(self._alert_row_kinds.get(row))]
        for index, row in enumerate(visible):
            self.log.move(row, "", index)

    def _on_log_double_click(self, event):
        self._close_log_comment_editor(save=True)
        row = self.log.identify_row(event.y)
        if not row:
            return "break"
        self.log.selection_set(row)

        col_name = ""
        for name in self.log["columns"]:
            bbox = self.log.bbox(row, name)
            if bbox and bbox[0] <= event.x < bbox[0] + bbox[2]:
                col_name = name
                break

        if col_name == "comment":
            self._edit_alert_comment(row)
        else:
            self._copy_symbol_from_tree(self.log, 2)
        return "break"

    def _set_alert_comment(self, row, comment):
        if not self.log.exists(row):
            return
        columns = list(self.log["columns"])
        comment_idx = columns.index("comment")
        vals = list(self.log.item(row, "values"))
        while len(vals) <= comment_idx:
            vals.append("")
        vals[comment_idx] = str(comment or "").strip()
        self.log.item(row, values=vals)

    def _edit_alert_comment(self, row):
        if not self.log.exists(row):
            return
        columns = list(self.log["columns"])
        comment_idx = columns.index("comment")
        vals = list(self.log.item(row, "values"))
        current = vals[comment_idx] if len(vals) > comment_idx else ""
        bbox = self.log.bbox(row, "comment")
        if not bbox:
            return

        editor = tk.Entry(self.log, bg="#f8fafc", fg="#111827",
                          insertbackground="#111827", relief="solid", bd=1)
        editor.insert(0, current)
        editor.select_range(0, "end")
        editor.icursor("end")
        editor.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        self._log_comment_editor = {"entry": editor, "row": row, "original": current}

        editor.bind("<Return>", lambda _event: self._close_log_comment_editor(save=True))
        editor.bind("<Escape>", lambda _event: self._close_log_comment_editor(save=False))
        editor.bind("<FocusOut>", lambda _event: self._close_log_comment_editor(save=True))
        editor.focus_set()

    def _close_log_comment_editor(self, save=True):
        editor_info = self._log_comment_editor
        if not editor_info:
            return "break"
        self._log_comment_editor = None
        entry = editor_info["entry"]
        row = editor_info["row"]
        if save:
            self._set_alert_comment(row, entry.get())
        elif self.log.exists(row):
            self._set_alert_comment(row, editor_info["original"])
        entry.destroy()
        return "break"

    def _ensure_manager(self, exchange):
        if exchange in self.ws_managers:
            return
        if exchange in BINANCE_STYLE:
            mgr = ExchangeWSManager(exchange, self._on_depth_update, self._on_status,
                                    on_trade_update=self._on_trade_update)
        elif exchange.startswith("GATE"):
            mgr = GateWSManager(self._on_depth_update, self._on_status, exchange=exchange)
        elif exchange.startswith("OKX"):
            mgr = OKXWSManager(self._on_depth_update, self._on_status, exchange=exchange)
        elif exchange in REST_POLLING_EXCHANGES:
            mgr = RestPollingManager(exchange, self._on_depth_update, self._on_status)
        else:
            return
        self._update_conn_label(exchange, "connecting")
        mgr.start()
        self.ws_managers[exchange] = mgr

    def _validator_for(self, exchange):
        if exchange in BINANCE_STYLE:
            return lambda s: binance_style_validate(exchange, s)
        if exchange.startswith("GATE"):
            return lambda s: gate_validate_symbol(s, exchange=exchange)
        if exchange.startswith("OKX"):
            return lambda s: okx_validate_symbol(s, exchange=exchange)
        if exchange in REST_POLLING_EXCHANGES:
            return lambda s: validate_rest_symbol(exchange, s)
        return lambda s: True

    def _validate_and_subscribe(self, exchange, symbol):
        if not self._validator_for(exchange)(symbol):
            self.event_queue.put(("STATUS", f"⚠ {exchange}:{symbol} не найден — проверь тикер"))
            return
        mgr = self.ws_managers.get(exchange)
        if mgr:
            mgr.subscribe_symbol(symbol)
        if exchange in BINANCE_STYLE:
            self._sync_snapshot(exchange, symbol)
        # GATE/OKX делают бутстрап стакана сами внутри своего менеджера

    def _sync_snapshot(self, exchange, symbol):
        key = f"{exchange}:{symbol}"
        # ВАЖНО (фикс шторма ресинков): раньше ресинк мог запускаться из двух
        # мест одновременно — при первичной подписке (_validate_and_subscribe)
        # и из обработчика разрыва последовательности в _on_depth_update. Два
        # конкурентных REST-запроса гонялись за одним и тем же OrderBook, и
        # более медленный из них перезатирал уже свежее состояние устаревшим —
        # следующий же дифф из WS переставал сходиться -> новый ресинк -> и
        # так по кругу до бесконечности (реально наблюдалось в debug.log, пока
        # биржа не отвечала 429). Плюс раньше при ошибке запроса поток просто
        # молча сдавался — символ навсегда оставался "не синхронизирован", а
        # индикатор при этом продолжал показывать 🟢 подключено. Здесь —
        # защита от дублирования + повтор с бэкоффом вместо тихой сдачи.
        with self._resync_lock:
            if key in self._resyncing:
                return
            self._resyncing.add(key)
        try:
            ob = self.orderbooks.get(key)
            backoff = 1
            while key in self.orderbooks and exchange in self.ws_managers:
                if ob:
                    # помечаем как "не синхронизирован" ДО запроса, а не после —
                    # иначе диффы из WS продолжат как ни в чём не бывало
                    # применяться поверх ещё старого состояния, пока снапшот
                    # летит туда-обратно
                    ob.synced = False
                dlog(f"_sync_snapshot: запрос REST-снапшота для {exchange}:{symbol}")
                try:
                    snap = fetch_depth_snapshot(exchange, symbol)
                    if ob:
                        ob.apply_snapshot(snap)
                        dlog(f"_sync_snapshot: OK для {exchange}:{symbol}, "
                             f"bids={len(ob.bids)} asks={len(ob.asks)} synced={ob.synced}")
                    return
                except Exception as e:
                    dlog(f"_sync_snapshot: ОШИБКА для {exchange}:{symbol}: {e!r}, повтор через {backoff}с")
                    self.event_queue.put(("STATUS", f"Ошибка снапшота {exchange}:{symbol}: {e}. Повтор через {backoff}с"))
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
        finally:
            with self._resync_lock:
                self._resyncing.discard(key)

    # ---------------- старт/стоп ----------------

    def _toggle_start(self):
        if not self.ws_managers:
            exchanges_needed = {self.tree.item(k, "values")[0] for k in self.tree.get_children()}
            for exch in exchanges_needed:
                self._ensure_manager(exch)
            self.start_btn.config(text="■ Стоп", bg="#dc2626")
            for key in list(self.orderbooks.keys()):
                exchange, symbol = key.split(":", 1)
                self.orderbooks[key] = OrderBook(symbol)
                threading.Thread(target=self._wait_and_subscribe,
                                  args=(exchange, symbol), daemon=True).start()
        else:
            for mgr in self.ws_managers.values():
                mgr.stop()
            self.ws_managers = {}
            self.start_btn.config(text="▶ Старт", bg="#16a34a")
            for exch in self.conn_labels:
                self._update_conn_label(exch, "idle")

    def _wait_and_subscribe(self, exchange, symbol):
        mgr = self.ws_managers.get(exchange)
        for _ in range(50):
            if mgr is not None and mgr.loop is not None:
                break
            time.sleep(0.1)
        self._validate_and_subscribe(exchange, symbol)

    # ---------------- колбэки websocket (фоновый поток!) ----------------

    def _on_depth_update(self, exchange, symbol, event):
        key = f"{exchange}:{symbol}"
        ob = self.orderbooks.get(key)
        if not ob:
            dlog(f"_on_depth_update: НЕТ orderbook для {key} (событие пришло, но некуда класть)")
            return

        if not getattr(ob, "_dlog_first_seen", False):
            ob._dlog_first_seen = True
            dlog(f"_on_depth_update: первое событие для {key}, synced_before={ob.synced}")

        if exchange in BINANCE_STYLE:
            ok = ob.apply_diff(event)
            if ok and ob.synced and not getattr(ob, "_dlog_synced_seen", False):
                # логируем именно МОМЕНТ реальной синхронизации (не путать с
                # "первым событием" выше) — без этого зависание в поиске
                # точки старта после снапшота (см. orderbook.py) было не
                # отличить в логе от нормальной работы
                ob._dlog_synced_seen = True
                dlog(f"_on_depth_update: {key} реально синхронизирован")
            if not ok:
                threading.Thread(target=self._sync_snapshot, args=(exchange, symbol), daemon=True).start()
                return
        else:
            if event.get("snapshot"):
                ob.set_snapshot(event["b"], event["a"])
            else:
                if not ob.synced:
                    return
                ob.apply_deltas(event["b"], event["a"])

        if not ob.synced:
            return

        events = self.detector.scan(exchange, symbol, ob)
        for ev in events:
            self._annotate_event_with_trades(ev)
        if self.audit_writer.is_open:
            self._write_audit_for_depth(exchange, symbol, ob, events)

        for ev in events:
            self.event_queue.put(("EVENT", ev))

        live_threshold = self.detector.last_threshold.get(key)
        self.event_queue.put(("BOOK", key, ob.best_bid(), ob.best_ask(),
                               len(self.detector.active_walls.get(key, {})), live_threshold))

        now = time.time()
        if now - self._last_walls_push.get(key, 0) >= WALLS_PUSH_INTERVAL:
            self._last_walls_push[key] = now
            self.event_queue.put(("WALLS", exchange, symbol, self.detector.snapshot(exchange, symbol, ob)))

    def _on_status(self, text):
        self.event_queue.put(("STATUS", text))

    def _on_trade_update(self, exchange, symbol, event):
        if exchange not in TRADE_TAPE_EXCHANGES:
            return
        try:
            trade = self.trade_tape.add_binance_trade(exchange, event)
            if trade and self.audit_writer.is_open:
                self.audit_writer.write_trade(trade)
            cluster = self.trade_tape.find_repeating_print_cluster(
                trade,
                min_count=REPEATING_PRINT_MIN_COUNT,
                window_sec=self.print_window_sec,
                similarity_pct=self.print_similarity_pct,
                min_usd=self.print_min_usd,
                max_usd=self.print_max_usd,
            )
            if cluster:
                self.event_queue.put(("PRINT_CLUSTER", cluster))
        except Exception as e:
            dlog(f"trade tape update error for {exchange}:{symbol}: {e!r}")

    def _annotate_event_with_trades(self, ev):
        if ev.exchange not in TRADE_TAPE_EXCHANGES:
            return
        try:
            self.trade_tape.annotate_wall_event(ev)
        except Exception as e:
            dlog(f"trade event annotation error for {ev.exchange}:{ev.symbol}: {e!r}")

    def _on_market_update(self, tickers):
        # вызывается из фонового потока MarketScanner — как и остальные
        # колбэки, кладём в очередь и обрабатываем в _poll_queue на главном потоке
        self.event_queue.put(("MARKET", tickers))

    def _on_hedgehog_update(self, tickers):
        self.event_queue.put(("HEDGEHOG", tickers))

    def _handle_status_for_conn(self, text):
        """Разбирает текст вида '[Binance] Подключено' и обновляет индикатор
        конкретной биржи. Сообщения не в этом формате (ошибки по конкретному
        символу и т.п.) индикатор не трогают."""
        if not text.startswith("["):
            return
        try:
            label, rest = text[1:].split("]", 1)
        except ValueError:
            return
        exchange = LABEL_TO_EXCHANGE.get(label)
        if not exchange or exchange not in self.conn_labels:
            return
        rest = rest.strip()
        if "Подключено" in rest:
            state = "connected"
        elif "Подключение" in rest:
            state = "connecting"
        elif "Обрыв связи" in rest:
            state = "error"
        elif "Отключено" in rest:
            state = "idle"
        else:
            return
        self._update_conn_label(exchange, state)

    def _update_conn_label(self, exchange, state):
        icon, color, text = CONN_STATE_DISPLAY.get(state, CONN_STATE_DISPLAY["idle"])
        lbl = self.conn_labels.get(exchange)
        if lbl:
            short = EXCHANGE_SHORT_LABELS.get(exchange, exchange)
            lbl.config(text=f"{short}: {icon} {text}", fg=color)

    # ---------------- очередь -> главный поток tkinter ----------------

    def _poll_queue(self):
        try:
            while True:
                item = self.event_queue.get_nowait()
                kind = item[0]
                if kind == "EVENT":
                    self._render_event(item[1])
                elif kind == "AUDIT_ERROR":
                    self._set_audit_ui(False)
                    self.status_var.set(item[1])
                elif kind == "STATUS":
                    self.status_var.set(item[1])
                    self._handle_status_for_conn(item[1])
                elif kind == "BOOK":
                    _, key, bid, ask, walls, live_threshold = item
                    if self.tree.exists(key):
                        vals = list(self.tree.item(key, "values"))
                        vals[4] = _format_compact_usd(live_threshold).replace("$", "") if live_threshold is not None else "прогрев..."
                        vals[6] = f"{bid:.6f}" if bid else "-"
                        vals[7] = f"{ask:.6f}" if ask else "-"
                        vals[8] = walls
                        self.tree.item(key, values=vals)
                elif kind == "WALLS":
                    _, exchange, symbol, snapshot = item
                    self._update_walls_tree(exchange, symbol, snapshot)
                elif kind == "PRINT_CLUSTER":
                    self._render_print_cluster(item[1])
                elif kind == "MARKET":
                    self._update_movers_trees(item[1])
                elif kind == "HEDGEHOG":
                    self._update_hedgehog_tree(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _render_event(self, ev):
        key = f"{ev.exchange}:{ev.symbol}"
        if key in self.muted_keys:
            return  # алерты выключены для этой пары; детекция в фоне продолжается как обычно

        ts = datetime.fromtimestamp(ev.ts).strftime("%H:%M:%S")
        side_ru = self._side_display(ev.side)
        price_str = f"{ev.price:g}" if ev.price else "-"
        symbol_display = self._symbol_display(ev.exchange, ev.symbol)
        iid = f"alert-{self._next_alert_seq}"
        self._next_alert_seq += 1
        self.log.insert("", 0, iid=iid, values=(ts, ev.exchange, symbol_display, side_ru, price_str,
                                                EVENT_LABELS[ev.kind], ev.extra, ""), tags=(ev.kind,))
        self._alert_rows.append(iid)
        self._alert_row_kinds[iid] = ev.kind
        if not self._passes_alert_filter(ev.kind):
            self.log.detach(iid)
        while len(self._alert_rows) > 500:
            old = self._alert_rows.pop(0)
            self._alert_row_kinds.pop(old, None)
            if self.log.exists(old):
                self.log.delete(old)

        if self.sound_enabled.get():
            threading.Thread(target=_play_beep, args=(ev.kind,), daemon=True).start()

    def _render_print_cluster(self, cluster):
        if not hasattr(self, "prints_tree"):
            return
        side = cluster.get("side", "")
        side_ru = "покупки" if side == "buy" else "продажи"
        ts = datetime.fromtimestamp(cluster["last_ts"]).strftime("%H:%M:%S")
        symbol_display = self._symbol_display(cluster["exchange"], cluster["symbol"])
        prices = (f"{cluster['min_price']:g}" if cluster["min_price"] == cluster["max_price"]
                  else f"{cluster['min_price']:g}-{cluster['max_price']:g}")
        span = "подряд" if cluster.get("window_sec", 0) == 0 else f"{cluster['span_sec']:.1f}с"
        print_values = " / ".join(_format_compact_usd(v) for v in cluster.get("print_usd", [])[-6:])
        if len(cluster.get("print_usd", [])) > 6:
            print_values = f"... / {print_values}"
        values = (
            ts,
            cluster["exchange"],
            symbol_display,
            side_ru,
            cluster["count"],
            _format_compact_usd(cluster["avg_usd"]),
            _format_compact_usd(cluster["total_usd"]),
            span,
            f"±{cluster['similarity_pct']:g}%",
            prices,
            print_values,
        )
        iid = cluster["series_id"]
        if self.prints_tree.exists(iid):
            self.prints_tree.item(iid, values=values, tags=(side,))
            self.prints_tree.move(iid, "", 0)
        else:
            self.prints_tree.insert("", 0, iid=iid, values=values, tags=(side,))
        children = self.prints_tree.get_children()
        if len(children) > MAX_PRINT_ROWS:
            self.prints_tree.delete(*children[MAX_PRINT_ROWS:])

    def _set_audit_ui(self, active):
        self.audit_enabled.set(active)
        if hasattr(self, "audit_btn"):
            self.audit_btn.config(
                text="csv",
                bg="#231316" if active else "#0a0a0d",
                fg="#dc6b75" if active else "#343842",
                activebackground="#231316" if active else "#0a0a0d",
                activeforeground="#fca5a5" if active else "#737883",
            )

    def _toggle_audit(self):
        if self.audit_writer.is_open:
            path = self.audit_writer.path
            self.audit_writer.stop()
            self._set_audit_ui(False)
            self.status_var.set(f"Аудит CSV остановлен: {path}")
            return
        try:
            path = self.audit_writer.start()
            self._set_audit_ui(True)
            self.status_var.set(f"Аудит CSV пишет файл: {path}")
        except Exception as e:
            self._set_audit_ui(False)
            messagebox.showerror("Аудит CSV", f"Не удалось начать запись:\n{e}")

    def _write_audit_for_depth(self, exchange, symbol, orderbook, events):
        try:
            for ev in events:
                self.audit_writer.write_event(ev)
            snapshot = self.detector.snapshot(exchange, symbol, orderbook)
            self.audit_writer.write_snapshot(exchange, symbol, snapshot)
        except Exception as e:
            dlog(f"audit csv write error: {e!r}")
            try:
                self.audit_writer.stop()
            finally:
                self.event_queue.put(("AUDIT_ERROR", f"Аудит CSV остановлен из-за ошибки записи: {e}"))

    def _update_walls_tree(self, exchange, symbol, snapshot):
        key = f"{exchange}:{symbol}"
        desired_iids = {f"{key}|{w['price']}" for w in snapshot}
        # снимаем только те строки ЭТОГО символа, которых больше нет в
        # снапшоте (плотность исчезла) — существующие НЕ трогаем, чтобы не
        # сбивать их позицию в таблице
        for iid in [i for i in self.walls_tree.get_children() if i.startswith(f"{key}|")]:
            if iid not in desired_iids:
                self.walls_tree.delete(iid)
                self._wall_row_seq.pop(iid, None)

        for w in snapshot:
            iid = f"{key}|{w['price']}"
            side_ru = self._side_display(w["side"])
            if w.get("near_spread"):
                side_ru = f"{side_ru}/у спреда"
            values = (exchange, symbol, side_ru, f"{w['price']:g}", _format_compact_usd(w["usd"]),
                      format_age(w["age"]), f"{w['dist_pct']:.2f}%")
            if self.walls_tree.exists(iid):
                self.walls_tree.item(iid, values=values, tags=(w["side"],))
            else:
                self.walls_tree.insert("", "end", iid=iid, values=values, tags=(w["side"],))
                self._wall_row_seq[iid] = self._next_wall_seq
                self._next_wall_seq += 1

        # стабильный порядок по очерёдности обнаружения (кто раньше нашёлся —
        # тот выше) — без этого строки "прыгали" бы по таблице при каждом
        # обновлении ЛЮБОГО другого отслеживаемого символа
        ordered = sorted(self.walls_tree.get_children(), key=lambda i: self._wall_row_seq.get(i, 0))
        for index, iid in enumerate(ordered):
            self.walls_tree.move(iid, "", index)

    # ---------------- топ движений рынка ----------------

    def _update_movers_trees(self, tickers):
        # "Топ движений" показывает только MARKET_TOP_EXCHANGES (набор Codex,
        # без spot и без MEXC/BYBIT). market_scanner при этом опрашивает шире
        # (MARKET_SCAN_EXCHANGES: +MEXC +BYBIT) — эти данные нужны вкладке
        # "Ранние", которой ниже передаётся ПОЛНЫЙ батч. MEXC мусорит микрокапами
        # в топах, а BYBIT исключён из "Топ движений" по решению Codex.
        movers = [t for t in tickers if t.get("exchange") in MARKET_TOP_EXCHANGES]
        gainers, losers = MarketScanner.top_movers(movers, n=MARKET_TOP_N)
        self._fill_movers_tree(self.gainers_tree, gainers, "up")
        self._fill_movers_tree(self.losers_tree, losers, "down")
        # импульс — по тому же набору, что и таблицы: монета может дать импульс
        # за 3 мин, не будучи в топ-20 за сутки
        self._check_impulse_alerts(movers)
        self._update_early_tree(tickers)

    def _fill_movers_tree(self, tree, rows, default_tag):
        tree.delete(*tree.get_children())
        for r in rows:
            key = f"{r['exchange']}:{r['symbol']}"
            impulse = r.get("impulse_pct", 0.0)
            impulse_str = f"{impulse:+.2f}%"
            if abs(impulse) >= self.impulse_threshold_pct:
                impulse_str = f"⚡ {impulse_str}"
                tag = "impulse"
            else:
                tag = default_tag
            tree.insert("", "end", iid=key, values=(
                r["exchange"], r["symbol"], f"{r['last']:g}",
                f"{r['change_pct_24h']:+.2f}%", impulse_str,
                _format_compact_usd(r["quote_volume"]),
            ), tags=(tag,))

    # ---------------- настройка/алерты импульса ----------------

    def _impulse_column_title(self):
        w = self.impulse_window_sec
        return f"Импульс {int(w / 60)}м" if w >= 60 else f"Импульс {int(w)}с"

    def _update_movers_hint(self):
        self.movers_hint_var.set(
            f"Обновляется раз в {int(MARKET_POLL_INTERVAL_SEC)}с. "
            f"⚡ = импульс {self.impulse_threshold_pct:g}%+ за {self._impulse_column_title().split(' ', 1)[1]}. "
            "Двойной клик — добавить в сканер (режим AUTO)."
        )

    def _apply_impulse_settings(self):
        try:
            threshold = float(self.impulse_threshold_entry.get().replace(",", "."))
            window_sec = float(self.impulse_window_entry.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Ошибка", "Порог и окно должны быть числами")
            return
        if not (IMPULSE_THRESHOLD_MIN_PCT <= threshold <= IMPULSE_THRESHOLD_MAX_PCT):
            messagebox.showerror("Ошибка", f"Порог должен быть от {IMPULSE_THRESHOLD_MIN_PCT:g} "
                                            f"до {IMPULSE_THRESHOLD_MAX_PCT:g} %")
            return
        if not (IMPULSE_WINDOW_MIN_SEC <= window_sec <= IMPULSE_WINDOW_MAX_SEC):
            messagebox.showerror("Ошибка", f"Окно должно быть от {IMPULSE_WINDOW_MIN_SEC:g} "
                                            f"до {IMPULSE_WINDOW_MAX_SEC:g} сек")
            return
        self.impulse_threshold_pct = threshold
        self.impulse_window_sec = window_sec
        self.market_scanner.impulse_window_sec = window_sec
        self._impulse_above.clear()  # порог/окно сменились — забываем прежнее состояние "выше/ниже"
        title = self._impulse_column_title()
        self.gainers_tree.heading("impulse", text=title)
        self.losers_tree.heading("impulse", text=title)
        self._update_movers_hint()
        self._save_impulse_settings()
        self.status_var.set(f"Импульс: порог {threshold:g}%, окно {int(window_sec)}с — применено")

    def _load_impulse_settings(self):
        if not os.path.exists(IMPULSE_SETTINGS_FILE):
            return
        try:
            with open(IMPULSE_SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            self.impulse_threshold_pct = float(data.get("threshold_pct", self.impulse_threshold_pct))
            self.impulse_window_sec = float(data.get("window_sec", self.impulse_window_sec))
            self.impulse_popup_enabled.set(bool(data.get("popup_enabled", True)))
            self.impulse_sound_enabled.set(bool(data.get("sound_enabled", True)))
        except Exception:
            pass

    def _save_impulse_settings(self):
        data = {
            "threshold_pct": self.impulse_threshold_pct,
            "window_sec": self.impulse_window_sec,
            "popup_enabled": self.impulse_popup_enabled.get(),
            "sound_enabled": self.impulse_sound_enabled.get(),
        }
        try:
            with open(IMPULSE_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _apply_print_settings(self):
        try:
            min_raw = self.print_min_usd_entry.get().strip()
            max_raw = self.print_max_usd_entry.get().strip()
            min_usd = _parse_decimal(min_raw) if min_raw else 0.0
            max_usd = _parse_decimal(max_raw) if max_raw else None
            window_sec = _parse_decimal(self.print_window_entry.get())
            similarity_pct = _parse_decimal(self.print_similarity_entry.get())
        except ValueError:
            messagebox.showerror("Повторяющиеся принты", "Объём, окно и похожесть должны быть числами")
            return
        if min_usd < 0:
            messagebox.showerror("Повторяющиеся принты", "«От $» не может быть меньше 0")
            return
        if max_usd is not None and max_usd <= min_usd:
            messagebox.showerror("Повторяющиеся принты", "«До $» должно быть больше «От $»")
            return
        if window_sec < 0:
            messagebox.showerror("Повторяющиеся принты", "Окно не может быть меньше 0 секунд")
            return
        if similarity_pct < 0:
            messagebox.showerror("Повторяющиеся принты", "Похожесть не может быть меньше 0%")
            return
        self.print_min_usd = min_usd
        self.print_max_usd = max_usd
        self.print_window_sec = window_sec
        self.print_similarity_pct = similarity_pct
        self.print_min_usd_entry.delete(0, "end")
        self.print_min_usd_entry.insert(0, f"{self.print_min_usd:g}")
        self.print_max_usd_entry.delete(0, "end")
        self.print_max_usd_entry.insert(0, "" if self.print_max_usd is None else f"{self.print_max_usd:g}")
        self.print_window_entry.delete(0, "end")
        self.print_window_entry.insert(0, f"{self.print_window_sec:g}")
        self.print_similarity_entry.delete(0, "end")
        self.print_similarity_entry.insert(0, f"{self.print_similarity_pct:g}")
        self._save_print_settings()
        volume_text = f"от {_format_compact_usd(min_usd)}" + (
            f" до {_format_compact_usd(max_usd)}" if max_usd is not None else " и выше"
        )
        self.status_var.set(
            f"Повторяющиеся принты: {volume_text}, минимум {REPEATING_PRINT_MIN_COUNT}, "
            f"окно {window_sec:g}с, похожесть ±{similarity_pct:g}%"
        )

    def _load_print_settings(self):
        if not os.path.exists(PRINT_SETTINGS_FILE):
            return
        try:
            with open(PRINT_SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            self.print_min_usd = max(0.0, float(data.get("min_usd", self.print_min_usd)))
            raw_max_usd = data.get("max_usd", self.print_max_usd)
            if raw_max_usd is None:
                self.print_max_usd = None
            else:
                raw_max_usd = float(raw_max_usd)
                self.print_max_usd = raw_max_usd if raw_max_usd > self.print_min_usd else None
            self.print_window_sec = max(0.0, float(data.get("window_sec", self.print_window_sec)))
            self.print_similarity_pct = max(0.0, float(data.get("similarity_pct", self.print_similarity_pct)))
        except Exception:
            pass

    def _save_print_settings(self):
        data = {
            "min_usd": self.print_min_usd,
            "max_usd": self.print_max_usd,
            "window_sec": self.print_window_sec,
            "similarity_pct": self.print_similarity_pct,
            "min_count": REPEATING_PRINT_MIN_COUNT,
        }
        try:
            with open(PRINT_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _check_impulse_alerts(self, tickers):
        """Edge-триггер: алерт только на ПЕРЕСЕЧЕНИЕ порога, не на каждый тик
        поверх него — иначе один и тот же импульс спамил бы тост каждые 15с,
        пока держится выше порога. Повторно сработает, только если сначала
        опустится ниже порога и снова его пересечёт (как антиспуф в detector.py)."""
        threshold = self.impulse_threshold_pct
        new_above = {}
        for t in tickers:
            key = f"{t['exchange']}:{t['symbol']}"
            impulse = t.get("impulse_pct", 0.0)
            above = abs(impulse) >= threshold
            new_above[key] = above
            if above and not self._impulse_above.get(key, False):
                self._fire_impulse_alert(t, impulse)
        self._impulse_above = new_above  # заодно вычищает делистнутые/пропавшие символы

    def _fire_impulse_alert(self, ticker, impulse):
        if self.impulse_popup_enabled.get():
            self._show_impulse_toast(ticker, impulse)
        if self.impulse_sound_enabled.get():
            threading.Thread(target=_play_beep, args=("IMPULSE",), daemon=True).start()

    def _show_impulse_toast(self, ticker, impulse):
        """Всплывающее окно без рамки, поверх всех окон, у правого нижнего
        угла ЭКРАНА (не окна приложения) — чтобы было видно независимо от
        того, какая вкладка сейчас открыта. Клик — переходит на вкладку
        "Топ движений" и копирует тикер в буфер (как двойной клик в таблицах)."""
        key = f"{ticker['exchange']}:{ticker['symbol']}"
        up = impulse > 0
        color = SIDE_COLOR["bid"] if up else SIDE_COLOR["ask"]
        arrow = "🚀" if up else "📉"

        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=color)
        inner = tk.Frame(toast, bg="#1f1f24")
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        tk.Label(inner, text=f"{arrow} Импульс {impulse:+.2f}%", bg="#1f1f24", fg=color,
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(inner, text=f"{ticker['exchange']}  {ticker['symbol']}   {ticker['last']:g}",
                 bg="#1f1f24", fg="white", font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        def _on_click(_event=None):
            self._go_to_movers_tab(key)
            self._remove_impulse_toast(toast)

        toast.bind("<Button-1>", _on_click)
        for w in (inner, *inner.winfo_children()):
            w.bind("<Button-1>", _on_click)

        self._active_impulse_toasts.append(toast)
        self._reposition_impulse_toasts()
        toast.after(IMPULSE_TOAST_MS, lambda: self._remove_impulse_toast(toast))

    def _reposition_impulse_toasts(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        margin = 12
        y = sh - margin
        for toast in reversed(self._active_impulse_toasts):
            if not toast.winfo_exists():
                continue
            y -= IMPULSE_TOAST_H + 8
            toast.geometry(f"{IMPULSE_TOAST_W}x{IMPULSE_TOAST_H}+{sw - IMPULSE_TOAST_W - margin}+{y}")

    def _remove_impulse_toast(self, toast):
        if toast in self._active_impulse_toasts:
            self._active_impulse_toasts.remove(toast)
        if toast.winfo_exists():
            toast.destroy()
        self._reposition_impulse_toasts()

    def _go_to_movers_tab(self, key):
        self.notebook.select(1)  # 0=Сканер плотностей, 1=Топ движений, 2=Ерши
        exchange, symbol = key.split(":", 1)
        self.root.clipboard_clear()
        self.root.clipboard_append(symbol)
        self.status_var.set(f"Импульс: перешли на «Топ движений», {symbol} скопирован в буфер")

    def _on_mover_double_click(self, event):
        tree = event.widget
        sel = tree.selection()
        if not sel:
            return
        key = sel[0]
        exchange, symbol = key.split(":", 1)
        # добавляем через тот же путь, что кнопка "Добавить" — заполняем поля
        # и вызываем _add_symbol(), чтобы не дублировать валидацию/подписку
        self.exchange_combo.set(exchange)
        self.symbol_entry.delete(0, "end")
        self.symbol_entry.insert(0, symbol)
        self.mode_combo.set("AUTO")
        self.volume_preset_combo.set("Вручную")
        self.threshold_entry.delete(0, "end")
        self.threshold_entry.insert(0, str(MOVER_ADD_DEFAULT_FLOOR))
        self.threshold_max_entry.delete(0, "end")
        self.max_distance_entry.delete(0, "end")
        self.max_distance_entry.insert(0, str(DEFAULT_MAX_DISTANCE_PCT))
        self.single_confirm_entry.delete(0, "end")
        self.single_confirm_entry.insert(0, str(DEFAULT_SINGLE_CONFIRM_SEC))
        self._add_symbol()
        self.root.clipboard_clear()
        self.root.clipboard_append(symbol)
        self.status_var.set(f"Добавлено в сканер (AUTO) и скопировано в буфер: {exchange}:{symbol}")
        self.notebook.select(0)

    # ---------------- ранние кандидаты (живая тишина) ----------------

    def _update_early_tree(self, tickers):
        candidates = MarketScanner.early_candidates(
            tickers, exchange="MEXC SPOT",
            exclude_majors=self.early_exclusive_only.get(),
            binance_spot_symbols=self.market_scanner.binance_spot_symbols)
        warming = not any(t.get("early_ready") for t in tickers if t.get("exchange") == "MEXC SPOT")

        self.early_tree.delete(*self.early_tree.get_children())
        for c in candidates:
            # самые сжатые (ближе к нижней границе диапазона) — подсвечиваем
            tight = c["range_60m"] <= (EARLY_RANGE_MIN_PCT + EARLY_RANGE_MAX_PCT) / 2
            also = ", ".join(c.get("also_on") or []) or "— только MEXC"

            # OI: прочерк для спотовых без фьючерса; растущий OI — отдельная подсветка
            oi_change = c.get("oi_change_pct", 0.0)
            if c.get("has_oi"):
                oi_str = f"${c['oi_usd']:,.0f}"
                oi_chg_str = f"{oi_change:+.0f}%"
            else:
                oi_str = "—"
                oi_chg_str = "—"
            rising = c.get("has_oi") and oi_change >= OI_RISE_HIGHLIGHT_PCT
            tag = "oi_rising" if rising else ("tight" if tight else "normal")

            self.early_tree.insert("", "end", iid=c["symbol"], values=(
                c["symbol"], f"{c['last']:g}", f"{c['range_60m']:.1f}%",
                f"${c['vol_60m']:,.0f}", f"{c['vol_accel']:.2f}x",
                f"{c['change_pct_24h']:+.1f}%", oi_str, oi_chg_str, also,
            ), tags=(tag,))

        symbols = [c["symbol"] for c in candidates]
        # вотч-лист рекордера идёт следом за таблицей: пишем стаканы ровно по
        # тем монетам, которые сейчас в профиле
        self.depth_recorder.set_watchlist(symbols)

        if warming:
            self.early_status_var.set("прогрев: копится час истории...")
        else:
            self.early_status_var.set(
                f"кандидатов: {len(symbols)} | снимков стакана записано: "
                f"{self.depth_recorder.snapshots_written:,}")

        if not warming:
            self._check_early_alerts(symbols)

    def _check_early_alerts(self, symbols):
        """Алерт на монету, которая ВОШЛА в профиль и удержалась в нём
        EARLY_CONFIRM_TICKS сканов подряд. Без этой выдержки монеты, болтающиеся
        на границе порога, моргали бы алертом каждые 15 секунд."""
        current = set(symbols)
        for symbol in list(self._early_streak):
            if symbol not in current:
                del self._early_streak[symbol]  # выпала из профиля — счётчик сбрасывается

        if not self.early_alerts_enabled.get():
            for symbol in current:
                self._early_streak[symbol] = self._early_streak.get(symbol, 0) + 1
            return

        now = time.time()
        for symbol in symbols:
            streak = self._early_streak.get(symbol, 0) + 1
            self._early_streak[symbol] = streak
            if streak != EARLY_CONFIRM_TICKS:
                continue  # ровно на подтверждающем тике, дальше молчим
            if now - self._early_alerted.get(symbol, 0) < EARLY_REALERT_SEC:
                continue
            self._early_alerted[symbol] = now
            self._show_early_toast(symbol)
            if self.impulse_sound_enabled.get():
                threading.Thread(target=_play_beep, args=("WALL",), daemon=True).start()

    def _show_early_toast(self, symbol):
        """Всплывашка про нового кандидата. Отдельный вид от импульсной — тут
        не «уже летит», а «встало в профиль, стоит посмотреть стакан»."""
        row = None
        if self.early_tree.exists(symbol):
            row = self.early_tree.item(symbol, "values")

        color = EVENT_COLORS["CASCADE"]
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=color)
        inner = tk.Frame(toast, bg="#1f1f24")
        inner.pack(fill="both", expand=True, padx=2, pady=2)
        tk.Label(inner, text=f"🎯 Ранний кандидат  MEXC", bg="#1f1f24", fg=color,
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        detail = f"{symbol}"
        if row:
            detail += f"   диап. {row[2]}  объём {row[3]}"
        tk.Label(inner, text=detail, bg="#1f1f24", fg="white",
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        def _on_click(_event=None):
            self.notebook.select(3)  # вкладка "🎯 Ранние"
            self.root.clipboard_clear()
            self.root.clipboard_append(symbol)
            self.status_var.set(f"Ранний кандидат: {symbol} скопирован в буфер")
            self._remove_impulse_toast(toast)

        toast.bind("<Button-1>", _on_click)
        for w in (inner, *inner.winfo_children()):
            w.bind("<Button-1>", _on_click)

        self._active_impulse_toasts.append(toast)
        self._reposition_impulse_toasts()
        toast.after(IMPULSE_TOAST_MS, lambda: self._remove_impulse_toast(toast))

    def _update_hedgehog_tree(self, tickers):
        candidates = MarketScanner.hedgehog_candidates(tickers, n=30)
        self.hedgehog_tree.delete(*self.hedgehog_tree.get_children())
        for c in candidates:
            key = f"{c['exchange']}:{c['symbol']}"
            self.hedgehog_tree.insert("", "end", iid=key, values=(
                c["exchange"], c["symbol"], f"{c['last']:g}",
                f"{c['hh_range_pct']:.2f}%",
                f"{c['hh_touch_top']:.2f}", f"{c['hh_touch_bot']:.2f}",
                _format_compact_usd(c["vol_60m"]), _format_compact_usd(c["vol_10m"]),
            ))

    # ---------------- сохранение конфига ----------------

    def _build_config_data(self):
        """Собирает текущий список монет из таблицы в список dict — общий
        источник и для обычного автосохранения (_save_config), и для
        экспорта в произвольный файл (_export_config)."""
        data = []
        for key in self.tree.get_children():
            vals = self.tree.item(key, "values")
            tmax_raw = vals[10] if len(vals) > 10 else "-"
            threshold_max = None
            if tmax_raw not in ("-", ""):
                try:
                    threshold_max = _parse_compact_usd(tmax_raw)
                except ValueError:
                    threshold_max = None
            dist_raw = vals[11] if len(vals) > 11 else DEFAULT_MAX_DISTANCE_PCT
            try:
                max_distance_pct = _normalize_distance_pct(dist_raw)
            except (ValueError, TypeError):
                max_distance_pct = DEFAULT_MAX_DISTANCE_PCT
            life_raw = vals[12] if len(vals) > 12 else DEFAULT_SINGLE_CONFIRM_SEC
            try:
                single_confirm_sec = _normalize_single_confirm_sec(life_raw)
            except (ValueError, TypeError):
                single_confirm_sec = DEFAULT_SINGLE_CONFIRM_SEC
            data.append({
                "exchange": vals[0],
                "symbol": vals[1],
                "mode": vals[2],
                "threshold": float(_parse_compact_usd(vals[3]) or 0.0),
                "threshold_max": threshold_max,
                "direction": "BOTH",
                "muted": key in self.muted_keys,
                "max_distance_pct": max_distance_pct,
                "single_confirm_sec": single_confirm_sec,
            })
        return data

    def _apply_config_data(self, data):
        """Добавляет монеты из списка dict (тот же формат, что и в
        config.json) через обычный _add_symbol — общий код для загрузки при
        старте (_load_config) и для импорта из произвольного файла
        (_import_config). ДОБАВЛЯЕТ к уже имеющимся, не стирает их —
        существующие монеты (тот же ключ биржа:символ) просто обновятся."""
        count = 0
        for item in data:
            try:
                for exchange in self._config_targets_for_exchange(item.get("exchange", "BINANCE")):
                    self._add_symbol(item["symbol"], item["threshold"], item["direction"],
                                      exchange=exchange,
                                      mode=item.get("mode", "FIXED"),
                                      muted=item.get("muted", False), silent=True,
                                      threshold_max=item.get("threshold_max"),
                                      max_distance_pct=item.get("max_distance_pct"),
                                      single_confirm_sec=item.get("single_confirm_sec"),
                                      exact_exchange=True)
                    count += 1
            except Exception:
                continue
        return count

    def _save_config(self):
        data = self._build_config_data()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            self._apply_config_data(data)
        except Exception:
            pass

    def _export_config(self):
        """Сохраняет текущий список монет в выбранный пользователем файл —
        чтобы перенести настройки со старой версии приложения на новую
        (config.json внутри exe не переживает пересборку/переустановку)."""
        path = filedialog.asksaveasfilename(
            title="Экспорт конфига сканера",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
            initialfile="wall_scanner_config.json",
        )
        if not path:
            return
        try:
            data = self._build_config_data()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Экспорт", f"Сохранено {len(data)} монет(ы) в:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка экспорта", str(e))

    def _import_config(self):
        """Загружает список монет из ранее экспортированного файла и
        добавляет их к текущему списку (не стирая уже имеющееся)."""
        path = filedialog.askopenfilename(
            title="Импорт конфига сканера",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("файл должен содержать список монет (как в config.json)")
            count = self._apply_config_data(data)
            messagebox.showinfo("Импорт", f"Добавлено/обновлено {count} из {len(data)} монет(ы).")
        except Exception as e:
            messagebox.showerror("Ошибка импорта", f"Не удалось прочитать файл:\n{e}")

    def _on_close(self):
        self.audit_writer.stop()
        for mgr in self.ws_managers.values():
            mgr.stop()
        self.market_scanner.stop()
        self.hedgehog_scanner.stop()
        self.depth_recorder.stop()
        self._save_config()
        self._save_impulse_settings()
        self._save_print_settings()
        self.root.destroy()
