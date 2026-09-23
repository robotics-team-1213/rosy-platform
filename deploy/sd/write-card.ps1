[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [Parameter(Mandatory = $true)][string]$WifiProfile,
    [string]$OperatorPublicKey,
    [string]$ReprovisionReceipt,
    [string]$EvidenceDir,
    [string]$RpiImager = "C:\Program Files\Raspberry Pi Ltd\Imager\rpi-imager.exe",
    [string]$PythonExe = "python",
    [string]$Confirmation,
    [switch]$PrintArguments,
    [string]$LogPath,
    [switch]$ResumeAfterWrite,
    [double]$WriterStallMinutes = 5,
    [double]$ReadbackStallMinutes = 5,
    [double]$MinReadMBps = 10,
    [double]$AssumedWriteMBps = 0,
    [switch]$AcceptSlowMedia,
    [switch]$Detach,
    [string]$ElevationLauncher
)
# Operator entry point: write one reviewed plan to its card (D-173).
#
# Everything is derived from the reviewed plan and the signed release directory,
# so an attempt cannot drift from what was reviewed. The card is found by the
# plan's serial, not by the Windows disk number (it changes as USB devices come
# and go). The script elevates itself, and every attempt keeps its own log and
# exit marker. The operator types the ERASE confirmation in the elevated window.
#
# D-181: each attempt also appends one JSON line per stage (and a heartbeat about
# every 60 s while writing and reading back) to <log>.progress.jsonl, and every
# failure names the card state and the next step. -ResumeAfterWrite skips the
# Imager write and re-runs the authoritative readback, bundle, receipt and registry.
#
# D-182: -Detach (the operator default) starts the elevated write in its own
# window with one UAC prompt and returns at once, printing the log, progress and
# status-command paths; the write survives this console or agent session closing.
# card-write-status.ps1 -LogPath <log> reads the progress file without elevation.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

$PlanPath = (Resolve-Path -LiteralPath $PlanPath).ProviderPath
$ReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir).ProviderPath
# D-182 review: the elevated window starts in C:\Windows\System32, so a relative
# path would split the progress file and lose the exit marker. Paths are made
# absolute against this console's location (PowerShell's, which
# [IO.Path]::GetFullPath does not follow). The writer is always a file path; a
# bare Python name stays a PATH lookup.
function ConvertTo-FullPath([string]$Path) {
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}
if ($LogPath) { $LogPath = ConvertTo-FullPath $LogPath }
$RpiImager = ConvertTo-FullPath $RpiImager
if ($PythonExe -match '[\\/]') { $PythonExe = ConvertTo-FullPath $PythonExe }
if (-not $EvidenceDir) { $EvidenceDir = Split-Path -Parent $PlanPath }
$EvidenceDir = (Resolve-Path -LiteralPath $EvidenceDir).ProviderPath

$plan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
if ([string]$plan.mode -cne "PLAN_ONLY") { Fail "the plan must be a PLAN_ONLY plan from prepare-rosy-sd.ps1 -PlanOnly -PlanPath" }
$releaseId = [string]$plan.release_id
$deviceName = [string]$plan.device_name
$image = Join-Path $ReleaseDir "rosy-os-pinky-pro-$releaseId-arm64.img.xz"
if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { Fail "the image for release $releaseId is not in $ReleaseDir" }
$receipt = Join-Path $EvidenceDir "receipt-$releaseId-$deviceName.json"
if (Test-Path -LiteralPath $receipt) { Fail "receipt already exists and will not be overwritten: $receipt" }

