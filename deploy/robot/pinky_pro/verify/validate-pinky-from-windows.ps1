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
    [ValidateRange(1, 300)]
    [int]$CommandTimeoutSec = 15,
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
$sshCommand = Get-Command "ssh" -ErrorAction SilentlyContinue
if (-not $sshCommand) {
    throw "Required command is unavailable: ssh"
}
$sshExecutable = $sshCommand.Source
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

function Invoke-BoundedSshProcess {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][int]$TimeoutSec,
        [Parameter(Mandatory)][string]$ScratchDirectory
    )

    $executablePayload = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($Executable)
    )
    $argumentJson = ConvertTo-Json -Compress -InputObject @($Arguments)
    $argumentPayload = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($argumentJson)
    )
    $childScript = @"
`$executable = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$executablePayload'))
`$argumentJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$argumentPayload'))
`$childArguments = @(ConvertFrom-Json -InputObject `$argumentJson)
`$output = (& `$executable @childArguments 2>&1 | Out-String).Trim()
`$exitCode = `$LASTEXITCODE
if (`$output) { [Console]::Out.Write(`$output) }
if (`$null -eq `$exitCode) { exit 255 }
exit [int]`$exitCode
"@
    $encodedChild = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($childScript)
    )
    $hostExecutable = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    $stdoutPath = Join-Path $ScratchDirectory ".ssh-$([Guid]::NewGuid().ToString('N')).stdout"
    $stderrPath = Join-Path $ScratchDirectory ".ssh-$([Guid]::NewGuid().ToString('N')).stderr"
    $process = $null
    try {
        $process = Start-Process -FilePath $hostExecutable `
            -ArgumentList @("-NoProfile", "-NonInteractive", "-EncodedCommand", $encodedChild) `
            -PassThru `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        $null = $process.Handle
        if (-not $process.WaitForExit($TimeoutSec * 1000)) {
            if ($env:OS -eq "Windows_NT") {
                try {
                    & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
                    if ($LASTEXITCODE -ne 0 -and -not $process.HasExited) {
                        throw "Unable to stop the timed-out SSH process."
                    }
                }
                catch {
                    # Natural exit after the deadline still counts as timeout.
                    if (-not $process.HasExited) { throw }
                }
            }
            elseif (-not $process.HasExited) {
                $process.Kill()
            }
            $process.WaitForExit()
            return [pscustomobject]@{
                TimedOut = $true
                ExitCode = $null
                Output = ""
            }
        }
        $stdout = (Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue)
        $stderr = (Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue)
        return [pscustomobject]@{
            TimedOut = $false
            ExitCode = $process.ExitCode
            Output = ($stdout | Out-String).Trim()
            Error = ($stderr | Out-String).Trim()
        }
    }
    finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Write-NewTextFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][Text.Encoding]$Encoding
    )

    $bytes = $Encoding.GetBytes($Text)
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
    }
    finally {
        $stream.Dispose()
    }
}

$connectionPassed = $false
try {
    & $peerVerifier `
        -PiHost $PiHost `
        -PiUser $PiUser `
        -NetworkInterface $NetworkInterface `
        -ApiPort $ApiPort `
        -ConnectTimeoutSec $ConnectTimeoutSec `
        -CommandTimeoutSec $CommandTimeoutSec `
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
    $readbackResult = Invoke-BoundedSshProcess `
        -Executable $sshExecutable `
        -Arguments $sshArguments `
        -TimeoutSec $CommandTimeoutSec `
        -ScratchDirectory $EvidenceDirectory
    if ($readbackResult.TimedOut) {
        Write-Warning "Device readback exceeded the wall-clock limit; the result remains HOLD."
    }
    elseif ($readbackResult.ExitCode -eq 0) {
        $readbackText = $readbackResult.Output
        try {
            $null = $readbackText | ConvertFrom-Json
            Write-NewTextFile `
                -Path $readbackPath `
                -Text $readbackText `
                -Encoding ([Text.UTF8Encoding]::new($false))
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
Write-NewTextFile `
    -Path $hashPath `
    -Text (($hashLines -join [Environment]::NewLine) + [Environment]::NewLine) `
    -Encoding ([Text.Encoding]::ASCII)

$summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
if ($summary.motion_authorized -ne $false) {
    throw "Invalid summary: stationary validation must keep motion_authorized false."
}
Write-Host "$($summary.outcome) STATIONARY_DEVICE_PREFLIGHT"
Write-Host "Dashboard: $($summary.dashboard_url)"
Write-Host "Evidence: $EvidenceDirectory"
Write-Host $summary.operator_message
exit $validationExitCode
