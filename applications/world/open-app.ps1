[CmdletBinding()]
param(
    [string]$Url = 'http://127.0.0.1:8140/?view=factory',
    [string]$Bundle = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Bundle)) {
    $Bundle = $PSScriptRoot
}
$root = (Resolve-Path -LiteralPath $Bundle).Path

function Test-WorldReady {
    try {
        $ready = Invoke-RestMethod -Uri 'http://127.0.0.1:8140/healthz' -TimeoutSec 1
        $mf = Invoke-WebRequest -Uri 'http://127.0.0.1:8140/manifest.json' -UseBasicParsing -TimeoutSec 1
        return ($ready.application -eq 'rosy-world' -and $ready.status -eq 'ready' -and $mf.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (-not (Test-WorldReady)) {
    $task = Get-ScheduledTask -TaskName 'Rosy World' -TaskPath '\' -ErrorAction SilentlyContinue
    if ($task) {
        Start-ScheduledTask -TaskName 'Rosy World'
    } else {
        $python = (Get-Command python.exe -ErrorAction Stop).Source
        $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
        $exe = if (Test-Path -LiteralPath $pythonw -PathType Leaf) { $pythonw } else { $python }
        $serve = Join-Path $root 'serve.py'
        Start-Process -FilePath $exe -ArgumentList @('-B', ('"{0}"' -f $serve), '--bundle', ('"{0}"' -f $root)) -WorkingDirectory $root | Out-Null
    }
    $ok = $false
    foreach ($attempt in 1..20) {
        if (Test-WorldReady) { $ok = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ok) {
        throw 'Rosy World service failed to become ready on http://127.0.0.1:8140/'
    }
}

$candidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)
$browser = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $browser) {
    $cmd = Get-Command msedge.exe, chrome.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { $browser = $cmd.Source }
}
if (-not $browser) {
    throw 'Could not find msedge.exe or chrome.exe to open standalone Rosy World app.'
}

$profileDir = 'D:\DevTemp\rosy-world-app-profile'
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
$launchArgs = @(
    "--app=$Url",
    "--user-data-dir=$profileDir",
    '--window-size=1440,920',
    '--ignore-gpu-blocklist',
    '--no-first-run',
    '--no-default-browser-check'
)

if ($DryRun) {
    Write-Output "BROWSER=$browser"
    Write-Output ("ARGS=" + ($launchArgs -join ' '))
    return
}

Start-Process -FilePath $browser -ArgumentList $launchArgs | Out-Null
Write-Output "Launched Rosy World standalone window: $Url"
