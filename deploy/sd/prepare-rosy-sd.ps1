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
    [switch]$PlanOnly,
    [string]$ProgressPath,
    [switch]$ResumeAfterWrite,
    [double]$WriterStallMinutes = 5,
    [double]$HeartbeatSeconds = 60,
    [double]$ReadbackStallMinutes = 5,
    [double]$MinReadMBps = 10,
    [double]$AssumedWriteMBps = 0,
    [switch]$AcceptSlowMedia,
    [int64]$ProbeBytes = 134217728
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# D-181: once the release checks start, every failure names the stage, what is on
# the card and the operator's next step, and is appended to the progress file.
$script:stage = ""
$script:cardState = "untouched"
$script:nextHint = ""
$script:failureRecorded = $false
$script:failureKind = ""
$imageSignature = $null
$resumeNext = "re-run the same command with -ResumeAfterWrite (skips the write and re-reads the whole card)"
$fullWriteNext = "re-run the full write (the same command without -ResumeAfterWrite)"

function Add-ProgressLine([string]$Stage, [string]$CardState, [string]$Detail, [object]$Bytes, [System.Collections.IDictionary]$Extra) {
    if (-not $ProgressPath) { return }
    $line = [ordered]@{ ts = [DateTime]::UtcNow.ToString("o"); stage = $Stage; card_state = $CardState }
    if ($Detail) { $line["detail"] = $Detail }
    if ($null -ne $Bytes) { $line["bytes"] = [int64]$Bytes }
    if ($Extra) { foreach ($key in $Extra.Keys) { $line[$key] = $Extra[$key] } }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($line | ConvertTo-Json -Compress) + "`n")
    # Not Start-Transcript: that buffers, and release 005 sat at its header for an hour.
    $stream = New-Object IO.FileStream($ProgressPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
}

function Set-Stage([string]$Stage, [string]$CardState, [string]$Detail, [System.Collections.IDictionary]$Extra) {
    $script:stage = $Stage
    $script:cardState = $CardState
    $script:nextHint = ""
    Add-ProgressLine $Stage $CardState $Detail $null $Extra
}

function Get-NextStep {
    if ($script:nextHint) { return $script:nextHint }
    switch ($script:cardState) {
        "untouched" {
            switch ($script:stage) {
                "verify-signature" { return "download the release again (image, SHA256SUMS, SHA256SUMS.sig), then re-run" }
                "select-disk" { return "reseat the card reader, re-run -PlanOnly to see which disk is found, then re-run the write" }
                default { return "re-run the same command" }
            }
        }
        "writing" { return "the card is partially written: $fullWriteNext" }
        "written-unverified" { return $resumeNext }
        "verified-no-bundle" { return $resumeNext }
        # D-182 (D-181 review): a bundle half-copied to the card makes the readback
        # see an extra file, so resume cannot finish it.
        "bundle-partial" { return "a partial provisioning bundle may be on the card and cannot be resumed: $fullWriteNext" }
        "complete" { return "the card has its bundle but no receipt: check the registry file, then $fullWriteNext" }
        default { return $fullWriteNext }
    }
}

function Format-Failure([string]$Message, [string]$Next) {
    if (-not $Next) { $Next = Get-NextStep }
    # D-182: the failed line carries the next step, so the status command can show it.
    $extra = [ordered]@{ next = $Next }
    if ($script:failureKind) { $extra["kind"] = $script:failureKind }
    Add-ProgressLine "failed" $script:cardState "$($script:stage): $Message" $null $extra
    $script:failureRecorded = $true
    return "$Message`nstage=$($script:stage) card_state=$($script:cardState)`nnext: $Next"
}

function Fail([string]$Message, [string]$Next) {
    if ($script:stage -and -not $script:failureRecorded) { $Message = Format-Failure $Message $Next }
    throw $Message
}

# Errors that do not come through Fail (a missing tool, a file that cannot be
# copied) get the same stage, card state and next step.
trap {
    if ($script:stage -and -not $script:failureRecorded) {
        throw (Format-Failure ([string]$_.Exception.Message) "")
    }
    break
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
    return @(Get-Disk | Select-Object Number, FriendlyName, SerialNumber, UniqueId, Size, BusType, IsBoot, IsSystem, IsOffline, IsReadOnly, Signature, Guid |
        ForEach-Object { Complete-DiskSerial $_ })
}

