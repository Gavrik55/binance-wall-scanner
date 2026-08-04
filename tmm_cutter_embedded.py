import os, time, json, threading, sqlite3, requests, subprocess, sys, shutil, csv, traceback, queue
import base64, ctypes, hashlib
import html, mimetypes, re, secrets, socket
import importlib.util
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

# --- НАЧАЛО БЛОКА МОСТА ---
# Умный поиск: внешний custom_logic.py рядом с EXE имеет приоритет, затем встроенная копия из one-file сборки.
def get_custom_logic_candidates():
    app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(app_dir, "custom_logic.py")]
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", app_dir), "custom_logic.py"))
    return candidates

def load_custom_logic():
    for plugin_path in get_custom_logic_candidates():
        if not os.path.exists(plugin_path):
            continue
        try:
            spec = importlib.util.spec_from_file_location("custom_logic", plugin_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            print(f"Ошибка плагина {plugin_path}: {e}")
    return None

CUSTOM_LOGIC = load_custom_logic()
# --- КОНЕЦ БЛОКА МОСТА ---

# ====================== ПУТИ ======================
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
LEGACY_CONFIG_PATH = os.path.join(APP_DIR, "config.json")
VENDOR_PACKAGES_DIR = os.path.join(APP_DIR, "vendor", "tkinterdnd2_pkg")
if os.path.isdir(VENDOR_PACKAGES_DIR) and VENDOR_PACKAGES_DIR not in sys.path:
    sys.path.insert(0, VENDOR_PACKAGES_DIR)

try:
    from tkinterdnd2 import COPY as DND_COPY, DND_FILES, Tk as DND_TK_ROOT
except Exception:
    DND_COPY = "copy"
    DND_FILES = None
    DND_TK_ROOT = None

def _default_data_dir():
    override = os.environ.get("TMM_CUTTER_DATA_DIR")
    if override:
        return os.path.abspath(override)
    if getattr(sys, "frozen", False) and not os.path.exists(LEGACY_CONFIG_PATH):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "TMM Video Cutter")
    return APP_DIR

def _default_output_dir():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desktop):
        return os.path.join(desktop, "Видео сделок")
    return os.path.join(BASE_DIR, "output")

def resource_path(*parts):
    return os.path.join(RESOURCE_DIR, *parts)

APP_ICON_PATH = resource_path("assets", "tmm_cutter_icon.ico")
APP_ICON_PNG_PATH = resource_path("assets", "tmm_cutter_icon.png")

def apply_window_icon(window):
    if os.path.exists(APP_ICON_PNG_PATH):
        try:
            icon_image = tk.PhotoImage(file=APP_ICON_PNG_PATH)
            window.iconphoto(True, icon_image)
            window._tmm_icon_image = icon_image
        except Exception:
            pass
    try:
        if os.path.exists(APP_ICON_PATH):
            window.iconbitmap(default=APP_ICON_PATH)
    except Exception:
        try:
            if os.path.exists(APP_ICON_PATH):
                window.iconbitmap(APP_ICON_PATH)
        except Exception:
            pass

def configure_windows_app_identity():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TMM.VideoCutter")
    except Exception:
        pass

def get_ffmpeg_path():
    candidates = [
        os.environ.get("TMM_CUTTER_FFMPEG_PATH"),
        resource_path("ffmpeg.exe"),
        os.path.join(APP_DIR, "ffmpeg.exe"),
        os.path.join(BASE_DIR, "ffmpeg.exe"),
        shutil.which("ffmpeg"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""

BASE_DIR = _default_data_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = os.path.join(BASE_DIR, "data.db")
TRADES_CACHE_PATH = os.path.join(BASE_DIR, "trades_cache.json")
LOG_PATH = os.path.join(BASE_DIR, "app.log")
CUT_VIDEOS_DIR = _default_output_dir()
DEVINFO_PATH = os.path.join(BASE_DIR, "dev_info.txt")
QUARANTINE_DIR = os.path.join(BASE_DIR, "quarantine")
def _find_runtime_dir(marker_file, *candidates):
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, marker_file)):
            return candidate
    return ""


TCL_RUNTIME_DIR = _find_runtime_dir(
    "init.tcl",
    os.path.join(RESOURCE_DIR, "runtime", "tcl8.6"),
    os.path.join(RESOURCE_DIR, "_tcl_data"),
)
TK_RUNTIME_DIR = _find_runtime_dir(
    "tk.tcl",
    os.path.join(RESOURCE_DIR, "runtime", "tk8.6"),
    os.path.join(RESOURCE_DIR, "_tk_data"),
)
if TCL_RUNTIME_DIR:
    os.environ["TCL_LIBRARY"] = TCL_RUNTIME_DIR
if TK_RUNTIME_DIR:
    os.environ["TK_LIBRARY"] = TK_RUNTIME_DIR
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(CUT_VIDEOS_DIR, exist_ok=True)

# ====================== ЦВЕТА ======================
COLORS = {
    "bg": "#1a1b2e", "panel": "#222440", "panel_border": "#2d2f48",
    "accent": "#5b9bd5", "accent_hover": "#7ab8e8",
    "success": "#4caf84", "warning": "#d4a843", "error": "#d35a5a",
    "text": "#c8cdd0", "text_dim": "#7a7e8a", "entry_bg": "#1e2038",
    "log_info": "#c8cdd0", "log_warn": "#d4a843", "log_error": "#d35a5a"
}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".ts"}

# ====================== WINDOWS DRAG-AND-DROP ======================
CF_HDROP = 15
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
DROPEFFECT_COPY = 1
S_OK = 0
E_NOINTERFACE = -2147467262
E_FAIL = -2147467259


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value):
        import uuid
        raw = uuid.UUID(value).bytes_le
        guid = cls()
        ctypes.memmove(ctypes.byref(guid), raw, ctypes.sizeof(guid))
        return guid


IID_IUNKNOWN = GUID.from_string("00000000-0000-0000-c000-000000000046")
IID_IDROPTARGET = GUID.from_string("00000122-0000-0000-c000-000000000046")


class POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", ctypes.c_ushort),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", ctypes.c_ulong),
        ("lindex", ctypes.c_long),
        ("tymed", ctypes.c_ulong),
    ]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", ctypes.c_ulong),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


class COMObject(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(ctypes.c_void_p))]


def _guid_equal(left, right):
    return ctypes.string_at(left, ctypes.sizeof(GUID)) == ctypes.string_at(ctypes.byref(right), ctypes.sizeof(GUID))


class WindowsFileDropTarget:
    """OLE drop target for files. Avoids subclassing Tk's WndProc, which can crash one-file builds."""

    QueryInterfaceProto = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
    )
    AddRefProto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    ReleaseProto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    DragEnterProto = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, POINTL, ctypes.POINTER(wintypes.DWORD)
    )
    DragOverProto = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, wintypes.DWORD, POINTL, ctypes.POINTER(wintypes.DWORD)
    )
    DragLeaveProto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
    DropProto = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, POINTL, ctypes.POINTER(wintypes.DWORD)
    )
    GetDataProto = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM)
    )

    def __init__(self, on_files):
        self.on_files = on_files
        self.ref_count = 1
        self._callbacks = [
            self.QueryInterfaceProto(self._query_interface),
            self.AddRefProto(self._add_ref),
            self.ReleaseProto(self._release),
            self.DragEnterProto(self._drag_enter),
            self.DragOverProto(self._drag_over),
            self.DragLeaveProto(self._drag_leave),
            self.DropProto(self._drop),
        ]
        self._vtable = (ctypes.c_void_p * len(self._callbacks))(
            *[ctypes.cast(callback, ctypes.c_void_p).value for callback in self._callbacks]
        )
        self._object = COMObject(ctypes.cast(self._vtable, ctypes.POINTER(ctypes.c_void_p)))
        self.pointer = ctypes.cast(ctypes.pointer(self._object), ctypes.c_void_p)

    def _query_interface(self, _this, riid, ppv):
        try:
            if _guid_equal(riid, IID_IUNKNOWN) or _guid_equal(riid, IID_IDROPTARGET):
                ppv[0] = self.pointer.value
                self._add_ref(_this)
                return S_OK
            ppv[0] = None
            return E_NOINTERFACE
        except Exception as error:
            log_to_file("ERROR", f"Drag-and-drop QueryInterface failed: {error}")
            return E_FAIL

    def _add_ref(self, _this):
        self.ref_count += 1
        return self.ref_count

    def _release(self, _this):
        self.ref_count = max(1, self.ref_count - 1)
        return self.ref_count

    def _set_copy_effect(self, effect):
        if effect:
            effect[0] = DROPEFFECT_COPY

    def _drag_enter(self, _this, _data_object, _key_state, _point, effect):
        self._set_copy_effect(effect)
        return S_OK

    def _drag_over(self, _this, _key_state, _point, effect):
        self._set_copy_effect(effect)
        return S_OK

    def _drag_leave(self, _this):
        return S_OK

    def _drop(self, _this, data_object, _key_state, _point, effect):
        try:
            self._set_copy_effect(effect)
            files = self._extract_files(data_object)
            if files:
                self.on_files(files)
            return S_OK
        except Exception as error:
            log_to_file("ERROR", f"Drag-and-drop Drop failed: {error}\n{traceback.format_exc()}")
            return E_FAIL

    def _extract_files(self, data_object):
        if not data_object:
            return []
        fmt = FORMATETC(CF_HDROP, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL)
        medium = STGMEDIUM()
        data_vtable = ctypes.cast(data_object, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_data = self.GetDataProto(data_vtable[3])
        hr = get_data(data_object, ctypes.byref(fmt), ctypes.byref(medium))
        if hr != S_OK or not medium.hGlobal:
            return []
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragQueryFileW.restype = wintypes.UINT
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.ReleaseStgMedium.argtypes = [ctypes.POINTER(STGMEDIUM)]
        files = []
        try:
            handle = wintypes.HANDLE(medium.hGlobal)
            count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            for index in range(count):
                length = shell32.DragQueryFileW(handle, index, None, 0)
                if not length:
                    continue
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(handle, index, buffer, length + 1)
                files.append(buffer.value)
            return files
        finally:
            ole32.ReleaseStgMedium(ctypes.byref(medium))

    def register(self, hwnd):
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.RegisterDragDrop.argtypes = [wintypes.HWND, ctypes.c_void_p]
        ole32.RegisterDragDrop.restype = ctypes.c_long
        hr = ole32.RegisterDragDrop(wintypes.HWND(hwnd), self.pointer)
        if hr not in (S_OK,):
            raise OSError(f"RegisterDragDrop failed: 0x{hr & 0xFFFFFFFF:08X}")

    @staticmethod
    def revoke(hwnd):
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.RevokeDragDrop.argtypes = [wintypes.HWND]
        ole32.RevokeDragDrop.restype = ctypes.c_long
        ole32.RevokeDragDrop(wintypes.HWND(hwnd))

# ====================== ЛОГИРОВАНИЕ ======================
LOG_LEVELS = {"INFO": "[INFO]", "WARN": "[WARN]", "ERROR": "[ERROR]"}
LOG_LOCK = threading.Lock()
def log_to_file(level, msg):
    try:
        with LOG_LOCK:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {LOG_LEVELS.get(level, '[INFO]')} {msg}\n")
    except: pass

def write_diagnostic_trace(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    for path in (LOG_PATH, os.path.join(APP_DIR, "diagnostic_trace.log")):
        try:
            with open(path, "a", encoding="utf-8") as target:
                target.write(line)
        except Exception:
            pass

def create_tk_root():
    configure_windows_app_identity()
    if DND_TK_ROOT is not None:
        try:
            return DND_TK_ROOT()
        except Exception as error:
            log_to_file("WARN", f"TkinterDnD startup failed, using plain Tk: {error}")
    return tk.Tk()

_SINGLE_INSTANCE_MUTEX = None

def ensure_single_instance():
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        mutex = kernel32.CreateMutexW(None, True, "TMMVideoCutterProSingleInstance")
        if not mutex:
            return True
        if kernel32.GetLastError() == 183:
            kernel32.CloseHandle(mutex)
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "TMM Cutter уже запущен. Закройте лишнее окно или продолжайте работу в открытом.",
                    "TMM Cutter",
                    0x40,
                )
            except Exception:
                pass
            return False
        _SINGLE_INSTANCE_MUTEX = mutex
        return True
    except Exception as error:
        log_to_file("WARN", f"Не удалось проверить второй запуск приложения: {error}")
        return True

# ====================== КОНФИГ ======================
DEFAULT_CONFIG = {
    "tmm_api_key": "",
    "obs_folder": "",
    "output_folder": "",
    "buffer_before": 5,
    "buffer_after": 5,
    "time_offset": 0,
    "python_path": "",
    "auto_process": False,
    "auto_process_interval": 60,
    "auto_sync_video_links": True,
    "local_server_port": 8765,
    "local_server_token": "",
    "tmm_timezone": "UTC",
    "tmm_timezone_updated_at": "",
    "folder_naming": "tmm_time_seconds_symbol_percent_duration_entry_reason",
    "trade_filter_mode": "all",
    "my_api_key_ids": []
}

TRADE_FILTER_ALL = "all"
TRADE_FILTER_MINE_ONLY = "mine_only"
TRADE_FILTER_MODES = {TRADE_FILTER_ALL, TRADE_FILTER_MINE_ONLY}
LAST_TMM_API_STATUS = None
LAST_TMM_CACHE_USED_STALE = False
LAST_TMM_CACHE_LAST_UPDATE = ""
TMM_API_COOLDOWN_UNTIL = 0.0
TMM_API_COOLDOWN_REASON = ""
TMM_API_COOLDOWN_LAST_LOG_AT = 0.0
TMM_CACHE_UPDATE_LOCK = threading.Lock()
TRADE_FILTER_LABELS = {
    TRADE_FILTER_ALL: "Все сделки",
    TRADE_FILTER_MINE_ONLY: "Только мои",
}

def normalize_trade_filter_mode(value):
    mode = str(value or TRADE_FILTER_ALL).strip().lower()
    if mode in ("mine", "my", "own", TRADE_FILTER_MINE_ONLY):
        return TRADE_FILTER_MINE_ONLY
    return TRADE_FILTER_ALL

def tmm_api_cooldown_remaining():
    return max(0.0, TMM_API_COOLDOWN_UNTIL - time.monotonic())

def set_tmm_api_cooldown(seconds, reason=""):
    global TMM_API_COOLDOWN_UNTIL, TMM_API_COOLDOWN_REASON
    delay = max(0.0, float(seconds or 0))
    TMM_API_COOLDOWN_UNTIL = max(TMM_API_COOLDOWN_UNTIL, time.monotonic() + delay)
    TMM_API_COOLDOWN_REASON = str(reason or "")

def clear_tmm_api_cooldown():
    global TMM_API_COOLDOWN_UNTIL, TMM_API_COOLDOWN_REASON, TMM_API_COOLDOWN_LAST_LOG_AT
    TMM_API_COOLDOWN_UNTIL = 0.0
    TMM_API_COOLDOWN_REASON = ""
    TMM_API_COOLDOWN_LAST_LOG_AT = 0.0

def parse_retry_after_seconds(response, default_seconds=300):
    raw_value = str(getattr(response, "headers", {}).get("Retry-After", "") or "").strip()
    try:
        # TMM sometimes answers with a very small Retry-After while still
        # continuing to throttle. Keep a real cooldown so auto modes do not
        # hammer the API and make the application look frozen.
        return max(float(default_seconds), float(raw_value))
    except (TypeError, ValueError):
        return float(default_seconds)

class TMMRateLimitError(RuntimeError):
    pass

def tmm_rate_limit_message(seconds=None):
    remaining = float(seconds if seconds is not None else tmm_api_cooldown_remaining())
    minutes = max(1, int((remaining + 59) // 60))
    return f"TMM API на паузе после ограничения запросов; повтор через {minutes} мин."

def raise_tmm_rate_limit(response=None):
    retry_seconds = parse_retry_after_seconds(response) if response is not None else max(60.0, tmm_api_cooldown_remaining())
    set_tmm_api_cooldown(retry_seconds, "HTTP 429")
    raise TMMRateLimitError(tmm_rate_limit_message(retry_seconds))

def normalize_api_key_id(value):
    text = str(value or "").strip()
    return text if text and text.lower() not in ("none", "null") else ""

def parse_api_key_ids(raw_value):
    if isinstance(raw_value, (list, tuple, set)):
        parts = raw_value
    else:
        parts = re.split(r"[\s,;]+", str(raw_value or ""))
    result = []
    seen = set()
    for part in parts:
        item = normalize_api_key_id(part)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result

def format_api_key_ids(api_key_ids):
    return ", ".join(parse_api_key_ids(api_key_ids))

def get_trade_api_key_ids(trade):
    ids = []
    if not isinstance(trade, dict):
        return ids
    for key in ("api_key_id", "apiKeyId"):
        item = normalize_api_key_id(trade.get(key))
        if item:
            ids.append(item)
    for order in trade.get("orders") or []:
        if not isinstance(order, dict):
            continue
        for key in ("api_key_id", "apiKeyId"):
            item = normalize_api_key_id(order.get(key))
            if item:
                ids.append(item)
    return parse_api_key_ids(ids)

def is_trade_from_api_key_ids(trade, api_key_ids):
    allowed = set(parse_api_key_ids(api_key_ids))
    if not allowed:
        return False
    return bool(set(get_trade_api_key_ids(trade)) & allowed)

def filter_trades_by_api_key_ids(trades, api_key_ids):
    allowed = set(parse_api_key_ids(api_key_ids))
    if not allowed:
        return []
    return [trade for trade in trades or [] if set(get_trade_api_key_ids(trade)) & allowed]

def get_api_key_id_counts(trades):
    counts = {}
    for trade in trades or []:
        for item in get_trade_api_key_ids(trade):
            counts[item] = counts.get(item, 0) + 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))

def format_api_key_id_counts(trades, limit=5):
    items = get_api_key_id_counts(trades)
    if not items:
        return ""
    shown = [f"{api_key_id}: {count}" for api_key_id, count in items[:limit]]
    remaining = len(items) - len(shown)
    if remaining > 0:
        shown.append(f"+{remaining} ещё")
    return ", ".join(shown)

def get_api_key_fingerprint(api_key):
    value = str(api_key or "").strip()
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

_CONFIG_API_KEY_DECRYPT_FAILED = False
_CONFIG_PROTECTED_API_KEY = ""
_CONFIG_WRITE_LOCK = threading.Lock()

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

def _make_data_blob(data):
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer

def _dpapi_transform(data, protect):
    if sys.platform != "win32":
        raise RuntimeError("DPAPI is available only on Windows")
    source, source_buffer = _make_data_blob(data)
    entropy, entropy_buffer = _make_data_blob(b"TMM Video Cutter API key v1")
    result = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "TMM Video Cutter API key", ctypes.byref(entropy),
            None, None, 0x01, ctypes.byref(result)
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, ctypes.byref(entropy),
            None, None, 0x01, ctypes.byref(result)
        )
    # Keep buffers alive until the WinAPI call has completed.
    _ = source_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)

def protect_api_key(api_key):
    value = str(api_key or "")
    if not value or value.startswith("dpapi:"):
        return value
    encrypted = _dpapi_transform(value.encode("utf-8"), True)
    return "dpapi:" + base64.b64encode(encrypted).decode("ascii")

def unprotect_api_key(stored_value):
    value = str(stored_value or "")
    if not value.startswith("dpapi:"):
        return value
    encrypted = base64.b64decode(value[6:].encode("ascii"), validate=True)
    return _dpapi_transform(encrypted, False).decode("utf-8")

def load_config():
    global _CONFIG_API_KEY_DECRYPT_FAILED, _CONFIG_PROTECTED_API_KEY
    d = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
                loaded = json.load(f)
                for k in DEFAULT_CONFIG:
                    if k in loaded:
                        d[k] = loaded[k]
                stored_key = str(loaded.get("tmm_api_key", "") or "")
                _CONFIG_PROTECTED_API_KEY = stored_key if stored_key.startswith("dpapi:") else ""
                try:
                    d["tmm_api_key"] = unprotect_api_key(stored_key)
                    _CONFIG_API_KEY_DECRYPT_FAILED = False
                except Exception:
                    d["tmm_api_key"] = ""
                    _CONFIG_API_KEY_DECRYPT_FAILED = bool(_CONFIG_PROTECTED_API_KEY)
        except: pass
    return d

def save_config(cfg):
    global _CONFIG_API_KEY_DECRYPT_FAILED, _CONFIG_PROTECTED_API_KEY
    stored_cfg = dict(cfg)
    plain_key = str(stored_cfg.get("tmm_api_key", "") or "")
    if plain_key:
        stored_key = protect_api_key(plain_key)
        _CONFIG_PROTECTED_API_KEY = stored_key
        _CONFIG_API_KEY_DECRYPT_FAILED = False
    elif _CONFIG_PROTECTED_API_KEY:
        # Пустое поле интерфейса не должно уничтожать уже сохранённый ключ.
        stored_key = _CONFIG_PROTECTED_API_KEY
    else:
        stored_key = ""
        _CONFIG_PROTECTED_API_KEY = ""
    stored_cfg["tmm_api_key"] = stored_key
    temp_path = CONFIG_PATH + ".tmp"
    with _CONFIG_WRITE_LOCK:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(stored_cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, CONFIG_PATH)

_TMM_TIMEZONE_LOCK = threading.Lock()
_TMM_TIMEZONE_NAME = "UTC"
_TMM_TIMEZONE = timezone.utc

def resolve_tmm_timezone(name):
    normalized = str(name or "UTC").strip() or "UTC"
    if normalized.upper() in ("UTC", "GMT", "ETC/UTC"):
        return "UTC", timezone.utc
    try:
        return normalized, ZoneInfo(normalized)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"Unsupported TMM timezone: {normalized}")

def set_tmm_timezone(name):
    global _TMM_TIMEZONE_NAME, _TMM_TIMEZONE
    normalized, tz = resolve_tmm_timezone(name)
    with _TMM_TIMEZONE_LOCK:
        _TMM_TIMEZONE_NAME = normalized
        _TMM_TIMEZONE = tz
    return normalized

def get_tmm_timezone():
    with _TMM_TIMEZONE_LOCK:
        return _TMM_TIMEZONE

def get_tmm_timezone_name():
    with _TMM_TIMEZONE_LOCK:
        return _TMM_TIMEZONE_NAME

class TMMApiRateLimiter:
    def __init__(self, min_interval=0.75, max_rate_limit_retries=0):
        self.min_interval = float(min_interval)
        self.max_rate_limit_retries = int(max_rate_limit_retries)
        self._lock = threading.Lock()
        self._next_request_at = 0.0
        self.total_requests = 0
        self.throttled_requests = 0
        self.rate_limit_hits = 0
        self.last_status = None
        self.last_request_at = ""

    def _wait_for_slot(self):
        with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_request_at - now)
            reserved_at = max(now, self._next_request_at)
            self._next_request_at = reserved_at + self.min_interval
            if wait_seconds > 0.001:
                self.throttled_requests += 1
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def _defer(self, seconds):
        delay = max(0.0, float(seconds))
        with self._lock:
            self._next_request_at = max(self._next_request_at, time.monotonic() + delay)

    @staticmethod
    def _retry_after(response, attempt):
        raw_value = str(response.headers.get("Retry-After", "") or "").strip()
        try:
            return max(300.0, float(raw_value))
        except ValueError:
            return max(300.0, float(2 ** attempt))

    def request(self, method, url, **kwargs):
        for attempt in range(self.max_rate_limit_retries + 1):
            self._wait_for_slot()
            response = requests.request(method, url, **kwargs)
            with self._lock:
                self.total_requests += 1
                self.last_status = response.status_code
                self.last_request_at = datetime.now().isoformat()
            if response.status_code != 429:
                return response
            with self._lock:
                self.rate_limit_hits += 1
            self._defer(self._retry_after(response, attempt + 1))
            return response
        return response

    def snapshot(self):
        with self._lock:
            return {
                "total_requests": self.total_requests,
                "throttled_requests": self.throttled_requests,
                "rate_limit_hits": self.rate_limit_hits,
                "last_status": self.last_status,
                "last_request_at": self.last_request_at,
                "min_interval": self.min_interval,
            }

TMM_API_LIMITER = TMMApiRateLimiter()

def tmm_request(method, url, **kwargs):
    return TMM_API_LIMITER.request(method, url, **kwargs)

def fetch_tmm_profile_timezone(api_key, timeout=15):
    if not api_key:
        raise ValueError("TMM API key is empty")
    response = tmm_request("GET",
        "https://tradermake.money/api/v2/auth/me",
        headers={"API-KEY": api_key, "Accept": "application/json"},
        timeout=timeout,
    )
    if response.status_code == 429:
        raise_tmm_rate_limit(response)
    response.raise_for_status()
    payload = response.json()
    profile = payload.get("data", payload) if isinstance(payload, dict) else {}
    timezone_name = profile.get("timezone") if isinstance(profile, dict) else None
    if not timezone_name:
        raise ValueError("TMM profile response does not contain timezone")
    normalized, _tz = resolve_tmm_timezone(timezone_name)
    return normalized

try:
    set_tmm_timezone(load_config().get("tmm_timezone", "UTC"))
except ValueError:
    set_tmm_timezone("UTC")

