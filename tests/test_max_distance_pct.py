import sys, os, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_max_distance_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)

# поле должно быть предзаполнено дефолтом при старте
assert app.max_distance_entry.get() == str(guimod.DEFAULT_MAX_DISTANCE_PCT)
print("OK: поле 'Дистанция %' предзаполнено дефолтом 10 при старте")

# 1) добавляем ESPORTSUSDT с кастомной дистанцией 2%
app.symbol_entry.insert(0, "ESPORTSUSDT")
app.threshold_entry.insert(0, "100000")
app.max_distance_entry.delete(0, "end")
app.max_distance_entry.insert(0, "2")
app._add_symbol()

# поле должно сброситься обратно на дефолт после добавления
assert app.max_distance_entry.get() == str(guimod.DEFAULT_MAX_DISTANCE_PCT), \
    f"поле должно сброситься на дефолт, получено {app.max_distance_entry.get()!r}"
print("OK: поле сбросилось на дефолт 10 после добавления ESPORTS с кастомным 2%")

# 2) добавляем BTCUSDT БЕЗ изменения поля -> должен получить дефолт 10
app.symbol_entry.insert(0, "BTCUSDT")
app.threshold_entry.insert(0, "50000")
app._add_symbol()

cfg_esports = app.detector.configs["BINANCE:ESPORTSUSDT"]
cfg_btc = app.detector.configs["BINANCE:BTCUSDT"]
print("ESPORTS max_distance_pct:", cfg_esports.max_distance_pct)
print("BTC max_distance_pct:", cfg_btc.max_distance_pct)
assert cfg_esports.max_distance_pct == 2.0, "ESPORTS должен сохранить свои кастомные 2%"
assert cfg_btc.max_distance_pct == 10.0, "BTC должен получить дефолт 10%, а НЕ унаследовать 2% от ESPORTS"
print("OK: настройки per-symbol независимы, дефолт для новых монет не 'заражается' кастомным значением")

# 3) проверяем отображение в таблице
vals_esports = app.tree.item("BINANCE:ESPORTSUSDT", "values")
vals_btc = app.tree.item("BINANCE:BTCUSDT", "values")
print("ESPORTS tree values:", vals_esports)
print("BTC tree values:", vals_btc)
assert vals_esports[11] == "2"
assert vals_btc[11] == "10"
print("OK: колонка 'Дист. %' в таблице показывает правильные значения")

# 4) сохранение и перезагрузка конфига
app._save_config()
with open(guimod.CONFIG_FILE, encoding="utf-8") as f:
    saved = json.load(f)
by_symbol = {item["symbol"]: item for item in saved}
assert by_symbol["ESPORTSUSDT"]["max_distance_pct"] == 2.0
assert by_symbol["BTCUSDT"]["max_distance_pct"] == 10.0
print("OK: max_distance_pct корректно сохранился в config.json для каждой монеты отдельно")

root2 = tk.Tk()
app2 = guimod.App(root2)
cfg_esports2 = app2.detector.configs["BINANCE:ESPORTSUSDT"]
cfg_btc2 = app2.detector.configs["BINANCE:BTCUSDT"]
assert cfg_esports2.max_distance_pct == 2.0
assert cfg_btc2.max_distance_pct == 10.0
print("OK: после перезагрузки конфига обе монеты сохранили свои раздельные настройки")

# 5) редактирование - двойной клик должен подставить правильное значение для КАЖДОЙ монеты
app2.tree.selection_set("BINANCE:ESPORTSUSDT")
app2._edit_selected(None)
assert app2.max_distance_entry.get() == "2", f"должно подставиться 2, получено {app2.max_distance_entry.get()!r}"
print("OK: редактирование ESPORTS подставляет именно её 2%, а не общий дефолт")

app2.tree.selection_set("BINANCE:BTCUSDT")
app2._edit_selected(None)
assert app2.max_distance_entry.get() == "10"
print("OK: редактирование BTC подставляет её 10%")

# 6) старый конфиг без поля max_distance_pct вообще (обратная совместимость)
old_config = [{"exchange": "BINANCE", "symbol": "OLDUSDT", "mode": "FIXED",
               "threshold": 30000.0, "direction": "LONG", "muted": False}]
with open(guimod.CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(old_config, f)
root3 = tk.Tk()
app3 = guimod.App(root3)
cfg_old = app3.detector.configs["BINANCE:OLDUSDT"]
assert cfg_old.max_distance_pct == 10.0, "старый конфиг без поля должен получить дефолт 10%"
print("OK: обратная совместимость - старый конфиг без max_distance_pct подхватывает дефолт")

root.destroy()
root2.destroy()
root3.destroy()
print("\nALL MAX_DISTANCE_PCT TESTS PASSED")
