@echo off
rem Runs tonight's export now, in a window you can watch.
cd /d "%~dp0"
".venv\Scripts\python.exe" pull.py --show
pause