# D-182: the serial names the reader, not the card. Cheap readers share dummy
# serials (000000000207 is a known Genesys one), so the plan also pins the
# inserted card's own identity: its MBR disk signature or GPT disk GUID.
function Get-CardIdentity([object]$Disk) {
    $signature = $null
    $guid = $null
    if ($Disk.PSObject.Properties["Signature"] -and $null -ne $Disk.Signature -and [int64]$Disk.Signature -ne 0) {
        $signature = "{0:x8}" -f [int64]$Disk.Signature
    }
    if ($Disk.PSObject.Properties["Guid"] -and -not [string]::IsNullOrWhiteSpace([string]$Disk.Guid)) {
        $guid = ([string]$Disk.Guid).Trim().Trim('{', '}').ToLowerInvariant()
    }
    [pscustomobject]@{ Signature = $signature; Guid = $guid }
}

function Assert-PlannedCard([object]$Disk, [string]$DeviceSignature) {
    if (-not $reviewedPlan) { return }
    if ($planKeys -cnotcontains "disk_signature" -or $planKeys -cnotcontains "disk_guid") {
        Write-Warning "the reviewed plan records no card identity (made before D-182); check the card label before the confirmation"
        return
    }
    $planned = [pscustomobject]@{
        Signature = $(if ($reviewedPlan.disk_signature) { [string]$reviewedPlan.disk_signature } else { $null })
        Guid = $(if ($reviewedPlan.disk_guid) { [string]$reviewedPlan.disk_guid } else { $null })
    }
    $found = Get-CardIdentity $Disk
    # The bytes read from the card win over what Get-Disk last cached.
    if ($DeviceSignature) { $found.Signature = $DeviceSignature }
    $describe = { param($identity) "disk signature $(if ($identity.Signature) { $identity.Signature } else { 'none' }), GPT GUID $(if ($identity.Guid) { $identity.Guid } else { 'none' })" }
    $otherCard = "put the planned card back (check its label), or make and review a new plan (-PlanOnly) for the card that is inserted"
    if ($found.Signature -ceq $planned.Signature -and $found.Guid -ceq $planned.Guid) {
        if (-not $planned.Signature -and -not $planned.Guid) {
            Write-Warning "the card has no disk signature or GUID (factory blank); it is identified only by reader serial and size, which another blank card of the same size in this reader would also match. Check the card label."
        }
        return
    }
    if ($imageSignature -and $found.Signature -ceq $imageSignature) {
        # An earlier attempt of this plan got as far as the partition table.
        Write-Warning "the card already holds this release's partition table (an earlier attempt?); any card written with this release would match. Check the card label."
        return
    }
    Fail ("a different card is in the reader: the plan recorded {0}; the inserted card has {1}" -f (& $describe $planned), (& $describe $found)) $otherCard
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
    # D-181: a -ResumeAfterWrite receipt has no Imager exit code; its full readback is the proof.
    $resumed = $receiptKeys -ccontains "resumed_after_write" -and $reprovision.resumed_after_write -is [bool] -and $reprovision.resumed_after_write
    $writerProven = ($exitCode -is [int] -or $exitCode -is [long]) -and $exitCode -eq 0
    if ($resumed -and $null -eq $exitCode) { $writerProven = $true }
    if (-not $writerProven -or -not ($verified -is [bool]) -or -not $verified) {
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
# D-181 review: a readback of another device would pass while the bundle and
# receipt went to the real card. -ReadbackDevice and a non-.exe writer are test
# fixtures, accepted only together with a fixture disk inventory.
if ($ReadbackDevice -and -not $DiskInventoryJson) {
    Fail "-ReadbackDevice is a test fixture option and is refused for a real disk (with or without -ResumeAfterWrite)"
}
if (-not $DiskInventoryJson -and -not $ResumeAfterWrite -and [IO.Path]::GetExtension($RpiImager) -ne ".exe") {
    Fail "-RpiImager must be the Raspberry Pi Imager .exe; a wrapper would hide the real writer from the stall watchdog"
}
if ($ReadbackStallMinutes -le 0 -or $WriterStallMinutes -le 0) { Fail "stall limits must be positive" }

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

if (-not $ProgressPath -and -not $PlanOnly) { $ProgressPath = "$ReceiptPath.progress.jsonl" }
Set-Stage "verify-signature" "untouched" $(if ($PlanOnly) { "plan" } elseif ($ResumeAfterWrite) { "resume-after-write" } else { "write" })
if (-not (Test-Path -LiteralPath $ImagePath -PathType Leaf)) { Fail "image file is missing" }
if ($ImageSha256 -notmatch '^[0-9a-fA-F]{64}$') { Fail "image SHA-256 is invalid" }
$actualHash = (Get-FileHash -LiteralPath $ImagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $ImageSha256.ToLowerInvariant()) { Fail "image SHA-256 does not match" }
if (-not (Test-Path -LiteralPath $ImageSignaturePath -PathType Leaf)) { Fail "image signature is missing" }
if (-not (Test-Path -LiteralPath $ReleasePublicKey -PathType Leaf)) { Fail "trusted release public key is missing" "restore deploy/release/public-keys from the repository, then re-run" }
if (Test-Path -LiteralPath $ReceiptPath) {
    Fail "receipt already exists and will not be overwritten" "this plan's card was already written and recorded; make a new plan (-PlanOnly) for another card"
}
if (-not (Test-Path -LiteralPath $RegistryJson -PathType Leaf)) { Fail "identity registry is missing" "restore the registry file named in the plan, then re-run" }
if (-not $ResumeAfterWrite -and -not (Test-Path -LiteralPath $RpiImager -PathType Leaf) -and -not (Get-Command $RpiImager -ErrorAction SilentlyContinue)) {
    Fail "Raspberry Pi Imager CLI is unavailable" "install Raspberry Pi Imager or pass -RpiImager, then re-run"
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
# The release is proven; what can still fail here is the plan, registry or arguments.
$script:nextHint = "correct the reported plan, registry or argument, then re-run"

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

Set-Stage "select-disk" "untouched" ""
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
$cardIdentity = Get-CardIdentity $firstDisk
$plan = [ordered]@{
    mode = $(if ($PlanOnly) { "PLAN_ONLY" } else { "WRITE" })
    physical_drive = $physicalDrive
    disk_number = [int]$firstDisk.Number
    disk_model = [string]$firstDisk.FriendlyName
    disk_serial = [string]$firstDisk.SerialNumber
    disk_size = [int64]$firstDisk.Size
    disk_signature = $cardIdentity.Signature
    disk_guid = $cardIdentity.Guid
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
            Fail "target no longer matches the reviewed plan: $field" "check that the planned card and release are in use; otherwise make and review a new plan (-PlanOnly)"
        }
    }
    # Windows paths are case-insensitive; a different registry would let one
    # plan provision two cards with the same identity.
    if ([string]$plan["registry_path"] -ne [string]$reviewedPlan.registry_path) {
        Fail "target no longer matches the reviewed plan: registry_path" "check that the planned card and release are in use; otherwise make and review a new plan (-PlanOnly)"
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

# D-182 pre-flight, before the ERASE confirmation: a timed, read-only sequential
# read of the card start predicts the job, the card's own identity is checked
# against the plan, and slow media is flagged. -PlanOnly cannot do this: opening
# \\.\PhysicalDriveN needs the elevation that only the write has.
$readbackVerifier = Join-Path $PSScriptRoot "verify-media-readback.py"
if (-not (Test-Path -LiteralPath $readbackVerifier -PathType Leaf)) { Fail "media readback verifier is missing" }
$readbackTarget = $(if ($ReadbackDevice) { $ReadbackDevice } else { $physicalDrive })
$invariant = [Globalization.CultureInfo]::InvariantCulture
Set-Stage "preflight" "untouched" ""
$probeOutput = & $PythonExe $readbackVerifier --image $ImagePath --device $readbackTarget --probe --probe-bytes $ProbeBytes
if ($LASTEXITCODE -ne 0) { Fail "the pre-flight probe failed (verifier exit code $LASTEXITCODE)" }
$probe = ($probeOutput | Out-String) | ConvertFrom-Json
function Get-ProbeValue([string]$Name) {
    if ($probe.PSObject.Properties[$Name]) { return $probe.$Name }
    return $null
}
# The xz index gives the raw size without decompressing; it tells a stall
# after the last byte (resume) from one mid-write (rewrite).
$imageRawSize = $(if ($null -ne (Get-ProbeValue "image_raw_size")) { [int64]$probe.image_raw_size } else { [int64]0 })
$imageSignature = $(if (Get-ProbeValue "image_mbr_signature") { [string]$probe.image_mbr_signature } else { $null })
$deviceSignature = $(if (Get-ProbeValue "device_mbr_signature") { [string]$probe.device_mbr_signature } else { $null })
$readMBps = $(if ($null -ne (Get-ProbeValue "device_read_mbps")) { [double]$probe.device_read_mbps } else { $null })
$probeError = [string](Get-ProbeValue "device_error")
# Without a measurement, fall back to release 005: Imager about 9 MB/s, the
# single-thread readback about 3.4 MB/s.
$readRate = $(if ($null -ne $readMBps) { $readMBps } else { 3.4 })
$writeRate = $(if ($AssumedWriteMBps -gt 0) { $AssumedWriteMBps } elseif ($null -ne $readMBps) { $readMBps * 0.8 } else { 9.0 })
$rawMB = $imageRawSize / 1e6
$predictedWrite = $(if ($ResumeAfterWrite) { 0 } else { [int64][Math]::Ceiling($rawMB / $writeRate) })
$predictedReadback = [int64][Math]::Ceiling($rawMB / $readRate)
$preflight = [ordered]@{
    read_mbps = $readMBps
    read_bytes = [int64](Get-ProbeValue "device_bytes_read")
    raw_bytes = $imageRawSize
    assumed_write_mbps = [Math]::Round($writeRate, 2)
    assumed_readback_mbps = [Math]::Round($readRate, 2)
    predicted_write_seconds = $predictedWrite
    predicted_readback_seconds = $predictedReadback
    predicted_total_seconds = $predictedWrite + $predictedReadback
    min_read_mbps = $MinReadMBps
}
if ($probeError) { $preflight["device_error"] = $probeError }
Add-ProgressLine "preflight" "untouched" "measured" $null $preflight
$readText = $(if ($null -ne $readMBps) { "{0:N1} MB/s over the first {1:N0} MB" -f $readMBps, ($preflight.read_bytes / 1e6) } else { "not measured ($probeError); assuming $readRate MB/s" })
Write-Host ("Pre-flight: card read {0}. Image {1:N0} MB: write about {2:N0} min at {3:N1} MB/s{4}, readback about {5:N0} min, total about {6:N0} min." -f
    $readText, $rawMB, [Math]::Ceiling($predictedWrite / 60), $writeRate,
    $(if ($ResumeAfterWrite) { " (skipped: -ResumeAfterWrite)" } else { "" }),
    [Math]::Ceiling($predictedReadback / 60), [Math]::Ceiling(($predictedWrite + $predictedReadback) / 60))

if ($ResumeAfterWrite) {
    # A fast pre-check before an hour of readback: a card that holds this
    # release's image starts with the image's MBR disk signature.
    if (-not $imageSignature) {
        Write-Warning "the image has no MBR disk signature; the card cannot be pre-checked, the readback decides"
    }
    elseif (-not $deviceSignature) {
        Write-Warning "the card's first sector gave no MBR disk signature ($probeError); the readback decides"
    }
    elseif ($deviceSignature -cne $imageSignature) {
        $script:cardState = "unknown"
        Fail ("the card does not hold this release's image: its MBR disk signature is {0}, the image's is {1}" -f $deviceSignature, $imageSignature) "check that the card this plan wrote is in the reader (label); if it is, its write never reached the partition table: $fullWriteNext"
    }
    # D-181 review: a bundle already on the card makes the readback fail as a
    # mismatch after the full read; stop before spending that hour.
    $existingBundle = $null
    if ($BootMountPath) {
        if (Test-Path -LiteralPath (Join-Path $BootMountPath "rosy-provision")) { $existingBundle = Join-Path $BootMountPath "rosy-provision" }
    }
    elseif (-not $DiskInventoryJson) {
        foreach ($partition in @(Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue)) {
            if ([string]$partition.DriveLetter -notmatch '^[A-Za-z]$') { continue }
            $candidate = "$($partition.DriveLetter):\rosy-provision"
            if (Test-Path -LiteralPath $candidate) { $existingBundle = $candidate }
        }
    }
    if ($existingBundle) {
        $script:cardState = "bundle-partial"
        Fail "the card already has a provisioning bundle ($existingBundle); -ResumeAfterWrite cannot finish it" "rewrite the card: $fullWriteNext; if the registry already lists $DeviceName, remove that entry first"
    }
}
else {
    Assert-PlannedCard $secondDisk $deviceSignature
}

if ($null -ne $readMBps -and $readMBps -lt $MinReadMBps) {
    $slowAdvice = "use another USB port or reader (a USB 3.0 reader, with an A1/A2 or U3 card)"
    Write-Warning ("SLOW MEDIA: the card reads at {0:N1} MB/s, below {1:N1} MB/s; the job will take about {2:N0} min. {3}." -f
        $readMBps, $MinReadMBps, [Math]::Ceiling($preflight.predicted_total_seconds / 60), $slowAdvice)
    if (-not $AcceptSlowMedia) {
        $slowFailure = "the card reads at {0:N1} MB/s, below -MinReadMBps {1:N1} (predicted about {2:N0} min)" -f $readMBps, $MinReadMBps, [Math]::Ceiling($preflight.predicted_total_seconds / 60)
        $slowNext = "$slowAdvice, then re-run; or re-run with -AcceptSlowMedia to write this card anyway"
        # A non-interactive run (confirmation passed in, or no console) cannot be asked.
        if ($Confirmation -or [Console]::IsInputRedirected) { Fail $slowFailure $slowNext }
        if ((Read-Host "Type SLOW to write this card anyway, anything else to stop") -cne "SLOW") { Fail $slowFailure $slowNext }
    }
}

Set-Stage "confirm" "untouched" ""
$expectedConfirmation = "ERASE SERIAL $($firstDisk.SerialNumber) $DeviceName"
if (-not $Confirmation) { $Confirmation = Read-Host "Type exactly: $expectedConfirmation" }
if ($Confirmation -cne $expectedConfirmation) {
    Fail "confirmation did not match the selected physical disk and device`ntyped: '$Confirmation'" "re-run and type exactly: $expectedConfirmation"
}

# Probe a third time immediately before the destructive call when live disk
# discovery is used. Fixture mode already supplied the explicit second probe.
if (-not $DiskInventoryJson) {
    $writeDisk = Select-SafeDisk (Read-DiskInventory "") $DiskNumber
    if ((Get-DiskFingerprint $firstDisk) -ne (Get-DiskFingerprint $writeDisk)) {
        Fail "target disk changed immediately before write" "reseat the card reader, re-run -PlanOnly to see which disk is found, then re-run the write"
    }
    if (-not $ResumeAfterWrite) { Assert-PlannedCard $writeDisk $null }
}

# Imager CPU and I/O counters summed over its whole process tree; $null once
# the root is gone. D-181 review: a launcher or wrapper can look idle while its
# child writes, and watching only the root PID would kill a working write.
function Get-WriterSample([int]$RootId) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $children = @{}
    $root = $null
    foreach ($process in $all) {
        if ([int]$process.ProcessId -eq $RootId) { $root = $process }
        $parentId = [int]$process.ParentProcessId
        if (-not $children.ContainsKey($parentId)) { $children[$parentId] = New-Object System.Collections.ArrayList }
        [void]$children[$parentId].Add($process)
    }
    if ($null -eq $root) { return $null }
    $tree = New-Object System.Collections.ArrayList
    [void]$tree.Add($root)
    $seen = @{ $RootId = $true }
    for ($index = 0; $index -lt $tree.Count; $index++) {
        $parent = $tree[$index]
        if (-not $children.ContainsKey([int]$parent.ProcessId)) { continue }
        foreach ($child in $children[[int]$parent.ProcessId]) {
            if ($seen.ContainsKey([int]$child.ProcessId)) { continue }
            # A reused parent PID: the "child" is older than its parent.
            if ($child.CreationDate -and $parent.CreationDate -and $child.CreationDate -lt $parent.CreationDate) { continue }
            $seen[[int]$child.ProcessId] = $true
            [void]$tree.Add($child)
        }
    }
    $sum = @{ Kernel = [uint64]0; User = [uint64]0; Read = [uint64]0; Write = [uint64]0; Other = [uint64]0 }
    foreach ($process in $tree) {
        $sum.Kernel += [uint64]$process.KernelModeTime
        $sum.User += [uint64]$process.UserModeTime
        $sum.Read += [uint64]$process.ReadTransferCount
        $sum.Write += [uint64]$process.WriteTransferCount
        $sum.Other += [uint64]$process.OtherTransferCount
    }
    [pscustomobject]@{
        Written = [int64]$sum.Write
        Key = "{0}/{1}/{2}/{3}/{4}/{5}" -f $sum.Kernel, $sum.User, $sum.Read, $sum.Write, $sum.Other, $tree.Count
    }
}

# D-181 review: taskkill writes to stderr when a process is already gone, and
# native stderr under ErrorAction Stop throws in PowerShell 5.1, which skipped the
# wait and the card-state update. Returns whether the tree is really gone.
function Stop-ProcessTree([System.Diagnostics.Process]$Process) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & taskkill.exe /PID $Process.Id /T /F *> $null
    }
    finally {
        $ErrorActionPreference = $previous
    }
    return $Process.WaitForExit(10000)
}