$arguments = [ordered]@{
    DiskSerial = [string]$plan.disk_serial
    WifiProfile = $WifiProfile
    ImagePath = $image
    ImageSha256 = [string]$plan.image_sha256
    ImageSignaturePath = Join-Path $ReleaseDir "SHA256SUMS.sig"
    ReleasePublicKey = Join-Path $PSScriptRoot "..\release\public-keys\rosy-release-2026-01.pem"
    ReleaseId = $releaseId
    RegistryJson = [string]$plan.registry_path
    ReceiptPath = $receipt
    RpiImager = $RpiImager
    PythonExe = $PythonExe
    PlanPath = $PlanPath
}
$arguments.ReleasePublicKey = (Resolve-Path -LiteralPath $arguments.ReleasePublicKey).ProviderPath
if ($OperatorPublicKey) { $arguments.OperatorPublicKey = (Resolve-Path -LiteralPath $OperatorPublicKey).ProviderPath }
if ($ReprovisionReceipt) { $arguments.ReprovisionReceipt = (Resolve-Path -LiteralPath $ReprovisionReceipt).ProviderPath }
if ($Confirmation) { $arguments.Confirmation = $Confirmation }
if ($ResumeAfterWrite) { $arguments.ResumeAfterWrite = $true }
$arguments.WriterStallMinutes = $WriterStallMinutes
$arguments.ReadbackStallMinutes = $ReadbackStallMinutes
$arguments.MinReadMBps = $MinReadMBps
if ($AssumedWriteMBps -gt 0) { $arguments.AssumedWriteMBps = $AssumedWriteMBps }
if ($AcceptSlowMedia) { $arguments.AcceptSlowMedia = $true }

if (-not $LogPath) {
    $stamp = Get-Date -Format "yyyyMMddTHHmmss"
    $LogPath = Join-Path $EvidenceDir "write-$releaseId-$deviceName-$stamp.log"
}
$exitMarker = "$LogPath.exit"
$progressPath = "$LogPath.progress.jsonl"
$arguments.ProgressPath = $progressPath
$statusScript = Join-Path $PSScriptRoot "card-write-status.ps1"
$statusCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$statusScript`" -LogPath `"$LogPath`""

if ($PrintArguments) {
    [ordered]@{ arguments = $arguments; log = $LogPath; exit_marker = $exitMarker; progress = $progressPath; status = $statusCommand } | ConvertTo-Json -Depth 4
    exit 0
}

function Get-LastProgress {
    if (-not (Test-Path -LiteralPath $progressPath -PathType Leaf)) { return $null }
    try { return (Get-Content -LiteralPath $progressPath -Tail 1 | ConvertFrom-Json) } catch { return $null }
}

