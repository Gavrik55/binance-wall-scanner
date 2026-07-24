import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_clipboard_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)


def clip():
    root.update()
    try:
        return root.clipboard_get()
    except tk.TclError:
        return None


# --- 1) основная таблица сканера: двойной клик -> редактирует И копирует ---
app._add_symbol("BTCUSDT", 100000, "LONG", exchange="BINANCE", mode="FIXED",
                silent=True, exact_exchange=True)
app.tree.selection_set("BINANCE:BTCUSDT")
app._edit_selected(None)
assert clip() == "BTCUSDT", f"должно скопироваться BTCUSDT, получено {clip()!r}"
assert app.symbol_entry.get() == "BTCUSDT", "редактирование по-прежнему должно работать"
print("OK: основная таблица - двойной клик и копирует, и подставляет в поля редактирования")

class FakeMouseEvent:
    pass

class FakeKeyEvent:
    pass

root.update_idletasks()
tree_bbox = app.tree.bbox("BINANCE:BTCUSDT", "symbol")
assert tree_bbox, "main table row must be visible for right-click copy"
right_click = FakeMouseEvent()
right_click.x = tree_bbox[0] + 2
right_click.y = tree_bbox[1] + 2
app._copy_symbol_from_tree_event(app.tree, 1, right_click)
assert clip() == "BTCUSDT", f"right-click copy from main table returned {clip()!r}"
assert "BTCUSDT" in app.copy_notice_var.get(), "right-click copy should show a subtle copied notice"
print("OK: правая кнопка по основной таблице копирует тикер")

ctrl_c_ru = FakeKeyEvent()
ctrl_c_ru.keysym = "Cyrillic_es"
ctrl_c_ru.keycode = 67
ctrl_c_ru.state = guimod.CTRL_MASK
app.tree.selection_set("BINANCE:BTCUSDT")
orig_focus_get = app.root.focus_get
app.root.focus_get = lambda: app.tree
app._on_global_keypress(ctrl_c_ru)
app.root.focus_get = orig_focus_get
assert clip() == "BTCUSDT", f"Ctrl+C on Russian layout should copy ticker, got {clip()!r}"
print("OK: Ctrl+C копирует тикер при русской раскладке")

# --- 2) активные плотности ---
app._update_walls_tree("BINANCE", "EVAAUSDT", [
    {"price": 0.755, "side": "bid", "usd": 62716, "age": 6, "dist_pct": 1.27},
])
app.walls_tree.selection_set("BINANCE:EVAAUSDT|0.755")
app._copy_symbol_from_tree(app.walls_tree, 1)
assert clip() == "EVAAUSDT", f"получено {clip()!r}"
print("OK: 'Активные плотности' копирует тикер по двойному клику")

# --- 3) лента алертов ---
from detector import WallEvent
app._add_symbol("LABUSDT", 1000, "LONG", exchange="BINANCE", mode="FIXED",
                silent=True, exact_exchange=True)
ev = WallEvent("BINANCE", "LABUSDT", "CASCADE", 0.82, 0, "bid", extra="тест")
app._render_event(ev)
first_row = app.log.get_children()[0]
first_values = app.log.item(first_row, "values")
assert first_values[3] == "низ", f"side display is {first_values[3]!r}"
assert first_values[7] == "", f"new alert comments should start blank, got {first_values[7]!r}"
app._set_alert_comment(first_row, "жду магнит/прострел")
first_values = app.log.item(first_row, "values")
assert first_values[7] == "жду магнит/прострел", f"comment display is {first_values[7]!r}"
root.update_idletasks()
comment_bbox = app.log.bbox(first_row, "comment")
assert comment_bbox, "comment cell must be visible for double-click editing"

class FakeLogEvent:
    pass