# Windows command-line quoting for Start-Process -ArgumentList.
function ConvertTo-ProcessArgument([string]$Value) {
    '"' + (($Value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}

$writerExitCode = $null
if ($ResumeAfterWrite) {
    # D-181: the readback below is authoritative, so a card that matches the signed
    # image byte for byte is good however it was written. Every pre-write check
    # above (signature, serial, fingerprint, plan, confirmation) still ran.
    Set-Stage "write" "written-unverified" "skipped: -ResumeAfterWrite" ([ordered]@{ total = $imageRawSize })
}
else {
    # D-180: the full readback below is the single authoritative media check.
    # Input authenticity was proven by the signed SHA256SUMS before any disk probe,
    # so Imager's own read-back pass (and a raw-hash pre-pass to feed it) is skipped.
    $writerArguments = @(
        "--cli",
        "--disable-verify",
        ('"{0}"' -f $ImagePath),
        ('"{0}"' -f $physicalDrive)
    )
    Set-Stage "write" "writing" "raw image $imageRawSize bytes" ([ordered]@{ total = $imageRawSize })
    # D-181: no Start-Process -Wait. Release 005 Imager wrote every byte, then sat
    # with 0 CPU and 0 I/O for 23 minutes while -Wait waited forever.
    $writerProcess = Start-Process -FilePath $RpiImager -ArgumentList $writerArguments -PassThru
    $null = $writerProcess.Handle  # keeps ExitCode readable after exit (PowerShell 5.1)
    $stallLimit = [TimeSpan]::FromMinutes($WriterStallMinutes)
    $pollMilliseconds = [int][Math]::Max(200, [Math]::Min(5000, $stallLimit.TotalMilliseconds / 4))
    $lastKey = ""
    $lastChange = [DateTime]::UtcNow
    $lastBeat = [DateTime]::UtcNow
    $written = [int64]0
    while (-not $writerProcess.WaitForExit($pollMilliseconds)) {
        $sample = Get-WriterSample $writerProcess.Id
        if ($null -eq $sample) { continue }
        $written = [Math]::Max($written, $sample.Written)
        $now = [DateTime]::UtcNow
        if ($sample.Key -ne $lastKey) {
            $lastKey = $sample.Key
            $lastChange = $now
        }
        elseif ($now - $lastChange -ge $stallLimit) {
            if (-not (Stop-ProcessTree $writerProcess)) {
                Fail ("image writer stalled after writing {0} of {1} bytes and could not be stopped" -f $written, $imageRawSize) "Imager could not be stopped: unplug the card reader and reboot the PC before anything else, then $fullWriteNext (do not resume)"
            }
            if ($imageRawSize -gt 0 -and $written -ge $imageRawSize) { $script:cardState = "written-unverified" }
            Fail ("image writer stalled: no CPU or I/O for {0} minutes after writing {1} of {2} bytes; it was stopped" -f $WriterStallMinutes, $written, $imageRawSize)
        }
        if ($now - $lastBeat -ge [TimeSpan]::FromSeconds($HeartbeatSeconds)) {
            $lastBeat = $now
            Add-ProgressLine "write" "writing" "heartbeat" $written
        }
    }
    $writerProcess.WaitForExit()
    $writerExitCode = $writerProcess.ExitCode
    if ($writerExitCode -ne 0) { Fail "image writer failed with exit code $writerExitCode" }
}

Set-Stage "readback" "written-unverified" "" ([ordered]@{ total = $imageRawSize })
# D-182: the readback runs as a watched process. Its heartbeats land in the
# progress file; if the verified byte count stops rising for
# -ReadbackStallMinutes, the verifier is stopped and the failure is an I/O one
# (release 005: the reader dropped out and the readback sat for an hour).
# A slow card that keeps moving is never stopped. The verifier's own stall
# timeout (twice this limit) is the backstop when this script is gone.
$readbackStallSeconds = $ReadbackStallMinutes * 60
$beatSeconds = [Math]::Min($HeartbeatSeconds, $readbackStallSeconds / 4)
$readbackOptions = @("--progress-seconds", $beatSeconds.ToString($invariant),
    "--stall-seconds", (2 * $readbackStallSeconds).ToString($invariant))
if ($ProgressPath) { $readbackOptions += @("--progress", $ProgressPath) }
# Windows auto-mounts the freshly written FAT32 partition and rewrites a few
# spec-defined fields; removable media cannot be set offline. The verifier
# tolerates exactly those fields and reports them (release 004, offset 1049576).
# The verifier's reason goes to a file: a PowerShell 5.1 transcript does not
# capture a native program's stderr, and 2>&1 under ErrorAction Stop would throw
# (release 005 rewrite: the log said only "readback verification failed").
$readbackStem = Join-Path ([IO.Path]::GetTempPath()) ("rosy-readback-" + [guid]::NewGuid().ToString("N"))
$readbackErrorPath = "$readbackStem.json"
$readbackOutputPath = "$readbackStem.out"
$readbackStderrPath = "$readbackStem.err"
$readbackOptions += @("--error-json", $readbackErrorPath)
$verifierArguments = @(@($readbackVerifier, "--image", $ImagePath, "--device", $readbackTarget) + $readbackOptions |
    ForEach-Object { ConvertTo-ProcessArgument ([string]$_) })

function Read-NewReadbackBytes {
    # Heartbeat lines appended since the last call; the partial last line waits.
    if (-not $ProgressPath -or -not (Test-Path -LiteralPath $ProgressPath -PathType Leaf)) { return [int64]-1 }
    $stream = New-Object IO.FileStream($ProgressPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        if ($stream.Length -le $script:progressOffset) { return [int64]-1 }
        $null = $stream.Seek($script:progressOffset, [IO.SeekOrigin]::Begin)
        $buffer = New-Object byte[] ($stream.Length - $script:progressOffset)
        $count = $stream.Read($buffer, 0, $buffer.Length)
    }
    finally {
        $stream.Dispose()
    }
    if ($count -le 0) { return [int64]-1 }
    $end = [Array]::LastIndexOf($buffer, [byte]10, $count - 1)
    if ($end -lt 0) { return [int64]-1 }
    $script:progressOffset += $end + 1
    $best = [int64]-1
    foreach ($text in [Text.Encoding]::UTF8.GetString($buffer, 0, $end + 1).Split("`n")) {
        if (-not $text.Trim()) { continue }
        try { $line = $text | ConvertFrom-Json } catch { continue }
        if ($line.PSObject.Properties["stage"] -and $line.stage -eq "readback" -and $line.PSObject.Properties["bytes"]) {
            $best = [Math]::Max($best, [int64]$line.bytes)
        }
    }
    return $best
}

$script:progressOffset = $(if ($ProgressPath -and (Test-Path -LiteralPath $ProgressPath -PathType Leaf)) { (Get-Item -LiteralPath $ProgressPath).Length } else { [int64]0 })
try {
    $readbackProcess = Start-Process -FilePath $PythonExe -ArgumentList $verifierArguments -NoNewWindow -PassThru `
        -RedirectStandardOutput $readbackOutputPath -RedirectStandardError $readbackStderrPath
    $null = $readbackProcess.Handle  # keeps ExitCode readable after exit (PowerShell 5.1)
    $readbackLimit = [TimeSpan]::FromSeconds($readbackStallSeconds)
    $readbackPoll = [int][Math]::Max(200, [Math]::Min(5000, $readbackLimit.TotalMilliseconds / 4))
    $verifiedBytes = [int64]0
    $lastAdvance = [DateTime]::UtcNow
    while (-not $readbackProcess.WaitForExit($readbackPoll)) {
        $seen = Read-NewReadbackBytes
        if ($seen -gt $verifiedBytes) {
            $verifiedBytes = $seen
            $lastAdvance = [DateTime]::UtcNow
        }
        elseif ([DateTime]::UtcNow - $lastAdvance -ge $readbackLimit) {
            $stopped = Stop-ProcessTree $readbackProcess
            $script:failureKind = "io"
            Fail ("the card could not be read during readback (stalled, kind io): no progress for {0} minutes after verifying {1} of {2} bytes; the verifier was {3}" -f
                $ReadbackStallMinutes, $verifiedBytes, $imageRawSize, $(if ($stopped) { "stopped" } else { "told to stop but is still running" })) "reinsert the card (or use another reader), then $resumeNext"
        }
    }
    $readbackProcess.WaitForExit()
    $readbackExitCode = $readbackProcess.ExitCode
    $mediaReadbackOutput = $(if (Test-Path -LiteralPath $readbackOutputPath -PathType Leaf) { Get-Content -LiteralPath $readbackOutputPath -Raw } else { "" })
    $readbackError = $null
    if (Test-Path -LiteralPath $readbackErrorPath -PathType Leaf) {
        try { $readbackError = Get-Content -LiteralPath $readbackErrorPath -Raw | ConvertFrom-Json } catch { $readbackError = $null }
    }
}
finally {
    foreach ($readbackFile in @($readbackErrorPath, $readbackOutputPath, $readbackStderrPath)) {
        if (Test-Path -LiteralPath $readbackFile) { Remove-Item -LiteralPath $readbackFile -Force -ErrorAction SilentlyContinue }
    }
}
if ($readbackExitCode -ne 0) {
    $reason = "no reason reported (verifier exit code $readbackExitCode)"
    $kind = "mismatch"
    if ($readbackError) {
        $reason = "{0} (verified {1} bytes before it stopped)" -f $readbackError.error, $readbackError.bytes_verified
        $kind = [string]$readbackError.kind
    }
    elseif ($readbackExitCode -eq 3) {
        $kind = "io"
    }
    $script:failureKind = $kind
    # A read error or a card that ends early is the reader or the connection,
    # not the data: the written bytes may be fine, so resume. A mismatch is bad data.
    if ($kind -eq "io") {
        Fail "the card could not be read during readback (removed, disconnected or I/O error): $reason" "reinsert the card (or use another reader), then $resumeNext"
    }
    if ($kind -eq "image") {
        $script:cardState = "unknown"
        Fail "the image file could not be decompressed during readback: $reason" "download the release again, then $fullWriteNext"
    }
    Fail "full media readback verification failed: $reason" "$fullWriteNext; if it fails again, replace the card"
}
try {
    $mediaReadback = $mediaReadbackOutput | ConvertFrom-Json
}
catch {
    Fail "media readback evidence is invalid"
}
if (-not [bool]$mediaReadback.verified) { Fail "full media readback was not verified" }
foreach ($digestField in @("image_raw_sha256", "device_sha256", "image_sha256")) {
    if (-not $mediaReadback.PSObject.Properties[$digestField] -or [string]$mediaReadback.$digestField -notmatch '^[0-9a-f]{64}$') {
        Fail "media readback evidence is invalid"
    }
}
if ([int64]$mediaReadback.bytes_verified -le 0) { Fail "media readback evidence is invalid" }
# Review MEDIUM-1: the readback hashed the compressed file it decompressed; it
# must be the file whose hash the signed SHA256SUMS vouched for.
if ([string]$mediaReadback.image_sha256 -cne $actualHash) {
    $script:cardState = "unknown"
    Fail "the image read back is not the signed image (image_sha256 $($mediaReadback.image_sha256), signed $actualHash)" "download the release again, then $fullWriteNext"
}
Set-Stage "bundle" "verified-no-bundle" ""

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

    # Review note: the card is re-selected by serial right before its boot
    # partition is touched; a reader swapped after the readback stops here.
    $bundleInventory = Read-DiskInventory $DiskInventoryJson
    $bundleNumber = $(if ($DiskSerial) { Resolve-DiskNumberBySerial $bundleInventory $DiskSerial } else { $DiskNumber })
    $bundleDisk = Select-SafeDisk $bundleInventory $bundleNumber
    if ((Get-DiskFingerprint $firstDisk) -ne (Get-DiskFingerprint $bundleDisk)) {
        Fail "target disk changed between the readback and the bundle"
    }
    $bootRoot = Resolve-BootMount $DiskNumber $BootMountPath ([bool]$DiskInventoryJson)
    $bundleDirectory = Join-Path $bootRoot "rosy-provision"
    # D-181 review: from the first byte on the boot partition, a failure (card
    # pulled mid-copy) leaves a partial bundle that the readback would call a
    # mismatch, so the advice is a full rewrite, not -ResumeAfterWrite.
    Set-Stage "bundle-writing" "bundle-partial" ""
    New-Item -ItemType Directory -Path $bundleDirectory -Force | Out-Null
    $bundleTarget = Join-Path $bundleDirectory "provision.json"
    if (Test-Path -LiteralPath $bundleTarget) { Fail "provisioning bundle already exists on the card" }
    $bundleTargetTemp = Join-Path $bundleDirectory ".provision.json.tmp"
    Copy-Item -LiteralPath $bundleTemp -Destination $bundleTargetTemp
    Move-Item -LiteralPath $bundleTargetTemp -Destination $bundleTarget
    # The bundle is on the card; the readback would now see it as an extra file,
    # so from here on a failure needs a full rewrite, not -ResumeAfterWrite.
    Set-Stage "receipt" "complete" ""
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
    resumed_after_write = [bool]$ResumeAfterWrite
    media_readback = $mediaReadback
    # D-181 review: the evidence names the device that was read back.
    readback_target = $readbackTarget
    preflight = $preflight
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
Set-Stage "done" "complete" "" ([ordered]@{ next = "the card is ready: put it in the Pinky and power on; the receipt is $ReceiptPath" })
# Shown once for the operator; not part of the JSON evidence on stdout.
[Console]::Error.WriteLine("Fallback AP for ${DeviceName}: SSID $DeviceName password $apLogin (stored in your Rosy AP store)")
