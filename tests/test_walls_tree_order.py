import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_walls_order_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)

# 1) находим плотность на ESPORTSUSDT первой
app._update_walls_tree("BINANCE", "ESPORTSUSDT", [
    {"price": 0.02, "side": "bid", "usd": 252560, "age": 6, "dist_pct": 2.65},
])
# 2) потом находим плотности на EVAAUSDT
app._update_walls_tree("BINANCE", "EVAAUSDT", [
    {"price": 0.755, "side": "bid", "usd": 62716, "age": 6, "dist_pct": 1.27},
    {"price": 0.75, "side": "bid", "usd": 98791, "age": 6, "dist_pct": 1.92},
])
order1 = list(app.walls_tree.get_children())
print("order after initial discovery:", order1)
assert order1[0] == "BINANCE:ESPORTSUSDT|0.02", "ESPORTS должен остаться первым (нашёлся раньше)"

# 3) теперь ESPORTSUSDT обновляется (просто возраст/цифры поменялись, монета та же) -
# раньше это переставляло бы её строку в конец таблицы. Проверяем что порядок НЕ сбился.
app._update_walls_tree("BINANCE", "ESPORTSUSDT", [
    {"price": 0.02, "side": "bid", "usd": 260000, "age": 10, "dist_pct": 2.70},
])
order2 = list(app.walls_tree.get_children())
print("order after ESPORTS update:", order2)
assert order2 == order1, f"порядок НЕ должен меняться от обновления существующей строки, было {order1}, стало {order2}"
print("OK: обновление значений существующей строки не переставляет её в таблице")

# 4) EVAAUSDT обновляется несколько раз подряд (как в реальном потоке WS) -
# порядок относительно ESPORTS всё равно должен сохраняться
for i in range(5):
    app._update_walls_tree("BINANCE", "EVAAUSDT", [
        {"price": 0.755, "side": "bid", "usd": 62716 + i, "age": 6 + i, "dist_pct": 1.27},
        {"price": 0.75, "side": "bid", "usd": 98791 + i, "age": 6 + i, "dist_pct": 1.92},
    ])
order3 = list(app.walls_tree.get_children())
print("order after repeated EVAA updates:", order3)
assert order3 == order1, "многократное обновление EVAA не должно ломать общий порядок"
print("OK: многократные обновления другого символа не 'дёргают' порядок остальных строк")

# 5) НОВАЯ плотность на LABUSDT появляется ПОСЛЕ всех предыдущих -> должна встать В КОНЕЦ
app._update_walls_tree("BINANCE", "LABUSDT", [
    {"price": 0.1657, "side": "ask", "usd": 155416, "age": 1, "dist_pct": 1.66},
])
order4 = list(app.walls_tree.get_children())
print("order after new LABUSDT wall:", order4)
assert order4[-1] == "BINANCE:LABUSDT|0.1657", "новая плотность должна встать в конец (нашлась последней)"
assert order4[:len(order1)] == order1, "порядок ранее найденных не должен меняться"
print("OK: новая плотность встаёт в конец, порядок остальных не ломается")

# 6) плотность исчезает -> строка удаляется, остальной порядок сохраняется
app._update_walls_tree("BINANCE", "EVAAUSDT", [
    {"price": 0.755, "side": "bid", "usd": 62716, "age": 20, "dist_pct": 1.27},
    # 0.75 пропала из снапшота
])
order5 = list(app.walls_tree.get_children())
print("order after EVAA 0.75 disappeared:", order5)
assert "BINANCE:EVAAUSDT|0.75" not in order5
assert "BINANCE:EVAAUSDT|0.755" in order5
print("OK: исчезнувшая плотность корректно убирается, остальной порядок цел")

root.destroy()
print("\nALL WALLS-TREE ORDER TESTS PASSED")
