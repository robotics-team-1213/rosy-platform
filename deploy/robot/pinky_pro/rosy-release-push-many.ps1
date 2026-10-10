[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Robot,
    [Parameter(Mandatory = $true)][string]$Tarball,
    [string]$LogDir = "",
    [switch]$PrintCommands
)
# D-553 addendum 2: push one signed payload tarball to several robots at the
# same time. Each robot gets its own unchanged rosy-release-push.ps1 process
# (own claim, calibration guard, readiness check and automatic rollback), so
# this only removes the wait between robots. Output goes to
# <LogDir>\push-<robot>.txt (default: the tarball's folder). Exit code is 0
# only when every robot's push exited 0. For a canary (one robot first, look,
# then the rest) run rosy-release-push.ps1 per robot instead.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# powershell -File passes "-Robot a,b" as one string; split it here.
$Robot = @($Robot | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
foreach ($name in $Robot) {
    if ($name -notmatch '^[A-Za-z0-9.-]+$') { throw "Robot must be a hostname or IPv4 address: $name" }
}
if (@($Robot | Select-Object -Unique).Count -ne $Robot.Count) { throw "a robot is listed twice: $($Robot -join ', ')" }
$Tarball = (Resolve-Path -LiteralPath $Tarball).ProviderPath
if (-not $LogDir) { $LogDir = Split-Path -Parent $Tarball }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$push = Join-Path $PSScriptRoot "rosy-release-push.ps1"

$jobs = foreach ($name in $Robot) {
    $log = Join-Path $LogDir "push-$name.txt"
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$push`"", "-Robot", $name, "-Tarball", "`"$Tarball`"")
    if ($PrintCommands) { $arguments += "-PrintCommands" }
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -NoNewWindow -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    [void]$process.Handle  # keeps ExitCode readable after the process ends
    Write-Host "started push to $name (pid $($process.Id)) -> $log"
    [pscustomobject]@{ Robot = $name; Process = $process; Log = $log }
}

$failed = @()
foreach ($job in $jobs) {
    $job.Process.WaitForExit()
    $code = $job.Process.ExitCode
    $errors = Get-Content -LiteralPath "$($job.Log).err" -ErrorAction SilentlyContinue
    if ($errors) { Add-Content -LiteralPath $job.Log -Value $errors }
    Remove-Item -LiteralPath "$($job.Log).err" -ErrorAction SilentlyContinue
    Write-Host "=== $($job.Robot): exit $code ($($job.Log))"
    if ($code -ne 0) {
        $failed += $job.Robot
        Get-Content -LiteralPath $job.Log -Tail 15 | ForEach-Object { Write-Host "  $_" }
        continue
    }
    Get-Content -LiteralPath $job.Log | Where-Object {
        $_ -match '^(current release|CORE runs|CORE readiness|image-layer sync applied|restarted:|WARNING)'
    } | ForEach-Object { Write-Host "  $_" }
}
if ($failed) {
    Write-Host "push FAILED on: $($failed -join ', '). Read the logs; a robot whose CORE failed readiness was rolled back by its activator."
    exit 1
}
Write-Host "all pushes exited 0: $($Robot -join ', ')"
exit 0
