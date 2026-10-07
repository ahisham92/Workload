# Runs nightly.ps1 every night, as you, without opening a window: 12:00 am on
# a team member's PC, and 1:00 am on the manager's, once the others are in.
# The task is listed openly in Task Scheduler as "Selecao+ nightly timesheets".
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$at = '12:00 AM'
foreach ($line in Get-Content (Join-Path $here 'settings.ini')) {
    if ($line -match '^\s*run_at\s*=\s*(.+)$') { $at = $matches[1].Trim() }
}
$script = Join-Path $here 'nightly.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $here `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '"')
$trigger = New-ScheduledTaskTrigger -Daily -At $at
# Wake the PC for it, and catch up at the next sign-in if it was off.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'Selecao+ nightly timesheets' -Action $action `
    -Trigger $trigger -Settings $settings -Force `
    -Description 'Exports Detailed Utilization from BISpark and sends it to Selecao+.' | Out-Null
Write-Host "Scheduled: Selecao+ nightly timesheets, every day at $at."
