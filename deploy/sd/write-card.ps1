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
    [string]$LogPath
)
# Operator entry point: write one reviewed plan to its card (D-173).
#
# Everything is derived from the reviewed plan and the signed release directory,
# so an attempt cannot drift from what was reviewed. The card is found by the
# plan's serial, not by the Windows disk number (it changes as USB devices come
# and go). The script elevates itself, and every attempt keeps its own log and
# exit marker. The operator types the ERASE confirmation in the elevated window.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

$PlanPath = (Resolve-Path -LiteralPath $PlanPath).ProviderPath
$ReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir).ProviderPath
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

if (-not $LogPath) {
    $stamp = Get-Date -Format "yyyyMMddTHHmmss"
    $LogPath = Join-Path $EvidenceDir "write-$releaseId-$deviceName-$stamp.log"
}
$exitMarker = "$LogPath.exit"

if ($PrintArguments) {
    [ordered]@{ arguments = $arguments; log = $LogPath; exit_marker = $exitMarker } | ConvertTo-Json -Depth 4
    exit 0
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    # Re-run elevated with the same inputs and a fixed log path, then report.
    $forward = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"",
        "-PlanPath", "`"$PlanPath`"", "-ReleaseDir", "`"$ReleaseDir`"", "-WifiProfile", $WifiProfile,
        "-EvidenceDir", "`"$EvidenceDir`"", "-RpiImager", "`"$RpiImager`"", "-PythonExe", "`"$PythonExe`"",
        "-LogPath", "`"$LogPath`"")
    if ($OperatorPublicKey) { $forward += @("-OperatorPublicKey", "`"$($arguments.OperatorPublicKey)`"") }
    if ($ReprovisionReceipt) { $forward += @("-ReprovisionReceipt", "`"$($arguments.ReprovisionReceipt)`"") }
    if ($Confirmation) { $forward += @("-Confirmation", "`"$Confirmation`"") }
    Write-Output "Requesting administrator rights; approve the UAC prompt. Log: $LogPath"
    Start-Process powershell -Verb RunAs -Wait -ArgumentList $forward
    if (-not (Test-Path -LiteralPath $exitMarker)) { Fail "the elevated write did not finish; see $LogPath" }
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
