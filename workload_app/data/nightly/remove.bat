@echo off
rem Removes the nightly export from this PC for good.
schtasks /Delete /TN "Selecao+ nightly timesheets" /F
echo.
echo Removed. You can now delete this folder.
echo To stop every PC at once, press "Stop nightly imports" on the Timesheets tab.
pause
