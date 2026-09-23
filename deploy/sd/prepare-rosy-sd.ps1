[CmdletBinding()]
param(
    [int]$DiskNumber,
    [string]$DiskSerial,
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
    [string]$PlanPath,
    [string]$OperatorPublicKey,
    [string]$ReprovisionReceipt,
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

# Some USB card readers intermittently report an empty Get-Disk SerialNumber
# (release 005: the same reader showed 000000000207, then blank after a replug)
# while the USB mass-storage instance ID still carries the device serial:
# USBSTOR\DISK&VEN_..&PROD_..&REV_..\<serial>&<n>. Use that only when it is a
# real serial; Windows invents "<digit>&<hash>&<n>" IDs for devices without one.
function Get-UsbInstanceSerial([string]$UniqueId) {
    if ($UniqueId -notmatch '^USBSTOR\\[^\\]+\\([^&\\]+)&') { return "" }
    $candidate = $Matches[1]
    if ($candidate.Length -lt 4) { return "" }
    return $candidate
}

function Complete-DiskSerial([object]$Disk) {
    if ($null -eq $Disk -or -not $Disk.PSObject.Properties["SerialNumber"]) { return $Disk }
    if (-not [string]::IsNullOrWhiteSpace([string]$Disk.SerialNumber)) { return $Disk }
    if ([string]$Disk.BusType -ne "USB" -or -not $Disk.PSObject.Properties["UniqueId"]) { return $Disk }
    $fallback = Get-UsbInstanceSerial ([string]$Disk.UniqueId)
    if ($fallback) { $Disk.SerialNumber = $fallback }
    return $Disk
}

function Read-DiskInventory([string]$FixturePath) {
    if ($FixturePath) {
        if (-not (Test-Path -LiteralPath $FixturePath -PathType Leaf)) {
            Fail "disk inventory fixture is missing"
        }
        return @((Get-Content -LiteralPath $FixturePath -Raw | ConvertFrom-Json) | ForEach-Object { Complete-DiskSerial $_ })
    }
    return @(Get-Disk | Select-Object Number, FriendlyName, SerialNumber, UniqueId, Size, BusType, IsBoot, IsSystem, IsOffline, IsReadOnly |
        ForEach-Object { Complete-DiskSerial $_ })
}

# Windows renumbers disks as USB devices come and go (release 004: the card moved
# from disk 2 to disk 1 between plan and write). The card is identified by its
# serial; the number is resolved from it right before each probe.
function Resolve-DiskNumberBySerial([object[]]$Inventory, [string]$Serial) {
    $wanted = $Serial.Trim()
    # StrictMode: an empty inventory can yield a property-less object, so read
    # the properties defensively.
    $matches = @($Inventory | Where-Object {
        $null -ne $_ -and $_.PSObject.Properties["BusType"] -and $_.PSObject.Properties["SerialNumber"] -and
        [string]$_.BusType -eq "USB" -and ([string]$_.SerialNumber).Trim() -ceq $wanted
    })
    if ($matches.Count -eq 0) { Fail "no USB disk has serial $wanted" }
    if ($matches.Count -gt 1) { Fail "more than one USB disk has serial $wanted" }
    return [int]$matches[0].Number
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

# D-176: each card's fallback AP gets its own random password. It is kept in the
# operator's DPAPI store (reused when the same device is rewritten) and shown
# once; plans and receipts never hold it.
function Get-ApPassword([string]$Device) {
    if (-not $env:LOCALAPPDATA) { Fail "LOCALAPPDATA is unavailable" }
    $store = Join-Path $env:LOCALAPPDATA "Rosy\ap"
    $file = Join-Path $store "$Device.credential.xml"
    if (Test-Path -LiteralPath $file -PathType Leaf) {
        return (Import-Clixml -LiteralPath $file).GetNetworkCredential().Password
    }
    $alphabet = "abcdefghjkmnpqrstuvwxyz" + "ABCDEFGHJKLMNPQRSTUVWXYZ" + "23456789"
    $bytes = New-Object byte[] 14
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
    New-Item -ItemType Directory -Path $store -Force | Out-Null
    $secure = ConvertTo-SecureString $password -AsPlainText -Force
    New-Object System.Management.Automation.PSCredential($Device, $secure) | Export-Clixml -LiteralPath $file
    return $password
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

foreach ($required in @("WifiProfile", "ImagePath", "ImageSha256", "ImageSignaturePath", "ReleasePublicKey", "ReleaseId", "RegistryJson", "ReceiptPath")) {
    if (-not $PSBoundParameters.ContainsKey($required)) { Fail "-$required is required" }
}

# A write may pin its identity to a plan the operator already reviewed, so the
# card receives exactly the robot number, name and Fleet values that were shown.
$reviewedPlan = $null
$robotNumberSource = $(if ($PSBoundParameters.ContainsKey("RobotNumber")) { "operator" } else { "auto" })

# D-174 F7: rewriting a card for an already registered robot is allowed only with
# the receipt of a verified earlier write of exactly that identity.
$reprovision = $null
if ($ReprovisionReceipt) {
    if (-not (Test-Path -LiteralPath $ReprovisionReceipt -PathType Leaf)) { Fail "reprovision receipt is missing" }
    try {
        $reprovision = Get-Content -LiteralPath $ReprovisionReceipt -Raw | ConvertFrom-Json
    }
    catch {
        Fail "reprovision receipt is not valid JSON"
    }
    $receiptKeys = @($reprovision.PSObject.Properties.Name)
    foreach ($key in @("device_uid", "device_name", "robot_number", "release_id", "image_sha256", "writer_exit_code", "media_readback", "created_at")) {
        if ($receiptKeys -cnotcontains $key) { Fail "reprovision receipt has no $key" }
    }
    # Typed checks: in PowerShell 5.1 [bool]"false" is True and [int]$null is 0.
    $exitCode = $reprovision.writer_exit_code
    $verified = $reprovision.media_readback.verified
    if (-not ($exitCode -is [int] -or $exitCode -is [long]) -or $exitCode -ne 0 -or -not ($verified -is [bool]) -or -not $verified) {
        Fail "reprovision receipt does not prove a verified earlier write"
    }
    $fromReceipt = [ordered]@{ RobotNumber = "robot_number"; DeviceName = "device_name"; DeviceUid = "device_uid" }
    foreach ($name in $fromReceipt.Keys) {
        $recorded = $reprovision.($fromReceipt[$name])
        if ($PSBoundParameters.ContainsKey($name) -and [string](Get-Variable -Name $name -ValueOnly) -cne [string]$recorded) {
            Fail "-$name does not match the reprovision receipt"
        }
        Set-Variable -Name $name -Value $recorded
    }
    $robotNumberSource = "reprovision"
}
$fleetSource = "operator"
if ($PlanPath -and $PlanOnly -and (Test-Path -LiteralPath $PlanPath)) {
    Fail "plan already exists and will not be overwritten"
}
if ($PlanPath -and -not $PlanOnly) {
    if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) { Fail "reviewed plan is missing" }
    try {
        $reviewedPlan = Get-Content -LiteralPath $PlanPath -Raw | ConvertFrom-Json
    }
    catch {
        Fail "reviewed plan is not valid JSON"
    }
    $planKeys = @($reviewedPlan.PSObject.Properties.Name)
    foreach ($key in @("mode", "robot_number_source", "fleet_source", "registry_path")) {
        if ($planKeys -cnotcontains $key) { Fail "reviewed plan has no $key" }
    }
    if ([string]$reviewedPlan.mode -cne "PLAN_ONLY") { Fail "reviewed plan is not a PLAN_ONLY plan" }
    $pinned = [ordered]@{
        RobotNumber = "robot_number"
        DeviceName = "device_name"
        DeviceUid = "device_uid"
        FleetEndpoint = "fleet_endpoint"
        FleetTrustProfile = "fleet_trust_profile"
        Model = "model"
        Preset = "requested_preset"
        CountryCode = "country_code"
    }
    foreach ($name in $pinned.Keys) {
        $key = $pinned[$name]
        if ($planKeys -cnotcontains $key -or [string]::IsNullOrWhiteSpace([string]$reviewedPlan.$key)) {
            Fail "reviewed plan has no $key"
        }
        $planned = $reviewedPlan.$key
        # Values on the card are case-sensitive; an argument that differs only in
        # case is a different value, and the plan value always wins.
        if ($PSBoundParameters.ContainsKey($name) -and [string](Get-Variable -Name $name -ValueOnly) -cne [string]$planned) {
            Fail "-$name contradicts the reviewed plan"
        }
        Set-Variable -Name $name -Value $planned
    }
    $robotNumberSource = [string]$reviewedPlan.robot_number_source
    $fleetSource = [string]$reviewedPlan.fleet_source
}
elseif (-not $PlanOnly -and $robotNumberSource -eq "auto") {
    # A number drawn inside a write would never be shown before the erase.
    Fail "an automatic robot number needs a reviewed plan: run -PlanOnly -PlanPath first, then write with -PlanPath"
}

# Fleet values are only recorded on the robot until a central Fleet server
# exists; default them to this console host rather than inventing a site URL.
if (-not $FleetEndpoint -and -not $FleetTrustProfile) {
    $consoleHost = ([string]$env:COMPUTERNAME).ToLowerInvariant()
    if ($consoleHost -notmatch '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$') {
        Fail "console host name cannot form a default Fleet endpoint; pass -FleetEndpoint"
    }
    $FleetEndpoint = "https://$consoleHost.local"
    $FleetTrustProfile = "rosy-pilot-lan"
    $fleetSource = "default"
}
elseif (-not $FleetEndpoint -or -not $FleetTrustProfile) {
    Fail "FleetEndpoint and FleetTrustProfile must be supplied together"
}

if ($reviewedPlan -and -not $DiskSerial -and -not $PSBoundParameters.ContainsKey("DiskNumber")) {
    $DiskSerial = [string]$reviewedPlan.disk_serial
}
if (-not $DiskSerial -and -not $PSBoundParameters.ContainsKey("DiskNumber")) {
    Fail "-DiskSerial (or -DiskNumber) is required"
}
if ($Model -ne "pinky_pro") { Fail "only pinky_pro is supported" }
if ($PSBoundParameters.ContainsKey("RobotNumber") -and ($RobotNumber -lt 1 -or $RobotNumber -gt 61)) {
    Fail "RobotNumber must be between 1 and 61"
}
if ($Preset -notin @("core", "motor", "hardware")) { Fail "Preset is invalid" }
if ($CountryCode -cnotmatch '^[A-Z]{2}$') { Fail "CountryCode must be two uppercase letters" }
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

# D-174 F3: an optional operator public key opens a key-only `rosy` login on the
# card. Only the key file's public line is read; the plan records its fingerprint.
$operatorKey = $null
$operatorFingerprint = ""
if ($OperatorPublicKey) {
    if (-not (Test-Path -LiteralPath $OperatorPublicKey -PathType Leaf)) { Fail "operator public key file is missing" }
    $operatorLines = @(Get-Content -LiteralPath $OperatorPublicKey | Where-Object { $_.Trim() })
    if ($operatorLines.Count -ne 1) { Fail "operator public key file must hold exactly one key" }
    $operatorKey = $operatorLines[0].Trim()
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    # A public key is not secret; pass it as an argument. Piping it through the
    # console can prepend a BOM on Windows PowerShell 5.1.
    $fingerprintCode = "import sys; from deploy.sd.personalization import operator_key_fingerprint; print(operator_key_fingerprint(sys.argv[1]))"
    Push-Location $repoRoot
    try {
        $operatorFingerprint = (& $PythonExe -c $fingerprintCode $operatorKey)
        if ($LASTEXITCODE -ne 0) { Fail "operator public key is not an allowed public key" }
    }
    finally {
        Pop-Location
    }
    $operatorFingerprint = ([string]$operatorFingerprint).Trim()
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
if ($robotNumberSource -eq "auto" -and -not $reviewedPlan) {
    # Draw from the free slots instead of taking the lowest one so two operator
    # PCs with separate registries are less likely to hand out the same DDS domain.
    $freeNumbers = @(1..61 | Where-Object { @($registry.robot_numbers) -notcontains $_ })
    if ($freeNumbers.Count -eq 0) { Fail "no free robot number remains in the registry (1-61)" }
    $RobotNumber = [int]($freeNumbers | Get-Random)
}
# Checked again after drawing or loading a plan: a tampered plan must never
# reach the writer with an identity the bundle validator would later refuse.
if ($RobotNumber -lt 1 -or $RobotNumber -gt 61) { Fail "RobotNumber must be between 1 and 61" }
if ($reprovision) {
    # A reviewed plan may not swap in another identity under this receipt, and the
    # receipt's identity must be the one the registry already holds.
    foreach ($pair in @(@("RobotNumber", "robot_number"), @("DeviceName", "device_name"), @("DeviceUid", "device_uid"))) {
        if ([string](Get-Variable -Name $pair[0] -ValueOnly) -cne [string]$reprovision.($pair[1])) {
            Fail "the plan identity does not match the reprovision receipt: $($pair[1])"
        }
    }
    if ($reviewedPlan -and [string]$reviewedPlan.robot_number_source -cne "reprovision") {
        Fail "the reviewed plan was not made for this reprovision receipt"
    }
    if (@($registry.robot_numbers) -notcontains $RobotNumber -or
        @($registry.device_names) -cnotcontains $DeviceName -or
        @($registry.device_uids) -cnotcontains $DeviceUid) {
        Fail "the reprovision receipt identity is not registered here"
    }
}
if ($DeviceName -cnotmatch '^rosy-pinky-[a-hj-km-np-z2-9]{4}$') { Fail "DeviceName is invalid" }
try { $parsedUid = [guid]$DeviceUid } catch { Fail "DeviceUid is invalid" }
if (-not $reprovision) {
    if (@($registry.robot_numbers) -contains $RobotNumber) { Fail "robot number is already registered" }
    if (@($registry.device_names) -contains $DeviceName) { Fail "device name is already registered" }
    if (@($registry.device_uids) -contains $DeviceUid) { Fail "device UID is already registered" }
}

$firstInventory = Read-DiskInventory $DiskInventoryJson
if ($DiskSerial) {
    $bySerial = Resolve-DiskNumberBySerial $firstInventory $DiskSerial
    if ($PSBoundParameters.ContainsKey("DiskNumber") -and $bySerial -ne $DiskNumber) {
        Fail "-DiskNumber $DiskNumber does not match -DiskSerial $DiskSerial (disk $bySerial)"
    }
    $DiskNumber = $bySerial
}
$firstDisk = Select-SafeDisk $firstInventory $DiskNumber
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
    robot_number_source = $robotNumberSource
    model = $Model
    requested_preset = $Preset
    country_code = $CountryCode
    ros_domain_id = 40 + $RobotNumber
    namespace = "rosy_{0:d2}" -f $RobotNumber
    release_id = $ReleaseId
    image_sha256 = $actualHash
    wifi_ssid = $wifiCredential.UserName
    fleet_endpoint = $FleetEndpoint
    fleet_trust_profile = $FleetTrustProfile
    fleet_source = $fleetSource
    operator_key_fingerprint = $operatorFingerprint
    registry_path = (Resolve-Path -LiteralPath $RegistryJson).ProviderPath
}

$secondSource = $(if ($SecondDiskInventoryJson) { $SecondDiskInventoryJson } else { $DiskInventoryJson })
$secondDisk = Select-SafeDisk (Read-DiskInventory $secondSource) $DiskNumber
if ((Get-DiskFingerprint $firstDisk) -ne (Get-DiskFingerprint $secondDisk)) {
    Fail "target disk changed between safety probes"
}

if ($reviewedPlan) {
    # The disk number is not part of the reviewed identity; the serial is.
    foreach ($field in @("disk_model", "disk_serial", "disk_size", "release_id", "image_sha256", "wifi_ssid", "namespace", "ros_domain_id", "operator_key_fingerprint")) {
        if ($planKeys -cnotcontains $field -or [string]$plan[$field] -cne [string]$reviewedPlan.$field) {
            Fail "target no longer matches the reviewed plan: $field"
        }
    }
    # Windows paths are case-insensitive; a different registry would let one
    # plan provision two cards with the same identity.
    if ([string]$plan["registry_path"] -ne [string]$reviewedPlan.registry_path) {
        Fail "target no longer matches the reviewed plan: registry_path"
    }
}

$planJson = $plan | ConvertTo-Json -Compress
if ($PlanOnly) {
    if ($PlanPath) {
        $planTemp = "$PlanPath.tmp-$([guid]::NewGuid().ToString('N'))"
        try {
            Set-Content -LiteralPath $planTemp -Value $planJson -Encoding UTF8
            Move-Item -LiteralPath $planTemp -Destination $PlanPath
        }
        finally {
            if (Test-Path -LiteralPath $planTemp) { Remove-Item -LiteralPath $planTemp -Force }
        }
    }
    $planJson
    exit 0
}

$expectedConfirmation = "ERASE SERIAL $($firstDisk.SerialNumber) $DeviceName"
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

$readbackVerifier = Join-Path $PSScriptRoot "verify-media-readback.py"
if (-not (Test-Path -LiteralPath $readbackVerifier -PathType Leaf)) { Fail "media readback verifier is missing" }

# D-180: the full readback below is the single authoritative media check.
# Input authenticity was proven by the signed SHA256SUMS before any disk probe,
# so Imager's own read-back pass (and a raw-hash pre-pass to feed it) is skipped.
$writerArguments = @(
    "--cli",
    "--disable-verify",
    ('"{0}"' -f $ImagePath),
    ('"{0}"' -f $physicalDrive)
)
$writerProcess = Start-Process -FilePath $RpiImager -ArgumentList $writerArguments -Wait -PassThru
$writerExitCode = $writerProcess.ExitCode
if ($writerExitCode -ne 0) { Fail "image writer failed with exit code $writerExitCode" }

$readbackTarget = $(if ($ReadbackDevice) { $ReadbackDevice } else { $physicalDrive })
# Windows auto-mounts the freshly written FAT32 partition and rewrites a few
# spec-defined fields; removable media cannot be set offline. The verifier
# tolerates exactly those fields and reports them (release 004, offset 1049576).
$mediaReadbackOutput = & $PythonExe $readbackVerifier --image $ImagePath --device $readbackTarget
if ($LASTEXITCODE -ne 0) { Fail "full media readback verification failed" }
try {
    $mediaReadback = $mediaReadbackOutput | ConvertFrom-Json
}
catch {
    Fail "media readback evidence is invalid"
}
if (-not [bool]$mediaReadback.verified) { Fail "full media readback was not verified" }
foreach ($digestField in @("image_raw_sha256", "device_sha256")) {
    if ([string]$mediaReadback.$digestField -notmatch '^[0-9a-f]{64}$') { Fail "media readback evidence is invalid" }
}
if ([int64]$mediaReadback.bytes_verified -le 0) { Fail "media readback evidence is invalid" }

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
        if ($operatorKey) { $bundleRequest["operator_ssh_keys"] = @($operatorKey) }
        $apLogin = Get-ApPassword $DeviceName
        $bundleRequest["ap_password"] = $apLogin
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
    # D-176: an editable settings file next to the bundle; never overwrite one a person edited.
    $configTarget = Join-Path $bootRoot "rosy-config.yaml"
    if (-not (Test-Path -LiteralPath $configTarget)) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot "rosy-config.template.yaml") -Destination $configTarget
    }
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
if ($reprovision) {
    $receipt["supersedes"] = [ordered]@{
        release_id = [string]$reprovision.release_id
        image_sha256 = [string]$reprovision.image_sha256
        created_at = [string]$reprovision.created_at
    }
}
# -Depth: the default (2) flattens nested receipt evidence such as fingerprint lists.
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ReceiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 10 -Compress
# Shown once for the operator; not part of the JSON evidence on stdout.
[Console]::Error.WriteLine("Fallback AP for ${DeviceName}: SSID $DeviceName password $apLogin (stored in your Rosy AP store)")