# ====================== БД ======================
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0); c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS processed (trade_id TEXT PRIMARY KEY, processed_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS video_cache (video_path TEXT PRIMARY KEY, processed_trades TEXT, last_processed TEXT)")
    # Умный кэш характеристик видеофайлов для предотвращения тормозов ПК
    c.execute("""CREATE TABLE IF NOT EXISTS video_metadata_cache (
        video_path TEXT PRIMARY KEY,
        start_time TEXT,
        duration_sec REAL,
        size_mb REAL,
        start_method TEXT,
        file_mtime REAL
    )""")
    processed_columns = {
        row[1] for row in c.execute("PRAGMA table_info(processed)").fetchall()
    }
    migrations = {
        "clip_path": "TEXT",
        "source_video_path": "TEXT",
        "clip_size": "INTEGER",
        "link_status": "TEXT DEFAULT 'legacy'",
        "link_error": "TEXT",
        "link_updated_at": "TEXT",
        "link_url": "TEXT",
        "link_attempts": "INTEGER DEFAULT 0",
        "link_next_retry": "TEXT",
    }
    for column, definition in migrations.items():
        if column not in processed_columns:
            c.execute(f"ALTER TABLE processed ADD COLUMN {column} {definition}")
    c.execute("UPDATE processed SET link_status='legacy' WHERE link_status IS NULL OR link_status=''")
    c.execute("""CREATE TABLE IF NOT EXISTS processing_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT NOT NULL,
        symbol TEXT,
        source_video_path TEXT,
        output_path TEXT,
        source_mode TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        message TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        buffer_before INTEGER DEFAULT 0,
        buffer_after INTEGER DEFAULT 0,
        time_offset INTEGER DEFAULT 0,
        output_dir TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status, created_at)")
    c.execute(
        "UPDATE processing_jobs SET status='interrupted', message='Программа была закрыта до завершения', "
        "finished_at=? WHERE status IN ('pending','running')",
        (datetime.now().isoformat(),)
    )
    c.execute("""CREATE TABLE IF NOT EXISTS quarantine_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id TEXT,
        original_path TEXT NOT NULL,
        quarantine_path TEXT NOT NULL,
        reason TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        file_hash TEXT,
        quarantined_at TEXT NOT NULL,
        restored_at TEXT,
        status TEXT NOT NULL DEFAULT 'quarantined'
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_quarantine_status ON quarantine_items(status, quarantined_at)")
    conn.commit(); conn.close()

def _valid_clip(path):
    try:
        return bool(path and os.path.isfile(path) and os.path.getsize(path) > 1024)
    except OSError:
        return False

def get_trade_output_path(trade, out_dir, folder_name_cb=None):
    ot = parse_trade_time(trade, True)
    if not ot:
        return ""
    trade_time_tmm = ot.astimezone(get_tmm_timezone())
    structured_base = os.path.join(
        out_dir, str(trade_time_tmm.year), get_month_name_ru(trade_time_tmm),
        get_week_folder(trade_time_tmm), get_day_folder(trade_time_tmm)
    )
    name_factory = folder_name_cb or get_trade_folder_name
    folder_name = name_factory(trade, trade_time_tmm)
    return os.path.join(structured_base, folder_name, f"{folder_name}.mp4")

def get_processed_record(tid):
    conn = sqlite3.connect(DB_PATH, timeout=30.0); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM processed WHERE trade_id=?", (str(tid),)).fetchone()
    conn.close()
    return dict(row) if row else None

def _set_missing_clip(tid):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute(
        "UPDATE processed SET clip_path=NULL, clip_size=NULL, link_status='missing', "
        "link_error='Файл клипа удалён', link_next_retry=NULL WHERE trade_id=?",
        (str(tid),)
    )
    conn.commit(); conn.close()

def is_processed(tid, trade=None, out_dir=None, folder_name_cb=None, source_video_path=None):
    tid = str(tid)
    record = get_processed_record(tid)
    if not record:
        return False
    clip_path = record.get("clip_path")
    if _valid_clip(clip_path):
        return True
    if trade and out_dir:
        inferred = get_trade_output_path(trade, out_dir, folder_name_cb)
        if _valid_clip(inferred):
            conn = sqlite3.connect(DB_PATH, timeout=30.0)
            conn.execute(
                "UPDATE processed SET clip_path=?, source_video_path=COALESCE(source_video_path, ?), "
                "clip_size=?, link_status=CASE WHEN link_status='missing' THEN 'legacy' ELSE link_status END "
                "WHERE trade_id=?",
                (inferred, source_video_path, os.path.getsize(inferred), tid)
            )
            conn.commit(); conn.close()
            return True
    _set_missing_clip(tid)
    return False

def mark_processed(tid, clip_path, source_video_path=""):
    tid = str(tid)
    if not _valid_clip(clip_path):
        raise ValueError(f"Готовый клип не найден: {clip_path}")
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("""
        INSERT INTO processed (
            trade_id, processed_at, clip_path, source_video_path, clip_size,
            link_status, link_error, link_updated_at, link_url, link_attempts, link_next_retry
        ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL, NULL, 0, NULL)
        ON CONFLICT(trade_id) DO UPDATE SET
            processed_at=excluded.processed_at,
            clip_path=excluded.clip_path,
            source_video_path=excluded.source_video_path,
            clip_size=excluded.clip_size,
            link_status='pending', link_error=NULL, link_updated_at=NULL,
            link_attempts=0, link_next_retry=NULL
    """, (tid, now, os.path.abspath(clip_path), os.path.abspath(source_video_path) if source_video_path else "", os.path.getsize(clip_path)))
    conn.commit(); conn.close()

def get_registered_clip(tid):
    record = get_processed_record(tid)
    if not record:
        return ""
    clip_path = record.get("clip_path") or ""
    if _valid_clip(clip_path):
        return clip_path
    _set_missing_clip(tid)
    return ""

def is_video_processed(vp, trade_ids=None):
    allowed = None if trade_ids is None else {str(value) for value in trade_ids}
    conn = sqlite3.connect(DB_PATH, timeout=30.0); c = conn.cursor()
    rows = c.execute(
        "SELECT trade_id, clip_path FROM processed WHERE source_video_path=?", (os.path.abspath(vp),)
    ).fetchall()
    scoped_rows = [(tid, path) for tid, path in rows if allowed is None or str(tid) in allowed]
    valid = [tid for tid, path in scoped_rows if _valid_clip(path)]
    missing = [tid for tid, path in scoped_rows if not _valid_clip(path)]
    r = c.execute("SELECT last_processed FROM video_cache WHERE video_path=?", (vp,)).fetchone()
    conn.close()
    for tid in missing:
        _set_missing_clip(tid)
    if not valid:
        return False, "", ""
    return True, str(len(valid)), r[0] if r else ""

def mark_video_processed(vp, cnt):
    conn = sqlite3.connect(DB_PATH, timeout=30.0); c = conn.cursor()
    if cnt > 0:
        c.execute("INSERT OR REPLACE INTO video_cache VALUES (?,?,?)", (vp, str(cnt), datetime.now().isoformat()))
    else:
        c.execute("DELETE FROM video_cache WHERE video_path=?", (vp,))
    conn.commit(); conn.close()

def get_link_sync_candidates(include_legacy=False):
    statuses = ["pending", "retry"] + (["legacy"] if include_legacy else [])
    placeholders = ",".join("?" for _ in statuses)
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=30.0); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT * FROM processed WHERE link_status IN ({placeholders}) "
        "AND (link_next_retry IS NULL OR link_next_retry<=?) ORDER BY processed_at",
        (*statuses, now)
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        if _valid_clip(item.get("clip_path")):
            result.append(item)
        else:
            _set_missing_clip(item["trade_id"])
    return result

def set_link_sync_result(tid, status, link_url=None, error="", attempts=0, next_retry=None):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute(
        "UPDATE processed SET link_status=?, link_url=COALESCE(?, link_url), link_error=?, "
        "link_updated_at=?, link_attempts=?, link_next_retry=? WHERE trade_id=?",
        (status, link_url, error[:500], datetime.now().isoformat(), attempts, next_retry, str(tid))
    )
    conn.commit(); conn.close()

def get_runtime_status_counts(trade_ids=None):
    allowed = None if trade_ids is None else {str(value) for value in trade_ids}
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    rows = conn.execute("SELECT trade_id, clip_path, link_status FROM processed").fetchall()
    conn.close()
    status_counts = defaultdict(int)
    valid_clips = 0
    missing_clips = 0
    counted_rows = 0
    for trade_id, clip_path, link_status in rows:
        if allowed is not None and str(trade_id) not in allowed:
            continue
        counted_rows += 1
        status_counts[str(link_status or "legacy")] += 1
        if _valid_clip(clip_path):
            valid_clips += 1
        else:
            missing_clips += 1
    return {
        "records": counted_rows,
        "valid_clips": valid_clips,
        "missing_clips": missing_clips,
        "synced": status_counts["synced"],
        "pending": status_counts["pending"] + status_counts["retry"] + status_counts["legacy"],
        "link_errors": status_counts["error"],
    }

def create_processing_jobs(trades, vi, source_mode, buffer_before, buffer_after, time_offset, output_dir):
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    job_ids = {}
    for trade in trades:
        trade_id = str(trade.get("id", ""))
        cursor = conn.execute("""
            INSERT INTO processing_jobs (
                trade_id, symbol, source_video_path, source_mode, status, message,
                created_at, buffer_before, buffer_after, time_offset, output_dir
            ) VALUES (?, ?, ?, ?, 'pending', '', ?, ?, ?, ?, ?)
        """, (
            trade_id, str(trade.get("symbol", "?")), os.path.abspath(vi.get("path", "")),
            source_mode, now, int(buffer_before), int(buffer_after), int(time_offset),
            os.path.abspath(output_dir)
        ))
        job_ids[trade_id] = cursor.lastrowid
    conn.commit(); conn.close()
    return job_ids

def update_processing_job(job_id, status, message="", output_path=""):
    if not job_id:
        return
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    if status == "running":
        conn.execute(
            "UPDATE processing_jobs SET status=?, message=?, started_at=COALESCE(started_at, ?) WHERE id=?",
            (status, str(message)[:500], now, int(job_id))
        )
    elif status in ("done", "error", "stopped", "interrupted"):
        conn.execute(
            "UPDATE processing_jobs SET status=?, message=?, output_path=COALESCE(NULLIF(?,''), output_path), "
            "finished_at=? WHERE id=?",
            (status, str(message)[:500], output_path, now, int(job_id))
        )
    else:
        conn.execute(
            "UPDATE processing_jobs SET status=?, message=? WHERE id=?",
            (status, str(message)[:500], int(job_id))
        )
    conn.commit(); conn.close()

def get_processing_jobs(limit=300):
    conn = sqlite3.connect(DB_PATH, timeout=30.0); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM processing_jobs ORDER BY id DESC LIMIT ?", (int(limit),)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_processing_job_counts(trade_ids=None):
    allowed = None if trade_ids is None else {str(value) for value in trade_ids}
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    if allowed is None:
        rows = conn.execute("SELECT status, COUNT(*) FROM processing_jobs GROUP BY status").fetchall()
    elif not allowed:
        rows = []
    else:
        placeholders = ",".join("?" for _ in allowed)
        rows = conn.execute(
            f"SELECT status, COUNT(*) FROM processing_jobs WHERE trade_id IN ({placeholders}) GROUP BY status",
            tuple(allowed)
        ).fetchall()
    conn.close()
    counts = defaultdict(int, {str(status): count for status, count in rows})
    return {
        "pending": counts["pending"],
        "running": counts["running"],
        "problems": counts["error"] + counts["interrupted"],
        "done": counts["done"],
    }

def clear_completed_processing_jobs():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.execute("DELETE FROM processing_jobs WHERE status IN ('done','stopped')")
    conn.commit(); conn.close()
    return cursor.rowcount

def get_link_status_rows(limit=500):
    conn = sqlite3.connect(DB_PATH, timeout=30.0); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT trade_id, clip_path, link_status, link_error, link_updated_at, "
        "link_attempts, link_next_retry, link_url FROM processed "
        "ORDER BY processed_at DESC LIMIT ?", (int(limit),)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def queue_link_retry(trade_id):
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute(
        "UPDATE processed SET link_status='pending', link_error=NULL, link_attempts=0, "
        "link_next_retry=NULL WHERE trade_id=?",
        (str(trade_id),)
    )
    conn.commit(); conn.close()

def _normalized_path(path):
    return os.path.normcase(os.path.abspath(path or ""))

def _path_is_inside(path, directory):
    try:
        return os.path.commonpath([_normalized_path(path), _normalized_path(directory)]) == _normalized_path(directory)
    except (ValueError, OSError):
        return False

def calculate_file_sha256(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()

def scan_storage(output_dir, progress_cb=None, stop_cb=None):
    output_root = os.path.abspath(output_dir or "")
    if not output_root or not os.path.isdir(output_root):
        raise ValueError("Папка сохранения не существует")
    temp_extensions = {".tmp", ".temp", ".part", ".partial"}
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    registered_rows = conn.execute("SELECT trade_id, clip_path FROM processed").fetchall()
    conn.close()
    registered = {
        _normalized_path(path): str(trade_id)
        for trade_id, path in registered_rows if path
    }
    missing_registered = sum(1 for _trade_id, path in registered_rows if not _valid_clip(path))

    files = []
    for root_dir, dirs, names in os.walk(output_root):
        dirs[:] = [name for name in dirs if not _path_is_inside(os.path.join(root_dir, name), QUARANTINE_DIR)]
        for name in names:
            path = os.path.join(root_dir, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            files.append({
                "path": path,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "extension": os.path.splitext(name)[1].lower(),
                "trade_id": registered.get(_normalized_path(path), ""),
            })
    candidates = {}

    def add_candidate(item, reason, file_hash=""):
        key = _normalized_path(item["path"])
        candidate = candidates.setdefault(key, {
            "path": item["path"], "size": item["size"],
            "trade_id": item.get("trade_id", ""), "reasons": [], "file_hash": file_hash,
        })
        if reason not in candidate["reasons"]:
            candidate["reasons"].append(reason)
        if file_hash:
            candidate["file_hash"] = file_hash

    videos = []
    now = time.time()
    for index, item in enumerate(files, 1):
        if stop_cb and stop_cb():
            break
        extension = item["extension"]
        if extension in temp_extensions and now - item["mtime"] > 600:
            add_candidate(item, "Временный файл старше 10 минут")
        if extension in VIDEO_EXTENSIONS:
            videos.append(item)
            if item["size"] <= 1024:
                add_candidate(item, "Пустой или повреждённый видеофайл")
            elif not item["trade_id"]:
                add_candidate(item, "Видеофайл не зарегистрирован в базе")
        if progress_cb and index % 100 == 0:
            progress_cb(index, len(files), "Сканирование файлов")

    size_groups = defaultdict(list)
    for item in videos:
        if item["size"] > 1024:
            size_groups[item["size"]].append(item)
    duplicate_groups = 0
    for size_group in size_groups.values():
        if len(size_group) < 2:
            continue
        hash_groups = defaultdict(list)
        for item in size_group:
            if stop_cb and stop_cb():
                break
            try:
                file_hash = calculate_file_sha256(item["path"])
                hash_groups[file_hash].append(item)
            except OSError:
                continue
        for file_hash, hash_group in hash_groups.items():
            if len(hash_group) < 2:
                continue
            duplicate_groups += 1
            registered_items = [item for item in hash_group if item["trade_id"]]
            keep = registered_items[0] if registered_items else min(hash_group, key=lambda item: item["mtime"])
            for item in hash_group:
                if item is keep or item["trade_id"]:
                    continue
                add_candidate(item, "Полная копия другого видеофайла", file_hash)

    result = sorted(candidates.values(), key=lambda item: (item["reasons"], item["path"].lower()))
    return {
        "output_dir": output_root,
        "files_scanned": len(files),
        "videos_scanned": len(videos),
        "missing_registered": missing_registered,
        "duplicate_groups": duplicate_groups,
        "candidates": result,
    }

def quarantine_storage_items(items, output_dir):
    output_root = os.path.abspath(output_dir or "")
    if not os.path.isdir(output_root):
        raise ValueError("Папка сохранения не существует")
    batch_name = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
    moved = []
    errors = []
    os.makedirs(QUARANTINE_DIR, exist_ok=True)
    for item in items:
        source = os.path.abspath(item.get("path", ""))
        if not _path_is_inside(source, output_root):
            errors.append((source, "Файл находится вне папки сохранения"))
            continue
        if not os.path.isfile(source):
            errors.append((source, "Файл уже отсутствует"))
            continue
        relative_path = os.path.relpath(source, output_root)
        destination = os.path.join(QUARANTINE_DIR, batch_name, relative_path)
        if os.path.exists(destination):
            stem, extension = os.path.splitext(destination)
            destination = f"{stem}_{secrets.token_hex(2)}{extension}"
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        try:
            size = os.path.getsize(source)
            shutil.move(source, destination)
            conn = sqlite3.connect(DB_PATH, timeout=30.0)
            cursor = conn.execute("""
                INSERT INTO quarantine_items (
                    trade_id, original_path, quarantine_path, reason, file_size,
                    file_hash, quarantined_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'quarantined')
            """, (
                str(item.get("trade_id") or ""), source, destination,
                "; ".join(item.get("reasons") or ["Подозрительный файл"]),
                size, item.get("file_hash") or "", datetime.now().isoformat()
            ))
            item_id = cursor.lastrowid
            conn.commit(); conn.close()
            if item.get("trade_id"):
                _set_missing_clip(str(item["trade_id"]))
            moved.append({"id": item_id, "source": source, "destination": destination})
        except Exception as error:
            if os.path.isfile(destination) and not os.path.exists(source):
                try:
                    os.makedirs(os.path.dirname(source), exist_ok=True)
                    shutil.move(destination, source)
                except OSError:
                    pass
            errors.append((source, str(error)))
    return moved, errors

def get_quarantine_items(active_only=False):
    conn = sqlite3.connect(DB_PATH, timeout=30.0); conn.row_factory = sqlite3.Row
    query = "SELECT * FROM quarantine_items"
    params = ()
    if active_only:
        query += " WHERE status='quarantined'"
    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_quarantine_summary():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(file_size),0) FROM quarantine_items WHERE status='quarantined'"
    ).fetchone()
    conn.close()
    return {"files": int(row[0]), "bytes": int(row[1])}

def restore_quarantine_item(item_id):
    conn = sqlite3.connect(DB_PATH, timeout=30.0); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM quarantine_items WHERE id=?", (int(item_id),)).fetchone()
    conn.close()
    if not row or row["status"] != "quarantined":
        return False, "Запись карантина не найдена"
    source = os.path.abspath(row["quarantine_path"])
    destination = os.path.abspath(row["original_path"])
    if not _path_is_inside(source, QUARANTINE_DIR):
        return False, "Некорректный путь карантина"
    if not os.path.isfile(source):
        return False, "Файл в карантине отсутствует"
    if os.path.exists(destination):
        return False, "Исходный путь уже занят"
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.move(source, destination)
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute(
            "UPDATE quarantine_items SET status='restored', restored_at=? WHERE id=?",
            (datetime.now().isoformat(), int(item_id))
        )
        trade_id = str(row["trade_id"] or "")
        if trade_id and _valid_clip(destination):
            conn.execute(
                "UPDATE processed SET clip_path=?, clip_size=?, link_status='pending', "
                "link_error=NULL, link_next_retry=NULL WHERE trade_id=?",
                (destination, os.path.getsize(destination), trade_id)
            )
        conn.commit(); conn.close()
        return True, destination
    except Exception as error:
        if os.path.isfile(destination) and not os.path.exists(source):
            try:
                os.makedirs(os.path.dirname(source), exist_ok=True)
                shutil.move(destination, source)
            except OSError:
                pass
        return False, str(error)

def format_trade_link_status(record):
    status = str((record or {}).get("link_status") or "")
    return {
        "synced": "ссылка отправлена",
        "pending": "ссылка ожидает отправки",
        "retry": "ссылка ожидает повтора",
        "missing": "файл удалён",
        "error": "ошибка ссылки",
        "legacy": "старая запись",
    }.get(status, "статус ссылки неизвестен")

def get_cached_video_info(vp):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0); c = conn.cursor()
        c.execute("SELECT start_time, duration_sec, size_mb, start_method, file_mtime FROM video_metadata_cache WHERE video_path=?", (vp,))
        r = c.fetchone(); conn.close()
        if r:
            return {
                'start_time': datetime.fromisoformat(r[0]),
                'duration_sec': r[1],
                'size_mb': r[2],
                'start_method': r[3],
                'file_mtime': r[4]
            }
    except: pass
    return None

def save_cached_video_info(vp, info, file_mtime):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO video_metadata_cache VALUES (?,?,?,?,?,?)", (
            vp,
            info['start_time'].isoformat(),
            info['duration_sec'],
            info['size_mb'],
            info['start_method'],
            file_mtime
        ))
        conn.commit(); conn.close()
    except: pass

# ====================== КЭШ СДЕЛOK ======================
def load_trades_cache(api_key=None):
    if os.path.exists(TRADES_CACHE_PATH):
        try:
            with open(TRADES_CACHE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                requested_hash = get_api_key_fingerprint(api_key)
                cached_hash = str(d.get("api_key_hash", "") or "")
                # The local cache is a fallback data source. Do not delete it
                # just because the API key was re-saved or temporarily cannot
                # be decrypted in another Windows session. The "Только мои"
                # filter below still scopes trades by api_key_id.
                _ = requested_hash, cached_hash
                return d.get("trades", []), d.get("last_update", "")
        except: pass
    return [], ""

def save_trades_cache(trades, api_key=None):
    with open(TRADES_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "last_update": datetime.now().isoformat(),
            "trades_count": len(trades),
            "api_key_hash": get_api_key_fingerprint(api_key),
            "trades": trades,
        }, f)

def merge_trades_for_cache(new_trades, old_trades):
    all_trades = list(new_trades or []) + list(old_trades or [])
    seen = set()
    deduped = []
    for trade in all_trades:
        tid = str(trade.get("id", ""))
        if tid and tid in seen:
            continue
        if tid:
            seen.add(tid)
        deduped.append(trade)

    def trade_sort_key(trade):
        try:
            return (1, int(trade.get('id', 0)))
        except (TypeError, ValueError):
            return (0, str(trade.get('id', '')))

    deduped.sort(key=trade_sort_key, reverse=True)
    return deduped

def update_trades_cache(api_key, prog_cb=None, log_cb=None, stop_cb=None, bypass_cooldown=False):
    global LAST_TMM_API_STATUS, TMM_API_COOLDOWN_LAST_LOG_AT
    LAST_TMM_API_STATUS = None
    old_trades, _ = load_trades_cache(api_key)
    remaining = tmm_api_cooldown_remaining()
    if remaining > 0 and not bypass_cooldown:
        LAST_TMM_API_STATUS = 429
        now = time.monotonic()
        if log_cb and now - TMM_API_COOLDOWN_LAST_LOG_AT > 60:
            minutes = max(1, int((remaining + 59) // 60))
            detail = f"TMM API на паузе после ограничения запросов; повтор через {minutes} мин."
            if TMM_API_COOLDOWN_REASON:
                detail += f" ({TMM_API_COOLDOWN_REASON})"
            log_cb("WARN", detail)
            TMM_API_COOLDOWN_LAST_LOG_AT = now
        return old_trades
    if not TMM_CACHE_UPDATE_LOCK.acquire(blocking=False):
        if log_cb:
            log_cb("INFO", "Обновление сделок TMM уже выполняется; использую текущую локальную базу.")
        return old_trades
    old_ids = {str(t.get('id')) for t in old_trades if t.get('id')}
    new_trades = []
    update_failed = False
    try:
        headers = {"API-KEY": api_key}
        for page in range(1, 50):
            if stop_cb and stop_cb():
                update_failed = True
                break
            try:
                r = tmm_request("GET", "https://tradermake.money/api/v2/trades",
                    headers=headers, params={"limit": 100, "page": page, "sort": "desc"}, timeout=15)
                if r.status_code != 200:
                    LAST_TMM_API_STATUS = r.status_code
                    if log_cb:
                        message = f"API код ответа: {r.status_code}"
                        if r.status_code in (401, 403):
                            message += ". TMM отклонил API-ключ; вставьте новый действующий ключ и сохраните настройки"
                        if r.status_code == 429:
                            retry_seconds = parse_retry_after_seconds(r)
                            set_tmm_api_cooldown(retry_seconds, "HTTP 429")
                            retry_after = str(r.headers.get("Retry-After", "") or "").strip()
                            message += ". TMM ограничил частоту запросов; закройте лишние копии приложения и повторите позже"
                            if retry_after:
                                message += f" (Retry-After: {retry_after} с)"
                            else:
                                message += f" (пауза: {int(retry_seconds // 60)} мин)"
                        log_cb("WARN" if r.status_code == 429 else "ERROR", message)
                    update_failed = True
                    break
                trades = r.json().get('data', [])
                clear_tmm_api_cooldown()
                if not trades: break
                found = False
                for t in trades:
                    tid = str(t.get('id', ''))
                    if tid not in old_ids: new_trades.append(t); old_ids.add(tid); found = True
                if not found:
                    if log_cb: log_cb("INFO", f"Достигли синхронизированных сделок (стр. {page})")
                    break
                if prog_cb: prog_cb(page, len(new_trades))
                time.sleep(0.2)
            except Exception as e:
                LAST_TMM_API_STATUS = "network"
                if log_cb: log_cb("WARN", f"Ошибка страницы {page}: {e}")
                update_failed = True
                break
        if update_failed:
            if new_trades:
                all_t = merge_trades_for_cache(new_trades, old_trades)
                save_trades_cache(all_t, api_key)
                if log_cb:
                    log_cb("WARN", f"Сделки TMM частично обновлены: добавлено {len(new_trades)} новых, продолжу догрузку позже.")
                return all_t
            return old_trades
        all_t = merge_trades_for_cache(new_trades, old_trades)
        save_trades_cache(all_t, api_key)
        return all_t
    except Exception as e:
        if log_cb: log_cb("ERROR", f"Ошибка API TMM: {e}")
        return old_trades
    finally:
        TMM_CACHE_UPDATE_LOCK.release()

def get_trades(api_key, log_cb=None):
    global LAST_TMM_CACHE_USED_STALE, LAST_TMM_CACHE_LAST_UPDATE
    LAST_TMM_CACHE_USED_STALE = False
    trades, lu = load_trades_cache(api_key)
    LAST_TMM_CACHE_LAST_UPDATE = lu
    if not trades:
        if log_cb: log_cb("INFO", "Загрузка сделок впервые...")
        return update_trades_cache(api_key, log_cb=log_cb)
    if lu:
        try:
            h = (datetime.now() - datetime.fromisoformat(lu)).total_seconds() / 3600
            if h > 1:
                if log_cb: log_cb("WARN", f"Данные сделок устарели на {h:.1f}ч, обновляем...")
                updated = update_trades_cache(api_key, log_cb=log_cb)
                LAST_TMM_CACHE_USED_STALE = LAST_TMM_API_STATUS is not None
                return updated
            else:
                if log_cb: log_cb("INFO", f"Загружена локальная база сделок: {len(trades)}")
        except: pass
    return trades

def get_trade_time_range(trades):
    times = []
    for trade in trades or []:
        value = parse_trade_time(trade, True)
        if value:
            times.append(value)
    if not times:
        return None, None
    return min(times), max(times)

def format_date_set(dates):
    values = sorted({date for date in dates if date})
    if not values:
        return "неизвестная дата"
    if len(values) == 1:
        return values[0].strftime("%d.%m.%Y")
    return f"{values[0].strftime('%d.%m.%Y')}-{values[-1].strftime('%d.%m.%Y')}"

# ====================== УТИЛИТЫ ======================
VIDEO_GLOBS = ('*.mp4', '*.mkv', '*.avi', '*.mov', '*.ts')

def parse_obs_filename(fn):
    """Распознает время старта видео из имени файла OBS (с поддержкой пробелов и подчеркиваний)"""
    n = os.path.splitext(fn)[0]
    n = n.replace('_', ' ') # Приводим "2026-06-14_21-24-50" к общему виду "2026-06-14 21-24-50"
    if ' ' in n:
        p = n.split(' ')
        if len(p) >= 2:
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
                try:
                    # Парсим как локальное время
                    return datetime.strptime(f"{p[0]} {p[1].replace('-', ':')}", fmt)
                except: pass
    return None

def iter_video_files(folder):
    if not folder or not os.path.exists(folder):
        return
    for ext in VIDEO_GLOBS:
        yield from Path(folder).glob(ext)

def get_video_quick_info(vp):
    try:
        s = os.stat(vp)
    except OSError:
        return None
    if time.time() - s.st_mtime < 180:
        return None
    file_size_mb = s.st_size / 1024 / 1024
    if file_size_mb <= 0.5:
        return None
    parsed_time = parse_obs_filename(os.path.basename(vp))
    if parsed_time:
        start_time = parsed_time.astimezone(timezone.utc)
        start_method = "имя файла OBS"
    else:
        start_time = datetime.fromtimestamp(s.st_ctime).astimezone(timezone.utc)
        start_method = "время создания файла Windows (ctime)"
    return {
        'path': vp,
        'name': os.path.basename(vp),
        'start_time': start_time,
        'size_mb': file_size_mb,
        'start_method': start_method,
    }

def get_video_date_index(folder):
    videos = []
    for vf in iter_video_files(folder):
        info = get_video_quick_info(str(vf))
        if info:
            videos.append(info)
    videos.sort(key=lambda v: v['start_time'], reverse=True)
    return videos

def get_video_duration(vp):
    """Вычисляет точную длительность видеофайла с помощью FFmpeg"""
    ff = get_ffmpeg_path()
    if not ff: return 0
    try:
        si = None; cf = 0
        if sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            cf = 0x08000000  # CREATE_NO_WINDOW
        r = subprocess.run([ff, "-i", vp], capture_output=True, text=True, startupinfo=si, creationflags=cf, timeout=15)
        content = r.stderr or r.stdout
        for line in content.split('\n'):
            if "Duration:" in line:
                dur_str = line.split("Duration:")[1].split(",")[0].strip()
                parts = dur_str.split(":")
                if len(parts) == 3:
                    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except Exception as e:
        log_to_file("ERROR", f"Ошибка получения длительности {os.path.basename(vp)}: {e}")
    return 0

def get_video_info(vp):
    s = os.stat(vp)
    file_mtime = s.st_mtime
    file_size_mb = s.st_size / 1024 / 1024

    # Пытаемся получить информацию из локального кэша, чтобы разгрузить ПК
    cached = get_cached_video_info(vp)
    if cached and abs(cached['file_mtime'] - file_mtime) < 1.0 and abs(cached['size_mb'] - file_size_mb) < 0.01:
        return {
            'path': vp,
            'name': os.path.basename(vp),
            'start_time': cached['start_time'],
            'size_mb': cached['size_mb'],
            'duration_sec': cached['duration_sec'],
            'start_method': cached['start_method']
        }

    # Если кэша нет или файл обновился - выполняем чтение заново
    ct_utc = datetime.fromtimestamp(s.st_ctime).astimezone(timezone.utc)
    pt = parse_obs_filename(os.path.basename(vp))
    if pt:
        pt_utc = pt.astimezone(timezone.utc)
    else:
        pt_utc = None

    dur = get_video_duration(vp)
    info = {
        'path': vp,
        'name': os.path.basename(vp),
        'start_time': pt_utc or ct_utc,  # Всегда точное UTC время старта видео
        'size_mb': file_size_mb,
        'duration_sec': dur if dur > 0 else 28800,
        'start_method': "имя файла OBS" if pt else "время создания файла Windows (ctime)"
    }

    save_cached_video_info(vp, info, file_mtime)
    return info

def video_overlaps_tmm_dates(video, dates):
    if not dates:
        return True
    selected_dates = {
        value.date() if isinstance(value, datetime) else value
        for value in dates
        if value
    }
    if not selected_dates:
        return True
    start_time = video.get("start_time")
    if not start_time:
        return False
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    duration = max(0.0, float(video.get("duration_sec") or 0.0))
    end_time = start_time + timedelta(seconds=duration)
    tmm_tz = get_tmm_timezone()
    for selected_date in selected_dates:
        day_start = datetime.combine(selected_date, datetime.min.time(), tzinfo=tmm_tz).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)
        if start_time < day_end and end_time > day_start:
            return True
    return False

def get_all_videos(folder, days=None, dates=None):
    if not folder or not os.path.exists(folder): return []
    videos = []
    for vf in iter_video_files(folder):
        quick = get_video_quick_info(str(vf))
        if not quick:
            continue
        info = get_video_info(str(vf))
        if info['size_mb'] > 0.5: videos.append(info)
    videos.sort(key=lambda v: v['start_time'], reverse=True)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        videos = [v for v in videos if v['start_time'] >= cutoff]
    if dates:
        # Для фильтрации дат переводим UTC время старта в локальную дату пользователя
        videos = [v for v in videos if video_overlaps_tmm_dates(v, dates)]
    return videos

def get_videos_for_tmm_dates(folder, dates):
    selected_dates = {
        value.date() if isinstance(value, datetime) else value
        for value in dates or []
        if value
    }
    if not selected_dates:
        return get_all_videos(folder)
    tmm_tz = get_tmm_timezone()
    candidates = []
    for quick in get_video_date_index(folder):
        start_date = quick['start_time'].astimezone(tmm_tz).date()
        # Include previous-day starts so long recordings crossing midnight are
        # still checked precisely with duration below.
        if start_date in selected_dates or (start_date + timedelta(days=1)) in selected_dates:
            candidates.append(quick['path'])
    videos = []
    for path in candidates:
        info = get_video_info(path)
        if info['size_mb'] > 0.5 and video_overlaps_tmm_dates(info, selected_dates):
            videos.append(info)
    videos.sort(key=lambda v: v['start_time'], reverse=True)
    return videos

def parse_trade_time(t, use_open=True):
    """Преобразует время сделки из TMM API в точное timezone-aware UTC datetime"""
    if not isinstance(t, dict): return None
    tv = t.get('open_time' if use_open else 'close_time')
    if not tv: return None
    try:
        # Вариант 1: API прислало UNIX timestamp в миллисекундах
        if isinstance(tv, (int, float)):
            ts = float(tv)
            if ts > 1_000_000_000_000: ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        # Вариант 2: API прислало форматированную ISO строку
        if isinstance(tv, str):
            normalized = tv.strip().replace('Z', '+00:00')
            try:
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
                    try:
                        return datetime.strptime(normalized.replace('T', ' '), fmt).replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
    except: pass
    return None

def filter_trades_by_tmm_dates(trades, dates):
    if not dates:
        return list(trades or [])
    selected_dates = {
        value.date() if isinstance(value, datetime) else value
        for value in dates
        if value
    }
    if not selected_dates:
        return list(trades or [])
    tmm_tz = get_tmm_timezone()
    result = []
    for trade in trades or []:
        open_time = parse_trade_time(trade, True)
        if open_time and open_time.astimezone(tmm_tz).date() in selected_dates:
            result.append(trade)
    return result

def match_trades_to_video(vi, trades):
    """Точное пересечение интервала сделки с фактическим временем видеофайла (работает по шкале UTC)"""
    vs = vi['start_time']
    ve = vs + timedelta(seconds=vi['duration_sec'])
    matched = []
    for t in trades:
        ot = parse_trade_time(t, True); ct = parse_trade_time(t, False)
        if not ot: continue
        actual_ct = ct if ct else (ot + timedelta(seconds=60))  # fallback если сделка еще открыта
        if max(vs, ot) <= min(ve, actual_ct):
            matched.append(t)
    return matched

def get_month_name_ru(date):
    months = ["январь","февраль","март","апрель","май","июнь",
              "июль","август","сентябрь","октябрь","ноябрь","декабрь"]
    return months[date.month - 1]

def get_week_folder(date):
    start = date - timedelta(days=date.weekday())
    end = start + timedelta(days=6)
    return f"{start.strftime('%d.%m')}-{end.strftime('%d.%m')}"

def get_day_folder(date):
    return f"{date.day} {get_month_name_ru(date)}"

def format_trade_percent(value):
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        number = 0.0
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return f"{text.replace('.', ',')}%"

def format_trade_duration(open_time, close_time):
    if not open_time or not close_time or close_time < open_time:
        return "open"
    duration = max(0, int(round((close_time - open_time).total_seconds())))
    minutes, seconds = divmod(duration, 60)
    return f"{seconds}s" if minutes == 0 else f"{minutes}m{seconds}s"

def get_trade_entry_reason(trade, max_length=48):
    """Возвращает безопасную для имени папки причину входа из первой колонки тегов TMM."""
    reasons = []
    for tag in trade.get("tags") or []:
        if not isinstance(tag, dict) or str(tag.get("column")) != "1":
            continue
        value = str(tag.get("name") or tag.get("title") or "").strip()
        if value and value not in reasons:
            reasons.append(value)
    if not reasons:
        return ""
    reason = " + ".join(reasons)
    reason = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", reason)
    reason = re.sub(r"\s+", " ", reason).strip(" ._")
    if len(reason) > max_length:
        reason = reason[:max_length].rstrip(" ._")
    return reason

def get_trade_folder_name(trade, trade_time):
    """Форматирует имя как ЧЧ-ММ-СС_ТИКЕР_ПРОЦЕНТ_Длительность_Причина."""
    s = str(trade.get("symbol", "?")).replace("/", "").replace(":", "")
    time_str = trade_time.strftime("%H-%M-%S")
    ot = parse_trade_time(trade, True)
    ct = parse_trade_time(trade, False)
    percent_str = format_trade_percent(trade.get("percent", 0))
    duration_str = format_trade_duration(ot, ct)
    base_name = f"{time_str}_{s}_{percent_str}_{duration_str}"
    entry_reason = get_trade_entry_reason(trade)
    return f"{base_name}_{entry_reason}" if entry_reason else base_name

def calculate_cut_window(trade, vi, buffer_before, buffer_after, time_offset=0):
    open_time = parse_trade_time(trade, True)
    close_time = parse_trade_time(trade, False)
    video_start = vi.get("start_time")
    video_duration = float(vi.get("duration_sec") or 0)
    if not open_time or not video_start:
        return None, "Нет времени сделки или видео"

    start_sec = max(
        0.0,
        (open_time - video_start).total_seconds() - buffer_before + time_offset
    ) if open_time >= video_start else 0.0

    if close_time and close_time >= video_start:
        end_sec = (close_time - video_start).total_seconds() + buffer_after + time_offset
    elif close_time and close_time < video_start:
        return None, "Сделка закрыта до начала видео"
    else:
        end_sec = start_sec + 60.0 + buffer_after

    end_sec = min(end_sec, video_duration)
    duration_sec = end_sec - start_sec
    if duration_sec < 2.0:
        return None, "Расчётный фрагмент короче двух секунд"
    return {
        "start_sec": start_sec,
        "end_sec": end_sec,
        "duration_sec": duration_sec,
        "open_time": open_time,
        "close_time": close_time,
    }, ""

# ====================== НАРЕЗКА ======================
def run_ffmpeg_command(cmd, timeout_sec, startupinfo=None, creationflags=0, cancel_event=None, process_cb=None):
    if cancel_event and cancel_event.is_set():
        return None, "", "", True
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        startupinfo=startupinfo, creationflags=creationflags
    )
    if process_cb:
        process_cb(process)
    started = time.monotonic()
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                cancelled = bool(cancel_event and cancel_event.is_set())
                return process.returncode, stdout, stderr, cancelled
            except subprocess.TimeoutExpired:
                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                    return process.returncode, stdout, stderr, True
                if time.monotonic() - started > timeout_sec:
                    process.kill()
                    process.communicate()
                    raise subprocess.TimeoutExpired(cmd, timeout_sec)
    finally:
        if process_cb:
            process_cb(None)

