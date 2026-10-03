<#
.SYNOPSIS
Registers the D-440 automatic site-candidate signer as a Windows scheduled task.

.DESCRIPTION
Runs `python auto_sign_candidates.py --config <ConfigPath>` every 10 minutes as
the current user, only while that user is logged on (gh keeps its token in the
user's credential store). A run that is still going blocks the next one
(MultipleInstances IgnoreNew); the script itself also holds a lock.

The config and the private key must live outside the repository. This script
does not create either, and it never prints key material.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File deploy\site\register_auto_sign_task.ps1 `
  -ConfigPath C:\RosySigning\auto-sign.json

Remove it again:
  Unregister-ScheduledTask -TaskName RosySiteAutoSign -Confirm:$false
Pause without removing:
  Disable-ScheduledTask -TaskName RosySiteAutoSign
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [string]$TaskName = "RosySiteAutoSign",
    [int]$IntervalMinutes = 10,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$config = (Resolve-Path -LiteralPath $ConfigPath).Path
$script = Join-Path $PSScriptRoot "auto_sign_candidates.py"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "auto_sign_candidates.py not found next to this script: $script"
}
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
if ($config.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "keep the signer config outside the repository: $config"
}
if (-not $Python) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
if ($IntervalMinutes -lt 5 -or $IntervalMinutes -gt 1440) {
    throw "IntervalMinutes must be between 5 and 1440"
}

$action = New-ScheduledTaskAction -Execute $Python `
    -Argument ('"{0}" --config "{1}"' -f $script, $config) `
    -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "ROSY D-440: sign CI-built site candidates (manifest-only) after provenance and main checks" |
    Out-Null

Write-Host "Registered scheduled task '$TaskName' (every $IntervalMinutes min, current user, while logged on)."
Write-Host "Exit codes in 'Last Run Result': 0 nothing to do, 10 (0xA) signed, 20 (0x14) refused or error, 2 config/lock."
Write-Host "Audit log: <state_dir>\audit.jsonl from the config."
Write-Host "Pause:  Disable-ScheduledTask -TaskName $TaskName"
Write-Host "Remove: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
