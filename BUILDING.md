# Сборка exe и передача проекта другой нейронке

Этот файл нужен для Codex, Claude или другой нейронки, которая получает проект и должна быстро понять, как собрать свежий `.exe`, что проверять и какие файлы нельзя отправлять в Git.

## Где лежит проект на этом ПК

Рабочая папка:

```powershell
C:\Users\Danya\Desktop\binance_wall_scanner_3\binance_wall_scanner
```

Основная рабочая ветка сейчас:

```text
agent/add-spot-markets
```

Если Git не найден в обычном `PATH` внутри Codex, на этом ПК используется встроенный Git:

```powershell
$gitRoot = 'C:\Users\Danya\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git'
$env:GIT_EXEC_PATH = "$gitRoot\mingw64\bin"
$env:PATH = "$gitRoot\mingw64\bin;$gitRoot\cmd;$env:PATH"
& "$gitRoot\mingw64\bin\git.exe" status --short --branch
```

## Что лежит в Git, а что нет

В Git должны попадать исходники и документация:

- `*.py`
- `tests/`
- `sounds/`
- `*.md`
- `*.bat`
- `*.spec`
- `requirements.txt`

В Git не добавлять:

- `build/`
- `dist/`
- `dist-versioned/`
- `*.exe`
- `config.json`
- `impulse_settings.json`
- `print_settings.json`
- `depth_data/`
- `debug.log`
- `debug_packs/`
- `audit_logs/`
- `screen-check-*.png`

Готовый `.exe` хранится локально или выкладывается через GitHub Releases, но не обычным commit.

## Быстрая сборка exe

Обычная команда из папки проекта:

```powershell
$env:NO_PAUSE = '1'
$env:SKIP_PIP = '1'
$env:TCL_LIBRARY = 'C:\TMM_Cutter\runtime\tcl8.6'
$env:TK_LIBRARY = 'C:\TMM_Cutter\runtime\tk8.6'
cmd /c build_exe.bat
```

`SKIP_PIP=1` нужен, когда зависимости уже установлены. Это быстрее и не требует интернета.

Если сборка идет на новом ПК и зависимостей нет, убрать `SKIP_PIP`:

```powershell
$env:NO_PAUSE = '1'
Remove-Item Env:\SKIP_PIP -ErrorAction SilentlyContinue
$env:TCL_LIBRARY = 'C:\TMM_Cutter\runtime\tcl8.6'
$env:TK_LIBRARY = 'C:\TMM_Cutter\runtime\tk8.6'
cmd /c build_exe.bat
```

В этом режиме скрипт выполнит:

```text
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

Для этого нужен интернет.

## Сборка с номером версии

Чтобы сразу получить отдельный файл версии:

```powershell
$env:NO_PAUSE = '1'
$env:SKIP_PIP = '1'
$env:BUILD_VERSION = 'v0.2.5-beta'
$env:TCL_LIBRARY = 'C:\TMM_Cutter\runtime\tcl8.6'
$env:TK_LIBRARY = 'C:\TMM_Cutter\runtime\tk8.6'
cmd /c build_exe.bat
```

После этого ожидаемые файлы:

```text
dist\BinanceWallScanner\BinanceWallScanner.exe
dist\BinanceWallScanner-Standalone.exe
dist\BinanceWallScanner-v0.2.5-beta.exe
dist-versioned\BinanceWallScanner-v0.2.5-beta.exe
```

`Standalone.exe` удобнее отправлять другим людям: это один файл.

## Почему важны TCL_LIBRARY и TK_LIBRARY

Приложение сделано на Tkinter. Если Tcl/Tk не попадет в сборку, при запуске exe будет ошибка вроде:

```text
Tcl data directory ... not found
No module named tkinter
```

На этом ПК рабочие пути:

```powershell
$env:TCL_LIBRARY = 'C:\TMM_Cutter\runtime\tcl8.6'
$env:TK_LIBRARY = 'C:\TMM_Cutter\runtime\tk8.6'
```

Они уже учитываются в `BinanceWallScanner.spec` и `BinanceWallScanner-Standalone.spec`, но перед сборкой их лучше выставлять явно.

## Что делает build_exe.bat

Скрипт:

1. Находит Python.
2. Закрывает запущенный `BinanceWallScanner.exe`, если он мешает пересборке.
3. Временно сохраняет пользовательские настройки из `dist/`.
4. При необходимости ставит зависимости.
5. Собирает onedir-версию:
   `dist\BinanceWallScanner\BinanceWallScanner.exe`.
6. Собирает standalone-версию:
   `dist\BinanceWallScanner-Standalone.exe`.
7. Возвращает настройки обратно.
8. Если задан `BUILD_VERSION`, делает версионные копии в `dist/` и `dist-versioned/`.

## Минимальные проверки перед сборкой

Из папки проекта:

```powershell
$py = 'C:\Users\Danya\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:TCL_LIBRARY = 'C:\TMM_Cutter\runtime\tcl8.6'
$env:TK_LIBRARY = 'C:\TMM_Cutter\runtime\tk8.6'
$env:PYTHONIOENCODING = 'utf-8'

& $py -m py_compile main.py gui.py market_scan.py depth_recorder.py rest_poll_manager.py ws_manager.py orderbook.py detector.py trade_tape.py audit_log.py
& $py tests\test_clipboard_copy.py
& $py tests\test_symbol_normalize_and_compact.py
& $py tests\test_spot_exchange_targets.py
& $py tests\test_spread_distance_and_lifetime.py
```

Live-тесты требуют интернет и могут временно падать из-за таймаутов бирж:

```powershell
& $py tests\test_market_scan.py
& $py tests\test_early_watchlist.py
```

Если live-тест упал на `Read timed out` у Gate/MEXC/Binance, это не всегда баг программы. Часто достаточно повторить. В самом приложении такие сетевые ошибки ловятся и не должны ронять окно.

## Как проверить готовый exe

Основной файл после свежей сборки:

```text
dist\BinanceWallScanner-Standalone.exe
```

Если собирали с `BUILD_VERSION`, удобный файл:

```text
dist\BinanceWallScanner-v0.2.5-beta.exe
```

Перед выдачей пользователю проверить:

- окно открывается без ошибки Tkinter;
- видна вкладка `Сканер плотностей`;
- видны вкладки `Топ движений`, `Ерши`, `Ранние`;
- автозаполнение тикера не двигает интерфейс, подсвечивает строку под мышкой и прокручивается колесиком;
- внизу читаются статусы бирж;
- старый `config.json` не потерялся.

## Правило слияния с коллегой

Если есть параллельная работа от коллеги:

1. Делать слияние через третью ветку, например:
   `merge/claude-codex-integration`.
2. Главной считать ветку пользователя `agent/add-spot-markets`.
3. Из ветки коллеги брать только согласованные области. Для текущего этапа это были:
   `Ерши` и вкладка `Ранние`.
4. После слияния обязательно прогнать тесты и только потом fast-forward/merge в ветку пользователя.

## Что писать в итоговом сообщении пользователю

Коротко:

```text
Собрано:
- dist\BinanceWallScanner-Standalone.exe
- dist\BinanceWallScanner-vX.Y.Z-beta.exe

Проверено:
- ...

Важно:
- exe не коммитится в Git, в Git ушли только исходники/документация.
```
