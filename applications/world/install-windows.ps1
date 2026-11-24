[CmdletBinding()]
param(
    [string]$Bundle = '',
    [switch]$Launch,
    [switch]$NoShortcut
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Bundle)) {
    $Bundle = $PSScriptRoot
}
$root = (Resolve-Path -LiteralPath $Bundle).Path
$script = Join-Path $root 'serve.py'
$openApp = Join-Path $root 'open-app.ps1'
foreach ($name in @('serve.py', 'index.html', 'manifest.json', 'SHA256SUMS.txt')) {
    if (!(Test-Path -LiteralPath (Join-Path $root $name) -PathType Leaf)) {
        throw "ROSY World bundle is missing $name."
    }
}

$python = (Get-Command python.exe -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (!(Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw 'Python for Windows with pythonw.exe is required.'
}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('-B "{0}" --bundle "{1}"' -f $script, $root) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$existing = Get-ScheduledTask -TaskName 'Rosy World' -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Actions.Count -ne 1 -or $existing.Actions[0].Arguments -notmatch 'serve\.py" --bundle "') {
        throw 'The Rosy World task name is already in use.'
    }
    Stop-ScheduledTask -InputObject $existing
    foreach ($wait in 1..6) {
        if (-not (Get-NetTCPConnection -LocalPort 8140 -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    }
    foreach ($c in (Get-NetTCPConnection -LocalPort 8140 -State Listen -ErrorAction SilentlyContinue)) {
        $p = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $c.OwningProcess) -ErrorAction SilentlyContinue
        if ($p -and $p.CommandLine -match 'serve\.py') {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 250
        }
    }
}
Register-ScheduledTask -TaskName 'Rosy World' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'ROSY World local application at 127.0.0.1:8140' -Force | Out-Null
Start-ScheduledTask -TaskName 'Rosy World'

$readyOk = $false
foreach ($attempt in 1..20) {
    try {
        $ready = Invoke-RestMethod -Uri 'http://127.0.0.1:8140/healthz' -TimeoutSec 1
        $bound = Get-NetTCPConnection -LocalPort 8140 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($ready.application -eq 'rosy-world' -and $ready.status -eq 'ready' -and $bound) {
            $owner = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $bound.OwningProcess) -ErrorAction SilentlyContinue
            if ($owner -and $owner.CommandLine -like "*$root*") {
                $readyOk = $true
                break
            }
        }
    } catch {}
    Start-Sleep -Milliseconds 250
}
if (-not $readyOk) {
    throw 'Rosy World did not become ready from the requested bundle on port 8140.'
}
Write-Output 'Rosy World is ready at http://127.0.0.1:8140/'

if (-not $NoShortcut -and (Test-Path -LiteralPath $openApp -PathType Leaf)) {
    $shell = New-Object -ComObject WScript.Shell
    $targets = @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Rosy World.lnk'),
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Rosy World.lnk')
    )
    foreach ($lnkPath in $targets) {
        $lnk = $shell.CreateShortcut($lnkPath)
        $lnk.TargetPath = 'powershell.exe'
        $lnk.Arguments = ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $openApp)
        $lnk.WorkingDirectory = $root
        $lnk.Description = 'Rosy World 공장 3D 앱'
        $lnk.Save()
        Write-Output "Shortcut: $lnkPath"
    }
}

if ($Launch -and (Test-Path -LiteralPath $openApp -PathType Leaf)) {
    & $openApp -Bundle $root
}
