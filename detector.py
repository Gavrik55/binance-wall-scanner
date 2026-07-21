"""
Логика детектора плотностей.

LONG  -> следим за bid-стороной (плотности снизу от спреда — "поддержка")
SHORT -> следим за ask-стороной (плотности сверху — "сопротивление")
BOTH  -> обе стороны

События на ОДИНОЧНУЮ плотность (один уровень цены, в пределах max_distance_pct):
  APPEARED - плотность простояла cfg.single_confirm_sec секунд статично (не
             исчезла, не просела ниже ALIVE_RATIO порога) — только тогда
             считается подтверждённой и приходит алерт о появлении. Если
             исчезла РАНЬШЕ этого срока — ни одного алерта не будет вообще
             (шум/спуф, отфильтровывается молча)
  MAGNET   - в окне [magnet_window_min_sec; magnet_window_max_sec] секунд
             после появления цена РЕАЛЬНО дошла/коснулась уровня плотности
             (best bid/ask пересёк её цену) — не имеет отношения к
             подтверждению APPEARED, считается от первого обнаружения
             независимо от него
  EATEN    - подтверждённая плотность исчезла, и цена прошла сквозь её
             уровень (поглощена)
  PULLED   - подтверждённая плотность исчезла/резко похудела, а цена до неё
             не дошла (снята/спуф)

События на СТЕНКУ (несколько плотностей РАВНОГО объёма рядом — самостоятельный,
более широкий радиус поиска, wall_max_distance_pct, т.к. стенка физически
может быть растянута сильнее одиночной плотности; зазор между соседними —
wall_cluster_gap_pct % от цены, участников — wall_min_components и больше,
объём — округление до целого $, БЕЗ мягкой группировки "около 10к/50к": набор
из разных по размеру плотностей (10к+20к+15к) стенкой не считается, это
органический шум стакана, а не осмысленный сигнал):
  WALL      - образовался кластер РАВНЫХ по объёму плотностей — отдельный
              сигнал ПОВЕРХ обычных APPEARED по каждой отдельной плотности
              (индивидуальные не подавляются)
  WALL_GONE - кластер перестал существовать (распался/просел ниже порога участников)

  CASCADE   - каскад: CASCADE_MIN_COMPONENTS (2) и больше плотностей РАВНОГО
              объёма (округление до целого $), появившихся ОДНОВРЕМЕННО (в
              одном и том же тике сканирования) и стоящих рядом по цене (тот
              же зазор wall_cluster_gap_pct, что у WALL). Разовый сигнал на
              сам факт одновременного появления — если позже кто-то из группы
              исчезнет и появится заново не в паре, повторно не сработает.

СТАРТОВЫЙ СНИМОК СТАКАНА: всё, что обнаружено в самом первом реальном скане
символа (сразу после синхронизации/добавления, до прогрева AUTO — см.
first_scan_done в WallDetector), помечается WallState.is_baseline=True и НЕ
даёт вообще никаких алертов (ни APPEARED, ни MAGNET, ни EATEN/PULLED) — эти
плотности уже были в стакане ДО того, как мы начали следить, а не появились
"при нас". Видны в UI-таблице активных плотностей, пока существуют.

То же самое касается и СТЕНОК: кластеры, уже стоящие в стакане на этом самом
первом скане, тоже помечаются baseline (в known_clusters) и никогда не дают
ни WALL, ни WALL_GONE — иначе стенка, простоявшая в рынке ДО запуска сканера,
просто "дозрела" бы до алерта через single_confirm_sec после старта, как
будто появилась только что. Статус baseline у кластера наследуется по мере
жизни (пока он физически существует в стакане, даже если чуть сдвинулся по
цене/составу) и снимается только когда кластер реально распадается и
собирается заново — вот это уже будет считаться настоящим новым появлением.

ПОРОГ ДЕТЕКЦИИ — FIXED (число как есть) или AUTO (медиана размера уровня в
этом же стакане × auto_multiplier, не ниже threshold_usd как пол).
"""

