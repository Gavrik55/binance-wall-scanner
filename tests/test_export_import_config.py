import sys, os, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

# messagebox мокаем, чтобы не блокировать тест реальным диалогом
messages = []
guimod.messagebox.showinfo = lambda title, msg: messages.append(("info", title, msg))
guimod.messagebox.showerror = lambda title, msg: messages.append(("error", title, msg))

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_export_import_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

export_path = os.path.join(tempfile.gettempdir(), "test_exported_scanner_config.json")
if os.path.exists(export_path):
    os.remove(export_path)

root = tk.Tk()
app = guimod.App(root)

# --- 1) наполняем разными настройками и экспортируем ---
app._add_symbol("BTCUSDT", 100000, "LONG", exchange="BINANCE", mode="FIXED", silent=True,
                 threshold_max=150000, max_distance_pct=5.0)
app._add_symbol("ETHUSDT", 50000, "SHORT", exchange="GATE", mode="AUTO", silent=True, muted=True,
                 max_distance_pct=20.0)

guimod.filedialog.asksaveasfilename = lambda **kw: export_path
app._export_config()

assert os.path.exists(export_path), "файл экспорта должен был создаться"
with open(export_path, encoding="utf-8") as f:
    exported = json.load(f)
by_symbol = {item["symbol"]: item for item in exported}
assert by_symbol["BTCUSDT"]["threshold_max"] == 150000.0
assert by_symbol["BTCUSDT"]["max_distance_pct"] == 5.0
assert by_symbol["ETHUSDT"]["mode"] == "AUTO"
assert by_symbol["ETHUSDT"]["muted"] is True
assert by_symbol["ETHUSDT"]["max_distance_pct"] == 20.0
assert messages[-1][0] == "info"
print("OK: экспорт сохранил все настройки (диапазон, дистанция, режим, muted) корректно")

# --- 2) импорт в СВЕЖЕЕ приложение (имитируем "новую версию") ---
guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_export_import_config_v2.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)
root2 = tk.Tk()
app2 = guimod.App(root2)
assert len(app2.orderbooks) == 0, "новое приложение должно стартовать пустым"

guimod.filedialog.askopenfilename = lambda **kw: export_path
messages.clear()
app2._import_config()

assert "BINANCE:BTCUSDT" in app2.orderbooks
assert "GATE:ETHUSDT" in app2.orderbooks
cfg_btc = app2.detector.configs["BINANCE:BTCUSDT"]
cfg_eth = app2.detector.configs["GATE:ETHUSDT"]
assert cfg_btc.threshold_max_usd == 150000.0
assert cfg_btc.max_distance_pct == 5.0
assert cfg_eth.mode == "AUTO"
assert cfg_eth.max_distance_pct == 20.0
assert "GATE:ETHUSDT" in app2.muted_keys
assert messages[-1][0] == "info"
print("OK: импорт в 'новую версию' приложения корректно перенёс все монеты со всеми настройками")

# --- 3) импорт ДОБАВЛЯЕТ к уже существующим, не стирая их ---
app2._add_symbol("SOLUSDT", 30000, "LONG", exchange="OKX", mode="FIXED", silent=True)
assert "OKX:SOLUSDT" in app2.orderbooks
app2._import_config()  # повторный импорт того же файла
assert "OKX:SOLUSDT" in app2.orderbooks, "существующая монета не должна пропасть после импорта"
assert "BINANCE:BTCUSDT" in app2.orderbooks
print("OK: повторный импорт не стирает уже добавленные монеты (мёрдж, а не замена)")

# --- 4) обработка ошибок: битый JSON не должен уронить приложение ---
bad_path = os.path.join(tempfile.gettempdir(), "test_bad_config.json")
with open(bad_path, "w", encoding="utf-8") as f:
    f.write("это не json {{{")
guimod.filedialog.askopenfilename = lambda **kw: bad_path
messages.clear()
app2._import_config()
assert messages[-1][0] == "error", "битый файл должен дать сообщение об ошибке, а не упасть"
print("OK: битый JSON корректно обрабатывается (сообщение об ошибке, без падения)")

# --- 5) файл с НЕ-списком (например просто {} ) -> тоже ошибка, не падение ---
notlist_path = os.path.join(tempfile.gettempdir(), "test_notlist_config.json")
with open(notlist_path, "w", encoding="utf-8") as f:
    json.dump({"not": "a list"}, f)
guimod.filedialog.askopenfilename = lambda **kw: notlist_path
messages.clear()
app2._import_config()
assert messages[-1][0] == "error"
print("OK: файл-не-список тоже корректно отклоняется с сообщением об ошибке")

# --- 6) отмена диалога (пустой путь) -> ничего не происходит, не падает ---
guimod.filedialog.askopenfilename = lambda **kw: ""
messages.clear()
app2._import_config()
assert not messages, "при отмене диалога сообщений быть не должно"
print("OK: отмена диалога выбора файла ничего не делает")

root.destroy()
root2.destroy()
print("\nALL EXPORT/IMPORT CONFIG TESTS PASSED")