# Same line format as prepare-rosy-sd.ps1 (D-181), flushed at once.
function Add-ProgressLine([string]$Stage, [string]$CardState, [string]$Detail, [string]$Next) {
    $line = [ordered]@{ ts = [DateTime]::UtcNow.ToString("o"); stage = $Stage; card_state = $CardState }
    if ($Detail) { $line["detail"] = $Detail }
    if ($Next) { $line["next"] = $Next }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($line | ConvertTo-Json -Compress) + "`n")
    $stream = New-Object IO.FileStream($progressPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

$invariant = [Globalization.CultureInfo]::InvariantCulture
# Re-run with the same inputs and a fixed log path.
$forward = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
    "-PlanPath", "`"$PlanPath`"", "-ReleaseDir", "`"$ReleaseDir`"", "-WifiProfile", $WifiProfile,
    "-EvidenceDir", "`"$EvidenceDir`"", "-RpiImager", "`"$RpiImager`"", "-PythonExe", "`"$PythonExe`"",
    "-LogPath", "`"$LogPath`"")
if ($OperatorPublicKey) { $forward += @("-OperatorPublicKey", "`"$($arguments.OperatorPublicKey)`"") }
if ($ReprovisionReceipt) { $forward += @("-ReprovisionReceipt", "`"$($arguments.ReprovisionReceipt)`"") }
if ($Confirmation) { $forward += @("-Confirmation", "`"$Confirmation`"") }
if ($ResumeAfterWrite) { $forward += "-ResumeAfterWrite" }
$forward += @("-WriterStallMinutes", $WriterStallMinutes.ToString($invariant))
$forward += @("-ReadbackStallMinutes", $ReadbackStallMinutes.ToString($invariant))
$forward += @("-MinReadMBps", $MinReadMBps.ToString($invariant))
if ($AssumedWriteMBps -gt 0) { $forward += @("-AssumedWriteMBps", $AssumedWriteMBps.ToString($invariant)) }
if ($AcceptSlowMedia) { $forward += "-AcceptSlowMedia" }

# -ElevationLauncher is a test seam standing in for Start-Process: UAC cannot be
# driven from a test, so a fixture script receives the same arguments.
function Start-WriteWindow([string[]]$ArgumentList, [bool]$Elevate, [bool]$Wait) {
    if ($ElevationLauncher) {
        & $ElevationLauncher -ArgumentList $ArgumentList -Elevate:$Elevate -Wait:$Wait
        return
    }
    if ($Elevate -and $Wait) { Start-Process powershell -Verb RunAs -Wait -ArgumentList $ArgumentList }
    elseif ($Elevate) { Start-Process powershell -Verb RunAs -ArgumentList $ArgumentList }
    else { Start-Process powershell -ArgumentList $ArgumentList }
}

function Invoke-WriteWindow([string[]]$ArgumentList, [bool]$Elevate, [bool]$Wait) {
    # The launcher creates the progress file, so it belongs to the operator and
    # the status command reads it without elevation.
    Add-ProgressLine "launch" "untouched" $(if ($Elevate) { "waiting for UAC approval and the elevated write window" } else { "starting the write window" }) ""
    try {
        Start-WriteWindow $ArgumentList $Elevate $Wait
    }
    catch {
        $uacNext = "re-run and approve the UAC prompt (nothing was written to the card)"
        Add-ProgressLine "failed" "untouched" ("launch: administrator rights were not granted (UAC prompt declined or timed out): " + $_.Exception.Message) $uacNext
        Fail ("administrator rights were not granted (UAC prompt declined or timed out): {0}`ncard_state=untouched`nnext: {1}" -f $_.Exception.Message, $uacNext)
    }
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdministrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($Detach) {
    # One visible window runs the whole write and stays open with its result;
    # this console, or the agent session that ran it, may close at once.
    Invoke-WriteWindow (@("-NoExit") + $forward) (-not $isAdministrator) $false
    Write-Output "The card write runs in its own window; this console can be closed."
    Write-Output "Log: $LogPath"
    Write-Output "Progress: $progressPath"
    Write-Output "Exit marker: $exitMarker"
    Write-Output "Status: $statusCommand"
    exit 0
}

if (-not $isAdministrator) {
    Write-Output "Requesting administrator rights; approve the UAC prompt. Log: $LogPath"
    Write-Output "Progress: $progressPath (one JSON line per stage, a heartbeat about every 60 s while writing and reading back)"
    Write-Output "Status: $statusCommand"
    Invoke-WriteWindow $forward $true $true
    if (-not (Test-Path -LiteralPath $exitMarker)) {
        $last = Get-LastProgress
        $where = $(if ($last) { "last stage=$($last.stage) card_state=$($last.card_state)" } else { "no stage was recorded, so the card is untouched" })
        Fail ("the elevated write did not finish ({0}); see $LogPath`nnext: if card_state is written-unverified or verified-no-bundle, re-run with -ResumeAfterWrite; if it is untouched, re-run; otherwise re-run the full write" -f $where)
    }
    $code = [int]((Get-Content -LiteralPath $exitMarker -Raw).Trim())
    Get-Content -LiteralPath $LogPath -Tail 20
    exit $code
}

# Elevated: the release signature verifier needs openssl; Git for Windows ships one.
if (-not (Get-Command openssl -ErrorAction SilentlyContinue)) {
    $gitOpenSsl = "C:\Program Files\Git\usr\bin"
    if (Test-Path -LiteralPath (Join-Path $gitOpenSsl "openssl.exe")) { $env:PATH = "$gitOpenSsl;$env:PATH" }
}

Start-Transcript -LiteralPath $LogPath | Out-Null
Write-Output "Progress: $progressPath"
Write-Output "Status: $statusCommand"
$code = 1
try {
    & (Join-Path $PSScriptRoot "prepare-rosy-sd.ps1") @arguments
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
}
catch {
    Write-Output "WRITE FAILED: $_"
    $code = 1
}
finally {
    Write-Output "EXIT_CODE=$code"
    Stop-Transcript | Out-Null
    Set-Content -LiteralPath $exitMarker -Value $code -Encoding ASCII
}
exit $code
