# Tiger DOM Logger

Это экспериментальный кастомный индикатор для Tiger.com / Tiger.Trade Windows.
Он пишет CSV-снимки стакана Tiger, чтобы сверять их с `Аудит CSV` нашего сканера.

## Установка

1. Закрой Tiger.
2. Скопируй `TigerDomLogger.cs` в папку:

   `C:\Users\Danya\Documents\TigerTrade\Indicators`

3. Запусти Tiger заново.
4. Открой график или DOM нужного инструмента.
5. Открой менеджер индикаторов.
6. Найди `*Tiger DOM Logger` и добавь его.
7. В настройках индикатора включи `Enabled = true`.

## Где будет CSV

По умолчанию файлы пишутся сюда:

`C:\Users\Danya\Documents\TigerTrade\DomLogs`

Имя файла примерно такое:

`tiger_dom_SYMBOL_20260723_153000.csv`

## Главные настройки

- `Enabled` - включает/выключает запись.
- `Interval, ms` - частота записи. Для первой проверки оставь `250`.
- `Max levels per side` - сколько уровней bid и ask писать от спреда. Для первой проверки оставь `50`.
- `Min raw size` - минимальный raw-объем Tiger. Для первой проверки оставь `0`.
- `Only changed rows` - писать только изменившиеся уровни. Для первой проверки лучше оставить `false`.
- `Output folder` - папка, куда писать CSV.

## Как сверять

1. В Tiger включи `*Tiger DOM Logger` на нужном инструменте.
2. В нашем сканере включи `Аудит CSV` на той же монете и том же рынке.
3. Записывай 2-5 минут.
4. Останови запись в обоих местах.
5. Сравни файлы:
   - Tiger: `Documents\TigerTrade\DomLogs`
   - Scanner: `binance_wall_scanner\audit_logs`

Важно: для точной сверки рынки должны совпадать: spot со spot, futures с futures.