fake_log_event = FakeLogEvent()
fake_log_event.x = comment_bbox[0] + 2
fake_log_event.y = comment_bbox[1] + 2
app._on_log_double_click(fake_log_event)
assert app._log_comment_editor is not None, "double click on alert comment cell must create inline editor"
editor = app._log_comment_editor["entry"]
assert str(editor) in [str(child) for child in app.log.winfo_children()], "comment editor must live inside alert table"
editor.delete(0, "end")
editor.insert(0, "магнит, жду удержание")
app._close_log_comment_editor(save=True)
first_values = app.log.item(first_row, "values")
assert first_values[7] == "магнит, жду удержание", f"inline comment edit saved {first_values[7]!r}"
app.log.selection_set(first_row)
app._copy_symbol_from_tree(app.log, 2)
assert clip() == "LABUSDT", f"получено {clip()!r}"
print("OK: 'Лента алертов' хранит комментарий в строке события и копирует тикер")

# --- 4) топ движений: двойной клик -> добавляет в сканер И копирует ---
spot_ev = WallEvent("BINANCE SPOT", "LABUSDT", "APPEARED", 0.82, 1000, "bid", extra="spot test")
app._render_event(spot_ev)
spot_row = app.log.get_children()[0]
spot_values = app.log.item(spot_row, "values")
assert spot_values[2] == "LABUSDT SPOT", f"spot symbol display is {spot_values[2]!r}"
assert spot_values[3] == "низ", f"spot side display is {spot_values[3]!r}"
app.log.selection_set(spot_row)
app._copy_symbol_from_tree(app.log, 2)
assert clip() == "LABUSDT", f"spot display must copy raw ticker, got {clip()!r}"
root.update_idletasks()
spot_bbox = app.log.bbox(spot_row, "symbol")
assert spot_bbox, "spot alert row must be visible for right-click copy"
right_click.x = spot_bbox[0] + 2
right_click.y = spot_bbox[1] + 2
app._copy_symbol_from_tree_event(app.log, 2, right_click)
assert clip() == "LABUSDT", f"right-click copy from spot alert must copy raw ticker, got {clip()!r}"
print("OK: spot alerts show SPOT in symbol column but copy the raw ticker")

old_askyesno = guimod.messagebox.askyesno
guimod.messagebox.askyesno = lambda *_args, **_kwargs: True
try:
    app._clear_alert_log()
finally:
    guimod.messagebox.askyesno = old_askyesno
assert not app.log.get_children(), "clear alert log button should remove all alert rows"
print("OK: кнопка очистки ленты алертов удаляет строки")

fake_tickers = [
    {"exchange": "OKX", "symbol": "MOVERUSDT", "last": 1.0, "change_pct_24h": 15.0,
     "quote_volume": 100000, "impulse_pct": 0.5},
]
app._update_movers_trees(fake_tickers)
app.gainers_tree.selection_set("OKX:MOVERUSDT")
class FakeEvent:
    widget = app.gainers_tree
orig_add_symbol = app._add_symbol
def add_symbol_sync(*args, **kwargs):
    kwargs["exact_exchange"] = True
    return orig_add_symbol(*args, **kwargs)
app._add_symbol = add_symbol_sync
app._on_mover_double_click(FakeEvent())
assert clip() == "MOVERUSDT", f"получено {clip()!r}"
assert "OKX:MOVERUSDT" in app.orderbooks, "должно было ещё и добавиться в сканер, как раньше"
print("OK: 'Топ движений' копирует тикер И по-прежнему добавляет в сканер")

# --- 5) ерши ---
app._update_hedgehog_tree([
    {"exchange": "BYBIT", "symbol": "HHUSDT", "last": 2.0, "hh_ready": True,
     "hh_range_pct": 1.0, "hh_touch_top": 0.3, "hh_touch_bot": 0.3, "vol_60m": 1000, "vol_10m": 100},
])
app.hedgehog_tree.selection_set("BYBIT:HHUSDT")
app._copy_symbol_from_tree(app.hedgehog_tree, 1)
assert clip() == "HHUSDT", f"получено {clip()!r}"
print("OK: 'Ерши' копирует тикер по двойному клику")

