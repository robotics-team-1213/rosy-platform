[CmdletBinding()]
param(
    [int]$DiskNumber,
    [int]$RobotNumber,
    [string]$Model = "pinky_pro",
    [string]$Preset = "core",
    [string]$WifiProfile,
    [string]$WifiSsid,
    [string]$ImagePath,
    [string]$ImageSha256,
    [string]$ImageSignaturePath,
    [string]$ReleasePublicKey,
    [string]$ReleaseId,
    [string]$FleetEndpoint,
    [string]$FleetTrustProfile,
    [string]$CountryCode = "KR",
    [string]$DeviceName,
    [string]$DeviceUid,
    [string]$RegistryJson,
    [string]$ReceiptPath,
    [string]$RpiImager = "rpi-imager.exe",
    [string]$ReadbackDevice,
    [string]$PythonExe = "python",
    [string]$DiskInventoryJson,
    [string]$SecondDiskInventoryJson,
    [string]$BootMountPath,
    [string]$Confirmation,
    [switch]$SetWifiCredential,
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

function Get-CredentialPath([string]$Profile) {
    if ($Profile -notmatch '^[A-Za-z0-9_.-]{1,64}$') {
        Fail "Wi-Fi profile name is invalid"
    }
    if (-not $env:LOCALAPPDATA) {
        Fail "LOCALAPPDATA is unavailable"
    }
    Join-Path $env:LOCALAPPDATA "Rosy\credentials\$Profile.credential.xml"
}

function Save-WifiCredential([string]$Profile, [string]$Ssid) {
    if ([string]::IsNullOrWhiteSpace($Ssid)) {
        Fail "-WifiSsid is required with -SetWifiCredential"
    }
    if ([Text.Encoding]::UTF8.GetByteCount($Ssid) -gt 32) {
        Fail "Wi-Fi SSID is too long"
    }
    $credentialPath = Get-CredentialPath $Profile
    $directory = Split-Path -Parent $credentialPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $secureValue = Read-Host -AsSecureString "Wi-Fi passphrase"
    $credential = New-Object System.Management.Automation.PSCredential($Ssid, $secureValue)
    $credential | Export-Clixml -LiteralPath $credentialPath
    Write-Output "Stored operator-local credential profile '$Profile'."
}

function Read-DiskInventory([string]$FixturePath) {
    if ($FixturePath) {
        if (-not (Test-Path -LiteralPath $FixturePath -PathType Leaf)) {
            Fail "disk inventory fixture is missing"
        }
        return @((Get-Content -LiteralPath $FixturePath -Raw | ConvertFrom-Json))
    }
    return @(Get-Disk | Select-Object Number, FriendlyName, SerialNumber, Size, BusType, IsBoot, IsSystem, IsOffline, IsReadOnly)
}

function Select-SafeDisk([object[]]$Inventory, [int]$Number) {
    $matches = @($Inventory | Where-Object { [int]$_.Number -eq $Number })
    if ($matches.Count -ne 1) { Fail "disk number does not resolve to exactly one disk" }
    $disk = $matches[0]
    if ([bool]$disk.IsBoot -or [bool]$disk.IsSystem) { Fail "boot/system disks are forbidden" }
    if ([string]$disk.BusType -ne "USB") { Fail "target disk must use USB bus" }
    if ([bool]$disk.IsOffline) { Fail "target disk is offline" }
    if ([bool]$disk.IsReadOnly) { Fail "target disk is read-only" }
    if ([string]::IsNullOrWhiteSpace([string]$disk.SerialNumber)) { Fail "target disk serial is missing" }
    $minimumSize = 8GB
    $maximumSize = 1TB
    if ([int64]$disk.Size -lt $minimumSize -or [int64]$disk.Size -gt $maximumSize) {
        Fail "target disk size is outside the approved SD range"
    }
    return $disk
}

function Get-DiskFingerprint([object]$Disk) {
    [ordered]@{
        Number = [int]$Disk.Number
        SerialNumber = [string]$Disk.SerialNumber
        Size = [int64]$Disk.Size
        BusType = [string]$Disk.BusType
        IsBoot = [bool]$Disk.IsBoot
        IsSystem = [bool]$Disk.IsSystem
        IsOffline = [bool]$Disk.IsOffline
        IsReadOnly = [bool]$Disk.IsReadOnly
    } | ConvertTo-Json -Compress
}

function Resolve-BootMount([int]$Number, [string]$ExplicitPath, [bool]$FixtureMode) {
    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Container)) {
            Fail "boot mount path is unavailable"
        }
        $resolved = (Resolve-Path -LiteralPath $ExplicitPath).Path
        if (-not $FixtureMode) {
            $qualifier = Split-Path -Qualifier $resolved
            if (-not $qualifier) { Fail "boot mount path must be a mounted volume" }
            $letter = $qualifier.TrimEnd('\').TrimEnd(':')
            $partition = Get-Partition -DriveLetter $letter -ErrorAction Stop
            if ([int]$partition.DiskNumber -ne $Number) {
                Fail "boot mount does not belong to the selected physical disk"
            }
        }
        return $resolved
    }

    Update-HostStorageCache
    foreach ($partition in @(Get-Partition -DiskNumber $Number -ErrorAction Stop)) {
        $volume = Get-Volume -Partition $partition -ErrorAction SilentlyContinue
        if ($null -eq $volume -or [string]$volume.FileSystem -ne "FAT32") { continue }
        if (-not $partition.DriveLetter) {
            $used = @((Get-Volume).DriveLetter | Where-Object { $_ })
            $letter = [char[]]([char]'Z'..[char]'D') | Where-Object { $used -notcontains $_ } | Select-Object -First 1
            if (-not $letter) { Fail "no drive letter is available for the SD boot partition" }
            Add-PartitionAccessPath -DiskNumber $Number -PartitionNumber $partition.PartitionNumber -DriveLetter $letter
        }
        else {
            $letter = $partition.DriveLetter
        }
        return "${letter}:\"
    }
    Fail "the flashed SD boot partition was not found"
}

