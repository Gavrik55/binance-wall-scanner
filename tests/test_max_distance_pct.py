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
assert app.single_confirm_entry.get() == str(guimod.DEFAULT_SINGLE_CONFIRM_SEC)
print("OK: поле 'Дистанция %' предзаполнено дефолтом 10 при старте")

# 1) добавляем ESPORTSUSDT с кастомной дистанцией 2%
app.symbol_entry.insert(0, "ESPORTSUSDT")
app.threshold_entry.insert(0, "100000")
app.max_distance_entry.delete(0, "end")
app.max_distance_entry.insert(0, "2,5")
app.single_confirm_entry.delete(0, "end")
app.single_confirm_entry.insert(0, "0,3")
app._add_symbol(exact_exchange=True)

# поле должно сброситься обратно на дефолт после добавления
assert app.max_distance_entry.get() == str(guimod.DEFAULT_MAX_DISTANCE_PCT), \
    f"поле должно сброситься на дефолт, получено {app.max_distance_entry.get()!r}"
assert app.single_confirm_entry.get() == str(guimod.DEFAULT_SINGLE_CONFIRM_SEC), \
    f"поле жизни должно сброситься на дефолт, получено {app.single_confirm_entry.get()!r}"
print("OK: поле сбросилось на дефолт 10 после добавления ESPORTS с кастомным 2,5%")

# 2) добавляем BTCUSDT БЕЗ изменения поля -> должен получить дефолт 10
app.symbol_entry.insert(0, "BTCUSDT")
app.threshold_entry.insert(0, "50000")
app._add_symbol(exact_exchange=True)

# 2b) явный ввод 0 превращается в минимальный практический радиус
app.symbol_entry.insert(0, "ZEROUSDT")
app.threshold_entry.insert(0, "25000")
app.max_distance_entry.delete(0, "end")
app.max_distance_entry.insert(0, "0")
app._add_symbol(exact_exchange=True)

# 2c) всё, что меньше минимального радиуса, тоже поднимается до минимума
app.symbol_entry.insert(0, "TINYUSDT")
app.threshold_entry.insert(0, "26000")
app.max_distance_entry.delete(0, "end")
app.max_distance_entry.insert(0, "0.001")
app._add_symbol(exact_exchange=True)

# 2d) явный ввод 0 во "Жизнь, с" означает "сразу, без ожидания"
app.symbol_entry.insert(0, "LIFEZEROUSDT")
app.threshold_entry.insert(0, "27000")
app.single_confirm_entry.delete(0, "end")
app.single_confirm_entry.insert(0, "0")
app._add_symbol(exact_exchange=True)

cfg_esports = app.detector.configs["BINANCE:ESPORTSUSDT"]
cfg_btc = app.detector.configs["BINANCE:BTCUSDT"]
cfg_zero = app.detector.configs["BINANCE:ZEROUSDT"]
cfg_tiny = app.detector.configs["BINANCE:TINYUSDT"]
cfg_lifezero = app.detector.configs["BINANCE:LIFEZEROUSDT"]
print("ESPORTS max_distance_pct:", cfg_esports.max_distance_pct)
print("BTC max_distance_pct:", cfg_btc.max_distance_pct)
assert cfg_esports.max_distance_pct == 2.5, "ESPORTS должен сохранить свои кастомные 2,5%"
assert cfg_esports.single_confirm_sec == 0.3, "ESPORTS должен сохранить свою кастомную жизнь 0.3с"
assert cfg_btc.max_distance_pct == 10.0, "BTC должен получить дефолт 10%, а НЕ унаследовать 2% от ESPORTS"
assert cfg_btc.single_confirm_sec == 10.0, "BTC должен получить дефолт жизни 10с"
assert cfg_zero.max_distance_pct == guimod.MIN_DISTANCE_PCT, "0 должен превращаться в минимальную дистанцию"
assert cfg_tiny.max_distance_pct == guimod.MIN_DISTANCE_PCT, "значение меньше минимума должно подниматься до минимума"
assert cfg_lifezero.single_confirm_sec == 0.0, "0 во времени жизни должен сохраняться как немедленный алерт"
print("OK: настройки per-symbol независимы, дефолт для новых монет не 'заражается' кастомным значением")