# --- 6) удаление нескольких монет через Delete/общий обработчик ---
app._add_symbol("DELONEUSDT", 1000, "LONG", exchange="BINANCE", mode="FIXED",
                silent=True, exact_exchange=True)
app._add_symbol("DELTWOUSDT", 1000, "LONG", exchange="BINANCE", mode="FIXED",
                silent=True, exact_exchange=True)
app.tree.selection_set(("BINANCE:DELONEUSDT", "BINANCE:DELTWOUSDT"))
delete_key = FakeKeyEvent()
delete_key.keysym = "Delete"
delete_key.keycode = 46
delete_key.state = 0
orig_focus_get = app.root.focus_get
app.root.focus_get = lambda: app.start_btn
app._on_global_keypress(delete_key)
app.root.focus_get = orig_focus_get
assert not app.tree.exists("BINANCE:DELONEUSDT")
assert not app.tree.exists("BINANCE:DELTWOUSDT")
assert "BINANCE:DELONEUSDT" not in app.orderbooks
assert "BINANCE:DELTWOUSDT" not in app.orderbooks
print("OK: global Delete handler deletes multiple selected scanner rows")

app._add_symbol("SAFEUSDT", 1000, "LONG", exchange="BINANCE", mode="FIXED",
                silent=True, exact_exchange=True)
app.tree.selection_set("BINANCE:SAFEUSDT")
orig_focus_get = app.root.focus_get
app.root.focus_get = lambda: app.symbol_entry
app._on_delete_key(FakeMouseEvent())
app.root.focus_get = orig_focus_get
assert app.tree.exists("BINANCE:SAFEUSDT"), "Delete must not remove symbols while a text input is focused"
orig_focus_get = app.root.focus_get
app.root.focus_get = lambda: app.symbol_entry
assert app._on_global_keypress(ctrl_c_ru) is None, "Ctrl+C must keep normal text-input behavior"
app.root.focus_get = orig_focus_get
app._remove_symbol()
print("OK: горячие клавиши не крадут нажатия у текстовых полей")

# --- 7) autocomplete popup: hover highlight + wheel/scrollbar ---
with app._symbol_suggestion_lock:
    app._symbol_suggestion_set = {f"COIN{i:02d}USDT" for i in range(30)}
app.symbol_entry.delete(0, "end")
app.symbol_entry.insert(0, "COIN")
assert app._show_symbol_suggestions(), "autocomplete popup should open for matching symbols"
root.update()
assert app.symbol_suggest.size() == 30, app.symbol_suggest.size()
assert int(app.symbol_suggest.cget("height")) == 8, app.symbol_suggest.cget("height")
assert app.symbol_suggest_scroll.winfo_ismapped(), "autocomplete scrollbar should be visible"

app.symbol_suggest.yview_moveto(0)
root.update()
yview_before = app.symbol_suggest.yview()
wheel_event = FakeMouseEvent()
wheel_event.delta = -120
app._scroll_symbol_suggestions(wheel_event)
root.update()
assert app.symbol_suggest.yview()[0] > yview_before[0], "mouse wheel should scroll autocomplete list"

app.symbol_suggest.yview_moveto(0)
root.update()
bbox = app.symbol_suggest.bbox(2)
assert bbox, "third autocomplete row should be visible"
hover_event = FakeMouseEvent()
hover_event.y = bbox[1] + max(1, bbox[3] // 2)
app._hover_symbol_suggestion(hover_event)
assert app.symbol_suggest.curselection() == (2,), app.symbol_suggest.curselection()
assert app.symbol_suggest.get(2) == "COIN02USDT"
app._hide_symbol_suggestions()
print("OK: autocomplete popup highlights hovered rows and scrolls with the mouse wheel")

root.destroy()
print("\nALL CLIPBOARD COPY TESTS PASSED")
