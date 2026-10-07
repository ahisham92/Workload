@echo off
rem Stops the nightly export. The folder can be deleted afterwards.
schtasks /Delete /TN "Selecao+ nightly timesheets" /F
pause
