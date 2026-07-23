# Чеклист перед выдачей версии

Использовать перед тем, как отдавать себе или коллеге новую сборку приложения.

## 1. Перед проверкой

- [ ] Рабочая ветка понятна по названию.
- [ ] Нет случайных файлов в изменениях: `dist/`, `build/`, `.exe`, скриншоты.
- [ ] Приложение закрыто перед сборкой.
- [ ] `config.json` не потерян после сборки.

## 2. Быстрые тесты

Запускать из папки проекта:

```bat
set PYTHONIOENCODING=utf-8
%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tests\test_spread_distance_and_lifetime.py
%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tests\test_max_distance_pct.py
%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tests\test_clipboard_copy.py
%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tests\test_all_exchanges.py
%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tests\test_spot_exchange_targets.py
```

Если Codex работает в проекте, можно просто попросить:

```text
Прогони стандартный чеклист тестов перед сборкой.
```

## 3. Проверка интерфейса глазами

- [ ] Окно открывается без ошибки Tcl/Tk.
- [ ] Вкладка `Сканер плотностей` видна сразу.
- [ ] Нет лишнего поля `Комментарий` сверху или в основной таблице.
- [ ] Колонка `Комментарий` есть только в `Ленте алертов`.
- [ ] Двойной клик по ячейке комментария редактирует текст прямо в строке.
- [ ] Правая прокрутка `Ленты алертов` видна.
- [ ] Нижние статусы бирж читаются.

## 4. Проверка фильтров плотности

- [ ] `Дистанция % = 0` превращается в минимальный радиус `0.01%`.
- [ ] `Жизнь, с = 0` остаётся `0` и даёт мгновенный алерт.
- [ ] `Дистанция % = 0` + `Жизнь, с = 0` ловит плотность у спреда.
- [ ] Фильтр `От $` не пропускает плотности меньше порога.
- [ ] Фильтр `До $` не пропускает плотности крупнее верхней границы.

## 5. Проверка spot/futures

- [ ] При выборе `BINANCE` приложение пытается добавить `BINANCE` и `BINANCE SPOT`.
- [ ] Spot обозначается в колонке `Биржа`.
- [ ] В ленте алертов spot-символ виден как `SYMBOL SPOT`.
- [ ] При копировании spot-строки в буфер копируется обычный тикер без `SPOT`.

## 6. Сборка

Запуск:

```bat
build.bat
```

Ожидаемые файлы:

- `dist\BinanceWallScanner\BinanceWallScanner.exe`
- `dist\BinanceWallScanner-Standalone.exe`

После сборки:

- [ ] Запустить `dist\BinanceWallScanner\BinanceWallScanner.exe`.
- [ ] Убедиться, что `config.json` рядом с exe сохранился.
- [ ] Коротко обновить `CHANGELOG.md`, если версия пойдёт дальше.

## 7. Что написать в итоговом сообщении

```text
Изменено:
- ...

Проверено:
- ...

Готовый запуск:
- dist\BinanceWallScanner\BinanceWallScanner.exe
```
