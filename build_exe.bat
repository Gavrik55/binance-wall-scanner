@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo === Binance Wall Scanner build ===

set "PY_EXE="
set "PY_ARGS="

if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    set "PY_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

if not defined PY_EXE (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_EXE=py"
        set "PY_ARGS=-3"
    )
)

if not defined PY_EXE (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_EXE=python"
    )
)

if not defined PY_EXE (
    echo ERROR: Python was not found.
    echo Install Python 3 or run this build through Codex on this computer.
    if not defined NO_PAUSE pause
    exit /b 1
)

echo Using Python: %PY_EXE% %PY_ARGS%

tasklist /FI "IMAGENAME eq BinanceWallScanner.exe" 2>nul | find /I "BinanceWallScanner.exe" >nul
if %errorlevel% equ 0 (
    echo Closing running BinanceWallScanner.exe...
    taskkill /IM BinanceWallScanner.exe /F >nul 2>nul
    ping 127.0.0.1 -n 3 >nul
)

set "BACKUP_DIR=.build_config_backup"
if exist "%BACKUP_DIR%" rmdir /S /Q "%BACKUP_DIR%"
mkdir "%BACKUP_DIR%"

if exist "dist\BinanceWallScanner\config.json" copy /Y "dist\BinanceWallScanner\config.json" "%BACKUP_DIR%\config.json" >nul
if exist "dist\BinanceWallScanner\impulse_settings.json" copy /Y "dist\BinanceWallScanner\impulse_settings.json" "%BACKUP_DIR%\impulse_settings.json" >nul
if exist "dist\BinanceWallScanner\print_settings.json" copy /Y "dist\BinanceWallScanner\print_settings.json" "%BACKUP_DIR%\print_settings.json" >nul
if exist "dist\BinanceWallScanner\ui_settings.json" copy /Y "dist\BinanceWallScanner\ui_settings.json" "%BACKUP_DIR%\ui_settings.json" >nul
if exist "dist\BinanceWallScanner\hedgehog_event_settings.json" copy /Y "dist\BinanceWallScanner\hedgehog_event_settings.json" "%BACKUP_DIR%\hedgehog_event_settings.json" >nul
if exist "dist\BinanceWallScanner\spike_reversal_settings.json" copy /Y "dist\BinanceWallScanner\spike_reversal_settings.json" "%BACKUP_DIR%\spike_reversal_settings.json" >nul
if exist "dist\config.json" copy /Y "dist\config.json" "%BACKUP_DIR%\dist-config.json" >nul
if exist "dist\impulse_settings.json" copy /Y "dist\impulse_settings.json" "%BACKUP_DIR%\dist-impulse_settings.json" >nul
if exist "dist\print_settings.json" copy /Y "dist\print_settings.json" "%BACKUP_DIR%\dist-print_settings.json" >nul
if exist "dist\ui_settings.json" copy /Y "dist\ui_settings.json" "%BACKUP_DIR%\dist-ui_settings.json" >nul
if exist "dist\hedgehog_event_settings.json" copy /Y "dist\hedgehog_event_settings.json" "%BACKUP_DIR%\dist-hedgehog_event_settings.json" >nul
if exist "dist\spike_reversal_settings.json" copy /Y "dist\spike_reversal_settings.json" "%BACKUP_DIR%\dist-spike_reversal_settings.json" >nul
if exist "dist\BinanceWallScanner\tmm_cutter_data" xcopy /E /I /Y "dist\BinanceWallScanner\tmm_cutter_data" "%BACKUP_DIR%\tmm_cutter_data" >nul
if exist "dist\tmm_cutter_data" xcopy /E /I /Y "dist\tmm_cutter_data" "%BACKUP_DIR%\dist-tmm_cutter_data" >nul

if defined SKIP_PIP (
    echo.
    echo === Skipping pip install because SKIP_PIP=1 ===
) else (
    echo.
    echo === Installing dependencies ===
    "%PY_EXE%" %PY_ARGS% -m pip install -r requirements.txt
    if %errorlevel% neq 0 goto build_error

    echo.
    echo === Installing PyInstaller ===
    "%PY_EXE%" %PY_ARGS% -m pip install pyinstaller
    if %errorlevel% neq 0 goto build_error
)

echo.
echo === Building onedir version ===
"%PY_EXE%" %PY_ARGS% -m PyInstaller --noconfirm "BinanceWallScanner.spec"
if %errorlevel% neq 0 goto build_error

echo.
echo === Building standalone version ===
"%PY_EXE%" %PY_ARGS% -m PyInstaller --noconfirm "BinanceWallScanner-Standalone.spec"
if %errorlevel% neq 0 goto build_error

