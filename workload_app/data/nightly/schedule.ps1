# Runs nightly.ps1 as you, without opening a window: at night (12:00 am on a
# team member's PC, 1:00 am on the manager's), every hour after that, at
# sign-in, and a minute after the PC joins a network -- FortiClient included.
# nightly.ps1 itself decides whether anything is still owed today.
# The task is listed openly in Task Scheduler as "Selecao+ nightly timesheets".
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$at = '12:00 AM'
foreach ($line in Get-Content (Join-Path $here 'settings.ini')) {
    if ($line -match '^\s*run_at\s*=\s*(.+)$') { $at = $matches[1].Trim() }
}
$script = Join-Path $here 'nightly.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $here `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '"')

$nightly = New-ScheduledTaskTrigger -Daily -At $at
$nightly.Repetition = (New-ScheduledTaskTrigger -Once -At $at `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Hours 23)).Repetition
$signIn = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# "Connected to a network", which Windows logs for the VPN as for any other.
$eventClass = Get-CimClass -ClassName MSFT_TaskEventTrigger `
    -Namespace Root/Microsoft/Windows/TaskScheduler
$connected = $eventClass | New-CimInstance -ClientOnly
$connected.Enabled = $true
$connected.Delay = 'PT1M'
$connected.Subscription = '<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"><Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[(EventID=10000)]]</Select></Query></QueryList>'

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName 'Selecao+ nightly timesheets' -Action $action `
    -Trigger @($nightly, $signIn, $connected) -Settings $settings -Force `
    -Description 'Exports Detailed Utilization from BISpark and sends it to Selecao+.' | Out-Null
Write-Host "Scheduled: Selecao+ nightly timesheets, from $at, and whenever this PC connects."
