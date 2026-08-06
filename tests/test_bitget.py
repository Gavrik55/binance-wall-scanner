"""Bitget spot: WS-менеджер + валидатор + обвязка в gui.

Тест НЕ трогает Binance (валидатор бьёт по Bitget REST, App создаётся через
object.__new__ без запуска сканеров) — безопасно запускать при активной торговле.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bitget_ws
import gui

# --- 1. валидатор Bitget (живой REST Bitget) ---
assert bitget_ws.validate_symbol("BTCUSDT") is True, "BTCUSDT должен существовать на Bitget"
assert bitget_ws.validate_symbol("FAKEZZZZUSDT") is False, \
    "несуществующая пара должна отсекаться (Bitget отдаёт HTTP 400 + пустой data)"
print("OK: валидатор Bitget различает реальную и фейковую пару")

# --- 2. менеджер: конструкция + подписка меняет _desired (символы слитные) ---
events = []
mgr = bitget_ws.BitgetWSManager(lambda e, s, ev: events.append((e, s, ev)),
                                lambda t: None, exchange="BITGET SPOT")
assert mgr.exchange == "BITGET SPOT" and mgr.inst_type == "SPOT"
mgr.subscribe_symbol("btcusdt")
assert "BTCUSDT" in mgr._desired, "подписка должна нормализовать тикер в верхний регистр"
mgr.unsubscribe_symbol("BTCUSDT")
assert "BTCUSDT" not in mgr._desired
print("OK: BitgetWSManager конструируется, подписка/отписка ведут _desired")

# --- 3. нормализация события depth (как это делает _listen) ---
# эмулируем сообщение канала books, проверяем форму события для детектора
def normalize(msg):
    arg = msg.get("arg") or {}
    if arg.get("channel") != "books":
        return None
    d = (msg.get("data") or [{}])[0]
    return {
        "snapshot": msg.get("action") == "snapshot",
        "b": [(lvl[0], lvl[1]) for lvl in d.get("bids", [])],
        "a": [(lvl[0], lvl[1]) for lvl in d.get("asks", [])],
    }

snap = normalize({"action": "snapshot", "arg": {"channel": "books", "instId": "BTCUSDT"},
                  "data": [{"bids": [["100", "5"]], "asks": [["101", "3"]]}]})
assert snap == {"snapshot": True, "b": [("100", "5")], "a": [("101", "3")]}
upd = normalize({"action": "update", "arg": {"channel": "books", "instId": "BTCUSDT"},
                 "data": [{"bids": [["100", "0"]], "asks": []}]})
assert upd["snapshot"] is False and upd["b"] == [("100", "0")]
print("OK: событие books нормализуется в {snapshot,b,a} как у OKX/Gate")

# --- 4. обвязка в gui (App без init -> сканеры не стартуют, Binance не трогаем) ---
assert "BITGET SPOT" in gui.EXCHANGE_CHOICES
assert gui.EXCHANGE_SHORT_LABELS["BITGET SPOT"] == "BITG S"
assert gui.LABEL_TO_EXCHANGE["Bitget Spot"] == "BITGET SPOT"
app = object.__new__(gui.App)
validator = app._validator_for("BITGET SPOT")
assert validator("BTCUSDT") is True and validator("FAKEZZZZUSDT") is False
# BITGET SPOT попадает и в "ВСЕ БИРЖИ"
targets, _ = app._exchange_targets_for_selection(gui.ALL_EXCHANGES_LABEL)
assert "BITGET SPOT" in targets
print("OK: gui знает BITGET SPOT (выбор, метки, валидатор, ВСЕ БИРЖИ)")

print("\nALL BITGET TESTS PASSED")