def cut_single_trade(trade, vi, bb, ba, out_dir, time_offset=0, folder_name_cb=None,
                     cancel_event=None, process_cb=None):
    of = ""
    try:
        window, window_error = calculate_cut_window(trade, vi, bb, ba, time_offset)
        if not window:
            return False, window_error
        ss = window["start_sec"]
        dur = window["duration_sec"]
        if cancel_event and cancel_event.is_set(): return False, "Остановлено"

        of = get_trade_output_path(trade, out_dir, folder_name_cb)
        if not of:
            return False, "Нет пути результата"
        os.makedirs(os.path.dirname(of), exist_ok=True)

        ff = get_ffmpeg_path()
        if not ff: return False, "Нет ffmpeg"

        # Быстрый input seek вместе с MP4 edit list скрывает служебные кадры до точки
        # реза. Не используем avoid_negative_ts=make_zero: он делал эти кадры
        # видимыми и создавал плавающий лишний буфер размером до интервала GOP.
        cmd = [
            ff, "-y", "-ss", f"{ss:.3f}", "-i", vi['path'], "-t", f"{dur:.3f}",
            "-map", "0:v:0", "-map", "0:a?", "-c", "copy", of
        ]

        si = None; cf = 0
        if sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            # Скрытое окно + приоритет "Ниже нормального" (0x00004000) для полного отсутствия лагов при торговле
            cf = 0x08000000 | 0x00004000

        timeout_sec = max(1800, int(dur * 10 + 600))
        returncode, _, stderr, cancelled = run_ffmpeg_command(
            cmd, timeout_sec, startupinfo=si, creationflags=cf,
            cancel_event=cancel_event, process_cb=process_cb
        )
        if cancelled:
            if os.path.exists(of):
                try: os.remove(of)
                except: pass
            return False, "Остановлено"
        if returncode == 0: return True, f"OK {os.path.getsize(of)/1024/1024:.1f}MB"

        # Резервное перекодирование поддерживает источники, которые нельзя без
        # преобразования поместить в MP4.
        log_to_file("WARN", f"Быстрая нарезка не удалась для {trade.get('symbol','?')}; пробуем перекодирование")
        cmd2 = [
            ff, "-y", "-ss", f"{ss:.3f}", "-i", vi['path'], "-t", f"{dur:.3f}",
            "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-movflags", "+faststart", of
        ]
        returncode2, _, stderr2, cancelled2 = run_ffmpeg_command(
            cmd2, timeout_sec, startupinfo=si, creationflags=cf,
            cancel_event=cancel_event, process_cb=process_cb
        )
        if cancelled2:
            if os.path.exists(of):
                try: os.remove(of)
                except: pass
            return False, "Остановлено"
        if returncode2 == 0: return True, f"OK {os.path.getsize(of)/1024/1024:.1f}MB"

        log_to_file("ERROR", f"FFmpeg Error Output для {trade.get('symbol','?')}: {stderr or stderr2}")
        return False, "Ошибка ffmpeg"
    except subprocess.TimeoutExpired:
        log_to_file("ERROR", f"Превышено динамическое время ожидания FFmpeg при нарезке сделки {trade.get('id','0')}")
        # Очищаем поврежденный файл, если он остался на диске
        if of and os.path.exists(of):
            try: os.remove(of)
            except: pass
        return False, "Таймаут FFmpeg"
    except Exception as e:
        # КРИТИЧЕСКИЙ АУДИТ: Пишем полный traceback ошибки в app.log для точной отладки
        log_to_file("ERROR", f"Критическое исключение при нарезке {trade.get('symbol','?')}: {e}\n{traceback.format_exc()}")
        if of and os.path.exists(of):
            try: os.remove(of)
            except: pass
        return False, f"Ошибка: {str(e)[:30]}"

def cut_trades_parallel(trades, vi, bb, ba, out_dir, max_workers=1, time_offset=0,
                        progress_cb=None, log_cb=None, folder_name_cb=None,
                        cancel_event=None, process_cb=None, job_ids=None):
    # По умолчанию max_workers=1 для предотвращения перегрузки диска и конфликтов записи
    results = []

    def run_trade(trade):
        trade_id = str(trade.get("id", ""))
        job_id = (job_ids or {}).get(trade_id)
        update_processing_job(job_id, "running")
        ok, message = cut_single_trade(
            trade, vi, bb, ba, out_dir, time_offset,
            folder_name_cb, cancel_event, process_cb
        )
        if ok:
            output_path = get_trade_output_path(trade, out_dir, folder_name_cb)
            update_processing_job(job_id, "done", message, output_path)
        elif message == "Остановлено":
            update_processing_job(job_id, "stopped", message)
        else:
            update_processing_job(job_id, "error", message)
        return ok, message

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_trade = {
            executor.submit(run_trade, t): t
            for t in trades
        }
        for future in as_completed(future_to_trade):
            trade = future_to_trade[future]
            try:
                ok, msg = future.result()
                results.append((trade, ok, msg))
                if progress_cb: progress_cb()
                if log_cb:
                    level = "INFO" if ok else "ERROR"
                    log_cb(level, f"{'OK' if ok else 'ERR'} {trade.get('symbol','?')} - {msg}")
            except Exception as e:
                update_processing_job((job_ids or {}).get(str(trade.get("id", ""))), "error", str(e))
                results.append((trade, False, str(e)))
                if log_cb: log_cb("ERROR", f"Сбой потока нарезки: {e}\n{traceback.format_exc()}")
    return results

# ====================== ЛОКАЛЬНЫЙ ВИДЕОСЕРВЕР ======================
class LocalVideoRequestHandler(BaseHTTPRequestHandler):
    server_version = "TMMVideoServer/1.0"

    def log_message(self, _format, *_args):
        return

    def _send_text(self, status, body, content_type="text/plain; charset=utf-8", head_only=False):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _authorized(self, query):
        provided = (parse_qs(query).get("key") or [""])[0]
        expected = getattr(self.server, "access_token", "")
        return bool(expected and secrets.compare_digest(provided, expected))

    def _serve_watch_page(self, trade_id, head_only):
        clip_path = get_registered_clip(trade_id)
        if not clip_path:
            self._send_text(404, "Видео удалено или ещё не нарезано", head_only=head_only)
            return
        token = getattr(self.server, "access_token", "")
        media_url = f"/media/{quote(trade_id, safe='')}?key={quote(token, safe='')}"
        title = html.escape(os.path.basename(clip_path))
        body = f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{title}</title><style>