import statistics
import time
from collections import deque


SIZE_LABELS = [
    (1_000_000, "🐋 ОГРОМНАЯ"),
    (500_000, "🔴 КРУПНАЯ"),
    (200_000, "🟠 СРЕДНЯЯ"),
    (0, "🟡 МЕЛКАЯ"),
]


def size_label(usd: float) -> str:
    for limit, label in SIZE_LABELS:
        if usd >= limit:
            return label
    return SIZE_LABELS[-1][1]


def format_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


class WallState:
    __slots__ = ("price", "side", "initial_qty", "current_qty", "max_qty",
                 "first_seen", "magnet_fired", "confirmed", "is_baseline")

    def __init__(self, price, qty, side, now):
        self.price = price
        self.side = side  # "bid" / "ask"
        self.initial_qty = qty
        self.current_qty = qty
        self.max_qty = qty
        self.first_seen = now
        self.magnet_fired = False  # True = либо сработал магнит, либо окно закрылось
        self.confirmed = False     # True = простояла single_confirm_sec, алерт APPEARED уже отправлен
        # True = уже была в стакане на момент первого скана после запуска/
        # добавления символа — не "новая" плотность, поэтому НИКАКИХ алертов
        # по ней не приходит вообще (ни появление, ни магнит, ни снятие),
        # только видна в таблице активных плотностей
        self.is_baseline = False


class WallEvent:
    def __init__(self, exchange, symbol, kind, price, qty, side, extra=""):
        self.exchange = exchange
        self.symbol = symbol
        self.kind = kind  # APPEARED / MAGNET / EATEN / PULLED / WALL / WALL_GONE
        self.price = price
        self.qty = qty
        self.side = side
        self.extra = extra
        self.ts = time.time()


class SymbolConfig:
    def __init__(self, symbol, threshold_usd, direction="LONG", exchange="BINANCE",
                 mode="FIXED", auto_multiplier=8.0, max_distance_pct=10.0,
                 magnet_window_min_sec=2.0, magnet_window_max_sec=10.0,
                 wall_min_components=3, wall_cluster_gap_pct=4.0,
                 wall_max_distance_pct=15.0, threshold_max_usd=None,
                 single_confirm_sec=10.0, wall_volume_tolerance_usd=30_000.0):
        self.symbol = symbol.upper()
        self.exchange = exchange.upper()
        self.threshold_usd = float(threshold_usd)  # FIXED: точный порог/"от". AUTO: пол.
        # верхняя граница диапазона объёма ("до $"). None = режим "от и выше"
        # (без разницы, насколько большая плотность) — плотность любого
        # размера от threshold_usd и выше считается подходящей. Заданное
        # значение = режим "от-до" — плотности крупнее этой границы в расчёт
        # не берутся (не считаются новой плотностью).
        self.threshold_max_usd = float(threshold_max_usd) if threshold_max_usd is not None else None
        self.direction = direction  # LONG / SHORT / BOTH
        self.mode = mode  # "FIXED" / "AUTO"
        self.auto_multiplier = auto_multiplier
        self.max_distance_pct = max_distance_pct  # диапазон для ОДИНОЧНЫХ плотностей

        # окно [min;max] секунд после появления, в течение которого проверяем
        # магнит (реальное касание уровня ценой, см. scan())
        self.magnet_window_min_sec = magnet_window_min_sec
        self.magnet_window_max_sec = magnet_window_max_sec

        # сколько секунд плотность должна простоять статично (не исчезнуть,
        # не просесть ниже ALIVE_RATIO порога), прежде чем считается
        # подтверждённой и приходит алерт APPEARED. Если снялась раньше —
        # молча игнорируется как шум/спуф, без единого алерта
        self.single_confirm_sec = single_confirm_sec

        # стенка = wall_min_components и больше плотностей подряд, с зазором
        # между соседними не больше wall_cluster_gap_pct % от цены, и не дальше
        # wall_max_distance_pct % от текущей цены (диапазон шире чем у одиночных
        # плотностей — стенка физически может быть растянута сильнее). Объём
        # соседних участников не обязан совпадать ТОЧНО — допуск
        # wall_volume_tolerance_usd (абсолютный $, не %) между соседними по
        # размеру: 10к/20к/15к разными считаются шумом и не сложатся в
        # стенку, а условные 129к/155к/160к (зазоры 26к и 5к) — сложатся.
        # Кандидаты должны ещё и "выстоять" single_confirm_sec, прежде чем
        # участвовать в стенке — так же, как одиночная плотность перед
        # APPEARED (см. wall_candidate_seen в WallDetector) — отсекает
        # быстро мелькающий спуф.
        self.wall_min_components = wall_min_components
        self.wall_cluster_gap_pct = wall_cluster_gap_pct
        self.wall_max_distance_pct = wall_max_distance_pct
        self.wall_volume_tolerance_usd = wall_volume_tolerance_usd


