[CmdletBinding()]
param(
    [string]$PiHost = "pinky-01.local",
    [string]$PiUser = "rosy",
    [string]$NetworkInterface = "eth0",
    [Parameter(Mandatory)]
    [ValidateRange(1, 101)]
    [int]$ExpectedRobotNumber,
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedRevision,
    [ValidateRange(1, 60)]
    [int]$ConnectTimeoutSec = 5,
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8080,
    [string]$EvidenceDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PiHost -notmatch '^[A-Za-z0-9.-]+$') {
    throw "PiHost must be a hostname or IPv4 address without shell characters."
}
if ($PiUser -notmatch '^[a-z_][a-z0-9_-]*$') {
    throw "PiUser is not a safe Linux account name."
}
if ($NetworkInterface -ne "auto" -and
    $NetworkInterface -notmatch '^[A-Za-z0-9_.:-]+$') {
    throw "NetworkInterface must be auto or a safe Linux interface name."
}
if (-not (Get-Command "ssh" -ErrorAction SilentlyContinue)) {
    throw "Required command is unavailable: ssh"
}
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    throw "Required command is unavailable: python"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$robotRoot = Split-Path -Parent $scriptRoot
$peerVerifier = Join-Path $scriptRoot "verify-from-windows.ps1"
$evaluator = Join-Path $robotRoot "pinky_validation.py"
if (-not (Test-Path -LiteralPath $peerVerifier -PathType Leaf) -or
    -not (Test-Path -LiteralPath $evaluator -PathType Leaf)) {
    throw "The stationary validation kit is incomplete."
}

if (-not $EvidenceDirectory) {
    $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $EvidenceDirectory = Join-Path $PWD "pinky-validation-$stamp"
}
$EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
if (Test-Path -LiteralPath $EvidenceDirectory) {
    throw "EvidenceDirectory already exists; refusing to replace prior evidence."
}
$evidenceParent = Split-Path -Parent $EvidenceDirectory
if (-not $evidenceParent -or -not (Test-Path -LiteralPath $evidenceParent -PathType Container)) {
    throw "EvidenceDirectory parent must already exist."
}
$null = New-Item -ItemType Directory -Path $EvidenceDirectory

$connectionPath = Join-Path $EvidenceDirectory "G0-connection.json"
$readbackPath = Join-Path $EvidenceDirectory "G2-device-readback.json"
$summaryPath = Join-Path $EvidenceDirectory "user-validation-summary.json"
$hashPath = Join-Path $EvidenceDirectory "SHA256SUMS.txt"

$connectionPassed = $false
try {
    & $peerVerifier `
        -PiHost $PiHost `
        -PiUser $PiUser `
        -NetworkInterface $NetworkInterface `
        -ApiPort $ApiPort `
        -ConnectTimeoutSec $ConnectTimeoutSec `
        -BatchMode `
        -EvidencePath $connectionPath
    $connectionPassed = $true
}
catch {
    Write-Warning "Connection is HOLD. The evidence bundle will remain stationary and fail closed."
}

$readbackAvailable = $false
if ($connectionPassed) {
    $remoteTarget = "${PiUser}@${PiHost}"
    $sshArguments = @(
        "-o", "ConnectTimeout=$ConnectTimeoutSec",
        "-o", "ConnectionAttempts=1",
        "-o", "BatchMode=yes",
        $remoteTarget,
        "sudo -n /opt/rosy/deploy/robot/verify/device-readback.sh --json"
    )
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $readbackText = (& ssh @sshArguments 2>&1 | Out-String).Trim()
        $readbackExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($readbackExitCode -eq 0) {
        try {
            $null = $readbackText | ConvertFrom-Json
            Set-Content -LiteralPath $readbackPath -Value $readbackText -Encoding utf8
            $readbackAvailable = $true
        }
        catch {
            Write-Warning "Device readback was not valid JSON; the result remains HOLD."
        }
    }
    else {
        Write-Warning "Device readback failed; use the Pi console if non-interactive sudo is unavailable."
    }
}

$evaluationArguments = @(
    $evaluator,
    "--connection", $connectionPath,
    "--expected-robot-number", $ExpectedRobotNumber,
    "--expected-revision", $ExpectedRevision,
    "--api-port", $ApiPort,
    "--output", $summaryPath
)
if ($readbackAvailable) {
    $evaluationArguments += @("--readback", $readbackPath)
}
& python @evaluationArguments
$validationExitCode = $LASTEXITCODE
if ($validationExitCode -notin @(0, 2)) {
    throw "The stationary evidence evaluator failed."
}

$evidenceFiles = @($connectionPath, $summaryPath)
if ($readbackAvailable) {
    $evidenceFiles += $readbackPath
}
$hashLines = foreach ($path in $evidenceFiles) {
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    "$digest  $([IO.Path]::GetFileName($path))"
}
Set-Content -LiteralPath $hashPath -Value $hashLines -Encoding ascii

$summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
if ($summary.motion_authorized -ne $false) {
    throw "Invalid summary: stationary validation must keep motion_authorized false."
}
Write-Host "$($summary.outcome) STATIONARY_DEVICE_PREFLIGHT"
Write-Host "Dashboard: $($summary.dashboard_url)"
Write-Host "Evidence: $EvidenceDirectory"
Write-Host $summary.operator_message
exit $validationExitCode
