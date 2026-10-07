@echo off
rem Stops the nightly export until resume.bat is run. Nothing is deleted.
schtasks /Change /TN "Selecao+ nightly timesheets" /DISABLE
pause
