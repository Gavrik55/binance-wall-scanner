@echo off
setlocal EnableExtensions
cd /d "%~dp0"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%I"
set "OUT_DIR=debug_packs\debug-%STAMP%"
set "ZIP_FILE=debug_packs\debug-%STAMP%.zip"

if not exist "debug_packs" mkdir "debug_packs"
mkdir "%OUT_DIR%"

echo Debug pack created at %DATE% %TIME%>"%OUT_DIR%\info.txt"
echo Project: %CD%>>"%OUT_DIR%\info.txt"

if exist "config.json" copy /Y "config.json" "%OUT_DIR%\project-config.json" >nul
if exist "debug.log" copy /Y "debug.log" "%OUT_DIR%\project-debug.log" >nul
if exist "impulse_settings.json" copy /Y "impulse_settings.json" "%OUT_DIR%\project-impulse_settings.json" >nul

if exist "dist\BinanceWallScanner\config.json" copy /Y "dist\BinanceWallScanner\config.json" "%OUT_DIR%\dist-config.json" >nul
if exist "dist\BinanceWallScanner\debug.log" copy /Y "dist\BinanceWallScanner\debug.log" "%OUT_DIR%\dist-debug.log" >nul
if exist "dist\BinanceWallScanner\impulse_settings.json" copy /Y "dist\BinanceWallScanner\impulse_settings.json" "%OUT_DIR%\dist-impulse_settings.json" >nul

if exist "PROJECT_NOTES.md" copy /Y "PROJECT_NOTES.md" "%OUT_DIR%\PROJECT_NOTES.md" >nul
if exist "CHANGELOG.md" copy /Y "CHANGELOG.md" "%OUT_DIR%\CHANGELOG.md" >nul
if exist "BUGS.md" copy /Y "BUGS.md" "%OUT_DIR%\BUGS.md" >nul
if exist "README.md" copy /Y "README.md" "%OUT_DIR%\README.md" >nul

powershell -NoProfile -Command "Compress-Archive -Path '%OUT_DIR%\*' -DestinationPath '%ZIP_FILE%' -Force"
if %errorlevel% neq 0 (
    echo Failed to create zip. Files are still here: %OUT_DIR%
    if not defined NO_PAUSE pause
    exit /b 1
)

echo.
echo Done: %ZIP_FILE%
echo Send this zip together with a screenshot if the issue is visual.
if not defined NO_PAUSE pause
