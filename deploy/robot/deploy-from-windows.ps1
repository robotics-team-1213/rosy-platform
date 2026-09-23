[CmdletBinding()]
param(
    [string]$RobotNumber = "",
    [string]$PiHost = "rosy-01.local",
    [string]$PiUser = "rosy",
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PiHost -notmatch '^[A-Za-z0-9.-]+$') {
    throw "PiHost must be a hostname or IPv4 address without shell characters."
}
if ($PiUser -notmatch '^[a-z_][a-z0-9_-]*$') {
    throw "PiUser is not a safe Linux account name."
}

# 신원은 로봇 번호 하나에서 나온다 (ADR D-33). 여기에 기본값을 두면 이 스크립트로
# 배포한 모든 기기가 같은 도메인과 같은 namespace 로 뜬다 — 설치기가 번호를
# 요구하는 이유와 똑같으므로 여기서도 요구한다. 호스트 이름에서 유추하지 않는다:
# rosy-01.local 은 기본값일 뿐이고 기기는 얼마든지 다른 이름을 쓴다.
if ([string]::IsNullOrWhiteSpace($RobotNumber)) {
    throw "RobotNumber is required: -RobotNumber 1 provisions ROS_DOMAIN_ID 41 and namespace rosy_01 (ADR D-33)."
}
# 앞자리 0 은 bash 산술이 팔진수로 읽어 010 을 8 로 만든다 — 설치기와 같은 규칙.
if ($RobotNumber -notmatch '^(0|[1-9][0-9]*)$') {
    throw "RobotNumber must be a decimal integer with no leading zero, got: $RobotNumber"
}
if (([int]$RobotNumber + 40) -gt 101) {
    throw "RobotNumber $RobotNumber gives ROS_DOMAIN_ID $([int]$RobotNumber + 40); the Linux-safe range ends at 101, so 61 is the last robot."
}

foreach ($commandName in @("git", "scp", "ssh")) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $commandName"
    }
}

$repoRoot = (& git rev-parse --show-toplevel 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    throw "Run this script from inside the Rosy Git repository."
}

Push-Location -LiteralPath $repoRoot
try {
    $dirtyState = (& git status --porcelain 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the Git worktree."
    }
    if (-not $AllowDirty -and -not [string]::IsNullOrWhiteSpace($dirtyState)) {
        throw "The worktree is dirty. Commit the release, or explicitly use -AllowDirty; only committed HEAD is uploaded."
    }

    $revision = (& git rev-parse HEAD 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to resolve the release revision."
    }
}
finally {
    Pop-Location
}

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempDir = [IO.Path]::GetFullPath((Join-Path $tempRoot ("rosy-deploy-" + [Guid]::NewGuid().ToString("N"))))
if (-not $tempDir.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or $tempDir -eq $tempRoot) {
    throw "Refusing to use a temporary path outside the system temp directory."
}

$archivePath = Join-Path $tempDir "rosy-release.tar.gz"
$checksumPath = Join-Path $tempDir "rosy-release.tar.gz.sha256"
$remoteTarget = "${PiUser}@${PiHost}"

try {
    New-Item -ItemType Directory -Path $tempDir | Out-Null

    Write-Host "Archiving committed revision $revision"
    Push-Location -LiteralPath $repoRoot
    try {
        & git archive --format=tar.gz --output=$archivePath HEAD
        $archiveExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($archiveExitCode -ne 0) {
        throw "git archive failed."
    }

    $archiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($checksumPath, "$archiveHash  rosy-release.tar.gz`n", [Text.UTF8Encoding]::new($false))

    Write-Host "Uploading release to $remoteTarget"
    & scp $archivePath $checksumPath "${remoteTarget}:/tmp/"
    if ($LASTEXITCODE -ne 0) {
        throw "scp upload failed."
    }

    $remoteCommand = @(
        "set -eu"
        "cd /tmp"
        "sha256sum -c rosy-release.tar.gz.sha256"
        "rm -rf -- /tmp/rosy-release"
        "mkdir -p /tmp/rosy-release"
        "tar -xzf rosy-release.tar.gz -C /tmp/rosy-release"
        "cd /tmp/rosy-release"
        "sudo ROSY_ROBOT_NUMBER=$RobotNumber bash deploy/robot/install-pi.sh"
        "sudo /opt/rosy/deploy/robot/verify/verify-pi.sh --require-internet"
        "cd /tmp"
        "rm -rf -- /tmp/rosy-release /tmp/rosy-release.tar.gz /tmp/rosy-release.tar.gz.sha256"
    ) -join "; "

    Write-Host "Installing Rosy and running Internet-required verification"
    & ssh -t $remoteTarget $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Remote installation or verification failed."
    }

    Write-Host "Deployment complete: http://${PiHost}:8080/dashboard"
    Write-Host "Release revision: $revision"

    $peerVerifier = Join-Path $repoRoot "deploy/robot/verify/verify-from-windows.ps1"
    Write-Host "Verifying API and dashboard from this Wi-Fi client"
    & $peerVerifier -PiHost $PiHost -PiUser $PiUser
}
finally {
    $cleanupPath = [IO.Path]::GetFullPath($tempDir)
    if ((Test-Path -LiteralPath $cleanupPath) -and
        $cleanupPath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        $cleanupPath -ne $tempRoot) {
        Remove-Item -LiteralPath $cleanupPath -Recurse -Force
    }
}
