@echo off
rem Runs tonight's export now.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0nightly.ps1"
pause