function New-PinkyIdentity {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $code = "from dataclasses import asdict; from deploy.sd.personalization import generate_device_identity; import json; print(json.dumps(asdict(generate_device_identity('pinky_pro'))))"
    Push-Location $repoRoot
    try {
        $output = & $PythonExe -c $code
        if ($LASTEXITCODE -ne 0) { Fail "device identity generator failed" }
        return ($output | ConvertFrom-Json)
    }
    finally {
        Pop-Location
    }
}

if ($SetWifiCredential) {
    Save-WifiCredential $WifiProfile $WifiSsid
    if (-not $PSBoundParameters.ContainsKey("DiskNumber")) { exit 0 }
}

foreach ($required in @("DiskNumber", "RobotNumber", "WifiProfile", "ImagePath", "ImageSha256", "ImageSignaturePath", "ReleasePublicKey", "ReleaseId", "FleetEndpoint", "FleetTrustProfile", "RegistryJson", "ReceiptPath")) {
    if (-not $PSBoundParameters.ContainsKey($required)) { Fail "-$required is required" }
}
if ($Model -ne "pinky_pro") { Fail "only pinky_pro is supported" }
if ($RobotNumber -lt 1 -or $RobotNumber -gt 61) { Fail "RobotNumber must be between 1 and 61" }
if ($Preset -notin @("core", "motor", "hardware")) { Fail "Preset is invalid" }
if ($ReleaseId -notmatch '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$') { Fail "ReleaseId is invalid" }
if ($FleetEndpoint -notmatch '^https://') { Fail "FleetEndpoint must use HTTPS" }
if ([string]::IsNullOrWhiteSpace($FleetTrustProfile)) { Fail "FleetTrustProfile is required" }

$credentialPath = Get-CredentialPath $WifiProfile
if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) {
    Fail "Wi-Fi credential profile is missing; use -SetWifiCredential first"
}
$wifiCredential = Import-Clixml -LiteralPath $credentialPath
if ($wifiCredential -isnot [System.Management.Automation.PSCredential] -or [string]::IsNullOrWhiteSpace($wifiCredential.UserName)) {
    Fail "Wi-Fi credential profile is invalid"
}

if (-not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) { Fail "image file is missing" }
if ($ImageSha256 -notmatch '^[0-9a-fA-F]{64}$') { Fail "image SHA-256 is invalid" }
$actualHash = (Get-FileHash -LiteralPath $ImagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $ImageSha256.ToLowerInvariant()) { Fail "image SHA-256 does not match" }
if (-not (Test-Path -LiteralPath $ImageSignaturePath -PathType Leaf)) { Fail "image signature is missing" }
if (-not (Test-Path -LiteralPath $ReleasePublicKey -PathType Leaf)) { Fail "trusted release public key is missing" }
if (Test-Path -LiteralPath $ReceiptPath) { Fail "receipt already exists and will not be overwritten" }
if (-not (Test-Path -LiteralPath $RegistryJson -PathType Leaf)) { Fail "identity registry is missing" }
if (-not (Test-Path -LiteralPath $RpiImager -PathType Leaf) -and -not (Get-Command $RpiImager -ErrorAction SilentlyContinue)) {
    Fail "Raspberry Pi Imager CLI is unavailable"
}