def _cluster_levels_from_prices(prices, gap_pct):
    """Группирует отсортированный список цен в кластеры соседних уровней
    (зазор между соседними не больше gap_pct % от цены)."""
    prices = sorted(prices)
    clusters = []
    current = []
    for p in prices:
        if current and abs(p - current[-1]) / current[-1] * 100 > gap_pct:
            clusters.append(current)
            current = []
        current.append(p)
    if current:
        clusters.append(current)
    return clusters


def _cluster_by_value(pairs, max_spread):
    """pairs: [(значение, payload), ...]. Группирует по возрастанию значения
    так, чтобы ВЕСЬ разброс (max-min) внутри группы не превышал max_spread
    (абсолютная величина в $, не %, в отличие от _cluster_levels_from_prices).
    ВАЖНО: специально не через "зазор до соседа" — цепочка 10к->20к->30к->...
    с шагом чуть меньше допуска на каждом шаге могла бы расползтись сколь
    угодно широко, оставаясь при этом формально "рядом" с каждым соседом.
    Используется для допуска по объёму у стенки: 129к/155к/160к при
    max_spread=30000 сложатся в одну группу (общий разброс 31к — на грани,
    при более строгом допуске может не сложиться), а 10к/20к/50к
    (разброс 40к) — не сложатся."""
    pairs = sorted(pairs, key=lambda x: x[0])
    clusters = []
    current = []
    for value, payload in pairs:
        if current and value - current[0][0] > max_spread:
            clusters.append(current)
            current = []
        current.append((value, payload))
    if current:
        clusters.append(current)
    return clusters


