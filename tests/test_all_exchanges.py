import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_all_exchanges_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)

values = app.exchange_combo.cget("values")
print("exchange combo values:", values)
assert guimod.ALL_EXCHANGES_LABEL in values

fake_results = {"BINANCE": True, "ASTERDEX": False, "GATE": True, "OKX": False}
app._validator_for = lambda exchange: (lambda s: fake_results[exchange])

app.symbol_entry.insert(0, "FAKEUSDT")
app.threshold_entry.insert(0, "50000")
app.exchange_combo.set(guimod.ALL_EXCHANGES_LABEL)
app._add_symbol()


def check_step1():
    print("orderbooks keys:", list(app.orderbooks.keys()))
    assert "BINANCE:FAKEUSDT" in app.orderbooks, "должен добавиться на BINANCE (валидатор вернул True)"
    assert "GATE:FAKEUSDT" in app.orderbooks, "должен добавиться на GATE (валидатор вернул True)"
    assert "ASTERDEX:FAKEUSDT" not in app.orderbooks, "НЕ должен добавиться на ASTERDEX (валидатор вернул False)"
    assert "OKX:FAKEUSDT" not in app.orderbooks, "НЕ должен добавиться на OKX (валидатор вернул False)"
    print("OK: добавлено только на биржи, где валидатор подтвердил тикер")

    print("status_var:", app.status_var.get())
    assert "BINANCE" in app.status_var.get() and "GATE" in app.status_var.get()
    print("OK: статус-бар сообщает, на каких биржах добавлено")

    cfg_b = app.detector.configs["BINANCE:FAKEUSDT"]
    cfg_g = app.detector.configs["GATE:FAKEUSDT"]
    assert cfg_b.threshold_usd == 50000.0 and cfg_g.threshold_usd == 50000.0
    print("OK: общие параметры (порог) применились на обеих добавленных биржах")

    # --- шаг 2: тест "ничего не найдено" ---
    fake_results2 = {"BINANCE": False, "ASTERDEX": False, "GATE": False, "OKX": False}
    app._validator_for = lambda exchange: (lambda s: fake_results2[exchange])
    app.symbol_entry.insert(0, "NOWHEREUSDT")
    app.threshold_entry.insert(0, "10000")
    app.exchange_combo.set(guimod.ALL_EXCHANGES_LABEL)
    app._add_symbol()
    root.after(1500, check_step2)


def check_step2():
    print("status_var (ничего не найдено):", app.status_var.get())
    assert "не найден" in app.status_var.get()
    assert not any(k.endswith(":NOWHEREUSDT") for k in app.orderbooks)
    print("OK: если тикера нет нигде - ничего не добавлено, статус предупреждает")
    print("\nALL 'ALL EXCHANGES' TESTS PASSED")
    root.destroy()


root.after(1500, check_step1)
root.mainloop()
print("EXIT OK")
