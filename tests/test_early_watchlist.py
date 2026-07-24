"""Профиль "живой тишины" (вкладка "🎯 Ранние") + фетчер MEXC.

Пороги в market_scan.EARLY_* выведены из 15 размеченных сигналов телеграм-канала
"splash 50% MEXC": у 7 из 9 пампов за час до старта диапазон был 3.9-14.8%,
объём $2.5-8к, разгон объёма 0.40-1.66x. Дампы выглядели противоположно
(диапазон 55-135%, разгон 1.8-10x). Тест проверяет, что фильтр действительно
разделяет эти два профиля, а не просто пропускает всё подряд.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import deque

import market_scan

scanner = market_scan.MarketScanner(lambda t: None, exchanges=["MEXC"])


def build_history(now, range_pct, minutes=70, step_sec=15):
    """История с заданным диапазоном колебаний за последний час."""
    dq = deque()
    n = int(minutes * 60 / step_sec)
    cum_vol = 1_000_000.0
    for i in range(n):
        ts = now - (n - i) * step_sec
        # пила между 1.0 и (1 + range_pct/100) — диапазон ровно заданный
        price = 1.0 + (range_pct / 100.0 if i % 2 == 0 else 0.0)
        cum_vol += 1.0
        dq.append((ts, price, cum_vol))
    return dq


now = time.time()

# --- 1. диапазон считается корректно и прогрев отрабатывает ---------------
dq = build_history(now, 8.0)
ticker = {"vol_60m": 5_000.0, "vol_10m": 800.0}
m = scanner._early_metrics(dq, now, ticker)
print("metrics for 8% range:", m)
assert m["early_ready"] is True, "часа истории должно хватить"
assert 7.5 < m["range_60m"] < 8.5, f"диапазон должен быть ~8%, получили {m['range_60m']}"
print("OK: диапазон за 60м посчитан верно")

# разгон: 800/10=80 за минуту в последние 10 мин против (5000-800)/50=84 до этого
assert 0.8 < m["vol_accel"] < 1.1, f"разгон должен быть ~0.95x, получили {m['vol_accel']}"
print("OK: разгон объёма считается как (10м) / (предыдущие 50м)")

# --- 2. короткая история НЕ выдаёт готовность (иначе ложное "затишье") ----
short = build_history(now, 8.0, minutes=10)
m_short = scanner._early_metrics(short, now, ticker)
assert m_short["early_ready"] is False, "10 минут истории — не готово, иначе диапазон занижен"
print("OK: непрогретая история помечена early_ready=False")

# плотная пачка замеров за 2 минуты тоже не должна считаться часом истории
dense = deque()
for i in range(300):
    dense.append((now - 120 + i * 0.4, 1.0 + (0.08 if i % 2 else 0.0), 1_000_000.0 + i))
m_dense = scanner._early_metrics(dense, now, ticker)
assert m_dense["early_ready"] is False, "много точек за 2 минуты — это не час истории"
print("OK: плотная пачка за 2 минуты не принимается за часовое окно")

# --- 3. фильтр разделяет профиль пампа и профиль дампа --------------------
def mk(symbol, rng, vol, accel, exchange="MEXC"):
    return {"exchange": exchange, "symbol": symbol, "last": 0.001,
            "change_pct_24h": 5.0, "early_ready": True,
            "range_60m": rng, "vol_60m": vol, "vol_accel": accel}


# реальные замеры перед пампами (из выгрузки канала)
pumps = [mk("CZUSDT", 3.9, 2554, 0.40), mk("LEVIUSDT", 4.5, 3197, 1.66),
         mk("HOODRATUSDT", 10.6, 3220, 0.80), mk("JIMOTHYUSDT", 10.9, 4726, 0.59),
         mk("PONSUSDT", 11.6, 8227, 0.53), mk("STONKBROKERUSDT", 12.7, 3090, 1.16),
         mk("JUGGERNAUTUSDT", 14.8, 3864, 0.74)]
# реальные замеры перед дампами — должны быть отсеяны все до одного
dumps = [mk("TJRUSDT", 135.3, 7403, 1.81), mk("WISHBONEUSDT", 120.0, 44177, 10.04),
         mk("VEXAIUSDT", 100.4, 24127, 3.61), mk("BRIANUSDT", 56.5, 3863, 4.60),
         mk("INDEXUSDT", 55.5, 10046, 6.16)]
# мёртвая монета: плоская цена, ровный ботовый объём — таких 35% рынка
dead = [mk("DEADUSDT", 0.1, 2600, 0.9), mk("FLATUSDT", 0.0, 2523, 0.42)]

got = {c["symbol"] for c in market_scan.MarketScanner.early_candidates(pumps + dumps + dead)}
print("\nprofile passed:", sorted(got))
assert got == {p["symbol"] for p in pumps}, f"должны пройти ровно 7 пампов, прошли {got}"
print("OK: 7/7 профилей перед пампом прошли, 0/5 дампов и 0/2 мёртвых")

# --- 4. непрогретые и чужие биржи не попадают в вотч-лист -----------------
warming = mk("WARMUSDT", 8.0, 5000, 0.9)
warming["early_ready"] = False
other = mk("BINANCECOINUSDT", 8.0, 5000, 0.9, exchange="BINANCE")
res = market_scan.MarketScanner.early_candidates([warming, other] + pumps, exchange="MEXC")
names = {c["symbol"] for c in res}
assert "WARMUSDT" not in names, "непрогретая монета не должна попадать в список"
assert "BINANCECOINUSDT" not in names, "фильтр по бирже должен отсекать не-MEXC"
print("OK: непрогретые и чужие биржи отфильтрованы")

# --- 5. сортировка: самые сжатые сверху -----------------------------------
order = [c["symbol"] for c in market_scan.MarketScanner.early_candidates(pumps)]
assert order[0] == "CZUSDT", f"самый узкий диапазон должен быть первым, получили {order[0]}"
assert order[-1] == "JUGGERNAUTUSDT", order
print("OK: сортировка по возрастанию диапазона")

# --- 6. фильтр эксклюзивности листинга ------------------------------------
# монета в профиле, но торгуется ещё и на биржах первого эшелона
exclusive = mk("OBSCUREUSDT", 8.0, 5000, 0.9)
on_binance = mk("BALUSDT", 8.0, 5000, 0.9)
on_bybit = mk("SNXUSDT", 8.0, 5000, 0.9)
on_gate_only = mk("MIDTIERUSDT", 8.0, 5000, 0.9)
batch = [exclusive, on_binance, on_bybit, on_gate_only,
         # те же символы, но с других бирж — так их видит реальный батч
         mk("BALUSDT", 1.0, 1, 1, exchange="BINANCE"),
         mk("SNXUSDT", 1.0, 1, 1, exchange="BYBIT"),
         mk("MIDTIERUSDT", 1.0, 1, 1, exchange="GATE")]

strict = {c["symbol"] for c in market_scan.MarketScanner.early_candidates(
    batch, exchange="MEXC", exclude_majors=True)}
print("\nэксклюзивы:", sorted(strict))
assert "BALUSDT" not in strict, "монета с Binance должна быть отсеяна"
assert "SNXUSDT" not in strict, "монета с Bybit должна быть отсеяна"
assert "MIDTIERUSDT" in strict, "Gate — второй эшелон, дисквалификацией не считается"
assert "OBSCUREUSDT" in strict
print("OK: Binance/OKX/Bybit отсеиваются, Gate/AsterDEX — нет")

loose = {c["symbol"] for c in market_scan.MarketScanner.early_candidates(
    batch, exchange="MEXC", exclude_majors=False)}
assert "BALUSDT" in loose, "с выключенным фильтром мажоры должны возвращаться"
print("OK: фильтр отключается флагом exclude_majors")

# спот Binance подхватывается отдельным списком (монета без фьючерса)
spot_only = {c["symbol"] for c in market_scan.MarketScanner.early_candidates(
    batch, exchange="MEXC", exclude_majors=True,
    binance_spot_symbols={"OBSCUREUSDT"})}
assert "OBSCUREUSDT" not in spot_only, \
    "монета со спота Binance (без фьючерса) тоже должна отсеиваться"
print("OK: спот Binance учитывается отдельным списком")

# also_on показывает, где ещё торгуется монета
res = market_scan.MarketScanner.early_candidates(batch, exchange="MEXC", exclude_majors=True)
midtier = next(c for c in res if c["symbol"] == "MIDTIERUSDT")
assert midtier["also_on"] == ["GATE"], midtier["also_on"]
obscure = next(c for c in res if c["symbol"] == "OBSCUREUSDT")
assert obscure["also_on"] == [], "эксклюзив MEXC — пустой список бирж"
print("OK: also_on заполняется корректно")

# --- 7. открытый интерес: ранжирование и прочерк для спота ----------------
from collections import deque

# монеты в одинаковом профиле, но с разным OI
spot = mk("SPOTONLYUSDT", 5.0, 5000, 0.9)          # нет фьючерса
oi_flat = mk("OIFLATUSDT", 4.0, 5000, 0.9)         # есть OI, но не растёт
oi_rising = mk("OIRISINGUSDT", 8.0, 5000, 0.9)     # есть OI и растёт — должен всплыть наверх
# метрики OI навешиваются как в _oi_metrics
spot.update({"has_oi": False, "oi_usd": 0.0, "oi_change_pct": 0.0})
oi_flat.update({"has_oi": True, "oi_usd": 50_000.0, "oi_change_pct": 3.0})
oi_rising.update({"has_oi": True, "oi_usd": 120_000.0, "oi_change_pct": 45.0})

ranked = market_scan.MarketScanner.early_candidates(
    [spot, oi_flat, oi_rising], exchange="MEXC", exclude_majors=False)
order = [c["symbol"] for c in ranked]
print("\nпорядок с учётом OI:", order)
# растущий OI впереди, несмотря на более широкий диапазон (8% против 4-5%)
assert order[0] == "OIRISINGUSDT", f"растущий OI должен быть первым, получили {order[0]}"
# спотовые НЕ выброшены — просто без бонуса
assert "SPOTONLYUSDT" in order, "спотовая монета без OI должна остаться в списке"
print("OK: растущий OI поднимается наверх, спот без OI остаётся в списке")

# _oi_metrics: спотовая монета без истории OI -> has_oi False
scanner2 = market_scan.MarketScanner(lambda t: None, exchanges=["MEXC"])
m_spot = scanner2._oi_metrics("NOSUCHFUTUSDT", time.time())
assert m_spot["has_oi"] is False, "монета без фьючерса — has_oi False"

# _oi_metrics: есть история -> OI в USD и ΔOI по числу контрактов
now2 = time.time()
scanner2.mexc_contract_size["TESTUSDT"] = 100.0
dq = deque()
dq.append((now2 - 1800, 1000.0, 0.5))   # 30 мин назад: 1000 контрактов
dq.append((now2, 1500.0, 0.5))          # сейчас: 1500 контрактов (+50%)
scanner2._oi_history["TESTUSDT"] = dq
m = scanner2._oi_metrics("TESTUSDT", now2)
print("OI-метрики TESTUSDT:", m)
assert m["has_oi"] is True
assert abs(m["oi_usd"] - 1500 * 100 * 0.5) < 1, f"OI в USD = 1500*100*0.5=75000, получили {m['oi_usd']}"
assert 49 < m["oi_change_pct"] < 51, f"ΔOI должен быть +50%, получили {m['oi_change_pct']}"
print("OK: OI в USD через contractSize, ΔOI по числу контрактов")

# ΔOI не считается, пока истории меньше минимального span (шум)
dq_short = deque()
dq_short.append((now2 - 60, 1000.0, 0.5))   # всего минута истории
dq_short.append((now2, 2000.0, 0.5))
scanner2._oi_history["SHORTUSDT"] = dq_short
scanner2.mexc_contract_size["SHORTUSDT"] = 100.0
m_short = scanner2._oi_metrics("SHORTUSDT", now2)
assert m_short["oi_change_pct"] == 0.0, "при <10 мин истории ΔOI должен быть 0 (шум)"
print("OK: ΔOI не считается на слишком короткой истории")

# --- 8. живые фетчеры OI --------------------------------------------------
print("\nживой запрос OI и размеров контрактов MEXC...")
sizes = market_scan.fetch_mexc_contract_sizes()
assert len(sizes) > 300, f"должно быть много контрактов, получили {len(sizes)}"
oi = market_scan.fetch_mexc_oi()
assert len(oi) > 300, f"OI должен прийти по многим контрактам, получили {len(oi)}"
btc = oi.get("BTCUSDT")
assert btc and btc[0] > 0, "у BTC должен быть ненулевой OI"
print(f"OK: контрактов {len(sizes)}, OI по {len(oi)} парам, BTC holdVol={btc[0]:,.0f}")

# --- 9. живой фетчер MEXC (спот) ------------------------------------------
print("\nживой запрос к MEXC...")
rows = market_scan._fetch_mexc()
assert len(rows) > 500, f"MEXC должен отдать больше 500 USDT-пар, отдал {len(rows)}"
sample = rows[0]
assert set(sample) == {"exchange", "symbol", "last", "change_pct_24h", "quote_volume"}, sample
assert all(r["symbol"].endswith("USDT") for r in rows), "должны остаться только USDT-пары"
print(f"OK: MEXC отдал {len(rows)} пар, пример: {sample['symbol']} {sample['change_pct_24h']:+.2f}%")

# главная ловушка MEXC: priceChangePercent приходит ДОЛЕЙ, а не процентами.
# Если забыть домножить на 100, все изменения будут в пределах +-1% — проверяем,
# что на живом рынке есть хоть одна монета с изменением больше 1.5%.
assert any(abs(r["change_pct_24h"]) > 1.5 for r in rows), \
    "подозрительно: ни одной монеты с изменением >1.5% — забыли домножить долю на 100?"
print("OK: priceChangePercent сконвертирован из доли в проценты")

print("\nALL EARLY WATCHLIST TESTS PASSED")
