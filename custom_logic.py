import ast
import importlib.util
import os
import shutil
import sys
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, scrolledtext

# sys.executable points to the EXE in a frozen build and to Python in source mode.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPDATES_DIR = os.path.join(BASE_DIR, "updates")
ARCHIVE_DIR = os.path.join(UPDATES_DIR, "archive")
ACTIVE_PATCH_PATH = os.path.join(UPDATES_DIR, "active_patch.py")


def _validate_patch(code):
    tree = ast.parse(code, filename="active_patch.py")
    has_entrypoint = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "apply_patch"
        for node in tree.body
    )
    if not has_entrypoint:
        raise ValueError("Патч должен содержать функцию apply_patch(app).")
    compile(tree, "active_patch.py", "exec")


def _load_patch_module(path):
    module_name = f"tmm_active_patch_{int(os.path.getmtime(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError("Не удалось создать загрузчик патча.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "apply_patch", None)):
        raise ValueError("В патче нет функции apply_patch(app).")
    return module


def apply_active_patch(app):
    """Loads exactly one active patch and passes the real application object."""
    if not os.path.exists(ACTIVE_PATCH_PATH):
        return True
    try:
        with open(ACTIVE_PATCH_PATH, "r", encoding="utf-8") as file:
            _validate_patch(file.read())
        module = _load_patch_module(ACTIVE_PATCH_PATH)
        module.apply_patch(app)
        app.log("INFO", "Активный патч успешно применён")
        return True
    except Exception as exc:
        app.log("ERROR", f"Активный патч отключён из-за ошибки: {exc}")
        messagebox.showerror(
            "Ошибка патча",
            f"Программа продолжит работу без патча.\n\n{exc}",
            parent=app.root,
        )
        return False


def _archive_active_patch():
    if not os.path.exists(ACTIVE_PATCH_PATH):
        return None
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = os.path.join(ARCHIVE_DIR, f"active_patch_{stamp}.py")
    shutil.copy2(ACTIVE_PATCH_PATH, destination)
    return destination


def open_patch_manager(app):
    os.makedirs(UPDATES_DIR, exist_ok=True)
    window = tk.Toplevel(app.root)
    window.title("Менеджер патчей")
    window.geometry("850x650")
    window.minsize(700, 500)
    window.transient(app.root)
    window.grab_set()

    warning = (
        "Внимание: патч является Python-кодом и получает полный доступ к программе и файлам. "
        "Вставляйте только код из доверенного источника. Одновременно активен только один патч."
    )
    tk.Label(
        window, text=warning, wraplength=800, justify="left",
        font=("Segoe UI", 10, "bold"), fg="#b00020"
    ).pack(fill=tk.X, padx=15, pady=(15, 8))

    status = "Активный патч установлен" if os.path.exists(ACTIVE_PATCH_PATH) else "Активного патча нет"
    tk.Label(window, text=status, font=("Segoe UI", 10)).pack(anchor="w", padx=15)

    editor = scrolledtext.ScrolledText(window, wrap=tk.NONE, font=("Consolas", 10))
    editor.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
    if os.path.exists(ACTIVE_PATCH_PATH):
        with open(ACTIVE_PATCH_PATH, "r", encoding="utf-8") as file:
            editor.insert("1.0", file.read())
    else:
        editor.insert(
            "1.0",
            "def apply_patch(app):\n"
            "    # Получен настоящий объект TMMVideoCutter.\n"
            "    # Измените только необходимое поведение программы.\n"
            "    pass\n",
        )

    buttons = tk.Frame(window)
    buttons.pack(fill=tk.X, padx=15, pady=(0, 15))

    def save_patch():
        code = editor.get("1.0", tk.END).strip() + "\n"
        try:
            _validate_patch(code)
            _archive_active_patch()
            temp_path = ACTIVE_PATCH_PATH + ".tmp"
            with open(temp_path, "w", encoding="utf-8", newline="\n") as file:
                file.write(code)
            os.replace(temp_path, ACTIVE_PATCH_PATH)
            app.log("INFO", "Новый активный патч сохранён")
            messagebox.showinfo(
                "Патч сохранён",
                "Патч проверен и сохранён. Перезапустите программу, чтобы применить его.",
                parent=window,
            )
            window.destroy()
        except Exception as exc:
            messagebox.showerror("Патч не сохранён", str(exc), parent=window)

    def disable_patch():
        if not os.path.exists(ACTIVE_PATCH_PATH):
            messagebox.showinfo("Патчи", "Активного патча нет.", parent=window)
            return
        if not messagebox.askyesno("Отключить патч", "Отключить активный патч?", parent=window):
            return
        _archive_active_patch()
        os.remove(ACTIVE_PATCH_PATH)
        app.log("INFO", "Активный патч отключён")
        messagebox.showinfo("Патч отключён", "Изменение вступит в силу после перезапуска.", parent=window)
        window.destroy()

    tk.Button(buttons, text="Сохранить патч", command=save_patch, bg="#4caf50", fg="white", padx=12, pady=6).pack(side=tk.LEFT)
    tk.Button(buttons, text="Отключить активный", command=disable_patch, padx=12, pady=6).pack(side=tk.LEFT, padx=8)
    tk.Button(buttons, text="Закрыть", command=window.destroy, padx=12, pady=6).pack(side=tk.RIGHT)