$releaseRoot = Split-Path -Parent $ImageSignaturePath
$releaseVerifier = Join-Path $PSScriptRoot "verify-image-release.py"
if (-not (Test-Path -LiteralPath $releaseVerifier -PathType Leaf)) { Fail "signed image release verifier is missing" }
$verification = & $PythonExe $releaseVerifier `
    --release-root $releaseRoot `
    --public-key $ReleasePublicKey `
    --image $ImagePath `
    --release-id $ReleaseId
if ($LASTEXITCODE -ne 0) { Fail "signed image release verification failed" }
$verification = $null

$registry = Get-Content -LiteralPath $RegistryJson -Raw | ConvertFrom-Json
if ($DeviceName -or $DeviceUid) {
    if (-not $DeviceName -or -not $DeviceUid) { Fail "DeviceName and DeviceUid must be supplied together" }
}
else {
    for ($attempt = 0; $attempt -lt 32; $attempt++) {
        $generated = New-PinkyIdentity
        if (@($registry.device_names) -notcontains $generated.device_name) {
            $DeviceName = $generated.device_name
            $DeviceUid = $generated.device_uid
            break
        }
    }
    if (-not $DeviceName) { Fail "could not allocate a unique Pinky device name after 32 attempts" }
}
if ($DeviceName -notmatch '^rosy-pinky-[a-hj-km-np-z2-9]{4}$') { Fail "DeviceName is invalid" }
try { $parsedUid = [guid]$DeviceUid } catch { Fail "DeviceUid is invalid" }
if (@($registry.robot_numbers) -contains $RobotNumber) { Fail "robot number is already registered" }
if (@($registry.device_names) -contains $DeviceName) { Fail "device name is already registered" }
if (@($registry.device_uids) -contains $DeviceUid) { Fail "device UID is already registered" }

$firstDisk = Select-SafeDisk (Read-DiskInventory $DiskInventoryJson) $DiskNumber
$physicalDrive = "\\.\PhysicalDrive$DiskNumber"
$plan = [ordered]@{
    mode = $(if ($PlanOnly) { "PLAN_ONLY" } else { "WRITE" })
    physical_drive = $physicalDrive
    disk_number = [int]$firstDisk.Number
    disk_model = [string]$firstDisk.FriendlyName
    disk_serial = [string]$firstDisk.SerialNumber
    disk_size = [int64]$firstDisk.Size
    device_uid = $DeviceUid
    device_name = $DeviceName
    robot_number = $RobotNumber
    ros_domain_id = 40 + $RobotNumber
    namespace = "rosy_{0:d2}" -f $RobotNumber
    release_id = $ReleaseId
    image_sha256 = $actualHash
    wifi_ssid = $wifiCredential.UserName
    fleet_endpoint = $FleetEndpoint
}

$secondSource = $(if ($SecondDiskInventoryJson) { $SecondDiskInventoryJson } else { $DiskInventoryJson })
$secondDisk = Select-SafeDisk (Read-DiskInventory $secondSource) $DiskNumber
if ((Get-DiskFingerprint $firstDisk) -ne (Get-DiskFingerprint $secondDisk)) {
    Fail "target disk changed between safety probes"
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Compress
    exit 0
}

$expectedConfirmation = "ERASE DISK $DiskNumber $DeviceName"
if (-not $Confirmation) { $Confirmation = Read-Host "Type exactly: $expectedConfirmation" }
if ($Confirmation -cne $expectedConfirmation) { Fail "confirmation did not match the selected physical disk and device" }

# Probe a third time immediately before the destructive call when live disk
# discovery is used. Fixture mode already supplied the explicit second probe.
if (-not $DiskInventoryJson) {
    $writeDisk = Select-SafeDisk (Read-DiskInventory "") $DiskNumber
    if ((Get-DiskFingerprint $firstDisk) -ne (Get-DiskFingerprint $writeDisk)) {
        Fail "target disk changed immediately before write"
    }
}

& $RpiImager --cli --sha256 $ImageSha256 $ImagePath $physicalDrive
$writerExitCode = $LASTEXITCODE
if ($writerExitCode -ne 0) { Fail "image writer failed with exit code $writerExitCode" }

