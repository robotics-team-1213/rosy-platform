[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Receipt,
    [Parameter(Mandatory = $true)][string]$ReleaseDir,
    [string]$PythonExe = "python",
    [double]$ReadbackStallMinutes = 5,
    [string]$DiskInventoryJson,
    [string]$ReadbackDevice
)
# D-385 follow-up for an emergency card write: the full readback that
# write-card.ps1 -Emergency skipped, run later on the same card. Read-only on
# the card. The card must not have booted yet: first boot changes the root
# filesystem and consumes the bundle, so a booted card cannot match its image.
#
# The boot partition may hold what the writer added after the image
# (rosy-provision/ and rosy-config.yaml); everything else is compared exactly as
# in the standard readback. A verified card gets a supplementary receipt,
# <receipt>.readback.json, next to the original; the original is never changed.
#
# -DiskInventoryJson and -ReadbackDevice are test fixtures, accepted only together.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message, [string]$Next) {
    if ($Next) { $Message = "$Message`nnext: $Next" }
    throw $Message
}

if ($ReadbackDevice -and -not $DiskInventoryJson) { Fail "-ReadbackDevice is a test fixture option and is refused for a real disk" }
if ($DiskInventoryJson -and -not $ReadbackDevice) { Fail "-DiskInventoryJson is a test fixture option and needs -ReadbackDevice" }
if ($ReadbackDevice -match '^\\\\[.?]\\') { Fail "-ReadbackDevice must be a file stand-in, not a device path" }

$Receipt = (Resolve-Path -LiteralPath $Receipt).ProviderPath
$record = Get-Content -LiteralPath $Receipt -Raw | ConvertFrom-Json
$keys = @($record.PSObject.Properties.Name)
foreach ($key in @("device_uid", "device_name", "release_id", "image_sha256", "disk_serial", "disk_size", "media_readback")) {
    if ($keys -cnotcontains $key) { Fail "the receipt has no $key" }
}
if ($keys -cnotcontains "emergency" -or $null -eq $record.emergency) {
    Fail "the receipt is not from an emergency write; its card was already read back when it was written"
}
if ($record.media_readback.verified -isnot [bool] -or $record.media_readback.verified) {
    Fail "the receipt's media_readback is not an unverified emergency record"
}
$supplement = [IO.Path]::ChangeExtension($Receipt, ".readback.json")
if (Test-Path -LiteralPath $supplement) { Fail "a supplementary readback receipt already exists and will not be overwritten: $supplement" }

$releaseId = [string]$record.release_id
$image = Join-Path (Resolve-Path -LiteralPath $ReleaseDir).ProviderPath "rosy-os-pinky-pro-$releaseId-arm64.img.xz"
if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { Fail "the image for release $releaseId is not in $ReleaseDir" }
# The receipt pins the hash that the signed SHA256SUMS vouched for at write time.
$imageHash = (Get-FileHash -LiteralPath $image -Algorithm SHA256).Hash.ToLowerInvariant()
if ($imageHash -cne [string]$record.image_sha256) { Fail "the image in $ReleaseDir is not the one this card was written from" "download release $releaseId again" }

# The card is found by the receipt's serial and size, never by a disk number.
if ($DiskInventoryJson) {
    $disks = @(Get-Content -LiteralPath $DiskInventoryJson -Raw | ConvertFrom-Json)
}
else {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail "reading the card needs administrator rights" "run this from an elevated PowerShell"
    }
    $disks = @(Get-Disk)
}
$serial = [string]$record.disk_serial
$matching = @($disks | Where-Object { [string]$_.SerialNumber -ceq $serial -and [string]$_.BusType -eq "USB" })
if ($matching.Count -ne 1) { Fail "found $($matching.Count) USB disks with serial $serial" "insert the card in the reader it was written with, then re-run" }
$disk = $matching[0]
if ($disk.IsBoot -or $disk.IsSystem) { Fail "disk $($disk.Number) is a boot or system disk" }
if ([int64]$disk.Size -ne [int64]$record.disk_size) { Fail "the disk with serial $serial is $($disk.Size) bytes, the receipt says $($record.disk_size)" "check that this is the card from the receipt" }
$target = $(if ($ReadbackDevice) { $ReadbackDevice } else { "\\.\PhysicalDrive$($disk.Number)" })

$verifier = Join-Path $PSScriptRoot "verify-media-readback.py"
$errorPath = Join-Path ([IO.Path]::GetTempPath()) ("rosy-emergency-readback-" + [guid]::NewGuid().ToString("N") + ".json")
$stall = ($ReadbackStallMinutes * 60).ToString([Globalization.CultureInfo]::InvariantCulture)
Write-Output "Reading back $($record.device_name) ($target) against release $releaseId; this takes as long as a standard readback."
try {
    $output = & $PythonExe $verifier --image $image --device $target --stall-seconds $stall --error-json $errorPath `
        --allow-boot-extra rosy-provision --allow-boot-extra rosy-config.yaml
    $exitCode = $LASTEXITCODE
    $reason = $(if (Test-Path -LiteralPath $errorPath) { [string](Get-Content -LiteralPath $errorPath -Raw | ConvertFrom-Json).error } else { "verifier exit code $exitCode" })
}
finally {
    if (Test-Path -LiteralPath $errorPath) { Remove-Item -LiteralPath $errorPath -Force }
}
if ($exitCode -ne 0) {
    Fail "the emergency card did NOT verify: $reason" "if the card has booted, it cannot match its image: rewrite it with a standard write (-ReprovisionReceipt $Receipt); if it has not, reseat it and re-run, then rewrite it if it fails again"
}
$evidence = ($output | Out-String) | ConvertFrom-Json
if (-not ($evidence.verified -is [bool] -and $evidence.verified) -or [string]$evidence.image_sha256 -cne $imageHash) {
    Fail "the readback evidence is invalid"
}
$result = [ordered]@{
    kind = "emergency-follow-up-readback"
    receipt = $Receipt
    receipt_sha256 = (Get-FileHash -LiteralPath $Receipt -Algorithm SHA256).Hash.ToLowerInvariant()
    device_uid = [string]$record.device_uid
    device_name = [string]$record.device_name
    release_id = $releaseId
    disk_serial = $serial
    readback_target = $target
    fixture = [bool]$DiskInventoryJson
    media_readback = $evidence
    verified_at = [DateTimeOffset]::UtcNow.ToString("o")
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $supplement -Encoding UTF8
Write-Output "VERIFIED: $($record.device_name) matches release $releaseId. Supplementary receipt: $supplement"
exit 0
