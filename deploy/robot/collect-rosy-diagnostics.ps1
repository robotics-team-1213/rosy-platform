[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][Alias("Host")][string]$HostName,
    [Parameter(Mandatory = $true)][string]$IdentityFile,
    [string]$User = "rosy",
    [string]$EvidenceRoot = (Join-Path (Get-Location) "evidence"),
    [string]$KnownHostsFile = (Join-Path $env:LOCALAPPDATA "Rosy\known_hosts"),
    [string]$CardDisk,
    [string]$CardBootPath,
    [ValidateRange(1, 120)][int]$ConnectTimeoutSec = 10,
    [string]$SshExe = "ssh",
    [string]$ScpExe = "scp",
    [switch]$PrintPlan
)
# Pull a D-175 L2 diagnostics bundle from a ROSY robot.
#
# SSH is key-only and non-interactive (BatchMode) against a pinned known_hosts
# file: the first connection records the host key (accept-new), later ones must
# match it. The robot runs rosy-diag collect; the bundle is copied into
# <EvidenceRoot>\<device>\<boot_id>\ and never overwrites earlier evidence.
#
# When SSH is unreachable and -CardDisk <serial> is given, the FAT32 boot
# partition's rosy-diag\ black box is copied from the card instead (no
# elevation; never rosy-provision). The journal then needs the elevated
# read-only ext4 reader deploy\sd\read-card-diagnostics.py.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

$RemoteTool = "/opt/rosy/native-runtime/rosy-diag"
$DeepReader = Join-Path $PSScriptRoot "..\sd\read-card-diagnostics.py"

if ($HostName -notmatch '^[A-Za-z0-9.-]+$') { Fail "Host must be a hostname or IPv4 address without shell characters" }
if ($User -notmatch '^[a-z_][a-z0-9_-]*$') { Fail "User is not a safe Linux account name" }
$IdentityFile = (Resolve-Path -LiteralPath $IdentityFile).ProviderPath
$EvidenceRoot = [IO.Path]::GetFullPath($EvidenceRoot)
$KnownHostsFile = [IO.Path]::GetFullPath($KnownHostsFile)
# ssh reads UserKnownHostsFile as a whitespace-separated list.
if ($KnownHostsFile -match '\s') { Fail "KnownHostsFile must not contain spaces: $KnownHostsFile" }

$target = "$User@$HostName"
$sshArguments = @(
    "-o", "BatchMode=yes",
    "-o", "PasswordAuthentication=no",
    "-o", "KbdInteractiveAuthentication=no",
    "-o", "PubkeyAuthentication=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "UserKnownHostsFile=$KnownHostsFile",
    "-o", "ConnectTimeout=$ConnectTimeoutSec",
    "-i", $IdentityFile
)
# No double quotes: Windows PowerShell 5.1 mangles embedded quotes in native arguments.
# sudo -n gives dmesg and the full journal when the rosy account may use it.
$remoteCommand = "d=`$(mktemp -d /tmp/rosy-diag.XXXXXX) && { sudo -n $RemoteTool collect --out `$d 2>/dev/null || $RemoteTool collect --out `$d; }"

if ($PrintPlan) {
    [ordered]@{
        target = $target
        ssh_exe = $SshExe
        scp_exe = $ScpExe
        ssh_arguments = $sshArguments
        remote_command = $remoteCommand
        known_hosts = $KnownHostsFile
        evidence_root = $EvidenceRoot
        card_disk = $CardDisk
        card_boot_path = $CardBootPath
    } | ConvertTo-Json -Depth 4
    exit 0
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $KnownHostsFile) | Out-Null

function Get-SafeName([string]$Value, [string]$Pattern, [string]$Fallback) {
    if ($Value -cmatch $Pattern) { return $Value }
    return $Fallback
}

