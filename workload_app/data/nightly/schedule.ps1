# Runs pull.py every night at 12:00 am, as you, with no window.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $here ".venv\Scripts\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $python `
    -Argument ('"' + (Join-Path $here "pull.py") + '"') -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At "12:00 AM"
# Wake the PC for it, and catch up at the next sign-in if it was off.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "Selecao+ nightly timesheets" -Action $action `
    -Trigger $trigger -Settings $settings -Force `
    -Description "Exports Detailed Utilization from BISpark and sends it to Selecao+." | Out-Null
Write-Host "Scheduled: Selecao+ nightly timesheets, every day at 12:00 AM."
