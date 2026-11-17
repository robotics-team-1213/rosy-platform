<#
.SYNOPSIS
Registers the D-1038 scheduled merge of the open publish/main-* PR as a Windows scheduled task.

.DESCRIPTION
Runs `python tools/publish_main.py --merge-when-green auto --apply` in the main checkout every IntervalMinutes
as the current user, only while logged on (gh keeps its token in the user's credential store). Every check of
`--merge-when-green` is unchanged: mergeable, ci-result SUCCESS, a green FULL record at the PR head, and
`--match-head-commit`. Exit 5 (not ready) and 0 (no PR) are normal; exit 7 means several publish PRs are open.
The task never closes, reopens or force-pushes. Register it yourself; this repository does not.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File tools\register_publish_merge_task.ps1 -MainCheckout D:\Dev\Robot\Rosy\rosy-platform

Remove it again:
  Unregister-ScheduledTask -TaskName RosyPublishMerge -Confirm:$false
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MainCheckout,
    [string]$TaskName = "RosyPublishMerge",
    [int]$IntervalMinutes = 15,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $MainCheckout).Path
$script = Join-Path $root "tools\publish_main.py"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "tools\publish_main.py not found under: $root"
}
if (-not $Python) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
if ($IntervalMinutes -lt 5 -or $IntervalMinutes -gt 1440) {
    throw "IntervalMinutes must be between 5 and 1440"
}

$action = New-ScheduledTaskAction -Execute $Python `
    -Argument ('"{0}" --merge-when-green auto --apply' -f $script) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "ROSY D-1038: merge the single open publish/main-* PR once its existing checks are green" | Out-Null

Write-Host "Registered scheduled task '$TaskName' (every $IntervalMinutes min, current user, while logged on)."
Write-Host "Last Run Result: 0 merged or no PR, 5 not ready yet, 6 sync needed, 7 several PRs, 1 refusal."
