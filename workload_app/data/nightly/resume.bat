@echo off
rem Starts the nightly export again after pause.bat.
schtasks /Change /TN "Selecao+ nightly timesheets" /ENABLE
pause
