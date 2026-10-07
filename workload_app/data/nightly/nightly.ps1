# Selecao+ nightly timesheets: export from BISpark, and send it on.
#
# Uses only what Windows already has. BISpark is asked for the same export the
# Export button asks for (request.json, saved from a browser), signed in with
# this PC's Windows login, so no password is stored anywhere.
#
# On a team member's PC (role = team) the export is copied to the team's
# shared folder and that is all: nothing leaves the company network. On the
# manager's PC (role = manager) every export in the shared folder is then sent
# to Selecao+ with the unit's key (settings.ini).
#
# Task Scheduler starts this at night, every hour, and whenever the PC joins a
# network (FortiClient included). Each run does only what is still owed: one
# export a day, and an upload only when the shared folder has something new.
# Off the company network it stops quietly and tries again next time.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$logs = Join-Path $here 'logs'
$exports = Join-Path $here 'exports'
New-Item -ItemType Directory -Force -Path $logs, $exports | Out-Null
$log = Join-Path $logs 'last-run.txt'
$exportedMark = Join-Path $logs 'last-export.txt'
$sentMark = Join-Path $logs 'last-upload.txt'

function Log([string]$message) {
    $line = '{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $message
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Host $line
}

function Read-Settings {
    $settings = @{}
    foreach ($line in Get-Content (Join-Path $here 'settings.ini')) {
        if ($line -match '^\s*([A-Za-z_]+)\s*=\s*(.*)$') {
            $settings[$matches[1]] = $matches[2].Trim()
        }
    }
    $settings
}

function Read-Mark([string]$path) {
    if (Test-Path $path) {
        try { return [datetime]::Parse((Get-Content $path -Raw).Trim()) } catch { }
    }
    return [datetime]::MinValue
}

function Write-Mark([string]$path) {
    Set-Content -Path $path -Value (Get-Date).ToString('o') -Encoding UTF8
}

function Error-Body($err) {
    # What the server said, when it said no.
    try {
        $reader = New-Object IO.StreamReader($err.Exception.Response.GetResponseStream())
        return $reader.ReadToEnd()
    } catch { return '' }
}

function Send-Selecao([string]$json) {
    Invoke-RestMethod -Uri ($settings.app_url.TrimEnd('/') + '/api/nightly/timesheets') `
        -Method Post -ContentType 'application/json' -TimeoutSec 600 `
        -Body ([Text.Encoding]::UTF8.GetBytes($json))
}

