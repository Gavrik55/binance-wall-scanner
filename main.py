import os
import sys


def _configure_tcl_tk_paths():
    def valid_pair(tcl_dir, tk_dir):
        return (
            tcl_dir and tk_dir
            and os.path.exists(os.path.join(tcl_dir, "init.tcl"))
            and os.path.exists(os.path.join(tk_dir, "tk.tcl"))
        )

    existing_tcl = os.environ.get("TCL_LIBRARY")
    existing_tk = os.environ.get("TK_LIBRARY")
    if valid_pair(existing_tcl, existing_tk) and not getattr(sys, "frozen", False):
        return

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        roots = [
            r"C:\TMM_Cutter\runtime",
            os.path.join(exe_dir, "runtime"),
            getattr(sys, "_MEIPASS", exe_dir),
        ]
    else:
        roots = [
            os.path.dirname(os.path.abspath(__file__)),
            r"C:\TMM_Cutter\runtime",
            os.path.join(sys.base_prefix, "tcl"),
        ]

    candidates = []
    for root in roots:
        candidates.append((os.path.join(root, "_tcl_data"), os.path.join(root, "_tk_data")))
        candidates.append((os.path.join(root, "tcl8.6"), os.path.join(root, "tk8.6")))
        candidates.append((os.path.join(root, "tcl", "tcl8.6"), os.path.join(root, "tcl", "tk8.6")))

    for tcl_dir, tk_dir in candidates:
        if valid_pair(tcl_dir, tk_dir):
            os.environ["TCL_LIBRARY"] = tcl_dir
            os.environ["TK_LIBRARY"] = tk_dir
            return


_configure_tcl_tk_paths()

_INSTANCE_MUTEX_HANDLE = None


def _claim_single_instance():
    """Return False when another GUI instance is already running."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        handle = kernel32.CreateMutexW(None, False, "Local\\BinanceWallScannerTMMCutter")
        if not handle:
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            user32.MessageBoxW(None, "Приложение уже запущено.", "Binance Wall Scanner", 0x40)
            return False

        global _INSTANCE_MUTEX_HANDLE
        _INSTANCE_MUTEX_HANDLE = handle
    except Exception:
        return True
    return True

# В PyInstaller --windowed сборках нет консоли, и sys.stdout/sys.stderr = None.
# Любая попытка куда-то что-то залогировать (например дефолтный обработчик
# необработанных исключений внутри asyncio) в таком случае падает с
# AttributeError прямо внутри фонового потока — молча, без единой видимой
# ошибки на экране. Подменяем на безопасную "заглушку", чтобы такие попытки
# логирования не роняли фоновые потоки незаметно.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


def _self_test():
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        return 0
    except Exception as e:
        try:
            base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
            with open(os.path.join(base, "self_test_error.txt"), "w", encoding="utf-8") as f:
                f.write(repr(e))
        except Exception:
            pass
        return 1


def _write_test_error(filename, error):
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
        with open(os.path.join(base, filename), "w", encoding="utf-8") as f:
            f.write(repr(error))
    except Exception:
        pass


def _app_smoke_test():
    root = None
    app = None
    try:
        import tkinter as tk
        from gui import App

        root = tk.Tk()
        root.withdraw()
        app = App(root)
        root.update_idletasks()

        labels = []
        if hasattr(app, "notebook"):
            labels = [app.notebook.tab(tab_id, "text") for tab_id in app.notebook.tabs()]
        if "TMM Cutter" not in labels:
            raise RuntimeError(f"TMM Cutter tab not found; tabs={labels!r}")

        tmm_cutter = getattr(app, "tmm_cutter", None)
        if tmm_cutter is None:
            raise RuntimeError("TMM Cutter tab did not initialize")
        if not getattr(tmm_cutter, "embedded", False):
            raise RuntimeError("TMM Cutter is not running in embedded mode")
        if getattr(tmm_cutter, "_drop_targets", []):
            raise RuntimeError("Drag-and-drop targets must stay disabled in embedded mode")

        import sqlite3
        from tmm_cutter_embedded import DB_PATH

        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {"processed", "video_cache", "processing_jobs"}
            missing = sorted(required - tables)
            if missing:
                raise RuntimeError(f"TMM database schema missing tables: {missing!r}")
            conn.execute("SELECT trade_id FROM processed LIMIT 1").fetchall()

        app._on_close()
        return 0
    except Exception as e:
        _write_test_error("app_smoke_test_error.txt", e)
        return 1
    finally:
        if app is not None:
            try:
                tmm_cutter = getattr(app, "tmm_cutter", None)
                if tmm_cutter is not None:
                    tmm_cutter.shutdown_background_services()
            except Exception:
                pass
        if root is not None:
            try:
                if root.winfo_exists():
                    root.destroy()
            except Exception:
                pass


def main():
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())
    if "--app-smoke-test" in sys.argv:
        raise SystemExit(_app_smoke_test())
    if not _claim_single_instance():
        return

    import tkinter as tk
    from gui import App

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