function Copy-CardBlackBox {
    $diskNumber = $null
    $bootPath = $CardBootPath
    if (-not $bootPath) {
        $disks = @(Get-Disk | Where-Object { $_.BusType -eq "USB" -and ([string]$_.SerialNumber).Trim() -eq $CardDisk })
        if ($disks.Count -ne 1) { Fail "card serial $CardDisk must match exactly one USB disk (found $($disks.Count))" }
        $diskNumber = $disks[0].Number
        $letters = @(Get-Partition -DiskNumber $diskNumber | ForEach-Object {
                $volume = $_ | Get-Volume -ErrorAction SilentlyContinue
                if ($volume -and $volume.FileSystem -eq "FAT32" -and $_.DriveLetter -and [int][char]$_.DriveLetter -ne 0) { $_.DriveLetter }
            })
        if ($letters.Count -ne 1) { Fail "the card's FAT32 boot partition has no drive letter; re-insert the card" }
        $bootPath = "$($letters[0]):\"
    }
    $source = Join-Path $bootPath "rosy-diag"
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { Fail "no rosy-diag black box on the card at $source" }

    $device = "unknown-device"
    $bootId = "unknown-boot"
    $latest = Join-Path $source "latest.txt"
    if (Test-Path -LiteralPath $latest -PathType Leaf) {
        foreach ($line in Get-Content -LiteralPath $latest -TotalCount 20) {
            if ($line -match '^device:\s+(\S+)') { $device = Get-SafeName $Matches[1] '^[a-z0-9][a-z0-9-]{0,62}$' $device }
            if ($line -match '^boot_id:\s+(\S+)') { $bootId = Get-SafeName ($Matches[1] -replace '-', '') '^[0-9a-f]{32}$' $bootId }
        }
    }
    $destination = Join-Path (Join-Path (Join-Path $EvidenceRoot $device) $bootId) "card-rosy-diag"
    if (Test-Path -LiteralPath $destination) { Fail "evidence already exists and will not overwrite: $destination" }
    New-Item -ItemType Directory -Path $destination | Out-Null
    Get-ChildItem -LiteralPath $source -File | Copy-Item -Destination $destination
    Write-Output "CARD_BLACK_BOX=$destination"
    $disk = if ($null -ne $diskNumber) { $diskNumber } else { "<disk number from Get-Disk>" }
    $deep = Join-Path (Join-Path (Join-Path $EvidenceRoot $device) $bootId) "card-deep-read"
    Write-Output "The journal and ext4 state need an administrator PowerShell (read-only, no wsl --mount):"
    Write-Output "  python `"$DeepReader`" --disk $disk --out `"$deep`""
}

$output = @(& $SshExe @sshArguments $target $remoteCommand)
$code = $LASTEXITCODE
if ($code -eq 255) {
    if (-not $CardDisk) {
        Fail "SSH to $target is unreachable or refused the key (exit 255); insert the card and pass -CardDisk <serial> to copy its rosy-diag black box"
    }
    Write-Output "SSH to $target is unreachable (exit 255); copying the card's black box instead."
    Copy-CardBlackBox
    exit 0
}
if ($code -ne 0) { Fail "rosy-diag collect failed on $target (exit $code)" }

$line = @($output | Where-Object { "$_".TrimStart().StartsWith("{") } | Select-Object -Last 1)
if ($line.Count -ne 1) { Fail "rosy-diag collect printed no result" }
$result = $line[0] | ConvertFrom-Json
$remoteBundle = [string]$result.bundle
if ($remoteBundle -cnotmatch '^/tmp/rosy-diag\.[A-Za-z0-9]+/rosy-diag-[a-z0-9-]+-[0-9a-z]+-\d{8}T\d{6}Z\.tar\.gz$') {
    Fail "unexpected bundle path from the robot: $remoteBundle"
}
$remoteDir = $remoteBundle.Substring(0, $remoteBundle.LastIndexOf("/"))
$device = Get-SafeName ([string]$result.device_name) '^[a-z0-9][a-z0-9-]{0,62}$' "unknown-device"
$bootId = Get-SafeName (([string]$result.boot_id) -replace '-', '') '^[0-9a-f]{32}$' "unknown-boot"
$directory = Join-Path (Join-Path $EvidenceRoot $device) $bootId
$local = Join-Path $directory $remoteBundle.Substring($remoteBundle.LastIndexOf("/") + 1)
$partial = "$local.partial"

try {
    if ((Test-Path -LiteralPath $local) -or (Test-Path -LiteralPath $partial)) {
        Fail "evidence already exists and will not overwrite: $local"
    }
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    & $ScpExe @sshArguments "${target}:$remoteBundle" $partial
    if ($LASTEXITCODE -ne 0) { Fail "scp of $remoteBundle failed (exit $LASTEXITCODE)" }
    Move-Item -LiteralPath $partial -Destination $local
}
finally {
    & $SshExe @sshArguments $target "rm -rf $remoteDir" | Out-Null
}
Write-Output "BUNDLE=$local"