# 3) проверяем отображение в таблице
vals_esports = app.tree.item("BINANCE:ESPORTSUSDT", "values")
vals_btc = app.tree.item("BINANCE:BTCUSDT", "values")
vals_zero = app.tree.item("BINANCE:ZEROUSDT", "values")
vals_tiny = app.tree.item("BINANCE:TINYUSDT", "values")
vals_lifezero = app.tree.item("BINANCE:LIFEZEROUSDT", "values")
print("ESPORTS tree values:", vals_esports)
print("BTC tree values:", vals_btc)
assert vals_esports[11] == "2.5"
assert vals_esports[12] == "0.3"
assert vals_btc[11] == "10"
assert vals_btc[12] == "10"
assert vals_zero[11] == "0.01"
assert vals_tiny[11] == "0.01"
assert vals_lifezero[12] == "0"
print("OK: колонка 'Дист. %' в таблице показывает правильные значения")

# 4) сохранение и перезагрузка конфига
app._save_config()
with open(guimod.CONFIG_FILE, encoding="utf-8") as f:
    saved = json.load(f)
by_symbol = {item["symbol"]: item for item in saved}
assert by_symbol["ESPORTSUSDT"]["max_distance_pct"] == 2.5
assert by_symbol["ESPORTSUSDT"]["single_confirm_sec"] == 0.3
assert "comment" not in by_symbol["ESPORTSUSDT"]
assert by_symbol["BTCUSDT"]["max_distance_pct"] == 10.0
assert by_symbol["BTCUSDT"]["single_confirm_sec"] == 10.0
assert by_symbol["ZEROUSDT"]["max_distance_pct"] == guimod.MIN_DISTANCE_PCT
assert by_symbol["TINYUSDT"]["max_distance_pct"] == guimod.MIN_DISTANCE_PCT
assert by_symbol["LIFEZEROUSDT"]["single_confirm_sec"] == 0.0
print("OK: max_distance_pct корректно сохранился в config.json для каждой монеты отдельно")

root2 = tk.Tk()
app2 = guimod.App(root2)
cfg_esports2 = app2.detector.configs["BINANCE:ESPORTSUSDT"]
cfg_btc2 = app2.detector.configs["BINANCE:BTCUSDT"]
cfg_zero2 = app2.detector.configs["BINANCE:ZEROUSDT"]
cfg_tiny2 = app2.detector.configs["BINANCE:TINYUSDT"]
cfg_lifezero2 = app2.detector.configs["BINANCE:LIFEZEROUSDT"]
assert cfg_esports2.max_distance_pct == 2.5
assert cfg_esports2.single_confirm_sec == 0.3
assert cfg_btc2.max_distance_pct == 10.0
assert cfg_btc2.single_confirm_sec == 10.0
assert cfg_zero2.max_distance_pct == guimod.MIN_DISTANCE_PCT
assert cfg_tiny2.max_distance_pct == guimod.MIN_DISTANCE_PCT
assert cfg_lifezero2.single_confirm_sec == 0.0
print("OK: после перезагрузки конфига обе монеты сохранили свои раздельные настройки")

# 5) редактирование - двойной клик должен подставить правильное значение для КАЖДОЙ монеты
app2.tree.selection_set("BINANCE:ESPORTSUSDT")
app2._edit_selected(None)
assert app2.max_distance_entry.get() == "2.5", f"должно подставиться 2.5, получено {app2.max_distance_entry.get()!r}"
assert app2.single_confirm_entry.get() == "0.3"
print("OK: редактирование ESPORTS подставляет именно её 2,5%, а не общий дефолт")

app2.tree.selection_set("BINANCE:BTCUSDT")
app2._edit_selected(None)
assert app2.max_distance_entry.get() == "10"
assert app2.single_confirm_entry.get() == "10"
print("OK: редактирование BTC подставляет её 10%")

app2.tree.selection_set("BINANCE:ZEROUSDT")
app2._edit_selected(None)
assert app2.max_distance_entry.get() == "0.01"
print("OK: редактирование монеты с введённым 0 подставляет минимальные 0.01%")

# 6) старый конфиг без поля max_distance_pct вообще (обратная совместимость)
old_config = [{"exchange": "BINANCE", "symbol": "OLDUSDT", "mode": "FIXED",
               "threshold": 30000.0, "direction": "LONG", "muted": False}]
with open(guimod.CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(old_config, f)
root3 = tk.Tk()
app3 = guimod.App(root3)
cfg_old = app3.detector.configs["BINANCE:OLDUSDT"]
assert cfg_old.max_distance_pct == 10.0, "старый конфиг без поля должен получить дефолт 10%"
assert cfg_old.single_confirm_sec == 10.0, "старый конфиг без поля жизни должен получить дефолт 10с"
print("OK: обратная совместимость - старый конфиг без max_distance_pct подхватывает дефолт")

root.destroy()
root2.destroy()
root3.destroy()
print("\nALL MAX_DISTANCE_PCT TESTS PASSED")