class WallDetector:
    ALIVE_RATIO = 0.15
    CASCADE_MIN_COMPONENTS = 2  # минимум одинаковых по объёму соседних плотностей для каскада

    # -- параметры авто-порога (AUTO mode) --
    BASELINE_WINDOW = 2000
    BASELINE_MIN_SAMPLES = 30
    BASELINE_RECALC_SEC = 1.0

    def __init__(self):
        self.configs = {}          # "EXCH:SYMBOL" -> SymbolConfig
        self.active_walls = {}     # "EXCH:SYMBOL" -> {price: WallState}
        self.baselines = {}        # "EXCH:SYMBOL" -> deque(usd размеров НЕ-стеночных уровней), для AUTO-порога
        self.baseline_median = {}
        self.baseline_recalc_at = {}
        self.last_threshold = {}   # "EXCH:SYMBOL" -> текущий рабочий порог (для UI), None = прогрев
        self.known_clusters = {}   # "EXCH:SYMBOL" -> [{"side","min","max","count"}]
        # "EXCH:SYMBOL", для которых уже прошёл первый реальный скан после
        # запуска/добавления — всё, что обнаружено В НЁМ, считается стартовым
        # состоянием стакана (is_baseline=True на WallState), а не "новой"
        # плотностью, и алертов по нему не будет
        self.first_scan_done = set()
        # "EXCH:SYMBOL" -> {(side, price): first_seen_ts} — отдельный от
        # active_walls таймер устойчивости КАНДИДАТОВ В СТЕНКУ (свой более
        # широкий радиус wall_max_distance_pct, независимый от одиночных
        # плотностей): кандидат должен непрерывно присутствовать
        # single_confirm_sec, прежде чем участвовать в кластеризации —
        # отсекает мгновенно мелькающий спуф без изменения радиуса поиска
        self.wall_candidate_seen = {}

    @staticmethod
    def _key(exchange, symbol):
        return f"{exchange.upper()}:{symbol.upper()}"

    def set_config(self, cfg: SymbolConfig):
        key = self._key(cfg.exchange, cfg.symbol)
        self.configs[key] = cfg
        self.active_walls.setdefault(key, {})
        self.baselines.setdefault(key, deque(maxlen=self.BASELINE_WINDOW))
        self.baseline_recalc_at.setdefault(key, 0.0)
        self.known_clusters.setdefault(key, [])

    def remove_symbol(self, exchange, symbol):
        key = self._key(exchange, symbol)
        self.configs.pop(key, None)
        self.active_walls.pop(key, None)
        self.baselines.pop(key, None)
        self.baseline_median.pop(key, None)
        self.baseline_recalc_at.pop(key, None)
        self.last_threshold.pop(key, None)
        self.known_clusters.pop(key, None)
        self.first_scan_done.discard(key)
        self.wall_candidate_seen.pop(key, None)

    @staticmethod
    def _sides_to_scan(direction):
        if direction == "LONG":
            return ["bid"]
        if direction == "SHORT":
            return ["ask"]
        return ["bid", "ask"]

    def _effective_threshold(self, key, cfg, now):
        if cfg.mode != "AUTO":
            return cfg.threshold_usd
        baseline = self.baselines.setdefault(key, deque(maxlen=self.BASELINE_WINDOW))
        if len(baseline) < self.BASELINE_MIN_SAMPLES:
            return None
        if now - self.baseline_recalc_at.get(key, 0.0) >= self.BASELINE_RECALC_SEC:
            self.baseline_median[key] = statistics.median(baseline)
            self.baseline_recalc_at[key] = now
        median = self.baseline_median.get(key)
        if median is None:
            return None
        return max(cfg.threshold_usd, median * cfg.auto_multiplier)

    def scan(self, exchange, symbol, orderbook):
        events = []
        key = self._key(exchange, symbol)
        cfg = self.configs.get(key)
        if not cfg or not orderbook.synced:
            return events

        mid = orderbook.mid()
        if not mid or mid <= 0:
            return events

        now = time.time()
        walls = self.active_walls.setdefault(key, {})
        sides = self._sides_to_scan(cfg.direction)
        book_side = {"bid": orderbook.bids, "ask": orderbook.asks}
        best = {"bid": orderbook.best_bid(), "ask": orderbook.best_ask()}

        def within_range(price):
            return abs(mid - price) / mid * 100 <= cfg.max_distance_pct

        # 0) AUTO: статистика "нормального" размера уровня (без уже-стенок, без дальних)
        if cfg.mode == "AUTO":
            baseline = self.baselines.setdefault(key, deque(maxlen=self.BASELINE_WINDOW))
            for side in sides:
                for price, qty in book_side[side].items():
                    if price in walls or not within_range(price):
                        continue
                    baseline.append(price * qty)

        threshold = self._effective_threshold(key, cfg, now)
        self.last_threshold[key] = threshold
        if threshold is None:
            return events  # прогревается

        # is_baseline_tick: самый первый реальный скан этого символа (после
        # запуска приложения / добавления символа / прогрева AUTO-порога).
        # Всё, что найдётся В НЁМ, — это то, что УЖЕ было в стакане, а не
        # что-то новое, поэтому по нему не будет вообще никаких алертов
        # (см. WallState.is_baseline и все проверки в шаге 2 ниже).
        is_baseline_tick = key not in self.first_scan_done

        # 1) новые плотности + обновление объёма существующих. ВАЖНО: алерт
        # APPEARED здесь больше НЕ отправляется — начинаем только отслеживать
        # (WallState), сам алерт откладывается до подтверждения статичности
        # в шаге 2 (cfg.single_confirm_sec). new_this_tick — отдельно, только
        # для каскада (шаг 1b): каскад остаётся МГНОВЕННЫМ сигналом на факт
        # одновременной постановки, независимым от подтверждения одиночных.
        # На baseline-тике в new_this_tick НИЧЕГО не попадает — стартовый
        # набор плотностей не может быть "каскадом", он просто там уже был.
        new_this_tick = []  # [(price, usd, side), ...]
        for side in sides:
            for price, qty in book_side[side].items():
                if not within_range(price):
                    continue
                usd = price * qty
                if usd < threshold:
                    continue
                if cfg.threshold_max_usd is not None and usd > cfg.threshold_max_usd:
                    continue  # режим "от-до": крупнее верхней границы — не считается
                if price not in walls:
                    w = WallState(price, qty, side, now)
                    w.is_baseline = is_baseline_tick
                    walls[price] = w
                    if not is_baseline_tick:
                        new_this_tick.append((price, usd, side))
                else:
                    w = walls[price]
                    w.current_qty = qty
                    w.max_qty = max(w.max_qty, qty)

        self.first_scan_done.add(key)

        # 1b) каскад: 2+ плотности РАВНОГО объёма (округление до $), появившиеся
        # ИМЕННО В ЭТОМ тике (new_this_tick — только что начавшие
        # отслеживаться, а не все активные walls), стоящие рядом по цене (тот
        # же зазор wall_cluster_gap_pct, что и у обычной стенки).
        if len(new_this_tick) >= self.CASCADE_MIN_COMPONENTS:
            by_side = {}
            for price, usd, side in new_this_tick:
                by_side.setdefault(side, []).append((price, usd))
            for side, items in by_side.items():
                usd_by_price = dict(items)
                prices = sorted(usd_by_price)
                for group_prices in _cluster_levels_from_prices(prices, cfg.wall_cluster_gap_pct):
                    if len(group_prices) < self.CASCADE_MIN_COMPONENTS:
                        continue
                    rounded_usd = {round(usd_by_price[p]) for p in group_prices}
                    if len(rounded_usd) != 1:
                        continue  # объёмы не совпадают — это не каскад
                    usd_each = usd_by_price[group_prices[0]]
                    events.append(WallEvent(
                        exchange, symbol, "CASCADE",
                        (group_prices[0] + group_prices[-1]) / 2, 0, side,
                        extra=f"{len(group_prices)} плотности по ${usd_each:,.0f}, "
                              f"цены {group_prices[0]:g}–{group_prices[-1]:g}"
                    ))

        # 2) магнит / подтверждение одиночной плотности (APPEARED) / съедено / снято
        for price, w in list(walls.items()):
            cur_qty = book_side[w.side].get(price, 0.0)
            w.current_qty = cur_qty
            age = now - w.first_seen
            dist_pct_now = abs(mid - price) / mid * 100
            b = best[w.side]
            # цена РЕАЛЬНО дошла/пересекла уровень плотности (не просто
            # приблизилась) — используется и магнитом, и определением EATEN/PULLED
            touched = (b is not None and b <= price) if w.side == "bid" else (b is not None and b >= price)
            still_wall = (price * cur_qty) >= threshold * self.ALIVE_RATIO

            if w.is_baseline:
                # была в стакане ещё до того, как мы начали следить — не
                # "новая" плотность, поэтому НИКАКИХ алертов по ней: ни
                # появления, ни магнита, ни съедено/снято. Просто убираем из
                # отслеживания, когда её не станет (видна в UI, пока жива)
                if not still_wall or dist_pct_now > cfg.max_distance_pct:
                    del walls[price]
                continue

            # магнит проверяем НЕЗАВИСИМО от подтверждения одиночной плотности
            # (single_confirm_sec) — считается от первого обнаружения, а не от
            # момента алерта APPEARED, у него свой раздельный таймер
            if not w.magnet_fired:
                if touched and age >= cfg.magnet_window_min_sec:
                    w.magnet_fired = True
                    usd_now = price * cur_qty
                    max_usd = price * w.max_qty
                    eaten_usd = max(0.0, max_usd - usd_now)
                    eaten_pct = (eaten_usd / max_usd * 100) if max_usd else 0
                    events.append(WallEvent(
                        exchange, symbol, "MAGNET", price, cur_qty, w.side,
                        extra=f"${usd_now:,.0f} осталось (съедено ${eaten_usd:,.0f}, {eaten_pct:.0f}%), "
                              f"цена дошла через {age:.1f}с после появления"
                    ))
                elif age > cfg.magnet_window_max_sec:
                    w.magnet_fired = True  # окно закрылось без притяжения

            if not w.confirmed:
                # ещё не простояла cfg.single_confirm_sec — алерта о появлении
                # ещё не было. Исчезла/просела раньше срока — молча забываем,
                # без единого алерта (ни о появлении, ни о снятии): шум/спуф
                if not still_wall or dist_pct_now > cfg.max_distance_pct:
                    del walls[price]
                    continue
                if age >= cfg.single_confirm_sec:
                    w.confirmed = True
                    usd = price * cur_qty
                    events.append(WallEvent(
                        exchange, symbol, "APPEARED", price, cur_qty, w.side,
                        extra=f"${usd:,.0f} {size_label(usd)}, стоит {format_age(age)}"
                    ))
                continue

            # дальше — только для уже ПОДТВЕРЖДЁННЫХ плотностей (был алерт APPEARED)
            if dist_pct_now > cfg.max_distance_pct:
                # унесло цену дальше max_distance_pct — просто перестаём
                # следить, без события (не съедено и не снято)
                del walls[price]
                continue

            if not still_wall:
                kind = "EATEN" if touched else "PULLED"
                max_usd = w.max_qty * price
                pct_left = (cur_qty * price / max_usd * 100) if max_usd else 0
                events.append(WallEvent(
                    exchange, symbol, kind, price, cur_qty, w.side,
                    extra=f"было ${max_usd:,.0f}, осталось {pct_left:.0f}%, жила {format_age(age)}"
                ))
                del walls[price]

        # 3) кластеризация: несколько плотностей БЛИЗКОГО объёма (допуск
        #    wall_volume_tolerance_usd, $ а не %) рядом по цене = СТЕНКА,
        #    отдельный сигнал поверх. Сканирует стакан САМОСТОЯТЕЛЬНО в своём,
        #    более широком радиусе (wall_max_distance_pct) — стенка физически
        #    может быть растянута сильнее, чем допустимо для одиночной
        #    плотности (max_distance_pct).
        #    ВАЖНО: раньше в стенку годился ЛЮБОЙ набор из 3+ плотностей рядом
        #    по цене, хоть 10к+20к+15к — обычный органический шум стакана, а
        #    не осмысленный сигнал. Теперь внутри price-кластера дополнительно
        #    группируем по объёму с допуском (129к/155к/160к, зазоры 26к и
        #    5к — сложатся при tolerance=30000, а 10к/20к/50к вразнобой —
        #    нет). Один price-кластер может дать несколько разных стенок.
        #    Плюс — устойчивость: кандидат должен непрерывно (без учёта
        #    вот прям этого тика — именно СТОЯТЬ) присутствовать
        #    single_confirm_sec, прежде чем участвовать в кластеризации —
        #    отдельный от active_walls таймер (wall_candidate_seen), со своим
        #    более широким радиусом. Отсекает мгновенно мелькающий спуф.
        # НА BASELINE-ТИКЕ (см. is_baseline_tick выше) кластеры, уже стоящие в
        # стакане, фиксируются как есть — БЕЗ ожидания single_confirm_sec и
        # БЕЗ единого алерта (ни WALL, ни впоследствии WALL_GONO) — точно так
        # же, как is_baseline у одиночных плотностей: они были в стакане ДО
        # того, как мы начали следить, а не появились "при нас". Статус
        # baseline у known-кластера наследуется по overlap из тика в тик
        # (см. ниже), пока кластер физически существует.
        known = self.known_clusters.setdefault(key, [])
        candidate_seen = self.wall_candidate_seen.setdefault(key, {})
        still_present = set()
        current_clusters = []
        for side in sides:
            raw_candidates = []  # [(price, usd), ...]
            for price, qty in book_side[side].items():
                if abs(mid - price) / mid * 100 > cfg.wall_max_distance_pct:
                    continue
                usd = price * qty
                if usd < threshold:
                    continue
                if cfg.threshold_max_usd is not None and usd > cfg.threshold_max_usd:
                    continue
                pk = (side, price)
                candidate_seen.setdefault(pk, now)
                still_present.add(pk)
                raw_candidates.append((price, usd))

            if is_baseline_tick:
                stable = raw_candidates  # без ожидания устойчивости — фиксируем как есть
            else:
                stable = [(p, u) for p, u in raw_candidates
                          if now - candidate_seen[(side, p)] >= cfg.single_confirm_sec]
            usd_by_price = dict(stable)
            for group in _cluster_levels_from_prices([p for p, _u in stable], cfg.wall_cluster_gap_pct):
                pairs = [(usd_by_price[p], p) for p in group]
                for vol_cluster in _cluster_by_value(pairs, cfg.wall_volume_tolerance_usd):
                    if len(vol_cluster) >= cfg.wall_min_components:
                        member_prices = [p for _u, p in vol_cluster]
                        usd_total = sum(u for u, _p in vol_cluster)
                        current_clusters.append({
                            "side": side, "min": min(member_prices), "max": max(member_prices),
                            "count": len(member_prices), "usd": usd_total,
                            "baseline": is_baseline_tick,
                        })

        # кандидаты, пропавшие из стакана (снялись/просели/унесло по цене) —
        # забываем таймер, чтобы при повторном появлении отсчёт шёл заново
        for pk in list(candidate_seen):
            if pk not in still_present:
                del candidate_seen[pk]

        def overlaps(a, b):
            return a["side"] == b["side"] and a["min"] <= b["max"] and a["max"] >= b["min"]

        new_known = []
        for cl in current_clusters:
            matched = next((k for k in known if overlaps(cl, k)), None)
            if matched is not None:
                cl["baseline"] = matched["baseline"]  # наследуем статус, пока кластер жив
            if not cl["baseline"] and matched is None:
                events.append(WallEvent(
                    exchange, symbol, "WALL", (cl["min"] + cl["max"]) / 2, 0, cl["side"],
                    extra=f"{cl['count']} плотности, ${cl['usd']:,.0f}, диапазон {cl['min']:g}–{cl['max']:g}"
                ))
            new_known.append(cl)

        for k in known:
            if k["baseline"]:
                continue  # о появлении не объявляли — и о распаде не объявляем
            if not any(overlaps(k, cl) for cl in current_clusters):
                events.append(WallEvent(
                    exchange, symbol, "WALL_GONE", (k["min"] + k["max"]) / 2, 0, k["side"],
                    extra=f"стенка из {k['count']} плотностей распалась"
                ))

        self.known_clusters[key] = new_known

        return events

    def snapshot(self, exchange, symbol, orderbook):
        """Текущее состояние активных плотностей для UI: возраст и дистанция от цены."""
        key = self._key(exchange, symbol)
        mid = orderbook.mid()
        now = time.time()
        result = []
        for price, w in self.active_walls.get(key, {}).items():
            dist_abs = abs(mid - price) if mid else 0.0
            dist_pct = (dist_abs / mid * 100) if mid else 0.0
            result.append({
                "price": price,
                "side": w.side,
                "usd": price * w.current_qty,
                "age": now - w.first_seen,
                "dist_abs": dist_abs,
                "dist_pct": dist_pct,
            })
        return result
