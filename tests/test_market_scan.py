import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_scan

assert market_scan._okx_quote_volume({"volCcy24h": "100"}, 10.0, "SWAP") == 1000.0
assert market_scan._okx_quote_volume({"volCcy24h": "1000"}, 10.0, "SPOT") == 1000.0
print("OK: OKX futures volume converts from coin volume to USDT; spot volume stays quote volume")

print("--- fetching each exchange individually ---")
for exch, fetch in market_scan.FETCHERS.items():
    data = fetch()
    print(f"{exch}: {len(data)} символов, пример: {data[0] if data else None}")
    assert len(data) > 0, f"{exch} вернул пустой список"
    for d in data[:3]:
        assert isinstance(d["last"], float)
        assert isinstance(d["change_pct_24h"], float)
        assert isinstance(d["quote_volume"], float)
        assert d["symbol"].endswith("USDT")

print("\n--- top movers (без импульса, все биржи разом) ---")
all_tickers = []
for exch, fetch in market_scan.FETCHERS.items():
    all_tickers.extend(fetch())
print("всего тикеров:", len(all_tickers))
gainers, losers = market_scan.MarketScanner.top_movers(all_tickers, n=10)
print("\nТОП-10 РОСТА:")
for g in gainers:
    print(f"  {g['exchange']:9s} {g['symbol']:14s} {g['change_pct_24h']:+7.2f}%  last={g['last']}")
print("\nТОП-10 ПАДЕНИЯ:")
for l in losers:
    print(f"  {l['exchange']:9s} {l['symbol']:14s} {l['change_pct_24h']:+7.2f}%  last={l['last']}")

# проверка сортировки
assert gainers[0]["change_pct_24h"] >= gainers[-1]["change_pct_24h"]
assert losers[0]["change_pct_24h"] <= losers[-1]["change_pct_24h"]
print("\nOK: сортировка топ-роста/топ-падения корректна")

print("\n--- MarketScanner: фоновый поток + импульс ---")
received = []
def on_update(tickers):
    received.append(tickers)
    print(f"on_update: {len(tickers)} тикеров, есть impulse_pct у первого: {'impulse_pct' in tickers[0]}")

def on_status(text):
    print("STATUS:", text)

# Ограничиваем ОДНОЙ биржей: после добавления spot-клонов и MEXC полный обход
# FETCHERS занимает ~10 запросов и цикл длится дольше интервала — тест по
# всем биржам стал бы флаки. Нас интересует сам факт периодического опроса и
# расчёт impulse_pct, для этого хватает одной быстрой биржи.
scanner = market_scan.MarketScanner(on_update, on_status, exchanges=["BINANCE"])
# для теста ускоряем опрос, чтобы не ждать реальные 15 сек
market_scan.POLL_INTERVAL_SEC = 3.0
scanner.start()
time.sleep(10)  # при интервале 3с и быстрой одиночной бирже уложатся 2+ цикла
scanner.stop()

assert len(received) >= 2, f"ожидалось минимум 2 цикла опроса за 10 сек, получено {len(received)}"
last_batch = received[-1]
sample = last_batch[0]
print("пример тикера после 2+ циклов:", sample)
assert "impulse_pct" in sample
print("OK: MarketScanner работает в фоне, impulse_pct считается")

print("\nALL MARKET SCAN TESTS PASSED")
