import os
import sys

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

import tkinter as tk
from gui import App


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
