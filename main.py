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


def main():
    if "--self-test" in sys.argv:
        raise SystemExit(_self_test())

    import tkinter as tk
    from gui import App

    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