if exist "%BACKUP_DIR%\config.json" copy /Y "%BACKUP_DIR%\config.json" "dist\BinanceWallScanner\config.json" >nul
if exist "%BACKUP_DIR%\impulse_settings.json" copy /Y "%BACKUP_DIR%\impulse_settings.json" "dist\BinanceWallScanner\impulse_settings.json" >nul
if exist "%BACKUP_DIR%\print_settings.json" copy /Y "%BACKUP_DIR%\print_settings.json" "dist\BinanceWallScanner\print_settings.json" >nul
if exist "%BACKUP_DIR%\ui_settings.json" copy /Y "%BACKUP_DIR%\ui_settings.json" "dist\BinanceWallScanner\ui_settings.json" >nul
if exist "%BACKUP_DIR%\hedgehog_event_settings.json" copy /Y "%BACKUP_DIR%\hedgehog_event_settings.json" "dist\BinanceWallScanner\hedgehog_event_settings.json" >nul
if exist "%BACKUP_DIR%\spike_reversal_settings.json" copy /Y "%BACKUP_DIR%\spike_reversal_settings.json" "dist\BinanceWallScanner\spike_reversal_settings.json" >nul
if exist "%BACKUP_DIR%\dist-config.json" copy /Y "%BACKUP_DIR%\dist-config.json" "dist\config.json" >nul
if exist "%BACKUP_DIR%\dist-impulse_settings.json" copy /Y "%BACKUP_DIR%\dist-impulse_settings.json" "dist\impulse_settings.json" >nul
if exist "%BACKUP_DIR%\dist-print_settings.json" copy /Y "%BACKUP_DIR%\dist-print_settings.json" "dist\print_settings.json" >nul
if exist "%BACKUP_DIR%\dist-ui_settings.json" copy /Y "%BACKUP_DIR%\dist-ui_settings.json" "dist\ui_settings.json" >nul
if exist "%BACKUP_DIR%\dist-hedgehog_event_settings.json" copy /Y "%BACKUP_DIR%\dist-hedgehog_event_settings.json" "dist\hedgehog_event_settings.json" >nul
if exist "%BACKUP_DIR%\dist-spike_reversal_settings.json" copy /Y "%BACKUP_DIR%\dist-spike_reversal_settings.json" "dist\spike_reversal_settings.json" >nul
if exist "%BACKUP_DIR%\tmm_cutter_data" xcopy /E /I /Y "%BACKUP_DIR%\tmm_cutter_data" "dist\BinanceWallScanner\tmm_cutter_data" >nul
if exist "%BACKUP_DIR%\dist-tmm_cutter_data" xcopy /E /I /Y "%BACKUP_DIR%\dist-tmm_cutter_data" "dist\tmm_cutter_data" >nul
if not exist "dist\BinanceWallScanner\tmm_cutter_data" if exist "tmm_cutter_data" xcopy /E /I /Y "tmm_cutter_data" "dist\BinanceWallScanner\tmm_cutter_data" >nul
if not exist "dist\tmm_cutter_data" if exist "tmm_cutter_data" xcopy /E /I /Y "tmm_cutter_data" "dist\tmm_cutter_data" >nul

if exist "%BACKUP_DIR%" rmdir /S /Q "%BACKUP_DIR%"

if not exist "dist\BinanceWallScanner\BinanceWallScanner.exe" (
    echo ERROR: onedir exe was not created.
    if not defined NO_PAUSE pause
    exit /b 1
)

if not exist "dist\BinanceWallScanner-Standalone.exe" (
    echo ERROR: standalone exe was not created.
    if not defined NO_PAUSE pause
    exit /b 1
)

if defined BUILD_VERSION (
    if not exist "dist-versioned" mkdir "dist-versioned"
    copy /Y "dist\BinanceWallScanner-Standalone.exe" "dist\BinanceWallScanner-%BUILD_VERSION%.exe" >nul
    copy /Y "dist\BinanceWallScanner-Standalone.exe" "dist-versioned\BinanceWallScanner-%BUILD_VERSION%.exe" >nul
)

echo.
echo === Done ===
echo Onedir:     dist\BinanceWallScanner\BinanceWallScanner.exe
echo Standalone: dist\BinanceWallScanner-Standalone.exe
if defined BUILD_VERSION (
    echo Versioned:  dist\BinanceWallScanner-%BUILD_VERSION%.exe
    echo Archive:    dist-versioned\BinanceWallScanner-%BUILD_VERSION%.exe
)
echo Config files were restored after build.
if not defined NO_PAUSE pause
exit /b 0

:build_error
echo.
echo ERROR: build failed. Config backup remains here: %BACKUP_DIR%
if not defined NO_PAUSE pause
exit /b 1
