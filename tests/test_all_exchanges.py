import sys, os, tempfile, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    fake_requests = types.ModuleType("requests")

    def _missing_get(*_args, **_kwargs):
        raise RuntimeError("requests is stubbed in this unit test")

    fake_requests.get = _missing_get
    sys.modules["requests"] = fake_requests

try:
    import websockets  # noqa: F401
except ModuleNotFoundError:
    fake_websockets = types.ModuleType("websockets")
    fake_websockets.connect = None
    sys.modules["websockets"] = fake_websockets

import tkinter as tk
import gui as guimod

guimod.CONFIG_FILE = os.path.join(tempfile.gettempdir(), "test_all_exchanges_config.json")
if os.path.exists(guimod.CONFIG_FILE):
    os.remove(guimod.CONFIG_FILE)

root = tk.Tk()
app = guimod.App(root)

values = app.exchange_combo.cget("values")
print("exchange combo values:", [str(v).encode("unicode_escape").decode("ascii") for v in values])
assert guimod.ALL_EXCHANGES_LABEL in values
for exch in guimod.BASE_EXCHANGE_CHOICES:
    assert exch in values
for exch in guimod.SPOT_EXCHANGE_BY_BASE.values():
    assert exch in values, "spot/futures должны быть отдельным выбором в UI"
assert "BINANCE ALPHA" in values

fake_results = {exch: False for exch in guimod.EXCHANGE_CHOICES}
fake_results.update({"BINANCE": True, "BINANCE SPOT": True})
app._validator_for = lambda exchange: (lambda s: fake_results[exchange])

app.symbol_entry.insert(0, "FAKEUSDT")
app.threshold_entry.insert(0, "50000")
app.exchange_combo.set("BINANCE")
app._add_symbol()


def check_step1():
    print("orderbooks keys:", list(app.orderbooks.keys()))
    assert "BINANCE:FAKEUSDT" in app.orderbooks, "должен добавиться на BINANCE (валидатор вернул True)"
    assert "BINANCE SPOT:FAKEUSDT" not in app.orderbooks, "BINANCE теперь отдельный futures-выбор без spot"
    assert "ASTERDEX:FAKEUSDT" not in app.orderbooks, "НЕ должен добавиться на ASTERDEX (валидатор вернул False)"
    assert "GATE:FAKEUSDT" not in app.orderbooks, "НЕ должен добавиться на GATE (это другой базовый выбор)"
    print("OK: выбор BINANCE добавляет только futures")

    cfg_b = app.detector.configs["BINANCE:FAKEUSDT"]
    assert cfg_b.threshold_usd == 50000.0
    print("OK: параметры применились к точному рынку")

    app.symbol_entry.insert(0, "FAKESPOTUSDT")
    app.threshold_entry.insert(0, "25000")
    app.exchange_combo.set("BINANCE SPOT")
    app._add_symbol()
    assert "BINANCE SPOT:FAKESPOTUSDT" in app.orderbooks
    print("OK: spot можно добавить отдельным выбором")

    # --- шаг 2: тест "все биржи" по всем concrete-рынкам ---
    fake_results2 = {exch: False for exch in guimod.EXCHANGE_CHOICES}
    fake_results2.update({"GATE": True, "OKX SPOT": True})
    app._validator_for = lambda exchange: (lambda s: fake_results2[exchange])
    app.symbol_entry.insert(0, "EVERYWHEREUSDT")
    app.threshold_entry.insert(0, "10000")
    app.exchange_combo.set(guimod.ALL_EXCHANGES_LABEL)
    app._add_symbol()
    root.after(1500, check_step2)


def check_step2():
    print("status_var (все биржи):", app.status_var.get())
    assert "GATE:EVERYWHEREUSDT" in app.orderbooks
    assert "OKX SPOT:EVERYWHEREUSDT" in app.orderbooks
    assert "BINANCE SPOT:EVERYWHEREUSDT" not in app.orderbooks
    print("OK: пункт 'все биржи' проверяет все futures+spot рынки и добавляет только найденные")
    print("\nALL 'ALL EXCHANGES' TESTS PASSED")
    root.destroy()


root.after(1500, check_step1)
root.mainloop()
print("EXIT OK")