$readbackVerifier = Join-Path $PSScriptRoot "verify-media-readback.py"
if (-not (Test-Path -LiteralPath $readbackVerifier -PathType Leaf)) { Fail "media readback verifier is missing" }
$readbackTarget = $(if ($ReadbackDevice) { $ReadbackDevice } else { $physicalDrive })
$mediaReadbackOutput = & $PythonExe $readbackVerifier --image $ImagePath --device $readbackTarget
if ($LASTEXITCODE -ne 0) { Fail "full media readback verification failed" }
try {
    $mediaReadback = $mediaReadbackOutput | ConvertFrom-Json
}
catch {
    Fail "media readback evidence is invalid"
}
if (-not [bool]$mediaReadback.verified) { Fail "full media readback was not verified" }

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$bundleTool = Join-Path $PSScriptRoot "create-provision-bundle.py"
if (-not (Test-Path -LiteralPath $bundleTool -PathType Leaf)) { Fail "bundle creator is missing" }
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("rosy-provision-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
$bundleTemp = Join-Path $temporaryRoot "provision.json"
$bundleReceiptTemp = Join-Path $temporaryRoot "receipt.json"
$bundleReceipt = $null
try {
    $networkValue = $wifiCredential.GetNetworkCredential().Password
    try {
        $bundleRequest = [ordered]@{
            device_uid = $DeviceUid
            device_name = $DeviceName
            model = $Model
            release_id = $ReleaseId
            robot_number = $RobotNumber
            requested_preset = $Preset
            country_code = $CountryCode
            ssid = $wifiCredential.UserName
            wifi_passphrase = $networkValue
            fleet_endpoint = $FleetEndpoint
            fleet_trust_profile = $FleetTrustProfile
            pairing_required = $false
        }
        $previousOutputEncoding = $OutputEncoding
        $previousPythonUtf8 = $env:PYTHONUTF8
        try {
            $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
            $env:PYTHONUTF8 = "1"
            $bundleRequest | ConvertTo-Json -Compress | & $PythonExe $bundleTool --output $bundleTemp --receipt $bundleReceiptTemp
            if ($LASTEXITCODE -ne 0) { Fail "provisioning bundle creation failed" }
        }
        finally {
            $OutputEncoding = $previousOutputEncoding
            $env:PYTHONUTF8 = $previousPythonUtf8
        }
    }
    finally {
        $networkValue = $null
        $bundleRequest = $null
    }

    $bootRoot = Resolve-BootMount $DiskNumber $BootMountPath ([bool]$DiskInventoryJson)
    $bundleDirectory = Join-Path $bootRoot "rosy-provision"
    New-Item -ItemType Directory -Path $bundleDirectory -Force | Out-Null
    $bundleTarget = Join-Path $bundleDirectory "provision.json"
    if (Test-Path -LiteralPath $bundleTarget) { Fail "provisioning bundle already exists on the card" }
    $bundleTargetTemp = Join-Path $bundleDirectory ".provision.json.tmp"
    Copy-Item -LiteralPath $bundleTemp -Destination $bundleTargetTemp
    Move-Item -LiteralPath $bundleTargetTemp -Destination $bundleTarget
    $bundleReceipt = Get-Content -LiteralPath $bundleReceiptTemp -Raw | ConvertFrom-Json
}
finally {
    foreach ($temporaryFile in @($bundleTemp, $bundleReceiptTemp)) {
        if (Test-Path -LiteralPath $temporaryFile) { Remove-Item -LiteralPath $temporaryFile -Force }
    }
    if (Test-Path -LiteralPath $temporaryRoot) { Remove-Item -LiteralPath $temporaryRoot -Force }
}

$registry.robot_numbers = @(@($registry.robot_numbers) + $RobotNumber | Sort-Object -Unique)
$registry.device_names = @(@($registry.device_names) + $DeviceName | Sort-Object -Unique)
$registry.device_uids = @(@($registry.device_uids) + $DeviceUid | Sort-Object -Unique)
$registryTemp = "$RegistryJson.tmp-$([guid]::NewGuid().ToString('N'))"
$registry | ConvertTo-Json | Set-Content -LiteralPath $registryTemp -Encoding UTF8
Move-Item -LiteralPath $registryTemp -Destination $RegistryJson -Force

$receipt = [ordered]@{
    device_uid = $DeviceUid
    device_name = $DeviceName
    robot_number = $RobotNumber
    release_id = $ReleaseId
    disk_serial = [string]$firstDisk.SerialNumber
    disk_size = [int64]$firstDisk.Size
    image_sha256 = $actualHash
    writer = [IO.Path]::GetFileName($RpiImager)
    writer_exit_code = $writerExitCode
    media_readback = $mediaReadback
    personalization = $bundleReceipt
    created_at = [DateTimeOffset]::UtcNow.ToString("o")
}
$receipt | ConvertTo-Json | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Compress
