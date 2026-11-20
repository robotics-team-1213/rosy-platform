<#
.SYNOPSIS
Registers the read-only cutover watch (tools/cutover_watch.py) as a Windows scheduled task.

.DESCRIPTION
Runs `python tools/cutover_watch.py` in the main checkout every IntervalMinutes as the current user, only while logged on.
The watch only runs `git fetch`, writes D:/DevTemp/ghmig/cutover-status.json and appends one board line when the state
changes. It never lands, publishes or kills anything. Register it yourself; this repository does not.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File tools\register_cutover_watch_task.ps1 -MainCheckout D:\Dev\Robot\Rosy\rosy-platform

Remove it again:
  Unregister-ScheduledTask -TaskName RosyCutoverWatch -Confirm:$false
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MainCheckout,
    [string]$TaskName = "RosyCutoverWatch",
    [int]$IntervalMinutes = 10,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $MainCheckout).Path
$script = Join-Path $root "tools\cutover_watch.py"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "tools\cutover_watch.py not found under: $root"
}
if (-not $Python) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
if ($IntervalMinutes -lt 5 -or $IntervalMinutes -gt 1440) {
    throw "IntervalMinutes must be between 5 and 1440"
}

$action = New-ScheduledTaskAction -Execute $Python `
    -Argument ('"{0}" --repo "{1}"' -f $script, $root) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "ROSY cutover watch: read-only state check, one board line per change" | Out-Null

Write-Host "Registered scheduled task '$TaskName' (every $IntervalMinutes min, current user, while logged on)."