# The log keeps the last few hundred lines, so hourly runs never grow it.
if ((Test-Path $log) -and @(Get-Content $log).Count -gt 400) {
    $tail = Get-Content $log | Select-Object -Last 200
    Set-Content -Path $log -Value $tail -Encoding UTF8
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$settings = Read-Settings
$refused = $false
$manager = $settings.role -eq 'manager'
$shared = $settings.shared_folder

try {
    $request = Get-Content (Join-Path $here 'request.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $uri = [Uri]$request.uri
    $origin = '{0}://{1}' -f $uri.Scheme, $uri.Host

    # -- the export: once a day ----------------------------------------------
    if ((Read-Mark $exportedMark) -lt (Get-Date).AddHours(-20)) {
        $web = $null
        try {
            # Picks up the site's own cookies the way a browser visit would.
            Invoke-WebRequest -Uri ($origin + '/reports/') -UseDefaultCredentials `
                -UseBasicParsing -SessionVariable web -TimeoutSec 30 | Out-Null
        } catch {
            if ($null -eq $_.Exception.Response) {
                # No answer at all: not on the company network yet.
                Log 'BISpark cannot be reached from here yet. Trying again on the next connection.'
                exit 0
            }
            $web = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        }

        Log 'Asking BISpark for the export'
        $headers = @{
            'Accept' = 'application/json, text/plain, */*'
            'Origin' = $origin
            'X-PowerBI-ResourceKey' = 'any'
            'ActivityId' = [guid]::NewGuid().ToString()
            'RequestId' = [guid]::NewGuid().ToString()
        }
        $file = Join-Path $exports ('bispark-{0:yyyy-MM-dd}.xlsx' -f (Get-Date))
        try {
            Invoke-WebRequest -Uri $request.uri -Method Post -UseDefaultCredentials `
                -UseBasicParsing -WebSession $web -Headers $headers `
                -ContentType 'application/json;charset=UTF-8' `
                -Body ([Text.Encoding]::UTF8.GetBytes($request.body)) `
                -OutFile $file -TimeoutSec 900
        } catch {
            throw ('BISpark refused the export: ' + $_.Exception.Message + ' ' + (Error-Body $_))
        }
        $bytes = [IO.File]::ReadAllBytes($file)
        if ($bytes.Length -lt 4 -or $bytes[0] -ne 0x50 -or $bytes[1] -ne 0x4B) {
            $text = [Text.Encoding]::UTF8.GetString($bytes)
            throw ('BISpark answered with something other than a spreadsheet: ' +
                   $text.Substring(0, [Math]::Min(300, $text.Length)))
        }
        Log ('Saved {0} ({1:N0} KB)' -f (Split-Path $file -Leaf), ($bytes.Length / 1KB))

        # Keep two weeks of exports, in case one is ever needed by hand.
        Get-ChildItem $exports -Filter 'bispark-*.xlsx' | Sort-Object LastWriteTime -Descending |
            Select-Object -Skip 14 | Remove-Item -Force

        if ($shared) {
            if (-not (Test-Path $shared)) { throw "The shared folder $shared cannot be reached." }
            $mine = Join-Path $shared ($env:USERNAME + '.xlsx')
            Copy-Item -Path $file -Destination $mine -Force
            (Get-Item $mine).LastWriteTime = Get-Date
            Log "Copied to $mine"
        }
        Write-Mark $exportedMark
    }

    if (-not $manager) { exit 0 }

    # -- the upload: whenever the shared folder has something new ------------
    if ($shared) {
        if (-not (Test-Path $shared)) { exit 0 }      # off the network again
        $toSend = @(Get-ChildItem $shared -Filter '*.xlsx')
        # Two weeks without a fresh export is a PC that has gone -- returned,
        # or its owner has left. Its last export is no longer sent.
        $gone = @($toSend | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) })
        if ($gone.Count) {
            Log ('Not sent, nothing new for two weeks: ' + (($gone | ForEach-Object { $_.BaseName }) -join ', '))
            $toSend = @($toSend | Where-Object { $_.LastWriteTime -ge (Get-Date).AddDays(-14) })
        }
    } else {
        $toSend = @(Get-ChildItem $exports -Filter 'bispark-*.xlsx' |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1)
    }
    $sent = Read-Mark $sentMark
    if ($toSend.Count -eq 0 -or @($toSend | Where-Object { $_.LastWriteTime -gt $sent }).Count -eq 0) {
        exit 0
    }

    # An export nobody has refreshed for a day and a half is from a PC that
    # has not been on the network. It still goes, and Selecao+ is told whose.
    $late = @($toSend | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-36) } |
        ForEach-Object { $_.BaseName })
    if ($late.Count) { Log ('Not refreshed since yesterday: ' + ($late -join ', ')) }

    Log ('Sending {0} export(s) to Selecao+' -f $toSend.Count)
    $parts = foreach ($item in $toSend) {
        '{"filename":"' + $item.Name.Replace('"', '') + '","content_base64":"' +
            [Convert]::ToBase64String([IO.File]::ReadAllBytes($item.FullName)) + '"}'
    }
    $json = '{"key":"' + $settings.key + '","late":' +
            (ConvertTo-Json -InputObject @($late) -Compress) + ',"files":[' + ($parts -join ',') + ']}'
    try {
        $result = Send-Selecao $json
    } catch {
        if ($null -eq $_.Exception.Response) {
            Log 'Selecao+ cannot be reached from here yet. Trying again next time.'
            exit 0
        }
        $refused = $true
        Write-Mark $sentMark          # the same files would only be refused again
        throw ('Selecao+ refused the import: ' + $_.Exception.Message + ' ' + (Error-Body $_))
    }
    Write-Mark $sentMark
    Log ('Imported {0} rows, {1} hours, {2} to {3}.' -f $result.rows, $result.hours,
         $result.first_date, $result.last_date)
    exit 0
} catch {
    $message = "$($_.Exception.Message)"
    Log ('Stopped: ' + $message)
    if (-not $refused -and $manager -and $settings.key) {
        try {
            $note = @{ key = $settings.key; failed = $message } | ConvertTo-Json -Compress
            Send-Selecao $note | Out-Null
        } catch { }
    }
    exit 1
}