html,body{{margin:0;background:#111522;color:#dce2e8;font-family:Segoe UI,Arial,sans-serif;height:100%}}
main{{box-sizing:border-box;display:flex;flex-direction:column;gap:12px;height:100%;padding:16px}}
h1{{font-size:15px;font-weight:500;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
video{{background:#000;border-radius:8px;max-height:calc(100vh - 62px);width:100%;flex:1}}
</style></head><body><main><h1>{title}</h1>
<video controls preload=\"metadata\" autoplay src=\"{media_url}\"></video>
</main></body></html>"""
        self.send_response(200)
        encoded = body.encode("utf-8")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; media-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        if not head_only:
            self.wfile.write(encoded)

    def _serve_media(self, trade_id, head_only):
        clip_path = get_registered_clip(trade_id)
        if not clip_path:
            self._send_text(404, "Видео не найдено", head_only=head_only)
            return
        try:
            source = open(clip_path, "rb")
            size = os.fstat(source.fileno()).st_size
        except OSError:
            _set_missing_clip(trade_id)
            self._send_text(404, "Видео удалено", head_only=head_only)
            return
        start, end = 0, size - 1
        range_header = self.headers.get("Range", "").strip()
        status = 200
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                source.close()
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                suffix = int(match.group(2))
                if suffix <= 0:
                    self.send_response(416); self.end_headers(); source.close(); return
                start = max(0, size - suffix)
                end = size - 1
            if start >= size or start < 0 or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                source.close()
                return
            end = min(end, size - 1)
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(clip_path)[0] or "video/mp4")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, no-cache")
        self.send_header("Content-Disposition", "inline")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            source.close()
            return
        try:
            with source:
                source.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle(self, head_only=False):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_text(200, '{"status":"ok"}', "application/json; charset=utf-8", head_only)
            return
        if not self._authorized(parsed.query):
            self._send_text(403, "Доступ запрещён", head_only=head_only)
            return
        match = re.fullmatch(r"/(watch|trade|media)/([A-Za-z0-9_-]+)", parsed.path)
        if not match:
            self._send_text(404, "Страница не найдена", head_only=head_only)
            return
        route, trade_id = match.groups()
        if route in ("watch", "trade"):
            self._serve_watch_page(trade_id, head_only)
        else:
            self._serve_media(trade_id, head_only)

    def do_GET(self):
        self._handle(False)

    def do_HEAD(self):
        self._handle(True)


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class LocalVideoServer:
    def __init__(self, port, token):
        self.host = "127.0.0.1"
        self.port = int(port)
        self.token = token
        self.httpd = None
        self.thread = None

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and self.httpd)

    def start(self):
        if self.running:
            return True, "Уже работает"
        try:
            httpd = ExclusiveThreadingHTTPServer((self.host, self.port), LocalVideoRequestHandler)
            httpd.daemon_threads = True
            httpd.access_token = self.token
            self.port = int(httpd.server_address[1])
            self.httpd = httpd
            self.thread = threading.Thread(target=httpd.serve_forever, name="TMM local video server", daemon=True)
            self.thread.start()
            return True, f"{self.host}:{self.port}"
        except OSError as error:
            self.httpd = None
            self.thread = None
            return False, str(error)

    def stop(self):
        httpd, thread = self.httpd, self.thread
        self.httpd = None
        self.thread = None
        if httpd:
            try:
                shutdown_thread = threading.Thread(
                    target=httpd.shutdown,
                    name="TMM local video server shutdown",
                    daemon=True,
                )
                shutdown_thread.start()
                shutdown_thread.join(timeout=2)
            except Exception as error:
                log_to_file("WARN", f"Local video server shutdown failed: {error}")
            try:
                httpd.server_close()
            except Exception as error:
                log_to_file("WARN", f"Local video server close failed: {error}")
        if thread and thread.is_alive():
            thread.join(timeout=1)

    def watch_url(self, trade_id):
        return f"http://{self.host}:{self.port}/watch/{quote(str(trade_id), safe='')}?key={quote(self.token, safe='')}"


def fetch_trades_by_ids(api_key, trade_ids, max_pages=50):
    remaining = {str(value) for value in trade_ids if value is not None}
    found = {}
    cooldown = tmm_api_cooldown_remaining()
    if cooldown > 0:
        raise TMMRateLimitError(tmm_rate_limit_message(cooldown))
    headers = {"API-KEY": api_key, "Accept": "application/json"}
    for page in range(1, max_pages + 1):
        if not remaining:
            break
        response = tmm_request("GET",
            "https://tradermake.money/api/v2/trades", headers=headers,
            params={"limit": 100, "page": page, "sort": "desc"}, timeout=15
        )
        if response.status_code == 429:
            raise_tmm_rate_limit(response)
        response.raise_for_status()
        trades = response.json().get("data", [])
        if not trades:
            break
        for trade in trades:
            tid = str(trade.get("id", ""))
            if tid in remaining:
                found[tid] = trade
                remaining.remove(tid)
    return found


def write_trade_video_link(api_key, trade, video_link):
    tid = str(trade.get("id", ""))
    if not tid:
        raise ValueError("У сделки отсутствует ID")
    response = tmm_request("POST",
        f"https://tradermake.money/api/v2/trades/{tid}/update",
        headers={"API-KEY": api_key, "Accept": "application/json"},
        json={
            "description": trade.get("description") or "",
            "conclusion": trade.get("conclusion") or "",
            "video_link": video_link,
        },
        timeout=15,
    )
    if response.status_code == 429:
        raise_tmm_rate_limit(response)
    response.raise_for_status()
    return True

def generate_dev_info():
    info = f"""================================================================================
TMM VIDEO CUTTER v24.13.15 - ТЕХНИЧЕСКАЯ ДОКУМЕНТАЦИЯ
================================================================================
1. НАЗНАЧЕНИЕ
Программа сопоставляет сделки Trader Make Money с записями OBS по шкале UTC
и создаёт отдельные видеофрагменты для анализа сделок.

2. ФАКТИЧЕСКАЯ АРХИТЕКТУРА
- TMM_Cutter.exe содержит базовую версию app.py, собранную PyInstaller.
- app.py является исходником; его изменение требует новой сборки EXE.
- custom_logic.py предоставляет менеджер одного активного патча.
- updates/active_patch.py загружается при старте и получает объект TMMVideoCutter.
- Старые файлы в updates/archive/ не исполняются.

3. ДАННЫЕ
- config.json: настройки и API-ключ, зашифрованный Windows DPAPI.
- trades_cache.json: локальная база сделок, обновляемая автоматически.
- data.db: пути готовых клипов, очередь ссылок TMM и метаданные видео.
- app.log: журнал работы.
- runtime/: постоянные библиотеки Tcl/Tk для стабильного запуска интерфейса без зависимости от папки _MEI.

4. ВИДЕО И ВРЕМЯ
- Поддерживаются MP4, MKV, AVI, MOV и TS.
- Рекомендуемое имя OBS: YYYY-MM-DD HH-MM-SS.ext.
- Если имя не распознано, используется время создания файла Windows.
- Активные записи, изменённые менее трёх минут назад, пропускаются.

5. НАРЕЗКА
- Быстрый режим без перекодирования включён автоматически.
- MP4 edit list скрывает кадры до точки реза и сохраняет заданный буфер.
- При несовместимости исходника автоматически используется H.264/AAC.
- Жёсткого ограничения длительности клипа нет; конец ограничен только исходным видео.
- Обработка выполняется последовательно, чтобы не перегружать диск.
- Кнопка остановки отменяет очередь и завершает активный FFmpeg.
- Дата и время папки берутся в часовом поясе профиля TMM, а не Windows.
- Часовой пояс TMM сохраняется локально и продолжает работать при сбое сайта.
- Формат папки сделки: ЧЧ-ММ-СС_ТИКЕР_ПРОЦЕНТ_Длительность_ПричинаВхода.
- Причина входа берётся из первой колонки тегов TMM, очищается для Windows и ограничивается 48 символами.
- Если причина не заполнена, имя остаётся без дополнительного суффикса.
- Примеры: 00-38-17_ESPORTSUSDT_1%_10s_отскок и 14-30-05_BTCUSDT_-0,5%_5m30s.

6. ПАТЧИ
- Кнопка "Установить патч" принимает Python-код с функцией apply_patch(app).
- Одновременно активен только updates/active_patch.py.
- Перед заменой активный патч сохраняется в updates/archive/.
- Патч имеет полный доступ к программе и файлам: используйте только доверенный код.

7. АВТООБРАБОТКА
- При включении сделки TMM обновляются перед каждым циклом.
- Готовые записи OBS сканируются от старых к новым.
- Сделка считается готовой только пока её зарегистрированный MP4 существует.
- Удалённый клип автоматически возвращается в очередь нарезки.
- Проверка повторяется через auto_process_interval секунд.

8. ЛОКАЛЬНЫЙ СЕРВЕР И ССЫЛКИ TMM
- Сервер запускается вместе с программой на 127.0.0.1:8765 и останавливается при закрытии.
- Выдаются только зарегистрированные клипы; произвольные пути к файлам запрещены.
- Секретный ключ установки защищает ссылки от случайного доступа других сайтов.
- HTTP Range и код 206 обеспечивают перемотку видео в браузере.
- После успешной нарезки video_link сделки обновляется через API TMM.
- При недоступности TMM ссылка остаётся в очереди и отправляется позже с задержкой.
- Описание и вывод сделки читаются заново и не перезаписываются устаревшими данными.

9. ДИАГНОСТИКА И ПРЕДПРОСМОТР
- Кнопка "Проверить систему" только читает состояние и ничего не исправляет автоматически.
- Проверяются API, DPAPI, FFmpeg, папки, SQLite, сервер, клипы и ссылки.
- Панель показывает количество готовых/удалённых клипов и ожидающих ссылок.
- Кнопка "Просмотр" показывает расчётные тайм-коды и путь без запуска FFmpeg.

10. ОЧЕРЕДЬ И ССЫЛКИ
- История обработки хранит ожидающие, активные, готовые, ошибочные и остановленные задания.
- После аварийного закрытия незавершённые задания помечаются как прерванные и доступны для повтора.
- Окно ссылок показывает состояние каждой ссылки и позволяет повторить только выбранную сделку.
- Ручная обработка по датам запускается одной кнопкой, а кнопка СТОП всегда остаётся крупной.

11. API И КАРАНТИН
- Все запросы TMM проходят через общий ограничитель с паузой между запросами.
- При HTTP 429 учитывается Retry-After и выполняется ограниченное число повторов.
- Сканирование хранилища ничего не перемещает и не удаляет автоматически.
- Подозрительные файлы можно вручную переместить в карантин и восстановить обратно.
- Постоянного удаления файлов из интерфейса нет.

12. СБОРКА
- Запущенный EXE нельзя перезаписать из самого себя.
- Для новой базовой версии запустите app.py через Python и соберите PyInstaller.
- Для небольших изменений поведения используйте менеджер патчей.
================================================================================
"""
    try:
        with open(DEVINFO_PATH, "w", encoding="utf-8") as f: f.write(info)
    except: pass
    return info

class TMMVideoCutter:
    def __init__(self, root, embedded=False, container=None):
        self.embedded = bool(embedded)
        self.container = container or root
        self.root = root if not self.embedded else self.container.winfo_toplevel()
        self.cfg = load_config(); self.running = False; self.stop_flag = False
        self._main_thread_id = threading.get_ident()
        self._ui_queue = queue.Queue()
        self._timezone_refresh_lock = threading.Lock()
        self._last_timezone_warning = ""
        self._diagnostics_running = False
        self._storage_scan_running = False
        self._storage_candidates = []
        self._storage_stop_event = threading.Event()
        self._date_task_lock = threading.Lock()
        self._date_task_running = False
        self.api_key = self.cfg.get("tmm_api_key", "")
        self.trade_filter_mode = normalize_trade_filter_mode(self.cfg.get("trade_filter_mode"))
        self.my_api_key_ids = parse_api_key_ids(self.cfg.get("my_api_key_ids"))
        self.cfg["trade_filter_mode"] = self.trade_filter_mode
        self.cfg["my_api_key_ids"] = self.my_api_key_ids
        try:
            set_tmm_timezone(self.cfg.get("tmm_timezone", "UTC"))
        except ValueError:
            self.cfg["tmm_timezone"] = set_tmm_timezone("UTC")
            self.cfg["tmm_timezone_updated_at"] = ""
        self.obs_folder = self.cfg.get("obs_folder", "")
        self.output_folder = self.cfg.get("output_folder") or CUT_VIDEOS_DIR
        self.buffer_before = int(self.cfg.get("buffer_before", 5))
        self.buffer_after = int(self.cfg.get("buffer_after", 5))
        self.time_offset = int(self.cfg.get("time_offset", 0))
        self.auto_sync_video_links = bool(self.cfg.get("auto_sync_video_links", True))
        self.local_server_port = int(self.cfg.get("local_server_port", 8765))
        self.local_server_token = self.cfg.get("local_server_token", "") or secrets.token_urlsafe(24)
        self.cfg["local_server_token"] = self.local_server_token
        self.cfg["local_server_port"] = self.local_server_port
        save_config(self.cfg)
        init_db()
        self.local_server = LocalVideoServer(self.local_server_port, self.local_server_token)
        self._last_server_error = ""
        self._link_sync_lock = threading.Lock()
        self._link_sync_running = False
        self._cache_update_lock = threading.Lock()
        self._cache_update_running = False
        self._cache_retry_scheduled = False
        self.auto_process_active = False
        self.auto_stop_event = threading.Event()
        self.processing_cancel_event = threading.Event()
        self._processing_state_lock = threading.Lock()
        self._active_process_lock = threading.Lock()
        self.processing_active = False
        self.processing_source = ""
        self.active_ffmpeg_process = None
        self._drop_targets = []
        self._drop_ole_initialized = False
        self._drop_hover_active = False
        self._drop_hover_after_id = None
        self._drop_hover_step = 0
        self.setup_ui()
        self._install_keyboard_shortcuts()
        if not self.embedded:
            self.root.after(100, self._install_file_drop_target)
        self.root.after(50, self._drain_ui_queue)
        if CUSTOM_LOGIC and hasattr(CUSTOM_LOGIC, "apply_active_patch"):
            CUSTOM_LOGIC.apply_active_patch(self)
        self.show_welcome()
        self.root.after(150, self.start_local_server)
        self.root.after(
            350,
            lambda: self._update_api_status(
                f"TMM API: не проверялся ({get_tmm_timezone_name()})",
                COLORS["text_dim"]
            )
        )
        self.root.after(2200, self.auto_update_cache)
        self.root.after(1200, self.reconcile_processed_files_async)
        self.root.after(1800, self._scheduled_status_refresh)
        self.root.after(30000, self._scheduled_link_sync)
        self.root.after(1000, generate_dev_info)
        if self.cfg.get("auto_process"):
            self.start_auto_process()
        if not self.embedded:
            self.root.protocol("WM_DELETE_WINDOW", self.save_on_exit)
        self.root.after(250, self.show_main_window)

    def show_main_window(self):
        if self.embedded:
            return
        try:
            self.root.update_idletasks()
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
            if sys.platform == "win32":
                hwnd = self.root.winfo_id()
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception as error:
            log_to_file("WARN", f"Main window activation failed: {error}")

    def _drain_ui_queue(self):
        try:
            while True:
                callback, args, kwargs = self._ui_queue.get_nowait()
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    log_to_file("ERROR", f"Ошибка обновления интерфейса: {e}")
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(50, self._drain_ui_queue)

    def run_on_ui(self, callback, *args, **kwargs):
        if threading.get_ident() == self._main_thread_id:
            return callback(*args, **kwargs)
        self._ui_queue.put((callback, args, kwargs))
        return None

    def _install_keyboard_shortcuts(self):
        try:
            self.root.bind_all("<Control-KeyPress>", self._handle_text_shortcut, add="+")
        except tk.TclError:
            pass

    @staticmethod
    def _shortcut_action_from_event(event):
        keycode_actions = {
            65: "select_all",  # A / Ф
            67: "copy",        # C / С
            86: "paste",       # V / М
            88: "cut",         # X / Ч
        }
        try:
            action = keycode_actions.get(int(getattr(event, "keycode", 0) or 0))
            if action:
                return action
        except (TypeError, ValueError):
            pass
        key = str(getattr(event, "keysym", "") or "").lower()
        return {
            "a": "select_all", "cyrillic_ef": "select_all",
            "c": "copy", "cyrillic_es": "copy",
            "v": "paste", "cyrillic_em": "paste",
            "x": "cut", "cyrillic_che": "cut",
        }.get(key, "")

    @staticmethod
    def _is_text_shortcut_widget(widget):
        try:
            tags = {str(tag) for tag in widget.bindtags()}
            widget_class = str(widget.winfo_class())
        except tk.TclError:
            return False
        return bool(tags & {"Entry", "TEntry", "Text"}) or widget_class in {"Entry", "TEntry", "Text"}

    def _widget_belongs_to_tmm_tab(self, widget):
        if not self.embedded:
            return True
        current = widget
        while current is not None:
            if current == self.container:
                return True
            try:
                parent_name = current.winfo_parent()
                current = current._nametowidget(parent_name) if parent_name else None
            except Exception:
                return False
        return False

    def _handle_text_shortcut(self, event):
        widget = event.widget
        if not self._widget_belongs_to_tmm_tab(widget):
            return None
        if not self._is_text_shortcut_widget(widget):
            return None
        action = self._shortcut_action_from_event(event)
        if not action:
            return None
        if action in ("paste", "cut") and self._is_readonly_text_widget(widget):
            return "break"
        if action == "select_all":
            self._select_all_text(widget)
        elif action == "copy":
            self._copy_text(widget)
        elif action == "cut":
            self._cut_text(widget)
        elif action == "paste":
            self._paste_text(widget)
        return "break"

    @staticmethod
    def _is_readonly_text_widget(widget):
        try:
            return str(widget.cget("state")) in {"disabled", "readonly"}
        except tk.TclError:
            return False

    def _select_all_text(self, widget):
        try:
            widget.event_generate("<<SelectAll>>")
        except tk.TclError:
            pass
        try:
            widget_class = str(widget.winfo_class())
        except tk.TclError:
            return
        try:
            if widget_class == "Text":
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "end-1c")
                widget.see("insert")
            else:
                widget.selection_range(0, tk.END)
                widget.icursor(tk.END)
        except tk.TclError:
            pass

    def _get_selected_text(self, widget):
        try:
            if str(widget.winfo_class()) == "Text":
                return widget.get("sel.first", "sel.last")
            return widget.selection_get()
        except tk.TclError:
            return ""

    def _delete_selected_text(self, widget):
        try:
            if str(widget.winfo_class()) == "Text":
                widget.delete("sel.first", "sel.last")
            else:
                widget.delete("sel.first", "sel.last")
            return True
        except tk.TclError:
            return False

    def _copy_text(self, widget):
        text = self._get_selected_text(widget)
        if not text:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            pass

    def _cut_text(self, widget):
        self._copy_text(widget)
        self._delete_selected_text(widget)

    def _paste_text(self, widget):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        self._delete_selected_text(widget)
        try:
            widget.insert(tk.INSERT, text)
        except tk.TclError:
            pass

    def _paste_from_clipboard(self, event):
        widget = event.widget
        if self._is_readonly_text_widget(widget):
            return "break"
        self._paste_text(widget)
        return "break"

    def _set_drop_hover(self, active):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self._set_drop_hover, active)
            return
        active = bool(active)
        if self._drop_hover_active == active:
            return
        self._drop_hover_active = active
        if active:
            self._drop_hover_step = 0
            if hasattr(self, "drop_label"):
                self.drop_label.config(
                    text="Отпустите видео здесь\nГотово к нарезке",
                    fg="white"
                )
            self._animate_drop_hover()
            return
        if self._drop_hover_after_id:
            try:
                self.root.after_cancel(self._drop_hover_after_id)
            except tk.TclError:
                pass
            self._drop_hover_after_id = None
        try:
            if hasattr(self, "drop_frame"):
                self.drop_frame.config(
                    bg=COLORS["bg"],
                    highlightbackground=COLORS["accent"],
                    highlightthickness=2
                )
            if hasattr(self, "drop_label"):
                self.drop_label.config(
                    text=getattr(self, "_drop_default_text", self.drop_label.cget("text")),
                    bg=COLORS["bg"],
                    fg=COLORS["accent"]
                )
        except tk.TclError:
            pass

    def _animate_drop_hover(self):
        if not self._drop_hover_active:
            return
        palette = [
            ("#203257", "#7ab8e8"),
            ("#22365f", "#8bc7f2"),
            ("#243a66", "#7ab8e8"),
            ("#22365f", "#6baee0"),
        ]
        bg, border = palette[self._drop_hover_step % len(palette)]
        self._drop_hover_step += 1
        try:
            if hasattr(self, "drop_frame"):
                self.drop_frame.config(bg=bg, highlightbackground=border, highlightthickness=2)
            if hasattr(self, "drop_label"):
                self.drop_label.config(bg=bg, fg="white")
            self._drop_hover_after_id = self.root.after(220, self._animate_drop_hover)
        except tk.TclError:
            self._drop_hover_after_id = None

    def _install_file_drop_target(self):
        if sys.platform != "win32":
            return
        if self._drop_targets:
            return
        try:
            self.root.update_idletasks()
        except tk.TclError:
            return
        try:
            ole32 = ctypes.WinDLL("ole32", use_last_error=True)
            ole32.OleInitialize.argtypes = [ctypes.c_void_p]
            ole32.OleInitialize.restype = ctypes.c_long
            hr = ole32.OleInitialize(None)
            if hr not in (S_OK, 1):  # S_FALSE means OLE was already initialized on this thread.
                raise OSError(f"OleInitialize failed: 0x{hr & 0xFFFFFFFF:08X}")
            self._drop_ole_initialized = True

            def schedule_files(files):
                try:
                    self.root.after(0, self._handle_dropped_files, files)
                except tk.TclError:
                    pass

            widgets = [self.root]
            for attr_name in ("drop_frame", "drop_label"):
                widget = getattr(self, attr_name, None)
                if widget is not None:
                    widgets.append(widget)

            seen_hwnds = set()
            errors = []
            for widget in widgets:
                try:
                    hwnd = int(widget.winfo_id())
                except (tk.TclError, ValueError):
                    continue
                if not hwnd or hwnd in seen_hwnds:
                    continue
                seen_hwnds.add(hwnd)
                target = WindowsFileDropTarget(schedule_files)
                try:
                    target.register(hwnd)
                    self._drop_targets.append((hwnd, target))
                except Exception as error:
                    errors.append(f"{hwnd}: {error}")
            if not self._drop_targets:
                raise RuntimeError("; ".join(errors) or "нет доступных окон для drag-and-drop")
            if errors:
                log_to_file("WARN", "Drag-and-drop частично включён: " + "; ".join(errors))
        except Exception as error:
            self._drop_targets = []
            if self._drop_ole_initialized:
                try:
                    ctypes.WinDLL("ole32", use_last_error=True).OleUninitialize()
                except Exception:
                    pass
                self._drop_ole_initialized = False
            log_to_file("WARN", f"Не удалось включить drag-and-drop: {error}")

    def _uninstall_file_drop_target(self):
        if sys.platform != "win32":
            return
        for hwnd, _target in list(self._drop_targets):
            try:
                WindowsFileDropTarget.revoke(hwnd)
            except Exception as error:
                log_to_file("WARN", f"Не удалось отключить drag-and-drop для окна {hwnd}: {error}")
        self._drop_targets = []
        if self._drop_ole_initialized:
            try:
                ctypes.WinDLL("ole32", use_last_error=True).OleUninitialize()
            except Exception as error:
                log_to_file("WARN", f"Не удалось завершить OLE drag-and-drop: {error}")
            self._drop_ole_initialized = False

    def _install_file_drop_target(self):
        if self.embedded:
            log_to_file("INFO", "Drag-and-drop disabled in embedded TMM Cutter tab")
            return
        if self._drop_targets:
            return
        if not DND_FILES or not hasattr(self.root, "drop_target_register"):
            log_to_file("WARN", "Drag-and-drop is unavailable: tkinterdnd2/tkdnd is not loaded")
            return

        widgets = [self.root]
        for attr_name in ("drop_frame", "drop_label"):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                widgets.append(widget)

        for widget in widgets:
            try:
                widget.drop_target_register(DND_FILES)
                drop_id = widget.dnd_bind("<<Drop>>", self._on_tk_drop)
                enter_id = widget.dnd_bind("<<DropEnter>>", self._on_tk_drop_enter)
                pos_id = widget.dnd_bind("<<DropPosition>>", self._on_tk_drop_position)
                leave_id = widget.dnd_bind("<<DropLeave>>", self._on_tk_drop_leave)
                self._drop_targets.append((widget, drop_id, enter_id, pos_id, leave_id))
            except Exception as error:
                log_to_file("WARN", f"Failed to register drag-and-drop for {widget}: {error}")
        if self._drop_targets:
            log_to_file("INFO", "Drag-and-drop target registered with tkinterdnd2")

    def _uninstall_file_drop_target(self):
        for widget, *_binding_ids in list(self._drop_targets):
            try:
                if hasattr(widget, "drop_target_unregister"):
                    widget.drop_target_unregister()
            except Exception as error:
                log_to_file("WARN", f"Failed to unregister drag-and-drop for {widget}: {error}")
        self._drop_targets = []

    def _parse_drop_data(self, data):
        if not data:
            return []
        try:
            return [str(item) for item in self.root.tk.splitlist(data)]
        except Exception:
            return [str(data)]

    def _on_tk_drop_enter(self, _event):
        self._set_drop_hover(True)
        return DND_COPY

    def _on_tk_drop_position(self, _event):
        if not self._drop_hover_active:
            self._set_drop_hover(True)
        return DND_COPY

    def _on_tk_drop_leave(self, _event):
        self._set_drop_hover(False)
        return DND_COPY

    def _on_tk_drop(self, event):
        try:
            self._handle_dropped_files(self._parse_drop_data(getattr(event, "data", "")))
        except Exception as error:
            self.log("ERROR", f"Drag-and-drop processing failed: {error}")
        finally:
            self._set_drop_hover(False)
        return DND_COPY

    def _handle_dropped_files(self, files):
        video_files = []
        for path in files or []:
            normalized = os.path.abspath(os.path.normpath(str(path)))
            if os.path.isfile(normalized) and os.path.splitext(normalized)[1].lower() in VIDEO_EXTENSIONS:
                video_files.append(normalized)
        if not video_files:
            self.log("WARN", "Перетащенный файл не является поддерживаемым видео")
            messagebox.showwarning("Видео", "Перетащите видеофайл: MP4, MKV, AVI, MOV или TS.")
            return
        if len(video_files) > 1:
            self.log("WARN", f"Перетащено несколько видеофайлов, запускаю первый: {os.path.basename(video_files[0])}")
        self.cut_single_video(video_files[0])

    def _update_api_status(self, text, color=None):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self._update_api_status, text, color)
            return
        if hasattr(self, "api_status_label"):
            self.api_status_label.config(text=text, fg=color or COLORS["text_dim"])

    def refresh_runtime_status(self):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self.refresh_runtime_status)
            return
        try:
            scope_ids = self._current_scope_trade_ids()
            counts = get_runtime_status_counts(scope_ids)
            if hasattr(self, "clips_status_label"):
                clip_color = COLORS["warning"] if counts["missing_clips"] else COLORS["success"]
                self.clips_status_label.config(
                    text=f"Клипы: {counts['valid_clips']} готово, {counts['missing_clips']} отсутствует",
                    fg=clip_color,
                )
            if hasattr(self, "links_status_label"):
                link_color = COLORS["warning"] if counts["pending"] or counts["link_errors"] else COLORS["success"]
                self.links_status_label.config(
                    text=f"Ссылки: {counts['synced']} отправлено, {counts['pending']} ожидает",
                    fg=link_color,
                )
            jobs = get_processing_job_counts(scope_ids)
            if hasattr(self, "queue_status_label"):
                queue_color = COLORS["warning"] if jobs["pending"] or jobs["running"] or jobs["problems"] else COLORS["success"]
                self.queue_status_label.config(
                    text=f"Очередь: {jobs['running']} выполняется, {jobs['pending']} ожидает, {jobs['problems']} проблем",
                    fg=queue_color,
                )
            self.refresh_queue_view()
            self.refresh_links_view()
        except Exception as error:
            log_to_file("WARN", f"Не удалось обновить панель статусов: {error}")

    def _scheduled_status_refresh(self):
        if self.stop_flag:
            return
        self.refresh_runtime_status()
        if self.root.winfo_exists():
            self.root.after(15000, self._scheduled_status_refresh)

    def refresh_tmm_timezone(self, force=False, api_key=None, log_success=False):
        key = (api_key or self.api_key or "").strip()
        cached_name = self.cfg.get("tmm_timezone", "UTC")
        try:
            cached_name = set_tmm_timezone(cached_name)
        except ValueError:
            cached_name = set_tmm_timezone("UTC")
            self.cfg["tmm_timezone"] = cached_name
            self.cfg["tmm_timezone_updated_at"] = ""

        if not key:
            self._update_api_status("TMM API: ключ не введён", COLORS["warning"])
            return cached_name

        cooldown = tmm_api_cooldown_remaining()
        if cooldown > 0:
            minutes = max(1, int((cooldown + 59) // 60))
            self._update_api_status(f"TMM API: лимит, пауза {minutes} мин", COLORS["warning"])
            return cached_name

        if not force:
            updated_text = self.cfg.get("tmm_timezone_updated_at", "")
            try:
                updated = datetime.fromisoformat(updated_text)
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - updated.astimezone(timezone.utc)
                if age < timedelta(hours=24):
                    return cached_name
            except (TypeError, ValueError):
                pass

        with self._timezone_refresh_lock:
            try:
                timezone_name = fetch_tmm_profile_timezone(key)
                changed = timezone_name != cached_name
                set_tmm_timezone(timezone_name)
                self.cfg["tmm_timezone"] = timezone_name
                self.cfg["tmm_timezone_updated_at"] = datetime.now(timezone.utc).isoformat()
                save_config(self.cfg)
                if changed or log_success:
                    self.log("INFO", f"Часовой пояс папок синхронизирован с TMM: {timezone_name}")
                self._update_api_status(f"TMM API: доступен ({timezone_name})", COLORS["success"])
                self._last_timezone_warning = ""
                return timezone_name
            except Exception as error:
                warning = f"Часовой пояс TMM недоступен; используется сохранённый {cached_name}: {error}"
                if warning != self._last_timezone_warning:
                    self.log("WARN", warning)
                    self._last_timezone_warning = warning
                self._update_api_status("TMM API: временно недоступен", COLORS["warning"])
                set_tmm_timezone(cached_name)
                return cached_name

    def refresh_tmm_timezone_async(self, force=False):
        threading.Thread(
            target=self.refresh_tmm_timezone,
            kwargs={"force": force, "log_success": True},
            name="TMM timezone sync",
            daemon=True,
        ).start()

    def _collect_diagnostics(self):
        checks = []

        def add(level, name, detail):
            checks.append({"level": level, "name": name, "detail": detail})

        api_key = (self.api_key or "").strip()
        if not api_key:
            add("ERROR", "TMM API", "API-ключ не введён")
        else:
            try:
                timezone_name = fetch_tmm_profile_timezone(api_key, timeout=10)
                add("OK", "TMM API", f"Доступен, часовой пояс {timezone_name}")
            except Exception as error:
                add("ERROR", "TMM API", f"Нет соединения: {error}")

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8-sig") as config_file:
                stored_key = str(json.load(config_file).get("tmm_api_key", ""))
            if stored_key.startswith("dpapi:"):
                add("OK", "API-ключ", "Зашифрован средствами Windows DPAPI")
            elif stored_key:
                add("WARN", "API-ключ", "Открытый ключ будет зашифрован при сохранении")
            else:
                add("WARN", "API-ключ", "Не сохранён")
        except Exception as error:
            add("ERROR", "Конфигурация", f"Не удалось прочитать: {error}")

        ffmpeg_path = get_ffmpeg_path()
        if ffmpeg_path:
            try:
                startupinfo = None
                creationflags = 0
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    creationflags = 0x08000000
                result = subprocess.run(
                    [ffmpeg_path, "-version"], capture_output=True, text=True,
                    timeout=10, startupinfo=startupinfo, creationflags=creationflags
                )
                if result.returncode == 0:
                    version_line = (result.stdout.splitlines() or ["ffmpeg"])[0]
                    add("OK", "FFmpeg", version_line[:100])
                else:
                    add("ERROR", "FFmpeg", "Команда проверки завершилась с ошибкой")
            except Exception as error:
                add("ERROR", "FFmpeg", str(error))
        else:
            add("ERROR", "FFmpeg", "Файл ffmpeg.exe не найден")

        if self.obs_folder and os.path.isdir(self.obs_folder):
            add("OK", "Папка OBS", self.obs_folder)
        else:
            add("ERROR", "Папка OBS", "Папка не выбрана или недоступна")
        output_folder = self.output_folder or CUT_VIDEOS_DIR
        if os.path.isdir(output_folder) and os.access(output_folder, os.W_OK):
            add("OK", "Папка сохранения", output_folder)
        else:
            add("ERROR", "Папка сохранения", "Папка недоступна для записи")

        try:
            conn = sqlite3.connect(DB_PATH, timeout=10.0)
            integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
            conn.close()
            if integrity == "ok":
                add("OK", "База данных", "Структура исправна")
            else:
                add("ERROR", "База данных", str(integrity))
        except Exception as error:
            add("ERROR", "База данных", str(error))

        try:
            trades, _updated = load_trades_cache(self.api_key)
            scoped_trades = self._filter_trades_for_current_scope(trades)
            details = f"Сделок: {len(scoped_trades)}/{len(trades)}" if self._trade_filter_active() else f"Сделок: {len(trades)}"
            add("OK" if scoped_trades else "WARN", "Сделки TMM", details)
        except Exception as error:
            add("ERROR", "Сделки TMM", str(error))

        try:
            health = requests.get(
                f"http://127.0.0.1:{self.local_server_port}/health", timeout=3
            )
            if health.status_code == 200:
                add("OK", "Локальный сервер", f"Порт {self.local_server_port}, HTTP 200")
            else:
                add("ERROR", "Локальный сервер", f"HTTP {health.status_code}")
        except Exception as error:
            add("ERROR", "Локальный сервер", f"Не отвечает: {error}")

        try:
            counts = get_runtime_status_counts(self._current_scope_trade_ids())
            level = "WARN" if counts["missing_clips"] or counts["link_errors"] else "OK"
            add(
                level, "Клипы и ссылки",
                f"готово {counts['valid_clips']}, отсутствует {counts['missing_clips']}, "
                f"ссылок ожидает {counts['pending']}"
            )
        except Exception as error:
            add("ERROR", "Клипы и ссылки", str(error))
        try:
            jobs = get_processing_job_counts()
            level = "WARN" if jobs["pending"] or jobs["running"] or jobs["problems"] else "OK"
            add(
                level, "Очередь обработки",
                f"выполняется {jobs['running']}, ожидает {jobs['pending']}, "
                f"проблем {jobs['problems']}, завершено {jobs['done']}"
            )
        except Exception as error:
            add("ERROR", "Очередь обработки", str(error))
        try:
            api_stats = TMM_API_LIMITER.snapshot()
            api_level = "WARN" if api_stats["rate_limit_hits"] else "OK"
            add(
                api_level, "Ограничитель TMM API",
                f"запросов {api_stats['total_requests']}, ожиданий {api_stats['throttled_requests']}, "
                f"ответов 429: {api_stats['rate_limit_hits']}"
            )
        except Exception as error:
            add("ERROR", "Ограничитель TMM API", str(error))
        try:
            quarantine = get_quarantine_summary()
            add(
                "OK", "Карантин",
                f"файлов {quarantine['files']}, размер {self._format_file_size(quarantine['bytes'])}"
            )
        except Exception as error:
            add("ERROR", "Карантин", str(error))
        return checks

    def run_diagnostics(self):
        if self._diagnostics_running:
            self.log("INFO", "Диагностика уже выполняется")
            return
        self.api_key = self.api_entry.get().strip()
        self._diagnostics_running = True
        self.set_status("Диагностика...", COLORS["warning"])
        self.log("INFO", "Запущена безопасная диагностика")

        def worker():
            try:
                checks = self._collect_diagnostics()
                self.run_on_ui(self._show_diagnostics_result, checks)
            except Exception as error:
                self.log("ERROR", f"Сбой диагностики: {error}")
                self.set_status("Ошибка диагностики", COLORS["error"])
            finally:
                self._diagnostics_running = False

        threading.Thread(target=worker, name="TMM diagnostics", daemon=True).start()

    def _show_diagnostics_result(self, checks):
        errors = sum(1 for item in checks if item["level"] == "ERROR")
        warnings = sum(1 for item in checks if item["level"] == "WARN")
        self.set_status("Готов" if not errors else "Нужна проверка", COLORS["success"] if not errors else COLORS["warning"])
        self.refresh_runtime_status()
        win = tk.Toplevel(self.root)
        win.title("Проверка системы")
        win.geometry("820x560")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        summary = "Все основные проверки пройдены" if not errors else f"Ошибок: {errors}, предупреждений: {warnings}"
        tk.Label(
            win, text=summary, font=("Segoe UI", 12, "bold"),
            bg=COLORS["bg"], fg=COLORS["success"] if not errors else COLORS["warning"]
        ).pack(anchor="w", padx=16, pady=(14, 8))
        body = tk.Frame(win, bg=COLORS["panel"], padx=12, pady=10)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))
        for item in checks:
            row = tk.Frame(body, bg=COLORS["panel"])
            row.pack(fill=tk.X, pady=3)
            color = {"OK": COLORS["success"], "WARN": COLORS["warning"], "ERROR": COLORS["error"]}[item["level"]]
            tk.Label(row, text=item["level"], width=7, anchor="w", font=("Segoe UI", 9, "bold"), bg=COLORS["panel"], fg=color).pack(side=tk.LEFT)
            tk.Label(row, text=item["name"], width=20, anchor="w", font=("Segoe UI", 9, "bold"), bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT)
            tk.Label(row, text=item["detail"], anchor="w", justify="left", wraplength=520, font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(win, text="Закрыть", command=win.destroy, bg=COLORS["accent"], fg="white", relief="flat", padx=22, pady=7).pack(pady=(0, 12))
        self.log("INFO", f"Диагностика завершена: ошибок {errors}, предупреждений {warnings}")

    def _set_active_ffmpeg_process(self, process):
        with self._active_process_lock:
            self.active_ffmpeg_process = process

    def _terminate_active_ffmpeg(self):
        with self._active_process_lock:
            process = self.active_ffmpeg_process
        if process and process.poll() is None:
            try:
                process.terminate()
            except Exception as e:
                log_to_file("WARN", f"Не удалось остановить FFmpeg: {e}")

    def _try_begin_processing(self, source):
        with self._processing_state_lock:
            if self.processing_active:
                return False
            self.processing_active = True
            self.processing_source = source
            self.processing_cancel_event.clear()
            return True

    def _finish_processing(self):
        with self._processing_state_lock:
            self.processing_active = False
            self.processing_source = ""
        self._set_active_ffmpeg_process(None)
        self.run_on_ui(self.refresh_runtime_status)

    def _try_begin_date_task(self):
        with self._processing_state_lock:
            if self.processing_active:
                return False
        with self._date_task_lock:
            if self._date_task_running:
                return False
            self._date_task_running = True
            self.processing_cancel_event.clear()
            return True

    def _finish_date_task(self):
        with self._date_task_lock:
            self._date_task_running = False

    def stop_all_processing(self):
        with self._processing_state_lock:
            was_processing = self.processing_active
            source = self.processing_source
        with self._date_task_lock:
            was_date_task = self._date_task_running
        was_auto = self.auto_process_active
        self.processing_cancel_event.set()
        self._terminate_active_ffmpeg()
        if was_auto:
            self.stop_auto_process()
        if was_processing or was_date_task:
            self.set_status("Остановка...", COLORS["warning"])
            label = source or "подготовка по датам"
            self.log("WARN", f"Запрошена остановка обработки ({label})")
        elif not was_auto:
            self.log("INFO", "Активной обработки для остановки нет")

    def _update_server_ui(self, text, color=None):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self._update_server_ui, text, color)
            return
        if hasattr(self, "server_status_label"):
            self.server_status_label.config(text=text, fg=color or COLORS["text_dim"])

    def start_local_server(self):
        ok, detail = self.local_server.start()
        if ok:
            self._update_server_ui(f"Локальный сервер: {detail}", COLORS["success"])
            if self._last_server_error or detail != "Уже работает":
                self.log("INFO", f"Локальный видеосервер запущен: {detail}")
            self._last_server_error = ""
            self.root.after(500, self.sync_pending_links_async)
        else:
            self._update_server_ui("Локальный сервер: ошибка порта", COLORS["error"])
            if detail != self._last_server_error:
                self.log("ERROR", f"Не удалось запустить локальный сервер на порту {self.local_server_port}: {detail}")
                self._last_server_error = detail

    def stop_local_server(self):
        try:
            self.local_server.stop()
            self._update_server_ui("Локальный сервер: остановлен", COLORS["text_dim"])
        except Exception as error:
            log_to_file("ERROR", f"Ошибка остановки локального сервера: {error}")

    def _mark_successful_results(self, results, vi, out_dir):
        registered = 0
        for trade, ok, _message in results:
            if not ok:
                continue
            clip_path = get_trade_output_path(trade, out_dir, self.format_trade_folder)
            try:
                mark_processed(str(trade.get("id", "")), clip_path, vi.get("path", ""))
                registered += 1
            except Exception as error:
                self.log("ERROR", f"Не удалось зарегистрировать клип {trade.get('symbol','?')}: {error}")
        if registered:
            self.sync_pending_links_async()
            self.run_on_ui(self.refresh_runtime_status)
        return registered

    def sync_pending_links_async(self, include_legacy=False, force=False):
        if not force and not self.auto_sync_video_links:
            return
        if not self.api_key or not self.local_server.running:
            return
        if self._trade_filter_active() and not self.my_api_key_ids:
            self.log("WARN", "Ссылки TMM не отправлены: режим 'Только мои' включён, но список api_key_id пуст.")
            return
        with self._link_sync_lock:
            if self._link_sync_running:
                return
            self._link_sync_running = True

        def worker():
            synced = 0
            failed = 0
            skipped = 0
            try:
                candidates = get_link_sync_candidates(include_legacy=include_legacy)
                if not candidates:
                    return
                ids = [row["trade_id"] for row in candidates]
                cached_trades, _ = load_trades_cache(self.api_key)
                fresh_trades = {
                    str(trade.get("id", "")): trade
                    for trade in cached_trades
                    if str(trade.get("id", "")) in ids
                }
                missing_ids = [tid for tid in ids if tid not in fresh_trades]
                if missing_ids:
                    try:
                        fresh_trades.update(fetch_trades_by_ids(self.api_key, missing_ids))
                    except TMMRateLimitError as error:
                        self.log("WARN", f"Ссылки TMM: {error}; использую локальную базу для {len(fresh_trades)} из {len(ids)} сделок.")
                    except Exception as error:
                        self.log("WARN", f"Не удалось получить сделки для синхронизации ссылок: {error}; использую локальную базу для {len(fresh_trades)} из {len(ids)} сделок.")
                for row in candidates:
                    tid = str(row["trade_id"])
                    attempts = int(row.get("link_attempts") or 0) + 1
                    try:
                        trade = fresh_trades.get(tid)
                        if not trade:
                            raise RuntimeError("Сделка не найдена в API TMM")
                        if not self._is_trade_allowed_by_current_scope(trade):
                            set_link_sync_result(
                                tid, "error",
                                error="Сделка пропущена фильтром api_key_id текущего режима.",
                                attempts=attempts
                            )
                            skipped += 1
                            continue
                        url = self.local_server.watch_url(tid)
                        write_trade_video_link(self.api_key, trade, url)
                        set_link_sync_result(tid, "synced", link_url=url, attempts=0)
                        synced += 1
                    except Exception as error:
                        delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
                        next_retry = (datetime.now() + timedelta(seconds=delay)).isoformat()
                        set_link_sync_result(
                            tid, "retry", error=str(error), attempts=attempts,
                            next_retry=next_retry
                        )
                        failed += 1
                        if isinstance(error, TMMRateLimitError):
                            break
                if synced:
                    self.log("INFO", f"Ссылки TMM синхронизированы: {synced}")
                if failed:
                    self.log("WARN", f"Ссылки TMM ожидают повторной отправки: {failed}")
                if skipped:
                    self.log("WARN", f"Ссылки TMM пропущены фильтром сделок: {skipped}")
            finally:
                with self._link_sync_lock:
                    self._link_sync_running = False
                self.run_on_ui(self.refresh_runtime_status)

        threading.Thread(target=worker, name="TMM link sync", daemon=True).start()

    def manual_sync_links(self):
        self.auto_sync_video_links = bool(self.link_sync_var.get())
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        if not self.api_key:
            messagebox.showerror("Ссылки TMM", "Введите API-ключ TMM.")
            return
        if not self.local_server.running:
            self.start_local_server()
            if not self.local_server.running:
                return
        self._reconcile_processed_files()
        self.log("INFO", "Запущена ручная синхронизация ссылок TMM")
        self.sync_pending_links_async(include_legacy=True, force=True)

    def _reconcile_processed_files(self):
        trades, _ = load_trades_cache(self.api_key)
        trades = self._filter_trades_for_current_scope(trades)
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        known_ids = {row[0] for row in conn.execute("SELECT trade_id FROM processed").fetchall()}
        conn.close()
        valid = 0
        missing = 0
        for trade in trades:
            tid = str(trade.get("id", ""))
            if tid not in known_ids:
                continue
            if is_processed(
                tid, trade, self.output_folder or CUT_VIDEOS_DIR,
                self.format_trade_folder
            ):
                valid += 1
            else:
                missing += 1
        return valid, missing

    def reconcile_processed_files_async(self):
        def worker():
            try:
                valid, missing = self._reconcile_processed_files()
                if missing:
                    self.log("WARN", f"Удалённые клипы возвращены в очередь: {missing}")
                if valid:
                    self.log("INFO", f"Проверено существующих клипов: {valid}")
                self.run_on_ui(self.refresh_runtime_status)
            except Exception as error:
                self.log("ERROR", f"Ошибка проверки готовых клипов: {error}")
        threading.Thread(target=worker, name="TMM clip reconciliation", daemon=True).start()

    def _scheduled_link_sync(self):
        if self.stop_flag:
            return
        if not self.local_server.running:
            self.start_local_server()
        self.sync_pending_links_async()
        if self.root.winfo_exists():
            self.root.after(60000, self._scheduled_link_sync)

    def on_link_sync_toggle(self):
        self.auto_sync_video_links = bool(self.link_sync_var.get())
        self.cfg["auto_sync_video_links"] = self.auto_sync_video_links
        save_config(self.cfg)
        state = "включена" if self.auto_sync_video_links else "выключена"
        self.log("INFO", f"Автоматическая отправка ссылок TMM {state}")
        if self.auto_sync_video_links:
            self.sync_pending_links_async()

    def _trade_filter_active(self):
        return self.trade_filter_mode == TRADE_FILTER_MINE_ONLY

    def _trade_filter_name(self):
        return TRADE_FILTER_LABELS.get(self.trade_filter_mode, TRADE_FILTER_LABELS[TRADE_FILTER_ALL])

    def _sync_trade_filter_from_ui(self):
        if hasattr(self, "trade_filter_var"):
            self.trade_filter_mode = normalize_trade_filter_mode(self.trade_filter_var.get())
        else:
            self.trade_filter_mode = normalize_trade_filter_mode(self.trade_filter_mode)
        if hasattr(self, "my_api_ids_var"):
            self.my_api_key_ids = parse_api_key_ids(self.my_api_ids_var.get())
        else:
            self.my_api_key_ids = parse_api_key_ids(self.my_api_key_ids)
        self.cfg["trade_filter_mode"] = self.trade_filter_mode
        self.cfg["my_api_key_ids"] = self.my_api_key_ids
        self._update_trade_filter_controls()

    def _update_trade_filter_controls(self):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self._update_trade_filter_controls)
            return
        if hasattr(self, "my_api_ids_entry"):
            self.my_api_ids_entry.config(state="normal" if self._trade_filter_active() else "disabled")
        if hasattr(self, "trade_filter_status_label"):
            if self._trade_filter_active():
                count = len(self.my_api_key_ids)
                text = f"Мои api_key_id: {count}" if count else "Мои api_key_id не заданы"
                color = COLORS["success"] if count else COLORS["warning"]
            else:
                text = "Фильтр сделок выключен"
                color = COLORS["text_dim"]
            self.trade_filter_status_label.config(text=text, fg=color)

    def _on_trade_filter_changed(self):
        self._sync_trade_filter_from_ui()
        save_config(self.cfg)
        self._refresh_trade_count_from_cache()
        self.log("INFO", f"Режим сделок: {self._trade_filter_name()}")
        if self._trade_filter_active() and not self.my_api_key_ids:
            self.log("WARN", "Режим 'Только мои' включён, но список api_key_id пуст.")

    def _on_my_api_ids_changed(self, _event=None):
        self._sync_trade_filter_from_ui()
        save_config(self.cfg)
        self._refresh_trade_count_from_cache()

    def _filter_trades_for_current_scope(self, trades, context=""):
        trades = list(trades or [])
        if not self._trade_filter_active():
            return trades
        if not self.my_api_key_ids:
            if context:
                self.log("WARN", f"{context}: режим 'Только мои' включён, но список api_key_id пуст.")
            return []
        filtered = filter_trades_by_api_key_ids(trades, self.my_api_key_ids)
        if context:
            ids = format_api_key_ids(self.my_api_key_ids)
            self.log("INFO", f"{context}: режим 'Только мои' оставил {len(filtered)} из {len(trades)} сделок (api_key_id: {ids})")
            if trades and not filtered:
                found_ids = format_api_key_id_counts(trades)
                if found_ids:
                    self.log("WARN", f"{context}: среди загруженных сделок нет api_key_id из настройки ({ids}); найдено: {found_ids}. Проверьте поле 'Мои api_key_id'.")
                else:
                    self.log("WARN", f"{context}: среди загруженных сделок нет поля api_key_id. Фильтр 'Только мои' не может выбрать сделки.")
        return filtered

    def _is_trade_allowed_by_current_scope(self, trade):
        if not self._trade_filter_active():
            return True
        return is_trade_from_api_key_ids(trade, self.my_api_key_ids)

    def _trade_count_text(self, count, total=None):
        if total is not None and total != count:
            return f"Сделок: {count}/{total}"
        return f"Сделок: {count}"

    def _refresh_trade_count_from_cache(self):
        try:
            trades, _updated = load_trades_cache(self.api_key)
            scoped = self._filter_trades_for_current_scope(trades)
            total = len(trades) if self._trade_filter_active() else None
            self._set_trade_count(len(scoped), total)
        except Exception:
            pass

    def _current_scope_trade_ids(self):
        if not self._trade_filter_active():
            return None
        trades, _updated = load_trades_cache(self.api_key)
        return {str(trade.get("id", "")) for trade in self._filter_trades_for_current_scope(trades) if trade.get("id")}

    def format_trade_folder(self, trade, trade_time):
        return get_trade_folder_name(trade, trade_time)

    def _stop_if_stale_cache_misses_video_dates(self, trades, videos, context):
        if not trades or not videos:
            return False
        if not LAST_TMM_CACHE_USED_STALE and LAST_TMM_API_STATUS not in (429, "network"):
            return False
        _earliest_trade, latest_trade = get_trade_time_range(trades)
        if not latest_trade:
            return False
        target_dates = {
            video["start_time"].astimezone(get_tmm_timezone()).date()
            for video in videos
            if video.get("start_time")
        }
        if not target_dates:
            return False
        latest_trade_date = latest_trade.astimezone(get_tmm_timezone()).date()
        if latest_trade_date >= min(target_dates):
            return False
        api_reason = "TMM API на паузе" if LAST_TMM_API_STATUS == 429 else "TMM API сейчас недоступен"
        message = (
            f"{context}: актуальные сделки не загружены. "
            f"В локальной базе сделки только до {latest_trade_date.strftime('%d.%m.%Y')}, "
            f"а выбрано видео за {format_date_set(target_dates)}. "
            f"{api_reason}; дождитесь автообновления сделок и повторите обработку."
        )
        self.log("WARN", message)
        self.set_status("Сделки устарели", COLORS["warning"])
        self.update_progress(0, "Данные сделок устарели")
        return True

    @staticmethod
    def _format_video_position(seconds):
        value = max(0.0, float(seconds or 0))
        hours, remainder = divmod(value, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"

    def show_cut_preview(self, vi, trade):
        try:
            buffer_before = int(self.bv.get())
            buffer_after = int(self.av.get())
            time_offset = int(self.ov.get())
        except (TypeError, ValueError):
            buffer_before = self.buffer_before
            buffer_after = self.buffer_after
            time_offset = self.time_offset
        window, error = calculate_cut_window(
            trade, vi, buffer_before, buffer_after, time_offset
        )
        output_path = get_trade_output_path(
            trade, self.output_folder or CUT_VIDEOS_DIR, self.format_trade_folder
        )
        open_time = parse_trade_time(trade, True)
        close_time = parse_trade_time(trade, False)
        tmm_tz = get_tmm_timezone()
        record = get_processed_record(str(trade.get("id", "")))
        lines = [
            ("Сделка", f"{trade.get('symbol', '?')} {trade.get('side', '')}".strip()),
            ("Открытие TMM", open_time.astimezone(tmm_tz).strftime("%d.%m.%Y %H:%M:%S %Z") if open_time else "нет"),
            ("Закрытие TMM", close_time.astimezone(tmm_tz).strftime("%d.%m.%Y %H:%M:%S %Z") if close_time else "сделка открыта"),
            ("Исходное видео", vi.get("name") or os.path.basename(vi.get("path", ""))),
            ("Старт видео Windows", vi.get("start_time").astimezone().strftime("%d.%m.%Y %H:%M:%S") if vi.get("start_time") else "нет"),
            ("Буфер", f"до {buffer_before} сек, после {buffer_after} сек"),
            ("Сдвиг", f"{time_offset:+d} сек"),
        ]
        if window:
            lines.extend([
                ("Начало фрагмента", self._format_video_position(window["start_sec"])),
                ("Конец фрагмента", self._format_video_position(window["end_sec"])),
                ("Ожидаемая длительность", f"{window['duration_sec']:.3f} сек"),
                ("Имя папки", os.path.basename(os.path.dirname(output_path))),
                ("Путь результата", output_path),
            ])
        else:
            lines.append(("Расчёт", error))
        if record:
            lines.append(("Текущий статус", format_trade_link_status(record)))

        win = tk.Toplevel(self.root)
        win.title("Предпросмотр нарезки")
        win.geometry("820x520")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        tk.Label(
            win, text="Предпросмотр без запуска обработки",
            font=("Segoe UI", 12, "bold"), bg=COLORS["bg"],
            fg=COLORS["accent"] if window else COLORS["error"]
        ).pack(anchor="w", padx=16, pady=(14, 8))
        body = tk.Frame(win, bg=COLORS["panel"], padx=14, pady=12)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))
        for label, value in lines:
            row = tk.Frame(body, bg=COLORS["panel"])
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label, width=24, anchor="w", font=("Segoe UI", 9, "bold"), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(side=tk.LEFT)
            tk.Label(row, text=value, anchor="w", justify="left", wraplength=560, font=("Segoe UI", 9), bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(win, text="Закрыть", command=win.destroy, bg=COLORS["accent"], fg="white", relief="flat", padx=22, pady=7).pack(pady=(0, 12))

    def open_queue_window(self):
        if hasattr(self, "queue_window") and self.queue_window.winfo_exists():
            self.queue_window.lift()
            self.refresh_queue_view()
            return
        win = tk.Toplevel(self.root)
        self.queue_window = win
        win.title("Очередь и история обработки")
        win.geometry("1100x620")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        tk.Label(win, text="Очередь и история обработки", font=("Segoe UI", 12, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(anchor="w", padx=14, pady=(12, 6))
        columns = ("status", "symbol", "mode", "created", "source", "message")
        tree = ttk.Treeview(win, columns=columns, show="headings", selectmode="browse")
        self.queue_tree = tree
        headings = {
            "status": "Статус", "symbol": "Тикер", "mode": "Режим",
            "created": "Создано", "source": "Видео", "message": "Результат",
        }
        widths = {"status": 110, "symbol": 120, "mode": 90, "created": 140, "source": 240, "message": 300}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)
        buttons = tk.Frame(win, bg=COLORS["bg"])
        buttons.pack(fill=tk.X, padx=14, pady=(4, 12))
        actions = [
            ("Обновить", self.refresh_queue_view, COLORS["entry_bg"]),
            ("Повторить выбранное", self.retry_selected_job, COLORS["accent"]),
            ("Открыть результат", self.open_selected_job_output, COLORS["entry_bg"]),
            ("Очистить завершённые", self.clear_completed_jobs_ui, COLORS["warning"]),
        ]
        for text, command, color in actions:
            tk.Button(buttons, text=text, command=command, bg=color, fg="white" if color != COLORS["entry_bg"] else COLORS["text"],
                      relief="flat", cursor="hand2", padx=12, pady=7).pack(side=tk.LEFT, padx=(0, 6))
        self.refresh_queue_view()

    def refresh_queue_view(self):
        if not hasattr(self, "queue_tree") or not self.queue_tree.winfo_exists():
            return
        selected = self.queue_tree.selection()
        selected_id = selected[0] if selected else ""
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        allowed_trade_ids = None
        if self._trade_filter_active():
            trades, _updated = load_trades_cache(self.api_key)
            scoped_trades = self._filter_trades_for_current_scope(trades)
            allowed_trade_ids = {str(trade.get("id", "")) for trade in scoped_trades if trade.get("id")}
        status_names = {
            "pending": "Ожидает", "running": "Выполняется", "done": "Готово",
            "error": "Ошибка", "stopped": "Остановлено", "interrupted": "Прервано",
        }
        for job in get_processing_jobs():
            item_id = str(job["id"])
            if allowed_trade_ids is not None and str(job.get("trade_id", "")) not in allowed_trade_ids:
                continue
            self.queue_tree.insert("", "end", iid=item_id, values=(
                status_names.get(job.get("status"), job.get("status", "")),
                job.get("symbol") or "?",
                job.get("source_mode") or "",
                str(job.get("created_at") or "")[:19].replace("T", " "),
                os.path.basename(job.get("source_video_path") or ""),
                job.get("message") or "",
            ))
        if selected_id and self.queue_tree.exists(selected_id):
            self.queue_tree.selection_set(selected_id)

    def _selected_processing_job(self):
        if not hasattr(self, "queue_tree") or not self.queue_tree.winfo_exists():
            return None
        selected = self.queue_tree.selection()
        if not selected:
            messagebox.showwarning("Очередь", "Выберите задание.")
            return None
        job_id = int(selected[0])
        return next((job for job in get_processing_jobs() if int(job["id"]) == job_id), None)

    def retry_selected_job(self):
        job = self._selected_processing_job()
        if not job:
            return
        if job.get("status") in ("pending", "running"):
            messagebox.showinfo("Очередь", "Это задание уже ожидает или выполняется.")
            return
        source_path = job.get("source_video_path") or ""
        if not os.path.isfile(source_path):
            messagebox.showerror("Очередь", "Исходное видео больше не найдено.")
            return
        trades, _updated = load_trades_cache(self.api_key)
        trade = next((item for item in trades if str(item.get("id", "")) == str(job.get("trade_id", ""))), None)
        if not trade:
            messagebox.showerror("Очередь", "Сделка отсутствует в локальной базе TMM.")
            return
        if not self._is_trade_allowed_by_current_scope(trade):
            messagebox.showerror("Очередь", "Сделка не входит в текущий режим фильтрации api_key_id.")
            return
        self._start_cutting(get_video_info(source_path), [trade])

    def open_selected_job_output(self):
        job = self._selected_processing_job()
        if not job:
            return
        output_path = job.get("output_path") or ""
        target = os.path.dirname(output_path) if output_path and os.path.exists(output_path) else job.get("output_dir")
        if target and os.path.isdir(target):
            os.startfile(target)
        else:
            messagebox.showwarning("Очередь", "Папка результата не найдена.")

    def clear_completed_jobs_ui(self):
        if not messagebox.askyesno("Очередь", "Удалить из истории завершённые и остановленные задания? Видеофайлы останутся на месте."):
            return
        removed = clear_completed_processing_jobs()
        self.log("INFO", f"Из истории очереди удалено записей: {removed}")
        self.refresh_queue_view()
        self.refresh_runtime_status()

    def open_links_window(self):
        if hasattr(self, "links_window") and self.links_window.winfo_exists():
            self.links_window.lift()
            self.refresh_links_view()
            return
        win = tk.Toplevel(self.root)
        self.links_window = win
        win.title("Ссылки TMM")
        win.geometry("1050x620")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        tk.Label(win, text="Состояние ссылок TMM", font=("Segoe UI", 12, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(anchor="w", padx=14, pady=(12, 6))
        columns = ("symbol", "status", "updated", "attempts", "error")
        tree = ttk.Treeview(win, columns=columns, show="headings", selectmode="browse")
        self.links_tree = tree
        specs = {
            "symbol": ("Сделка", 150), "status": ("Статус", 170),
            "updated": ("Обновлено", 150), "attempts": ("Попытки", 70),
            "error": ("Последняя ошибка", 450),
        }
        for column, (heading, width) in specs.items():
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)
        buttons = tk.Frame(win, bg=COLORS["bg"])
        buttons.pack(fill=tk.X, padx=14, pady=(4, 12))
        actions = [
            ("Обновить", self.refresh_links_view, COLORS["entry_bg"]),
            ("Отправить ожидающие", self.sync_waiting_links, COLORS["accent"]),
            ("Повторить выбранную", self.retry_selected_link, COLORS["warning"]),
            ("Открыть видео", self.open_selected_link_video, COLORS["entry_bg"]),
        ]
        for text, command, color in actions:
            tk.Button(buttons, text=text, command=command, bg=color, fg="white" if color != COLORS["entry_bg"] else COLORS["text"],
                      relief="flat", cursor="hand2", padx=12, pady=7).pack(side=tk.LEFT, padx=(0, 6))
        self.refresh_links_view()

    def refresh_links_view(self):
        if not hasattr(self, "links_tree") or not self.links_tree.winfo_exists():
            return
        selected = self.links_tree.selection()
        selected_id = selected[0] if selected else ""
        for item in self.links_tree.get_children():
            self.links_tree.delete(item)
        trades, _updated = load_trades_cache(self.api_key)
        scoped_trades = self._filter_trades_for_current_scope(trades)
        allowed_trade_ids = {str(trade.get("id", "")) for trade in scoped_trades if trade.get("id")}
        symbols = {str(trade.get("id", "")): trade.get("symbol", "?") for trade in scoped_trades}
        status_names = {
            "synced": "Отправлена", "pending": "Ожидает", "retry": "Повтор позже",
            "missing": "Файл удалён", "error": "Ошибка", "legacy": "Старая запись",
        }
        for row in get_link_status_rows():
            trade_id = str(row.get("trade_id", ""))
            if self._trade_filter_active() and trade_id not in allowed_trade_ids:
                continue
            self.links_tree.insert("", "end", iid=trade_id, values=(
                f"{symbols.get(trade_id, '?')}  #{trade_id}",
                status_names.get(row.get("link_status"), row.get("link_status") or ""),
                str(row.get("link_updated_at") or "")[:19].replace("T", " "),
                row.get("link_attempts") or 0,
                row.get("link_error") or "",
            ))
        if selected_id and self.links_tree.exists(selected_id):
            self.links_tree.selection_set(selected_id)

    def _selected_link_trade_id(self):
        if not hasattr(self, "links_tree") or not self.links_tree.winfo_exists():
            return ""
        selected = self.links_tree.selection()
        if not selected:
            messagebox.showwarning("Ссылки TMM", "Выберите сделку.")
            return ""
        return str(selected[0])

    def sync_waiting_links(self):
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        if not self.api_key:
            messagebox.showerror("Ссылки TMM", "Введите API-ключ TMM.")
            return
        self.log("INFO", "Запущена отправка ожидающих ссылок TMM")
        self.sync_pending_links_async(force=True)

    def retry_selected_link(self):
        trade_id = self._selected_link_trade_id()
        if not trade_id:
            return
        trades, _updated = load_trades_cache(self.api_key)
        trade = next((item for item in trades if str(item.get("id", "")) == trade_id), None)
        if self._trade_filter_active() and (not trade or not self._is_trade_allowed_by_current_scope(trade)):
            messagebox.showerror("Ссылки TMM", "Сделка не входит в текущий режим фильтрации api_key_id.")
            return
        record = get_processed_record(trade_id)
        if not record or not _valid_clip(record.get("clip_path")):
            messagebox.showerror("Ссылки TMM", "Готовый видеофайл этой сделки отсутствует.")
            return
        queue_link_retry(trade_id)
        self.log("INFO", f"Ссылка сделки {trade_id} поставлена на повторную отправку")
        self.sync_pending_links_async(force=True)
        self.refresh_links_view()

    def open_selected_link_video(self):
        trade_id = self._selected_link_trade_id()
        if not trade_id:
            return
        if not get_registered_clip(trade_id):
            messagebox.showerror("Ссылки TMM", "Видео этой сделки отсутствует.")
            return
        if not self.local_server.running:
            self.start_local_server()
        if self.local_server.running:
            os.startfile(self.local_server.watch_url(trade_id))

    def open_storage_window(self):
        if hasattr(self, "storage_window") and self.storage_window.winfo_exists():
            self.storage_window.lift()
            self.refresh_quarantine_view()
            return
        win = tk.Toplevel(self.root)
        self.storage_window = win
        win.title("Проверка хранилища и карантин")
        win.geometry("1120x680")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        tk.Label(win, text="Проверка хранилища", font=("Segoe UI", 12, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"]).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(win, text="Сканирование ничего не удаляет. Файлы перемещаются только после подтверждения.",
                 font=("Segoe UI", 8), bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(anchor="w", padx=14, pady=(0, 6))
        self.storage_summary_label = tk.Label(win, text="Сканирование ещё не запускалось", font=("Segoe UI", 9, "bold"),
                                              bg=COLORS["bg"], fg=COLORS["text_dim"])
        self.storage_summary_label.pack(anchor="w", padx=14, pady=(0, 6))
        notebook = ttk.Notebook(win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)

        candidates_tab = tk.Frame(notebook, bg=COLORS["panel"])
        quarantine_tab = tk.Frame(notebook, bg=COLORS["panel"])
        notebook.add(candidates_tab, text="Найдено")
        notebook.add(quarantine_tab, text="Карантин")

        candidate_columns = ("reason", "size", "registered", "path")
        candidate_tree = ttk.Treeview(candidates_tab, columns=candidate_columns, show="headings", selectmode="extended")
        self.storage_candidates_tree = candidate_tree
        candidate_specs = {
            "reason": ("Причина", 300), "size": ("Размер", 100),
            "registered": ("В базе", 80), "path": ("Путь", 580),
        }
        for column, (heading, width) in candidate_specs.items():
            candidate_tree.heading(column, text=heading)
            candidate_tree.column(column, width=width, anchor="w")
        candidate_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        candidate_buttons = tk.Frame(candidates_tab, bg=COLORS["panel"])
        candidate_buttons.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(candidate_buttons, text="Сканировать", command=self.start_storage_scan,
                  bg=COLORS["accent"], fg="white", relief="flat", padx=16, pady=7).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(candidate_buttons, text="В карантин выбранные", command=self.quarantine_selected_storage,
                  bg=COLORS["warning"], fg="white", relief="flat", padx=16, pady=7).pack(side=tk.LEFT)

        quarantine_columns = ("status", "date", "size", "reason", "path")
        quarantine_tree = ttk.Treeview(quarantine_tab, columns=quarantine_columns, show="headings", selectmode="extended")
        self.quarantine_tree = quarantine_tree
        quarantine_specs = {
            "status": ("Статус", 100), "date": ("Дата", 140), "size": ("Размер", 90),
            "reason": ("Причина", 270), "path": ("Исходный путь", 540),
        }
        for column, (heading, width) in quarantine_specs.items():
            quarantine_tree.heading(column, text=heading)
            quarantine_tree.column(column, width=width, anchor="w")
        quarantine_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        quarantine_buttons = tk.Frame(quarantine_tab, bg=COLORS["panel"])
        quarantine_buttons.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(quarantine_buttons, text="Обновить", command=self.refresh_quarantine_view,
                  bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", padx=16, pady=7).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(quarantine_buttons, text="Восстановить выбранные", command=self.restore_selected_quarantine,
                  bg=COLORS["success"], fg="white", relief="flat", padx=16, pady=7).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(quarantine_buttons, text="Открыть папку карантина", command=self.open_quarantine_folder,
                  bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", padx=16, pady=7).pack(side=tk.LEFT)
        self.refresh_quarantine_view()

    @staticmethod
    def _format_file_size(size):
        value = float(size or 0)
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if value < 1024 or unit == "ГБ":
                return f"{value:.1f} {unit}"
            value /= 1024

    def start_storage_scan(self):
        if self._storage_scan_running:
            self.log("INFO", "Сканирование хранилища уже выполняется")
            return
        output_dir = self.output_folder or CUT_VIDEOS_DIR
        self._storage_scan_running = True
        self._storage_stop_event.clear()
        self.storage_summary_label.config(text="Сканирование...", fg=COLORS["warning"])
        self.log("INFO", f"Начато безопасное сканирование хранилища: {output_dir}")

        def progress(done, total, stage):
            self.run_on_ui(
                self.storage_summary_label.config,
                text=f"{stage}: {done}/{total}", fg=COLORS["warning"]
            )

        def worker():
            try:
                result = scan_storage(
                    output_dir, progress_cb=progress,
                    stop_cb=self._storage_stop_event.is_set
                )
                self.run_on_ui(self._apply_storage_scan_result, result)
            except Exception as error:
                self.log("ERROR", f"Ошибка сканирования хранилища: {error}")
                self.run_on_ui(
                    self.storage_summary_label.config,
                    text=f"Ошибка: {error}", fg=COLORS["error"]
                )
            finally:
                self._storage_scan_running = False

        threading.Thread(target=worker, name="TMM storage scan", daemon=True).start()

    def _apply_storage_scan_result(self, result):
        self._storage_candidates = result["candidates"]
        for item in self.storage_candidates_tree.get_children():
            self.storage_candidates_tree.delete(item)
        for index, candidate in enumerate(self._storage_candidates):
            self.storage_candidates_tree.insert("", "end", iid=str(index), values=(
                "; ".join(candidate["reasons"]),
                self._format_file_size(candidate["size"]),
                "да" if candidate.get("trade_id") else "нет",
                candidate["path"],
            ))
        self.storage_summary_label.config(
            text=(
                f"Проверено файлов: {result['files_scanned']}; кандидатов: {len(self._storage_candidates)}; "
                f"отсутствующих зарегистрированных клипов: {result['missing_registered']}"
            ),
            fg=COLORS["warning"] if self._storage_candidates else COLORS["success"]
        )
        self.log("INFO", f"Сканирование завершено: кандидатов в карантин {len(self._storage_candidates)}")

    def quarantine_selected_storage(self):
        selected = self.storage_candidates_tree.selection()
        if not selected:
            messagebox.showwarning("Карантин", "Выберите один или несколько файлов.")
            return
        items = [self._storage_candidates[int(item_id)] for item_id in selected]
        if not messagebox.askyesno(
            "Перемещение в карантин",
            f"Переместить выбранные файлы в карантин: {len(items)}?\n\nФайлы не будут удалены и смогут быть восстановлены."
        ):
            return
        output_dir = self.output_folder or CUT_VIDEOS_DIR

        def worker():
            moved, errors = quarantine_storage_items(items, output_dir)
            self.log("INFO", f"В карантин перемещено файлов: {len(moved)}")
            if errors:
                self.log("WARN", f"Не удалось переместить файлов: {len(errors)}")
            self.run_on_ui(self.refresh_quarantine_view)
            self.run_on_ui(self.start_storage_scan)
            self.run_on_ui(self.refresh_runtime_status)

        threading.Thread(target=worker, name="TMM quarantine move", daemon=True).start()

    def refresh_quarantine_view(self):
        if not hasattr(self, "quarantine_tree") or not self.quarantine_tree.winfo_exists():
            return
        for item in self.quarantine_tree.get_children():
            self.quarantine_tree.delete(item)
        status_names = {"quarantined": "В карантине", "restored": "Восстановлен"}
        for item in get_quarantine_items():
            self.quarantine_tree.insert("", "end", iid=str(item["id"]), values=(
                status_names.get(item["status"], item["status"]),
                str(item["quarantined_at"] or "")[:19].replace("T", " "),
                self._format_file_size(item["file_size"]),
                item["reason"], item["original_path"],
            ))

    def restore_selected_quarantine(self):
        selected = self.quarantine_tree.selection()
        if not selected:
            messagebox.showwarning("Карантин", "Выберите один или несколько файлов.")
            return
        if not messagebox.askyesno("Восстановление", f"Восстановить выбранные файлы: {len(selected)}?"):
            return

        def worker():
            restored = 0
            errors = []
            for item_id in selected:
                ok, detail = restore_quarantine_item(int(item_id))
                if ok:
                    restored += 1
                else:
                    errors.append(detail)
            self.log("INFO", f"Из карантина восстановлено файлов: {restored}")
            if errors:
                self.log("WARN", f"Не удалось восстановить файлов: {len(errors)}")
            self.run_on_ui(self.refresh_quarantine_view)
            self.run_on_ui(self.refresh_runtime_status)

        threading.Thread(target=worker, name="TMM quarantine restore", daemon=True).start()

    def open_quarantine_folder(self):
        os.makedirs(QUARANTINE_DIR, exist_ok=True)
        os.startfile(QUARANTINE_DIR)

    @staticmethod
    def _short_path(path, limit=25):
        if not path:
            return "Не выбрана"
        return path if len(path) <= limit else f"...{path[-(limit - 3):]}"

    def save_on_exit(self):
        auto_was_active = self.auto_process_active
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        self.cfg["tmm_api_key"] = self.api_key
        self.cfg["obs_folder"] = self.obs_folder
        self.cfg["output_folder"] = self.output_folder
        self.cfg["buffer_before"] = self.buffer_before
        self.cfg["buffer_after"] = self.buffer_after
        self.cfg["time_offset"] = self.time_offset
        self.cfg["auto_process"] = auto_was_active
        self.auto_sync_video_links = bool(self.link_sync_var.get()) if hasattr(self, "link_sync_var") else self.auto_sync_video_links
        self.cfg["auto_sync_video_links"] = self.auto_sync_video_links
        self.cfg["local_server_port"] = self.local_server_port
        self.cfg["local_server_token"] = self.local_server_token
        self.cfg["folder_naming"] = "tmm_time_seconds_symbol_percent_duration_entry_reason"
        save_config(self.cfg)
        self.stop_flag = True
        self.auto_process_active = False
        self.auto_stop_event.set()
        self.processing_cancel_event.set()
        self._terminate_active_ffmpeg()
        self.stop_local_server()
        self._uninstall_file_drop_target()
        if not self.embedded:
            self.root.destroy()

    def shutdown_background_services(self):
        self.stop_flag = True
        self.auto_process_active = False
        self.auto_stop_event.set()
        self.processing_cancel_event.set()
        try:
            self._terminate_active_ffmpeg()
        except Exception as error:
            log_to_file("WARN", f"FFmpeg shutdown skipped: {error}")
        try:
            self.local_server.stop()
        except Exception as error:
            log_to_file("WARN", f"Local server shutdown skipped: {error}")
        try:
            self._uninstall_file_drop_target()
        except Exception as error:
            log_to_file("WARN", f"Drop target shutdown skipped: {error}")

    def setup_ui(self):
        if not self.embedded:
            self.root.title("TMM Video Cutter v24.13.15"); self.root.geometry("1400x850")
            apply_window_icon(self.root)
            self.root.configure(bg=COLORS["bg"]); self.root.minsize(1200, 750)
        else:
            self.container.configure(bg=COLORS["bg"])
        outer_pad = 12 if self.embedded else 20
        content_pad = 8 if self.embedded else 12
        card_pad_x = 16 if self.embedded else 20
        card_pad_y = 12 if self.embedded else 18
        main = tk.Frame(self.container, bg=COLORS["bg"]); main.pack(fill=tk.BOTH, expand=True, padx=outer_pad, pady=outer_pad)

        # === ВЕРХНЯЯ ПАНЕЛЬ ===
        bar = tk.Frame(main, bg=COLORS["panel"], height=44); bar.pack(fill=tk.X, pady=(0, 8)); bar.pack_propagate(False)
        self.sc = tk.Canvas(bar, width=10, height=10, bg=COLORS["panel"], highlightthickness=0); self.sc.pack(side=tk.LEFT, padx=(15, 5))
        self.dot = self.sc.create_oval(0, 0, 10, 10, fill=COLORS["success"], outline="")
        self.sl = tk.Label(bar, text="Готов", font=("Segoe UI", 9, "bold"), bg=COLORS["panel"], fg=COLORS["success"]); self.sl.pack(side=tk.LEFT, padx=4)
        tk.Frame(bar, bg=COLORS["panel_border"], width=1, height=26).pack(side=tk.LEFT, padx=12)
        trades, _ = load_trades_cache(self.api_key)
        scoped_trades = self._filter_trades_for_current_scope(trades)
        total_trades = len(trades) if self._trade_filter_active() else None
        self.cl = tk.Label(bar, text=self._trade_count_text(len(scoped_trades), total_trades), font=("Segoe UI", 9), bg=COLORS["panel"], fg=COLORS["text_dim"]); self.cl.pack(side=tk.LEFT, padx=8)
        self.cache_time_label = tk.Label(bar, text="", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.cache_time_label.pack(side=tk.LEFT, padx=5)
        self.update_cache_time_display()
        tk.Label(bar, text="v24.13.15", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(side=tk.RIGHT, padx=15)
        tk.Button(bar, text="◉", command=self.show_dev_info, font=("Segoe UI", 7), bg=COLORS["panel"], fg=COLORS["panel_border"], relief="flat", cursor="hand2", bd=0, padx=4).pack(side=tk.RIGHT, padx=8)

        content = tk.Frame(main, bg=COLORS["bg"]); content.pack(fill=tk.BOTH, expand=True, pady=content_pad)
        left_width = 380 if self.embedded else 400
        left = tk.Frame(content, bg=COLORS["bg"], width=left_width); left.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10)); left.pack_propagate(False)
        right = tk.Frame(content, bg=COLORS["bg"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # === КАРТОЧКА 1: НАРЕЗАТЬ ВИДЕО ===
        c1 = tk.Frame(left, bg=COLORS["panel"], padx=card_pad_x, pady=card_pad_y); c1.pack(fill=tk.X, pady=5)
        tk.Label(c1, text="Нарезать видео", font=("Segoe UI", 12, "bold"), bg=COLORS["panel"], fg=COLORS["accent"]).pack(anchor="w")
        drop_height = 82 if self.embedded else 105
        self.drop_frame = tk.Frame(c1, bg=COLORS["bg"], height=drop_height, highlightbackground=COLORS["accent"], highlightthickness=2, cursor="hand2")
        self.drop_frame.pack(fill=tk.X, pady=(8, 6))
        self.drop_frame.pack_propagate(False)
        self.drop_label = tk.Label(self.drop_frame, text="🎬 Нажмите или перетащите видео сюда\nMP4, MKV, AVI, MOV, TS", font=("Segoe UI", 10, "bold"), bg=COLORS["bg"], fg=COLORS["accent"], cursor="hand2")
        self.drop_label.pack(expand=True)
        self._drop_default_text = self.drop_label.cget("text")
        # Безопасное открытие файлового диалога при клике на всю область
        self.drop_frame.bind("<Button-1>", lambda e: self.cut_single_video())
        self.drop_label.bind("<Button-1>", lambda e: self.cut_single_video())

        # === КАРТОЧКА 2: ВЫБРАТЬ ДАТЫ ===
        c2 = tk.Frame(left, bg=COLORS["panel"], padx=card_pad_x, pady=card_pad_y); c2.pack(fill=tk.X, pady=5)
        tk.Label(c2, text="Выбрать даты", font=("Segoe UI", 12, "bold"), bg=COLORS["panel"], fg=COLORS["success"]).pack(anchor="w")
        tk.Label(c2, text="Обработать видео за выбранные дни", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w", pady=(2, 8))
        self.selected_dates_label = tk.Label(c2, text="Даты выбираются перед запуском", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.selected_dates_label.pack(anchor="w", pady=(0, 6))
        self.selected_dates = []
        tk.Button(c2, text="Обработать по датам", command=lambda: self.select_dates(auto_start=True), font=("Segoe UI", 10, "bold"), bg=COLORS["success"], fg="white", relief="flat", cursor="hand2", padx=20, pady=10).pack(fill=tk.X)

        # === КАРТОЧКА 3: АВТООБРАБОТКА ===
        c3 = tk.Frame(left, bg=COLORS["panel"], padx=card_pad_x, pady=12 if self.embedded else 15); c3.pack(fill=tk.X, pady=5)
        tk.Label(c3, text="Автообработка", font=("Segoe UI", 11, "bold"), bg=COLORS["panel"], fg=COLORS["warning"]).pack(anchor="w")
        tk.Label(c3, text="Ищет новые сделки и готовые записи OBS", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w", pady=(2, 6))
        self.auto_status_label = tk.Label(c3, text="Выключена", font=("Segoe UI", 9, "bold"), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.auto_status_label.pack(anchor="w", pady=(0, 6))
        action_button_font = ("Segoe UI", 10, "bold")
        self.auto_button = tk.Button(c3, text="Запустить автообработку", command=self.toggle_auto_process,
                                     font=action_button_font, bg=COLORS["success"], fg="white",
                                     relief="flat", cursor="hand2", pady=10)
        self.auto_button.pack(fill=tk.X, pady=(0, 8))
        self.server_status_label = tk.Label(c3, text="Локальный сервер: запуск...", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.server_status_label.pack(anchor="w", pady=(0, 4))
        self.api_status_label = tk.Label(c3, text="TMM API: проверка...", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.api_status_label.pack(anchor="w", pady=(0, 3))
        self.clips_status_label = tk.Label(c3, text="Клипы: подсчёт...", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.clips_status_label.pack(anchor="w", pady=(0, 3))
        self.links_status_label = tk.Label(c3, text="Ссылки: подсчёт...", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.links_status_label.pack(anchor="w", pady=(0, 4))
        self.queue_status_label = tk.Label(c3, text="Очередь: подсчёт...", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.queue_status_label.pack(anchor="w", pady=(0, 4))
        self.link_sync_var = tk.BooleanVar(value=self.auto_sync_video_links)
        tk.Checkbutton(
            c3, text="Автоматически добавлять ссылки в TMM", variable=self.link_sync_var,
            command=self.on_link_sync_toggle,
            bg=COLORS["panel"], fg=COLORS["text"], selectcolor=COLORS["entry_bg"],
            activebackground=COLORS["panel"], activeforeground=COLORS["text"],
            font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(0, 5))
        self.stop_button = tk.Button(c3, text="Стоп обработки", command=self.stop_all_processing,
                                     font=action_button_font, bg=COLORS["error"], fg="white",
                                     activebackground="#b74444", activeforeground="white",
                                     relief="flat", cursor="hand2", pady=10)
        self.stop_button.pack(fill=tk.X, pady=(8, 4))
        tk.Button(c3, text="Проверить систему", command=self.run_diagnostics,
                  font=("Segoe UI", 9, "bold"), bg=COLORS["entry_bg"], fg=COLORS["text"],
                  relief="flat", cursor="hand2", pady=7).pack(fill=tk.X, pady=2)

        service_actions = [
            [("Обновить сделки", self.update_cache), ("Папка", lambda: os.startfile(self.output_folder)),
             ("Очередь", self.open_queue_window)],
            [("Ссылки", self.open_links_window), ("Хранилище", self.open_storage_window)],
        ]
        if CUSTOM_LOGIC and hasattr(CUSTOM_LOGIC, "open_patch_manager"):
            service_actions[1].append(("Патч", lambda: CUSTOM_LOGIC.open_patch_manager(self)))
        for row_actions in service_actions:
            service = tk.Frame(c3, bg=COLORS["panel"]); service.pack(fill=tk.X, pady=(5, 0))
            for txt, cmd in row_actions:
                tk.Button(service, text=txt, command=cmd, font=("Segoe UI", 8), bg=COLORS["entry_bg"],
                          fg=COLORS["text"], relief="flat", cursor="hand2", padx=7, pady=5).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # === ПРАВАЯ ЧАСТЬ (ЛОГИ) ===
        lf = tk.Frame(right, bg=COLORS["panel"], padx=15, pady=12); lf.pack(fill=tk.BOTH, expand=True)
        hdr = tk.Frame(lf, bg=COLORS["panel"]); hdr.pack(fill=tk.X, pady=(0, 8))
        tk.Label(hdr, text="Логи работы", font=("Segoe UI", 10, "bold"), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(side=tk.LEFT)
        for txt, cmd in [("Очистить", self.clear_logs), ("Копировать", self.copy_logs)]:
            tk.Button(hdr, text=txt, command=cmd, font=("Segoe UI", 7), bg=COLORS["entry_bg"], fg=COLORS["text_dim"], relief="flat", cursor="hand2", padx=8).pack(side=tk.RIGHT, padx=2)
        self.log_text = scrolledtext.ScrolledText(lf, font=("Segoe UI", 9), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", borderwidth=0, padx=10, pady=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.tag_config("INFO", foreground=COLORS["log_info"])
        self.log_text.tag_config("WARN", foreground=COLORS["log_warn"])
        self.log_text.tag_config("ERROR", foreground=COLORS["log_error"])

        pf = tk.Frame(lf, bg=COLORS["panel"]); pf.pack(fill=tk.X, pady=(8, 0))
        self.progress_canvas = tk.Canvas(pf, height=6, bg=COLORS["entry_bg"], highlightthickness=0); self.progress_canvas.pack(fill=tk.X)
        self.progress_label = tk.Label(pf, text="", font=("Segoe UI", 7), bg=COLORS["panel"], fg=COLORS["text_dim"]); self.progress_label.pack(anchor="e", pady=(2, 0))

        # === НИЖНЯЯ ПАНЕЛЬ НАСТРОЕК ===
        sf = tk.Frame(main, bg=COLORS["panel"], padx=12 if self.embedded else 15, pady=8 if self.embedded else 10); sf.pack(fill=tk.X, pady=(6 if self.embedded else 8, 0))

        af = tk.Frame(sf, bg=COLORS["panel"]); af.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        tk.Label(af, text="API ключ TMM", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w")
        api_frame = tk.Frame(af, bg=COLORS["panel"]); api_frame.pack(fill=tk.X, pady=(2, 0))
        self.api_var = tk.StringVar(value=self.api_key)
        self.api_entry = tk.Entry(
            api_frame, textvariable=self.api_var, font=("Segoe UI", 9),
            bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", show="*"
        )
        self.api_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.api_entry.bind("<KeyRelease>", self._on_api_key_changed)
        self.show_api_var = tk.BooleanVar(value=False)
        self.api_toggle_btn = tk.Button(api_frame, text="👁", command=self.toggle_api_visibility,
                                        font=("Segoe UI", 9), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", cursor="hand2", padx=4)
        self.api_toggle_btn.pack(side=tk.RIGHT)

        filter_frame = tk.Frame(af, bg=COLORS["panel"])
        filter_frame.pack(fill=tk.X, pady=(6, 0))
        tk.Label(filter_frame, text="Режим сделок", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w")
        filter_buttons = tk.Frame(filter_frame, bg=COLORS["panel"])
        filter_buttons.pack(fill=tk.X, pady=(2, 0))
        self.trade_filter_var = tk.StringVar(value=self.trade_filter_mode)
        for mode, text in ((TRADE_FILTER_ALL, "Все"), (TRADE_FILTER_MINE_ONLY, "Только мои")):
            tk.Radiobutton(
                filter_buttons, text=text, value=mode, variable=self.trade_filter_var,
                command=self._on_trade_filter_changed, bg=COLORS["panel"], fg=COLORS["text"],
                selectcolor=COLORS["entry_bg"], activebackground=COLORS["panel"],
                activeforeground=COLORS["text"], font=("Segoe UI", 8)
            ).pack(side=tk.LEFT, padx=(0, 8))
        ids_frame = tk.Frame(filter_frame, bg=COLORS["panel"])
        ids_frame.pack(fill=tk.X, pady=(3, 0))
        tk.Label(ids_frame, text="Мои api_key_id", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(0, 6))
        self.my_api_ids_var = tk.StringVar(value=format_api_key_ids(self.my_api_key_ids))
        self.my_api_ids_entry = tk.Entry(
            ids_frame, textvariable=self.my_api_ids_var, font=("Segoe UI", 8),
            bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat"
        )
        self.my_api_ids_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.my_api_ids_entry.bind("<KeyRelease>", self._on_my_api_ids_changed)
        self.trade_filter_status_label = tk.Label(filter_frame, text="", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"])
        self.trade_filter_status_label.pack(anchor="w", pady=(2, 0))
        self._update_trade_filter_controls()

        ff = tk.Frame(sf, bg=COLORS["panel"]); ff.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        tk.Label(ff, text="Папка OBS", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w")
        fr = tk.Frame(ff, bg=COLORS["panel"]); fr.pack(fill=tk.X, pady=(2, 0))
        self.fl = tk.Label(fr, text=self._short_path(self.obs_folder), font=("Segoe UI", 8), bg=COLORS["entry_bg"], fg=COLORS["text_dim"], anchor="w", padx=5, pady=3)
        self.fl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(fr, text="...", command=self.choose_obs_folder, font=("Segoe UI", 7), bg=COLORS["accent"], fg="white", relief="flat", cursor="hand2", padx=6).pack(side=tk.RIGHT)

        of = tk.Frame(sf, bg=COLORS["panel"]); of.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        tk.Label(of, text="Куда сохранять", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w")
        ofr = tk.Frame(of, bg=COLORS["panel"]); ofr.pack(fill=tk.X, pady=(2, 0))
        self.out_label = tk.Label(ofr, text=self.output_folder[:25] if self.output_folder else CUT_VIDEOS_DIR[:25], font=("Segoe UI", 8), bg=COLORS["entry_bg"], fg=COLORS["text_dim"], anchor="w", padx=5, pady=3)
        self.out_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(ofr, text="...", command=self.choose_output_folder, font=("Segoe UI", 7), bg=COLORS["accent"], fg="white", relief="flat", cursor="hand2", padx=6).pack(side=tk.RIGHT)

        # Буферы
        bf = tk.Frame(sf, bg=COLORS["panel"]); bf.pack(side=tk.LEFT, padx=8)
        tk.Label(bf, text="Буфер (сек)", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w")
        br = tk.Frame(bf, bg=COLORS["panel"]); br.pack(pady=(2, 0))
        self.bv = tk.StringVar(value=str(self.buffer_before)); self.av = tk.StringVar(value=str(self.buffer_after))
        tk.Label(br, text="До:", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(side=tk.LEFT)
        tk.Button(br, text="−", command=lambda: self._adj_buf("before", -1), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", cursor="hand2", width=2).pack(side=tk.LEFT)
        self.blabel = tk.Label(br, text=str(self.buffer_before), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["accent"], width=2, anchor="center"); self.blabel.pack(side=tk.LEFT)
        tk.Button(br, text="+", command=lambda: self._adj_buf("before", 1), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", cursor="hand2", width=2).pack(side=tk.LEFT)
        tk.Label(br, text="После:", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(br, text="−", command=lambda: self._adj_buf("after", -1), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", cursor="hand2", width=2).pack(side=tk.LEFT)
        self.alabel = tk.Label(br, text=str(self.buffer_after), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["accent"], width=2, anchor="center"); self.alabel.pack(side=tk.LEFT)
        tk.Button(br, text="+", command=lambda: self._adj_buf("after", 1), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", cursor="hand2", width=2).pack(side=tk.LEFT)

        # Сдвиг времени (Time Offset) для ручной калибровки рассинхронизации ПК и биржи
        tf = tk.Frame(sf, bg=COLORS["panel"]); tf.pack(side=tk.LEFT, padx=8)
        tk.Label(tf, text="Сдвиг (сек)", font=("Segoe UI", 8), bg=COLORS["panel"], fg=COLORS["text_dim"]).pack(anchor="w")
        tr = tk.Frame(tf, bg=COLORS["panel"]); tr.pack(pady=(2, 0))
        self.ov = tk.StringVar(value=str(self.time_offset))
        tk.Button(tr, text="−", command=lambda: self._adj_offset(-1), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", cursor="hand2", width=2).pack(side=tk.LEFT)
        self.olabel = tk.Label(tr, text=str(self.time_offset), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["warning"], width=3, anchor="center"); self.olabel.pack(side=tk.LEFT)
        tk.Button(tr, text="+", command=lambda: self._adj_offset(1), font=("Segoe UI", 10, "bold"), bg=COLORS["entry_bg"], fg=COLORS["text"], relief="flat", cursor="hand2", width=2).pack(side=tk.LEFT)

    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========
    def _adj_buf(self, which, delta):
        if which == "before":
            self.buffer_before = max(0, min(60, self.buffer_before + delta))
            self.bv.set(str(self.buffer_before)); self.blabel.config(text=str(self.buffer_before))
        else:
            self.buffer_after = max(0, min(60, self.buffer_after + delta))
            self.av.set(str(self.buffer_after)); self.alabel.config(text=str(self.buffer_after))

    def _adj_offset(self, delta):
        self.time_offset = max(-3600, min(3600, self.time_offset + delta))
        self.ov.set(str(self.time_offset))
        self.olabel.config(text=str(self.time_offset))

    def log(self, level, msg):
        ts = datetime.now().strftime("%H:%M:%S"); line = f"[{ts}] {LOG_LEVELS.get(level, '[INFO]')} {msg}"
        print(line); log_to_file(level, msg)
        def append_line():
            if hasattr(self, 'log_text') and self.log_text.winfo_exists():
                self.log_text.insert(tk.END, line+"\n", level)
                self.log_text.see(tk.END)
        self.run_on_ui(append_line)

    def clear_logs(self): self.log_text.delete(1.0, tk.END)

    def copy_logs(self):
        self.root.clipboard_clear(); self.root.clipboard_append(self.log_text.get(1.0, tk.END))

    def set_status(self, t, c=None):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self.set_status, t, c)
            return
        self.sl.config(text=t, fg=c or COLORS["success"])
        self.sc.itemconfig(self.dot, fill=c or COLORS["success"])

    def update_progress(self, pct, txt=""):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self.update_progress, pct, txt)
            return
        self.progress_canvas.delete("all")
        w = self.progress_canvas.winfo_width() or 400
        self.progress_canvas.create_rectangle(0, 0, (pct/100)*w, 6, fill=COLORS["accent"], outline="")
        if txt is not None:
            self.progress_label.config(text=txt)

    def update_cache_time_display(self):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self.update_cache_time_display)
            return
        _, lu = load_trades_cache(self.api_key)
        if lu:
            try:
                dt = datetime.fromisoformat(lu)
                diff = datetime.now() - dt
                mins = int(diff.total_seconds() / 60)
                self.cache_time_label.config(text=f"({mins}м назад)" if mins < 60 else f"({mins//60}ч назад)")
            except: self.cache_time_label.config(text="")
        else: self.cache_time_label.config(text="")

    def toggle_api_visibility(self):
        if self.show_api_var.get():
            self.api_entry.config(show="*")
            self.api_toggle_btn.config(text="👁")
            self.show_api_var.set(False)
        else:
            self.api_entry.config(show="")
            self.api_toggle_btn.config(text="🔒")
            self.show_api_var.set(True)

    def _on_api_key_changed(self, _event=None):
        self.api_key = self.api_var.get().strip()

    def choose_obs_folder(self):
        p = filedialog.askdirectory(title="Папка с video OBS")
        if p:
            self.obs_folder = p
            self.cfg["obs_folder"] = p
            self.fl.config(text=self._short_path(p))
            self.log("INFO", f"Папка OBS: {p}")

    def choose_output_folder(self):
        p = filedialog.askdirectory(title="Папка для сохранения нарезок")
        if p:
            self.output_folder = p
            self.out_label.config(text=p[:25])
            self.log("INFO", f"Папка сохранения: {p}")

    def save_settings(self):
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        self.cfg["tmm_api_key"] = self.api_key
        self.cfg["obs_folder"] = self.obs_folder
        self.cfg["output_folder"] = self.output_folder
        self.cfg["buffer_before"] = self.buffer_before; self.cfg["buffer_after"] = self.buffer_after
        self.cfg["time_offset"] = self.time_offset
        self.cfg["auto_process"] = self.auto_process_active
        self.auto_sync_video_links = bool(self.link_sync_var.get())
        self.cfg["auto_sync_video_links"] = self.auto_sync_video_links
        self.cfg["local_server_port"] = self.local_server_port
        self.cfg["local_server_token"] = self.local_server_token
        self.cfg["folder_naming"] = "tmm_time_seconds_symbol_percent_duration_entry_reason"
        save_config(self.cfg); self.log("INFO", "Настройки сохранены"); messagebox.showinfo("Готово","Настройки успешно сохранены!")
        self.auto_update_cache(force=True)

    def show_dev_info(self):
        if not os.path.exists(DEVINFO_PATH): generate_dev_info()
        try:
            with open(DEVINFO_PATH, "r", encoding="utf-8") as f: info = f.read()
        except: info = "Документ не найден"
        win = tk.Toplevel(self.root); win.title("Техническая информация"); win.geometry("700x500"); win.configure(bg=COLORS["bg"])
        txt = scrolledtext.ScrolledText(win, font=("Consolas", 9), bg=COLORS["panel"], fg=COLORS["text"]); txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        txt.insert(1.0, info); txt.config(state="disabled")
        tk.Button(win, text="Закрыть", command=win.destroy, bg=COLORS["panel"], fg=COLORS["text"]).pack(pady=5)

    def show_welcome(self):
        self.log("INFO", "="*50); self.log("INFO", "TMM Video Cutter Pro v24.13.15"); self.log("INFO", "="*50)
        t, _ = load_trades_cache(self.api_key)
        scoped = self._filter_trades_for_current_scope(t)
        if t and self._trade_filter_active():
            self.log("INFO", f"Сделки TMM: {len(scoped)} из {len(t)} в текущем режиме")
            if not scoped:
                found_ids = format_api_key_id_counts(t)
                selected_ids = format_api_key_ids(self.my_api_key_ids) or "не заданы"
                if found_ids:
                    self.log("WARN", f"В локальной базе нет сделок для выбранных api_key_id ({selected_ids}); найдено: {found_ids}")
                else:
                    self.log("WARN", "В локальной базе нет поля api_key_id, поэтому режим 'Только мои' не может выбрать сделки.")
        else:
            self.log("INFO", f"Сделки TMM: {len(t)} в локальной базе" if t else "Сделки TMM ещё не загружены; дождитесь автообновления.")
        self.log("INFO", f"Часовой пояс папок TMM: {get_tmm_timezone_name()}")

    def auto_update_cache(self, force=False):
        if not self.api_key:
            return
        should_update = bool(force)
        t, lu = load_trades_cache(self.api_key)
        if not t:
            should_update = True
        elif lu:
            try:
                should_update = should_update or (datetime.now() - datetime.fromisoformat(lu)).total_seconds() / 3600 > 1
            except Exception:
                should_update = True
        if should_update:
            self._start_cache_update(self.api_key, "Автообновление сделок", force=force, retry_on_empty=True)

    def _set_trade_count(self, count, total=None):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self._set_trade_count, count, total)
            return
        self.cl.config(text=self._trade_count_text(count, total))

    def _start_cache_update(self, api_key, context="Обновление сделок", force=False, retry_on_empty=False):
        with self._cache_update_lock:
            if self._cache_update_running:
                return False
            self._cache_update_running = True
        threading.Thread(
            target=self._cache_update_worker,
            args=(api_key, context, force, retry_on_empty),
            daemon=True
        ).start()
        return True

    def _schedule_cache_retry(self, delay_seconds=300):
        if self._cache_retry_scheduled or self.stop_flag:
            return
        self._cache_retry_scheduled = True
        minutes = max(1, int(delay_seconds / 60))
        self.log("WARN", f"Сделки TMM не обновились; повторю автоматически через {minutes} мин.")

        def retry():
            self._cache_retry_scheduled = False
            if not self.stop_flag and self.api_key:
                self.auto_update_cache(force=False)

        self.run_on_ui(lambda: self.root.after(int(delay_seconds * 1000), retry))

    def _cache_update_worker(self, api_key, context="Обновление сделок", force=False, retry_on_empty=False):
        try:
            remaining = tmm_api_cooldown_remaining()
            if remaining > 0:
                t, _ = load_trades_cache(api_key)
                scoped = self._filter_trades_for_current_scope(t, context)
                self._set_trade_count(len(scoped), len(t) if self._trade_filter_active() else None)
                minutes = max(1, int((remaining + 59) // 60))
                self.set_status("TMM API на паузе", COLORS["warning"])
                self._update_api_status(f"TMM API: лимит, пауза {minutes} мин", COLORS["warning"])
                if retry_on_empty:
                    self._schedule_cache_retry(max(60, remaining))
                return
            self.refresh_tmm_timezone(force=force, api_key=api_key, log_success=force)
            t = update_trades_cache(api_key, log_cb=self.log, bypass_cooldown=False)
            scoped = self._filter_trades_for_current_scope(t, context)
            self._set_trade_count(len(scoped), len(t) if self._trade_filter_active() else None)
            self.update_cache_time_display()
            if LAST_TMM_API_STATUS == 429:
                remaining = tmm_api_cooldown_remaining()
                minutes = max(1, int((remaining + 59) // 60))
                self.set_status("TMM API на паузе", COLORS["warning"])
                self._update_api_status(f"TMM API: лимит, пауза {minutes} мин", COLORS["warning"])
                if t:
                    self.log("WARN", f"{context}: TMM не обновился, использую локальную базу: {len(t)} сделок, доступно в текущем режиме: {len(scoped)}")
                if retry_on_empty:
                    self._schedule_cache_retry(max(60, remaining))
            elif t:
                self.set_status("Готов", COLORS["success"])
                self.log("INFO", f"{context}: обновлено {len(t)} сделок, доступно в текущем режиме: {len(scoped)}")
            elif LAST_TMM_API_STATUS in (401, 403):
                self.set_status("API-ключ TMM отклонён", COLORS["error"])
                self._update_api_status("TMM API: ключ отклонён", COLORS["error"])
                self.log("ERROR", "Автоповтор обновления сделок остановлен: TMM отклонил API-ключ. Вставьте новый ключ и сохраните настройки.")
            elif retry_on_empty:
                self.set_status("Нет данных TMM", COLORS["warning"])
                self._schedule_cache_retry()
        finally:
            with self._cache_update_lock:
                self._cache_update_running = False

    def update_cache(self):
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        if not self.api_key: messagebox.showerror("Ошибка","Введите API ключ!"); return
        self.log("INFO", "Обновление сделок TMM..."); self.set_status("Обновление...", COLORS["warning"])
        if not self._start_cache_update(self.api_key, "Обновление сделок", force=True, retry_on_empty=True):
            self.log("INFO", "Обновление сделок уже выполняется")

    def _update_cache_worker(self, api_key):
        self._cache_update_worker(api_key, "Обновление сделок", force=True, retry_on_empty=True)

    # ========== НАРЕЗКА ОДНОГО ВИДЕО ==========
    def cut_single_video(self, filepath=None):
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        if not self.api_key: messagebox.showerror("Ошибка","Введите API ключ!"); return
        if not filepath:
            filepath = filedialog.askopenfilename(title="Выберите видеозапись экрана", filetypes=[("Видео файлы","*.mp4 *.mkv *.avi *.mov *.ts"),("Все файлы","*.*")])
        if not filepath: return
        self.do_cut_video(filepath)

    def do_cut_video(self, vp):
        self.log("INFO", f"Анализ видеофайла: {os.path.basename(vp)}")
        wp, ti, lt = is_video_processed(vp, self._current_scope_trade_ids())
        if wp and not messagebox.askyesno("Повторный запуск", f"Это видео уже нарезалось.\nСделок создано: {ti}\nДата нарезки: {lt[:19]}\n\nНарезать повторно?"): return
        self.set_status("Поиск совпадений...", COLORS["warning"])
        self.update_progress(5, "Запуск анализа...")
        threading.Thread(target=self._analyze_video, args=(vp, self.api_key), daemon=True).start()

    def _analyze_video(self, vp, api_key):
        self.refresh_tmm_timezone(api_key=api_key)
        vi = get_video_info(vp)
        if vi['duration_sec'] <= 0:
            self.log("ERROR", "FFmpeg не смог прочитать длительность видео.")
        self.log("INFO", f"Анализ: {vi['name']} ({vi['size_mb']:.1f}MB, длит. {vi['duration_sec']:.0f} сек)")
        self.log("INFO", f"Время старта видео определено как: {vi['start_time'].astimezone().strftime('%Y-%m-%d %H:%M:%S')} (метод: {vi['start_method']})")

        trades = get_trades(api_key, log_cb=self.log)
        if not trades: self.log("ERROR","Сделки TMM не загружены, API не вернуло данных."); self.set_status("Ошибка", COLORS["error"]); return
        if self._stop_if_stale_cache_misses_video_dates(trades, [vi], "Ручной анализ"):
            return
        trades = self._filter_trades_for_current_scope(trades, "Ручной анализ")
        if not trades: self.log("WARN","В текущем режиме фильтрации нет доступных сделок."); self.set_status("Нет сделок", COLORS["warning"]); return

        matched = match_trades_to_video(vi, trades)
        self.log("INFO", f"Найдено сделок в этом промежутке: {len(matched)}")
        if not matched: self.log("WARN","Нет сделок, попадающих во временной интервал видео"); self.set_status("Нет сделок", COLORS["warning"]); return
        self.run_on_ui(self._show_trade_selection, vi, matched)

    def _show_trade_selection(self, vi, matched):
        win = tk.Toplevel(self.root); win.title("Выберите сделки для нарезки"); win.geometry("600x500"); win.configure(bg=COLORS["bg"])
        win.transient(self.root); win.grab_set()

        video_start_local = vi['start_time'].astimezone().strftime('%H:%M:%S')
        tk.Label(win, text=f"Видео началось в: {video_start_local}", font=("Segoe UI",10,"bold"), bg=COLORS["bg"], fg=COLORS["warning"]).pack(pady=(10, 2))
        tk.Label(win, text="Сделки в интервале видео", font=("Segoe UI",12,"bold"), bg=COLORS["bg"], fg=COLORS["accent"]).pack(pady=(0, 10))

        frame = tk.Frame(win, bg=COLORS["bg"]); frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        canvas = tk.Canvas(frame, bg=COLORS["bg"], highlightthickness=0); canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)
        inner = tk.Frame(canvas, bg=COLORS["bg"]); canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        vars = []
        for t in matched:
            tid = str(t.get('id', ''))
            already_done = is_processed(
                tid, t, self.output_folder or CUT_VIDEOS_DIR,
                self.format_trade_folder, vi.get("path", "")
            )
            # По умолчанию выбираем только те сделки, которые еще не нарезались
            var = tk.BooleanVar(value=not already_done)
            vars.append(var)

            ot = parse_trade_time(t, True); ct = parse_trade_time(t, False)
            ot_local = ot.astimezone(get_tmm_timezone()) if ot else None
            ct_local = ct.astimezone(get_tmm_timezone()) if ct else None

            txt = f"{t.get('symbol','?')} {t.get('side','?')} PnL={t.get('realized_pnl',0)}"
            if ot_local: txt += f"  откр:{ot_local.strftime('%H:%M:%S')}"
            if ct_local: txt += f"  закрыт:{ct_local.strftime('%H:%M:%S')}"
            record = get_processed_record(tid)
            if already_done:
                txt += f" [НАРЕЗАНО, {format_trade_link_status(record)}]"
            elif record and record.get("link_status") == "missing":
                txt += " [ФАЙЛ УДАЛЁН]"

            row = tk.Frame(inner, bg=COLORS["bg"])
            row.pack(fill=tk.X, pady=2)
            tk.Checkbutton(row, text=txt, variable=var,
                           bg=COLORS["bg"],
                           fg=COLORS["text_dim"] if already_done else COLORS["text"],
                           selectcolor=COLORS["panel"],
                           activebackground=COLORS["bg"]).pack(side=tk.LEFT, anchor="w", fill=tk.X, expand=True)
            tk.Button(row, text="Просмотр", command=lambda trade=t: self.show_cut_preview(vi, trade),
                      font=("Segoe UI", 7), bg=COLORS["entry_bg"], fg=COLORS["text_dim"],
                      relief="flat", cursor="hand2", padx=6).pack(side=tk.RIGHT, padx=3)

        btn_frame = tk.Frame(win, bg=COLORS["bg"]); btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Выбрать все", command=lambda: [v.set(True) for v in vars], bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Снять все", command=lambda: [v.set(False) for v in vars], bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT, padx=5)
        def start_cut():
            selected = [t for t, v in zip(matched, vars) if v.get()]
            if not selected: messagebox.showwarning("Ничего не выбрано","Выберите хотя бы одну сделку"); return
            win.destroy()
            self._start_cutting(vi, selected)
        tk.Button(btn_frame, text="Нарезать выбранные", command=start_cut, font=("Segoe UI",10,"bold"), bg=COLORS["accent"], fg="white").pack(side=tk.LEFT, padx=10)

    def _start_cutting(self, vi, trades):
        if not self._try_begin_processing("ручная нарезка"):
            messagebox.showwarning("Обработка занята", "Сначала остановите текущую обработку.")
            return
        self.set_status("Нарезка...", COLORS["warning"])
        self.update_progress(0, "Нарезка...")
        bf, ba = int(self.bv.get()), int(self.av.get())
        to = int(self.ov.get())
        out_dir = self.output_folder or CUT_VIDEOS_DIR
        total = len(trades)
        completed = 0
        def progress_cb():
            nonlocal completed; completed += 1
            self.update_progress(completed/total*100, f"Нарезано: {completed}/{total}")
        def log_cb(level, msg): self.log(level, f"  {msg}")
        threading.Thread(target=self._run_cutting, args=(trades, vi, bf, ba, to, out_dir, progress_cb, log_cb), daemon=True).start()

    def _run_cutting(self, trades, vi, bf, ba, _to, out_dir, progress_cb, log_cb):
        try:
            job_ids = create_processing_jobs(trades, vi, "Ручная", bf, ba, _to, out_dir)
            self.run_on_ui(self.refresh_queue_view)
            results = cut_trades_parallel(
                trades, vi, bf, ba, out_dir, max_workers=1, time_offset=_to,
                progress_cb=progress_cb, log_cb=log_cb,
                folder_name_cb=self.format_trade_folder,
                cancel_event=self.processing_cancel_event,
                process_cb=self._set_active_ffmpeg_process,
                job_ids=job_ids
            )
            ok_count = self._mark_successful_results(results, vi, out_dir)
            mark_video_processed(vi['path'], ok_count)
            if self.processing_cancel_event.is_set():
                self.update_progress(0, "Остановлено")
                self.set_status("Остановлено", COLORS["warning"])
                log_cb("WARN", f"Обработка остановлена. Готово: {ok_count}/{len(trades)}")
            else:
                self.update_progress(100, f"Завершено: {ok_count}/{len(trades)}")
                self.set_status("Готов", COLORS["success"])
                log_cb("INFO", f"Успешно обработано: {ok_count} клипов из {len(trades)}")
                if ok_count > 0:
                    self.run_on_ui(os.startfile, out_dir)
        finally:
            self._finish_processing()

    # ========== ВЫБОР ДАТ (ПАКЕТНЫЙ РЕЖИМ) ==========
    def select_dates(self, auto_start=False):
        obs = self.obs_folder
        if not obs or not os.path.exists(obs):
            messagebox.showerror("Ошибка","Сначала укажите рабочую папку OBS в настройках.")
            return
        if not self._try_begin_date_task():
            messagebox.showwarning("Обработка занята", "Дождитесь завершения текущей подготовки или остановите обработку.")
            return
        self.set_status("Поиск дат OBS...", COLORS["warning"])
        self.update_progress(3, "Поиск дат OBS...")
        threading.Thread(target=self._select_dates_worker, args=(obs, auto_start), daemon=True).start()

    def _select_dates_worker(self, obs, auto_start=False):
        try:
            videos = get_video_date_index(obs)
            if self.processing_cancel_event.is_set():
                self.update_progress(0, "Остановлено")
                self.set_status("Остановлено", COLORS["warning"])
                return
            dates_set = set()
            tmm_tz = get_tmm_timezone()
            today_tmm = datetime.now(tmm_tz).date()
            for v in videos:
                start_date = v['start_time'].astimezone(tmm_tz).date()
                dates_set.add(start_date)
                next_date = start_date + timedelta(days=1)
                if next_date <= today_tmm:
                    # A recording can start before midnight and contain trades from the next TMM day.
                    dates_set.add(next_date)
            dates_list = sorted(dates_set, reverse=True)
            if not dates_list:
                self.run_on_ui(
                    messagebox.showinfo,
                    "Папка пуста",
                    "В указанной папке OBS не найдено поддерживаемых видеофайлов"
                )
                self.update_progress(0, "Видео не найдены")
                self.set_status("Нет видео", COLORS["warning"])
                return
            self.run_on_ui(self._show_date_selection_window, dates_list, auto_start)
            self.update_progress(0, "")
            self.set_status("Готов", COLORS["success"])
        except Exception as error:
            self.log("ERROR", f"Ошибка поиска дат OBS: {error}")
            self.update_progress(0, "Ошибка поиска дат")
            self.set_status("Ошибка", COLORS["error"])
        finally:
            self._finish_date_task()

    def _show_date_selection_window(self, dates_list, auto_start=False):
        win = tk.Toplevel(self.root); win.title("Выбор дней для обработки"); win.geometry("400x500"); win.configure(bg=COLORS["bg"])
        win.transient(self.root); win.grab_set()
        tk.Label(win, text="Выберите дни для пакетного сканирования", font=("Segoe UI",12,"bold"), bg=COLORS["bg"], fg=COLORS["accent"]).pack(pady=10)
        frame = tk.Frame(win, bg=COLORS["bg"]); frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        canvas = tk.Canvas(frame, bg=COLORS["bg"], highlightthickness=0); canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)
        inner = tk.Frame(canvas, bg=COLORS["bg"]); canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        vars = {}
        for d in dates_list:
            var = tk.BooleanVar(value=False)
            vars[d] = var
            txt = d.strftime("%d.%m.%Y") + f" ({get_day_folder(d)})"
            tk.Checkbutton(inner, text=txt, variable=var, bg=COLORS["bg"], fg=COLORS["text"], selectcolor=COLORS["panel"], activebackground=COLORS["bg"]).pack(anchor="w", pady=2)
        btn_frame = tk.Frame(win, bg=COLORS["bg"]); btn_frame.pack(pady=10)
        def apply():
            selected = [d for d, var in vars.items() if var.get()]
            if not selected:
                messagebox.showwarning("Внимание","Не выбрано ни одного дня")
                return
            self.selected_dates = selected
            self.selected_dates_label.config(text=f"Выбрано дней: {len(selected)}")
            self.log("INFO", f"Выбраны даты для пакетной нарезки: {', '.join(d.strftime('%d.%m.%Y') for d in selected)}")
            win.destroy()
            if auto_start:
                self.root.after(100, self.process_selected_dates)
        tk.Button(btn_frame, text="Выбрать все", command=lambda: [v.set(True) for v in vars.values()], bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Снять все", command=lambda: [v.set(False) for v in vars.values()], bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Применить", command=apply, font=("Segoe UI",10,"bold"), bg=COLORS["accent"], fg="white").pack(side=tk.LEFT, padx=10)

    def process_selected_dates(self):
        if not self.selected_dates:
            messagebox.showwarning("Внимание","Сначала выберите даты!")
            return
        obs = self.obs_folder
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        if not obs or not self.api_key:
            messagebox.showerror("Ошибка","Убедитесь, что API ключ введен и папка OBS выбрана")
            return
        if not self._try_begin_date_task():
            messagebox.showwarning("Обработка занята", "Дождитесь завершения текущей подготовки или остановите обработку.")
            return
        selected_dates = list(self.selected_dates or [])
        self.log("INFO", f"Запущена пакетная обработка по датам: {', '.join(d.strftime('%d.%m.%Y') for d in selected_dates)}")
        self.set_status("Поиск видео...", COLORS["warning"])
        self.update_progress(4, "Поиск видео OBS...")
        threading.Thread(
            target=self._process_dates_prepare_worker,
            args=(obs, selected_dates, self.api_key),
            daemon=True
        ).start()

    def _process_dates_prepare_worker(self, obs, selected_dates, api_key):
        try:
            videos = get_videos_for_tmm_dates(obs, selected_dates)
            if self.processing_cancel_event.is_set():
                self.update_progress(0, "Остановлено")
                self.set_status("Остановлено", COLORS["warning"])
                return
            if not videos:
                self.run_on_ui(
                    messagebox.showwarning,
                    "Файлы не найдены",
                    "За выбранные дни видеофайлы не найдены."
                )
                self.update_progress(0, "Видео не найдены")
                self.set_status("Нет видео", COLORS["warning"])
                return
            self.log("INFO", f"Найдено видеофайлов за выбранные дни: {len(videos)}")
            self.set_status("Поиск сделок...", COLORS["warning"])
            self.update_progress(12, "Синхронизация сделок...")
            self._process_dates_worker(videos, api_key, selected_dates)
        except Exception as error:
            self.log("ERROR", f"Ошибка пакетной обработки по датам: {error}")
            self.update_progress(0, "Ошибка")
            self.set_status("Ошибка", COLORS["error"])
        finally:
            self._finish_date_task()

    def _process_dates_worker(self, videos, api_key, selected_dates=None):
        self.refresh_tmm_timezone(api_key=api_key)
        if self.processing_cancel_event.is_set():
            self.update_progress(0, "Остановлено")
            self.set_status("Остановлено", COLORS["warning"])
            return
        trades = get_trades(api_key, log_cb=self.log)
        if self.processing_cancel_event.is_set():
            self.update_progress(0, "Остановлено")
            self.set_status("Остановлено", COLORS["warning"])
            return
        if not trades:
            self.log("ERROR","Не удалось получить сделки."); self.set_status("Ошибка", COLORS["error"]); return
        if self._stop_if_stale_cache_misses_video_dates(trades, videos, "Пакетная обработка"):
            return
        trades = self._filter_trades_for_current_scope(trades, "Пакетная обработка")
        if not trades:
            self.log("WARN","В текущем режиме фильтрации нет доступных сделок."); self.set_status("Нет сделок", COLORS["warning"]); return
        selected_dates = list(selected_dates or [])
        if selected_dates:
            before_date_filter = len(trades)
            trades = filter_trades_by_tmm_dates(trades, selected_dates)
            self.log("INFO", f"Пакетная обработка: фильтр дат TMM оставил {len(trades)} из {before_date_filter} сделок")
            if not trades:
                self.log("WARN", "За выбранные даты TMM нет доступных сделок."); self.set_status("Нет сделок", COLORS["warning"]); return
        all_matched = []
        total_videos = max(1, len(videos))
        for index, vi in enumerate(videos, start=1):
            if self.processing_cancel_event.is_set():
                self.update_progress(0, "Остановлено")
                self.set_status("Остановлено", COLORS["warning"])
                return
            self.update_progress(12 + (index / total_videos) * 35, f"Сопоставление видео: {index}/{len(videos)}")
            matched = match_trades_to_video(vi, trades)
            if matched:
                self.log("INFO", f"  В видео {vi['name']} найдено сделок: {len(matched)}")
                for t in matched:
                    all_matched.append((vi, t))
        if not all_matched:
            self.log("WARN","Во всех видеозаписях за эти даты не найдено подходящих сделок."); self.set_status("Нет сделок", COLORS["warning"]); return
        self.update_progress(50, "Готово к выбору сделок")
        self.log("INFO", f"Всего найдено совпадений: {len(all_matched)}")
        self.run_on_ui(self._show_batch_selection, all_matched)

    def _show_batch_selection(self, all_matched):
        grouped = defaultdict(list)
        for vi, t in all_matched:
            grouped[vi['name']].append((vi, t))
        win = tk.Toplevel(self.root); win.title("Пакетная обработка сделок"); win.geometry("650x600"); win.configure(bg=COLORS["bg"])
        win.transient(self.root); win.grab_set()
        tk.Label(win, text="Групповой выбор сделок", font=("Segoe UI",12,"bold"), bg=COLORS["bg"], fg=COLORS["accent"]).pack(pady=10)
        frame = tk.Frame(win, bg=COLORS["bg"]); frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        canvas = tk.Canvas(frame, bg=COLORS["bg"], highlightthickness=0); canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)
        inner = tk.Frame(canvas, bg=COLORS["bg"]); canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        vars = []
        for vname, pairs in grouped.items():
            tk.Label(inner, text=f"📹 {vname}", font=("Segoe UI",10,"bold"), bg=COLORS["bg"], fg=COLORS["warning"]).pack(anchor="w", pady=(8,2))
            for vi, t in pairs:
                tid = str(t.get('id', ''))
                already_done = is_processed(
                    tid, t, self.output_folder or CUT_VIDEOS_DIR,
                    self.format_trade_folder, vi.get("path", "")
                )
                var = tk.BooleanVar(value=not already_done)
                vars.append((var, vi, t))

                ot = parse_trade_time(t, True); ct = parse_trade_time(t, False)
                ot_local = ot.astimezone(get_tmm_timezone()) if ot else None

                txt = f"   {t.get('symbol','?')} {t.get('side','?')} PnL={t.get('realized_pnl',0)}"
                if ot_local: txt += f" (откр {ot_local.strftime('%H:%M:%S')})"
                record = get_processed_record(tid)
                if already_done:
                    txt += f" [НАРЕЗАНО, {format_trade_link_status(record)}]"
                elif record and record.get("link_status") == "missing":
                    txt += " [ФАЙЛ УДАЛЁН]"

                row = tk.Frame(inner, bg=COLORS["bg"])
                row.pack(fill=tk.X, pady=2)
                tk.Checkbutton(row, text=txt, variable=var,
                               bg=COLORS["bg"],
                               fg=COLORS["text_dim"] if already_done else COLORS["text"],
                               selectcolor=COLORS["panel"],
                               activebackground=COLORS["bg"]).pack(side=tk.LEFT, anchor="w", fill=tk.X, expand=True)
                tk.Button(row, text="Просмотр", command=lambda video=vi, trade=t: self.show_cut_preview(video, trade),
                          font=("Segoe UI", 7), bg=COLORS["entry_bg"], fg=COLORS["text_dim"],
                          relief="flat", cursor="hand2", padx=6).pack(side=tk.RIGHT, padx=3)

        btn_frame = tk.Frame(win, bg=COLORS["bg"]); btn_frame.pack(pady=10)
        def start_batch():
            selected_pairs = [(vi, t) for var, vi, t in vars if var.get()]
            if not selected_pairs:
                messagebox.showwarning("Внимание","Выберите сделки для экспорта"); return
            win.destroy()
            self._start_batch_cutting(selected_pairs)
        tk.Button(btn_frame, text="Выбрать все", command=lambda: [v.set(True) for v,_,_ in vars], bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Снять все", command=lambda: [v.set(False) for v,_,_ in vars], bg=COLORS["panel"], fg=COLORS["text"]).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Запустить нарезку", command=start_batch, font=("Segoe UI",10,"bold"), bg=COLORS["accent"], fg="white").pack(side=tk.LEFT, padx=10)

    def _start_batch_cutting(self, selected_pairs):
        if not self._try_begin_processing("пакетная нарезка"):
            messagebox.showwarning("Обработка занята", "Сначала остановите текущую обработку.")
            return
        self.set_status("Нарезка...", COLORS["warning"])
        self.update_progress(0, "Нарезка...")
        bf, ba = int(self.bv.get()), int(self.av.get())
        to = int(self.ov.get())
        out_dir = self.output_folder or CUT_VIDEOS_DIR
        total = len(selected_pairs)
        completed = 0
        def progress_cb():
            nonlocal completed; completed += 1
            self.update_progress(completed/total*100, f"Нарезано: {completed}/{total}")
        def log_cb(level, msg): self.log(level, f"  {msg}")

        def cut_thread():
            completed_ok = 0
            try:
                grouped_pairs = defaultdict(list)
                for vi, t in selected_pairs:
                    grouped_pairs[vi['path']].append(t)
                for vi_path, trades_list in grouped_pairs.items():
                    if self.processing_cancel_event.is_set():
                        break
                    vi = get_video_info(vi_path)
                    job_ids = create_processing_jobs(
                        trades_list, vi, "По датам", bf, ba, to, out_dir
                    )
                    self.run_on_ui(self.refresh_queue_view)
                    results = cut_trades_parallel(
                        trades_list, vi, bf, ba, out_dir, max_workers=1,
                        time_offset=to, progress_cb=progress_cb, log_cb=log_cb,
                        folder_name_cb=self.format_trade_folder,
                        cancel_event=self.processing_cancel_event,
                        process_cb=self._set_active_ffmpeg_process,
                        job_ids=job_ids
                    )
                    ok_count = self._mark_successful_results(results, vi, out_dir)
                    completed_ok += ok_count
                    mark_video_processed(vi['path'], ok_count)
                if self.processing_cancel_event.is_set():
                    self.update_progress(0, "Остановлено")
                    self.set_status("Остановлено", COLORS["warning"])
                    log_cb("WARN", f"Пакетная обработка остановлена. Готово клипов: {completed_ok}")
                else:
                    self.update_progress(100, f"Готово: {completed_ok}/{total}")
                    self.set_status("Готов", COLORS["success"])
                    log_cb("INFO", "Пакетная обработка завершена успешно.")
                    if completed_ok > 0:
                        self.run_on_ui(os.startfile, out_dir)
            finally:
                self._finish_processing()
        threading.Thread(target=cut_thread, daemon=True).start()

    # ========== АВТООБРАБОТКА (ФОНОВЫЙ ЦИКЛ) ==========
    def toggle_auto_process(self):
        if self.auto_process_active:
            self.stop_auto_process()
        else:
            self.start_auto_process()

    def _update_auto_ui(self, status_text=None):
        if threading.get_ident() != self._main_thread_id:
            self.run_on_ui(self._update_auto_ui, status_text)
            return
        if not hasattr(self, "auto_button"):
            return
        if self.auto_process_active:
            self.auto_button.config(text="Остановить автообработку", bg=COLORS["warning"])
            self.auto_status_label.config(text=status_text or "Работает", fg=COLORS["success"])
        else:
            self.auto_button.config(text="Запустить автообработку", bg=COLORS["success"])
            self.auto_status_label.config(text=status_text or "Выключена", fg=COLORS["text_dim"])

    def start_auto_process(self):
        if self.auto_process_active: return
        self.api_key = self.api_entry.get().strip()
        self._sync_trade_filter_from_ui()
        if not self.api_key:
            messagebox.showerror("Автообработка", "Введите API-ключ TMM.")
            return
        if not self.obs_folder or not os.path.isdir(self.obs_folder):
            messagebox.showerror("Автообработка", "Выберите существующую папку OBS.")
            return
        self.auto_process_active = True
        self.auto_stop_event.clear()
        self.cfg["auto_process"] = True
        self.cfg["tmm_api_key"] = self.api_key
        self.cfg["obs_folder"] = self.obs_folder
        save_config(self.cfg)
        self._update_auto_ui("Первое сканирование...")
        self.log("INFO", "Автообработка включена")
        threading.Thread(target=self._auto_process_loop, daemon=True).start()

    def stop_auto_process(self):
        if not self.auto_process_active:
            self._update_auto_ui()
            return
        self.auto_process_active = False
        self.auto_stop_event.set()
        with self._processing_state_lock:
            if self.processing_source == "автообработка":
                self.processing_cancel_event.set()
        self.cfg["auto_process"] = False
        save_config(self.cfg)
        self._update_auto_ui("Выключена")
        self.log("INFO", "Автообработка отключена")

    def _auto_process_loop(self):
        interval = max(10, int(self.cfg.get("auto_process_interval", 60)))
        while self.auto_process_active and not self.auto_stop_event.is_set():
            wait_seconds = interval
            try:
                obs = self.obs_folder
                api = self.api_key
                remaining = tmm_api_cooldown_remaining()
                use_cached_trades_only = False
                if remaining > 0:
                    cached_trades, _ = load_trades_cache(api)
                    wait_seconds = max(interval, remaining)
                    minutes = max(1, int((remaining + 59) // 60))
                    self._update_auto_ui(f"TMM API на паузе: {minutes} мин")
                    use_cached_trades_only = True
                else:
                    self.refresh_tmm_timezone(api_key=api)
                if use_cached_trades_only:
                    trades = cached_trades
                else:
                    self._update_auto_ui("Обновление сделок...")
                    trades = update_trades_cache(
                        api,
                        log_cb=lambda level, msg: self.log(level, msg) if level in ("WARN", "ERROR") else None
                    )
                all_trades_count = len(trades)
                trades = self._filter_trades_for_current_scope(trades, "Автообработка")
                self._set_trade_count(len(trades), all_trades_count if self._trade_filter_active() else None)
                if LAST_TMM_API_STATUS == 429 and not trades:
                    remaining = tmm_api_cooldown_remaining()
                    wait_seconds = max(interval, remaining)
                    minutes = max(1, int((remaining + 59) // 60))
                    self._update_auto_ui(f"TMM API на паузе: {minutes} мин")
                elif not trades:
                    self._update_auto_ui("Нет данных TMM")
                else:
                    self._update_auto_ui("Сканирование OBS...")
                    videos = sorted(get_all_videos(obs), key=lambda video: video['start_time'])
                    cycle_found = 0
                    cycle_done = 0
                    for vi in videos:
                        if self.auto_stop_event.is_set():
                            break
                        matched = match_trades_to_video(vi, trades)
                        pending = [
                            t for t in matched
                            if not is_processed(
                                str(t.get('id', '')), t,
                                self.output_folder or CUT_VIDEOS_DIR,
                                self.format_trade_folder, vi.get("path", "")
                            )
                        ]
                        if not pending:
                            continue
                        cycle_found += len(pending)
                        if not self._try_begin_processing("автообработка"):
                            self.log("WARN", "Автообработка ждёт завершения другой нарезки")
                            break
                        self._update_auto_ui(f"Нарезка: {vi['name']}")
                        self.log("INFO", f"Автообработка: найдено {len(pending)} новых сделок в {vi['name']}")
                        try:
                            output_dir = self.output_folder or CUT_VIDEOS_DIR
                            job_ids = create_processing_jobs(
                                pending, vi, "Авто", self.buffer_before, self.buffer_after,
                                self.time_offset, output_dir
                            )
                            self.run_on_ui(self.refresh_queue_view)
                            results = cut_trades_parallel(
                                pending, vi, self.buffer_before, self.buffer_after,
                                output_dir, max_workers=1,
                                time_offset=self.time_offset,
                                log_cb=lambda level, msg: self.log(level, f"  {msg}"),
                                folder_name_cb=self.format_trade_folder,
                                cancel_event=self.processing_cancel_event,
                                process_cb=self._set_active_ffmpeg_process,
                                job_ids=job_ids
                            )
                            ok_count = self._mark_successful_results(
                                results, vi, self.output_folder or CUT_VIDEOS_DIR
                            )
                            cycle_done += ok_count
                            processed_count = len([
                                trade for trade in matched
                                if is_processed(
                                    str(trade.get('id', '')), trade,
                                    self.output_folder or CUT_VIDEOS_DIR,
                                    self.format_trade_folder, vi.get("path", "")
                                )
                            ])
                            mark_video_processed(vi['path'], processed_count)
                        finally:
                            self._finish_processing()
                    if self.auto_process_active and not self.auto_stop_event.is_set():
                        if cycle_found:
                            self.log("INFO", f"Автообработка: готово {cycle_done} из {cycle_found} новых клипов")
                        self._update_auto_ui(f"Ожидание, проверка через {interval} сек")
            except Exception as e:
                self.log("ERROR", f"Ошибка автообработки: {e}\n{traceback.format_exc()}")
                self._update_auto_ui("Ошибка, повтор через интервал")
            if self.auto_stop_event.wait(wait_seconds):
                break

    # ========== ЭКСПОРТ И ПЕРЕСБОРКА ==========
    def export_trades_csv(self):
        trades, _ = load_trades_cache(self.api_key)
        trades = self._filter_trades_for_current_scope(trades)
        if not trades: messagebox.showwarning("Внимание","Сделки TMM ещё не загружены."); return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Таблица","*.csv")])
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["id","symbol","side","open_time","close_time","realized_pnl"])
                for t in trades:
                    ot = parse_trade_time(t, True); ct = parse_trade_time(t, False)
                    # Преобразуем UTC-время в часовой пояс профиля TMM.
                    writer.writerow([
                        t.get("id",""), t.get("symbol",""), t.get("side",""),
                        ot.astimezone(get_tmm_timezone()).isoformat() if ot else "",
                        ct.astimezone(get_tmm_timezone()).isoformat() if ct else "",
                        t.get("realized_pnl",0)
                    ])
            self.log("INFO", f"Экспортировано {len(trades)} строк в {path}")
            messagebox.showinfo("Готово", "Данные успешно сохранены.")
        except Exception as e: self.log("ERROR", f"Не удалось выполнить экспорт: {e}")

    def save_logs(self):
        if not os.path.exists(LOG_PATH): messagebox.showwarning("Внимание","Логи работы еще пусты."); return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Текстовый документ","*.txt")])
        if not path:
            os.startfile(LOG_PATH)
            return
        try:
            shutil.copy2(LOG_PATH, path)
            self.log("INFO", f"Лог-файл скопирован в {path}")
            messagebox.showinfo("Готово", "Лог сохранен.")
        except Exception as e: self.log("ERROR", f"Сбой сохранения файла: {e}")

    def rebuild(self):
        # Запущенный EXE заблокирован Windows, поэтому пересборка доступна только из исходника.
        if getattr(sys, 'frozen', False):
            self.log("ERROR", "Попытка пересборки из запущенного EXE файла. Сборка заблокирована.")
            messagebox.showerror(
                "Ошибка пересборки",
                "Вы запустили программу через готовый файл TMM_Cutter.exe!\n\n"
                "Изнутри EXE-файла обновить код нельзя, так как он заблокирован Windows.\n\n"
                "ПОЖАЛУЙСТА, СДЕЛАЙТЕ СЛЕДУЮЩЕЕ:\n"
                "1. Полностью закройте это окно программы.\n"
                "2. Запустите командную строку (PowerShell) в папке C:\\TMM_Cutter\n"
                "3. Установите Python и запустите: python app.py\n"
                "4. В открывшемся окне нажмите «Пересобрать exe»."
            )
            return

        python_path = shutil.which("python") or shutil.which("python3") or shutil.which("py")
        if not python_path: messagebox.showerror("Ошибка окружения","Локальный интерпретатор Python не найден в PATH."); return
        if messagebox.askyesno("Пересборка EXE","Выполнить автоматическую компиляцию exe-файла через PyInstaller из текущего исходного кода?"):
            self.log("INFO","Инициализация сборки компилятором PyInstaller..."); self.set_status("Сборка EXE...", COLORS["warning"])
            threading.Thread(target=self._run_build, args=(python_path,), daemon=True).start()

    def _run_build(self, python_path):
        self.update_progress(10, "Подготовка библиотек...")
        try: subprocess.run([python_path, "-m", "pip", "install", "pyinstaller"], capture_output=True, timeout=30)
        except: pass
        ffmpeg_path = get_ffmpeg_path() or os.path.join(APP_DIR, "ffmpeg.exe")

        # Компилируем напрямую в TMM_Cutter.exe (он не заблокирован, так как мы запущены из исходного кода python app.py)
        cmd = [python_path, "-m", "PyInstaller", "--clean", "--onefile", "--noconsole", "--add-binary", f"{ffmpeg_path};.", "--name", "TMM_Cutter", "--distpath", BASE_DIR, __file__]
        self.log("INFO", "Сборка исполняемого файла...")
        self.update_progress(30, "Компиляция...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=BASE_DIR)
        except Exception as e:
            self.log("ERROR", f"Не удалось запустить сборку: {e}")
            self.set_status("Ошибка", COLORS["error"])
            return

        if result.returncode == 0:
            self.log("INFO", "Сборка успешно завершена!")
            self.update_progress(100, "Готово")
            time.sleep(1)

            exe_path = os.path.join(BASE_DIR, "TMM_Cutter.exe")
            if os.path.exists(exe_path):
                self.set_status("Готов", COLORS["success"])
                self.run_on_ui(self._show_build_success, exe_path)
            else:
                self.log("ERROR", "Сборщик отчитался об успехе, но готовый EXE файл не найден на диске.")
                self.set_status("Ошибка", COLORS["error"])
        else:
            self.log("ERROR", f"Ошибка сборщика PyInstaller: {result.stderr[-200:] if result.stderr else 'Неизвестная ошибка компиляции'}")
            self.set_status("Ошибка", COLORS["error"])

    def _show_build_success(self, exe_path):
        messagebox.showinfo(
            "Сборка завершена",
            "Новый файл TMM_Cutter.exe успешно создан!\n\n"
            "Вы можете найти его в папке программы и использовать для запуска."
        )
        if messagebox.askyesno("Запуск", "Хотите закрыть исходную версию и запустить созданный EXE-файл?"):
            subprocess.Popen([exe_path])
            self.save_on_exit()

def main():
    if not ensure_single_instance():
        return
    init_db()
    root = None
    app = None
    try:
        root = create_tk_root()
        app = TMMVideoCutter(root)
        root.mainloop()
    except Exception:
        log_to_file("ERROR", "Unhandled UI error:\n" + traceback.format_exc())
        try:
            messagebox.showerror("TMM Cutter", "Приложение остановлено из-за ошибки. Подробности записаны в app.log.")
        except Exception:
            pass
    finally:
        if app:
            app.shutdown_background_services()
        elif root:
            try:
                if root.winfo_exists():
                    root.destroy()
            except Exception:
                pass

def run_self_test():
    global DB_PATH, QUARANTINE_DIR
    write_diagnostic_trace("self-test: start")
    self_test_root = os.path.join(APP_DIR, ".tmm_self_test")
    os.makedirs(self_test_root, exist_ok=True)
    DB_PATH = os.path.join(self_test_root, "data.db")
    QUARANTINE_DIR = os.path.join(self_test_root, "quarantine")
    init_db()
    write_diagnostic_trace("self-test: db initialized")
    write_diagnostic_trace(
        "self-test: Tcl env "
        f"TCL_LIBRARY={os.environ.get('TCL_LIBRARY')} "
        f"TK_LIBRARY={os.environ.get('TK_LIBRARY')} "
        f"tcl_init_exists={os.path.isfile(os.path.join(TCL_RUNTIME_DIR, 'init.tcl')) if TCL_RUNTIME_DIR else False} "
        f"tk_tcl_exists={os.path.isfile(os.path.join(TK_RUNTIME_DIR, 'tk.tcl')) if TK_RUNTIME_DIR else False}"
    )
    try:
        if getattr(sys, "frozen", False):
            write_diagnostic_trace("self-test: frozen Tcl/Tk check is covered by ui-test")
        else:
            interpreter = tk.Tcl()
            interpreter.eval("info patchlevel")
            write_diagnostic_trace("self-test: Tcl ok")
    except tk.TclError:
        if getattr(sys, "frozen", False):
            raise
        log_to_file("WARN", "Tcl недоступен в среде разработки; проверка продолжена без GUI")
    if not get_ffmpeg_path():
        raise RuntimeError("ffmpeg не найден")
    write_diagnostic_trace("self-test: ffmpeg ok")
    load_config()
    write_diagnostic_trace("self-test: config loaded")
    protected_key = protect_api_key("self-test-api-key")
    if not protected_key.startswith("dpapi:") or unprotect_api_key(protected_key) != "self-test-api-key":
        raise RuntimeError("DPAPI round-trip failed")
    write_diagnostic_trace("self-test: dpapi ok")
    class FakeResponse:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}
    original_request = requests.request
    fake_responses = iter([FakeResponse(429, {"Retry-After": "0"}), FakeResponse(200)])
    try:
        requests.request = lambda *_args, **_kwargs: next(fake_responses)
        test_limiter = TMMApiRateLimiter(min_interval=0, max_rate_limit_retries=1)
        limiter_response = test_limiter.request("GET", "https://example.invalid")
        limiter_stats = test_limiter.snapshot()
        if limiter_response.status_code != 429 or limiter_stats["rate_limit_hits"] != 1 or limiter_stats["total_requests"] != 1:
            raise RuntimeError(f"API limiter failed: {limiter_stats}")
    finally:
        requests.request = original_request
    write_diagnostic_trace("self-test: limiter ok")
    previous_timezone = get_tmm_timezone_name()
    try:
        set_tmm_timezone("Europe/London")
        test_trade = {
            "id": "timezone-self-test",
            "symbol": "TESTUSDT",
            "open_time": int(datetime(2026, 6, 21, 23, 30, 7, tzinfo=timezone.utc).timestamp() * 1000),
            "close_time": int(datetime(2026, 6, 21, 23, 30, 17, tzinfo=timezone.utc).timestamp() * 1000),
            "percent": 1,
            "tags": [{"column": 1, "name": "тест/причина:*"}],
        }
        test_path = get_trade_output_path(test_trade, os.path.join(BASE_DIR, "timezone-self-test"))
        expected_name = "00-30-07_TESTUSDT_1%_10s_тест причина"
        if os.path.basename(os.path.dirname(test_path)) != expected_name:
            raise RuntimeError(f"unexpected TMM folder name: {test_path}")
        test_trade_without_reason = dict(test_trade, tags=[])
        test_time_tmm = parse_trade_time(test_trade_without_reason, True).astimezone(get_tmm_timezone())
        if get_trade_folder_name(test_trade_without_reason, test_time_tmm) != "00-30-07_TESTUSDT_1%_10s":
            raise RuntimeError("trade without entry reason changed its folder name")
        if not any(part.startswith("22 ") for part in Path(test_path).parts):
            raise RuntimeError(f"TMM date rollover failed: {test_path}")
        video_info = {
            "start_time": datetime(2026, 6, 21, 23, 29, 7, tzinfo=timezone.utc),
            "duration_sec": 180,
        }
        cut_window, cut_error = calculate_cut_window(test_trade, video_info, 3, 4, 0)
        if cut_error or not cut_window or abs(cut_window["duration_sec"] - 17.0) > 0.001:
            raise RuntimeError(f"cut preview calculation failed: {cut_error or cut_window}")
    finally:
        set_tmm_timezone(previous_timezone)
    write_diagnostic_trace("self-test: timezone/cut ok")
    original_db_path = DB_PATH
    original_quarantine_dir = QUARANTINE_DIR
    queue_test_db = os.path.join(self_test_root, "queue.db")
    storage_test_root = os.path.join(self_test_root, "storage")
    try:
        if os.path.exists(queue_test_db):
            os.remove(queue_test_db)
        if os.path.isdir(storage_test_root):
            shutil.rmtree(storage_test_root)
        DB_PATH = queue_test_db
        QUARANTINE_DIR = os.path.join(storage_test_root, "quarantine")
        init_db()
        test_jobs = create_processing_jobs(
            [test_trade], {"path": os.path.join(BASE_DIR, "source.mp4")},
            "Self-test", 3, 4, 0, BASE_DIR
        )
        job_id = test_jobs[str(test_trade["id"])]
        update_processing_job(job_id, "running")
        update_processing_job(job_id, "done", "OK", os.path.join(BASE_DIR, "result.mp4"))
        jobs = get_processing_jobs()
        if len(jobs) != 1 or jobs[0]["status"] != "done":
            raise RuntimeError(f"processing queue failed: {jobs}")
        if clear_completed_processing_jobs() != 1:
            raise RuntimeError("processing queue cleanup failed")
        storage_output = os.path.join(storage_test_root, "output")
        os.makedirs(storage_output, exist_ok=True)
        registered_path = os.path.join(storage_output, "registered.mp4")
        orphan_path = os.path.join(storage_output, "orphan-copy.mp4")
        temp_path = os.path.join(storage_output, "unfinished.tmp")
        with open(registered_path, "wb") as target:
            target.write(b"A" * 2048)
        shutil.copy2(registered_path, orphan_path)
        with open(temp_path, "wb") as target:
            target.write(b"temp")
        old_time = time.time() - 1200
        os.utime(temp_path, (old_time, old_time))
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute(
            "INSERT INTO processed (trade_id, processed_at, clip_path, link_status) VALUES (?, ?, ?, 'synced')",
            ("registered-self-test", datetime.now().isoformat(), registered_path)
        )
        conn.commit(); conn.close()
        storage_scan = scan_storage(storage_output)
        candidate_paths = {_normalized_path(item["path"]): item for item in storage_scan["candidates"]}
        if _normalized_path(registered_path) in candidate_paths:
            raise RuntimeError("registered file was incorrectly marked for quarantine")
        if _normalized_path(orphan_path) not in candidate_paths or _normalized_path(temp_path) not in candidate_paths:
            raise RuntimeError(f"storage scan missed candidates: {storage_scan}")
        moved, move_errors = quarantine_storage_items(
            [candidate_paths[_normalized_path(orphan_path)]], storage_output
        )
        if move_errors or len(moved) != 1 or os.path.exists(orphan_path):
            raise RuntimeError(f"quarantine move failed: {move_errors}")
        restored, restore_detail = restore_quarantine_item(moved[0]["id"])
        if not restored or not os.path.isfile(orphan_path):
            raise RuntimeError(f"quarantine restore failed: {restore_detail}")
    finally:
        DB_PATH = original_db_path
        QUARANTINE_DIR = original_quarantine_dir
        if os.path.exists(queue_test_db):
            os.remove(queue_test_db)
        if os.path.isdir(storage_test_root):
            shutil.rmtree(storage_test_root)
    write_diagnostic_trace("self-test: queue/storage ok")
    test_server = LocalVideoServer(0, "self-test-token")
    write_diagnostic_trace("self-test: local server starting")
    started, detail = test_server.start()
    if not started:
        raise RuntimeError(f"локальный сервер не запустился: {detail}")
    write_diagnostic_trace(f"self-test: local server started {detail}")
    test_server.stop()
    write_diagnostic_trace("self-test: local server stopped")
    if False and sys.platform == "win32":
        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD),
                ("x", ctypes.c_long),
                ("y", ctypes.c_long),
                ("fNC", wintypes.BOOL),
                ("fWide", wintypes.BOOL),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        test_drop_path = r"C:\TMM_Cutter\drag drop self-test.mp4"
        encoded_paths = (test_drop_path + "\0\0").encode("utf-16le")
        header_size = ctypes.sizeof(DROPFILES)
        hglobal = kernel32.GlobalAlloc(0x0002 | 0x0040, header_size + len(encoded_paths))
        if not hglobal:
            raise ctypes.WinError(ctypes.get_last_error())
        locked = kernel32.GlobalLock(hglobal)
        if not locked:
            raise ctypes.WinError(ctypes.get_last_error())
        dropfiles = DROPFILES(header_size, 0, 0, False, True)
        ctypes.memmove(locked, ctypes.byref(dropfiles), header_size)
        ctypes.memmove(locked + header_size, encoded_paths, len(encoded_paths))
        kernel32.GlobalUnlock(hglobal)

        def fake_get_data(_this, _format, medium):
            medium[0].tymed = TYMED_HGLOBAL
            medium[0].hGlobal = hglobal
            medium[0].pUnkForRelease = None
            return S_OK

        get_data_callback = WindowsFileDropTarget.GetDataProto(fake_get_data)
        fake_vtable = (ctypes.c_void_p * 4)(0, 0, 0, ctypes.cast(get_data_callback, ctypes.c_void_p).value)
        fake_object = COMObject(ctypes.cast(fake_vtable, ctypes.POINTER(ctypes.c_void_p)))
        fake_data_object = ctypes.cast(ctypes.pointer(fake_object), ctypes.c_void_p)
        dropped_files = []
        drop_target = WindowsFileDropTarget(lambda files: dropped_files.extend(files))
        effect = wintypes.DWORD(0)
        hr = drop_target._drop(None, fake_data_object, 0, POINTL(0, 0), ctypes.pointer(effect))
        if hr != S_OK or dropped_files != [test_drop_path] or effect.value != DROPEFFECT_COPY:
            raise RuntimeError(f"drag-and-drop HDROP self-test failed: hr={hr}, effect={effect.value}, files={dropped_files}")
    write_diagnostic_trace("self-test: done")

def run_lifecycle_test():
    global load_config, save_config
    original_loader = load_config
    original_saver = save_config
    test_cfg = dict(original_loader())
    test_cfg["auto_process"] = False
    load_config = lambda: dict(test_cfg)
    save_config = lambda _cfg: None
    try:
        init_db()
        root = create_tk_root()
        root.withdraw()
        app = TMMVideoCutter(root)
        server_ref = app.local_server
        root.after(1200, app.save_on_exit)
        root.mainloop()
        if server_ref.running:
            raise RuntimeError("локальный сервер не остановился вместе с приложением")
    finally:
        load_config = original_loader
        save_config = original_saver

def run_diagnostics_test():
    init_db()
    cfg = load_config()
    server = LocalVideoServer(cfg.get("local_server_port", 8765), cfg.get("local_server_token", ""))
    started, detail = server.start()
    if not started:
        raise RuntimeError(f"diagnostic server failed: {detail}")
    try:
        diagnostic_app = TMMVideoCutter.__new__(TMMVideoCutter)
        diagnostic_app.cfg = cfg
        diagnostic_app.api_key = cfg.get("tmm_api_key", "")
        diagnostic_app.obs_folder = cfg.get("obs_folder", "")
        diagnostic_app.output_folder = cfg.get("output_folder") or CUT_VIDEOS_DIR
        diagnostic_app.local_server_port = int(cfg.get("local_server_port", 8765))
        checks = diagnostic_app._collect_diagnostics()
        for item in checks:
            log_to_file(item["level"] if item["level"] in ("WARN", "ERROR") else "INFO",
                        f"Diagnostic {item['name']}: {item['detail']}")
        errors = [item for item in checks if item["level"] == "ERROR"]
        if errors:
            raise RuntimeError("; ".join(f"{item['name']}: {item['detail']}" for item in errors))
    finally:
        server.stop()

def run_ui_test():
    global load_config, save_config
    init_db()
    original_loader = load_config
    original_saver = save_config
    original_cfg = original_loader()
    test_cfg = dict(original_cfg)
    test_cfg["auto_process"] = False
    test_cfg["tmm_api_key"] = "ui-test-api-key"
    load_config = lambda: dict(test_cfg)
    save_config = lambda _cfg: None
    root = None
    app = None
    try:
        root = create_tk_root()
        root.withdraw()
        app = TMMVideoCutter(root)
        expected_api_key = str(test_cfg.get("tmm_api_key", "") or "")
        if expected_api_key and app.api_entry.get() != expected_api_key:
            raise RuntimeError("saved API key was not loaded into the input field")
        app.open_queue_window()
        app.queue_window.withdraw()
        app.open_links_window()
        app.links_window.withdraw()
        app.open_storage_window()
        app.storage_window.withdraw()
        preview_trade = {
            "id": "ui-preview-test", "symbol": "TESTUSDT", "side": "LONG",
            "open_time": int(datetime(2026, 6, 21, 12, 0, 10, tzinfo=timezone.utc).timestamp() * 1000),
            "close_time": int(datetime(2026, 6, 21, 12, 0, 20, tzinfo=timezone.utc).timestamp() * 1000),
            "percent": 1,
        }
        preview_video = {
            "name": "2026-06-21 12-00-00.mp4",
            "path": os.path.join(BASE_DIR, "2026-06-21 12-00-00.mp4"),
            "start_time": datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc),
            "duration_sec": 120,
        }
        app.show_cut_preview(preview_video, preview_trade)
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.withdraw()
        root.update_idletasks()
        app._install_file_drop_target()
        if not DND_FILES or not hasattr(root, "drop_target_register") or not app._drop_targets:
            raise RuntimeError("tkinterdnd2 drag-and-drop target was not registered")
        app._set_drop_hover(True)
        root.update_idletasks()
        if not app._drop_hover_active or app.drop_frame.cget("bg") == COLORS["bg"]:
            raise RuntimeError("drag-and-drop hover highlight was not enabled")
        app._set_drop_hover(False)
        root.update_idletasks()
        if app._drop_hover_active or app.drop_label.cget("text") != app._drop_default_text or app.drop_frame.cget("bg") != COLORS["bg"]:
            raise RuntimeError("drag-and-drop hover highlight was not reset")
        dropped_video = os.path.join(BASE_DIR, ".ui-drop-test.mp4")
        dropped_text = os.path.join(BASE_DIR, ".ui-drop-test.txt")
        with open(dropped_video, "wb") as target:
            target.write(b"video")
        with open(dropped_text, "w", encoding="utf-8") as target:
            target.write("not a video")
        dropped_calls = []
        original_cut_single_video = app.cut_single_video
        try:
            app.cut_single_video = lambda filepath=None: dropped_calls.append(filepath)
            app._handle_dropped_files([dropped_text, dropped_video])
        finally:
            app.cut_single_video = original_cut_single_video
            for temp_path in (dropped_video, dropped_text):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        if dropped_calls != [os.path.abspath(dropped_video)]:
            raise RuntimeError(f"drag-and-drop handler selected wrong file: {dropped_calls}")
        if app.stop_button.winfo_reqheight() < 45:
            raise RuntimeError(f"stop button is too small: {app.stop_button.winfo_reqheight()}")
        if str(app.stop_button.cget("font")) != str(app.auto_button.cget("font")):
            raise RuntimeError("stop and auto buttons use different fonts")
        if app.stop_button.cget("text") != "Стоп обработки":
            raise RuntimeError("unexpected stop button text")
        if (not app.queue_tree.winfo_exists() or not app.links_tree.winfo_exists()
                or not app.storage_candidates_tree.winfo_exists() or not app.quarantine_tree.winfo_exists()):
            raise RuntimeError("queue, links or storage window was not created")
    finally:
        if app:
            app.stop_flag = True
            app.stop_local_server()
        if root and root.winfo_exists():
            root.destroy()
        load_config = original_loader
        save_config = original_saver

if __name__ == "__main__":
    if any(flag in sys.argv for flag in ("--self-test", "--lifecycle-test", "--diagnostics-test", "--ui-test")):
        write_diagnostic_trace(f"diagnostic entry: {' '.join(sys.argv)}")
        try:
            if "--lifecycle-test" in sys.argv:
                run_lifecycle_test()
            elif "--diagnostics-test" in sys.argv:
                run_diagnostics_test()
            elif "--ui-test" in sys.argv:
                run_ui_test()
            else:
                run_self_test()
        except Exception as error:
            diagnostic_traceback = traceback.format_exc()
            write_diagnostic_trace(f"diagnostic failed: {error}\n{diagnostic_traceback}")
            log_to_file("ERROR", f"Diagnostic test: {error}\n{diagnostic_traceback}")
            os._exit(1)
        os._exit(0)
    main()
