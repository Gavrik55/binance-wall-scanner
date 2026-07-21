@echo off
REM Build script for Binance Wall Scanner (PyInstaller).
REM Run this on Windows, in the project folder (where main.py lives).

echo === Installing dependencies (requests, websockets) ===
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: failed to install requirements.txt
    pause
    exit /b 1
)

echo.
echo === Installing pyinstaller ===
python -m pip install pyinstaller
if %errorlevel% neq 0 (
    echo.
    echo ERROR: failed to install pyinstaller
    pause
    exit /b 1
)

echo.
echo === Building exe (folder dist\BinanceWallScanner) ===
REM --onedir: folder with exe + files (fast startup, fewer antivirus false
REM           positives than --onefile, which self-extracts on every launch)
REM --windowed: no console window behind the GUI
REM --noconfirm: don't ask to confirm if dist folder already exists
REM "python -m PyInstaller" instead of the bare "pyinstaller" command works
REM even if pip's Scripts folder is not on PATH (common with Python
REM installed from the Microsoft Store - this is what happened last time).
REM --add-data "sounds;sounds" bundles the alert sound file(s) into the exe
REM (Windows path separator for --add-data is ";", source;dest-inside-bundle).
python -m PyInstaller --onedir --windowed --noconfirm --name BinanceWallScanner --add-data "sounds;sounds" main.py
if %errorlevel% neq 0 (
    echo.
    echo ERROR: PyInstaller build failed, see the error text above
    pause
    exit /b 1
)

if not exist "dist\BinanceWallScanner\BinanceWallScanner.exe" (
    echo.
    echo ERROR: exe did not appear where expected - something went wrong
    pause
    exit /b 1
)

if exist "config.json" (
    echo.
    echo === Copying your current config.json into the built folder ===
    copy /Y "config.json" "dist\BinanceWallScanner\config.json" >nul
)

echo.
echo === Done ===
echo Exe is here: dist\BinanceWallScanner\BinanceWallScanner.exe
echo You can copy the whole dist\BinanceWallScanner folder anywhere you like
echo (e.g. to the Desktop) and make a shortcut to the .exe inside it.
pause
