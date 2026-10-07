@echo off
rem Sets up the nightly export from BISpark to Selecao+ on this PC.
rem Run it once, by double-clicking. It needs no administrator rights.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed on this PC.
  echo Install "Python 3.12" from the Microsoft Store, then run setup.bat again.
  start "" "ms-windows-store://search/?query=python 3.12"
  pause
  exit /b 1
)

echo [1/4] Making a private Python for the job...
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto :fail
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip playwright || goto :fail

echo [2/4] Where the report is
".venv\Scripts\python.exe" pull.py --setup || goto :fail

echo [3/4] A first run you can watch. Edge opens, exports the table and sends it.
echo       If BISpark asks you to sign in, sign in in that window.
".venv\Scripts\python.exe" pull.py --show || goto :fail

echo [4/4] Scheduling it for 12:00 am every night
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0schedule.ps1" || goto :fail

echo.
echo Done. Selecao+ will get your timesheets every night at 12:00 am.
echo Leave the PC on or asleep; if it was off, the job runs when you next sign in.
pause
exit /b 0

:fail
echo.
echo Setup stopped. What happened is in logs\last-run.txt
pause
exit /b 1
