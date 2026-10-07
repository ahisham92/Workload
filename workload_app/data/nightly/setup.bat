@echo off
rem Sets up the nightly export from BISpark to Selecao+ on this PC.
rem Double-click it once. It installs nothing and needs no administrator.
setlocal
cd /d "%~dp0"

echo [1/2] Exporting once now, so you can see it work...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0nightly.ps1"
if errorlevel 1 goto :fail

echo.
echo [2/2] Scheduling it for every night...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0schedule.ps1"
if errorlevel 1 goto :fail

echo.
echo Done. It now runs every night by itself.
echo pause.bat stops it for a while, remove.bat removes it for good.
pause
exit /b 0

:fail
echo.
echo Setup stopped. What happened is in logs\last-run.txt
pause
exit /b 1
