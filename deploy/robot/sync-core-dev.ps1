# Invocation: sync-core-dev.ps1 -PiHost <host> -PiUser rosy -Backend docker
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PiHost,
    [Parameter(Mandatory = $true)]
    [string]$PiUser,
    [Parameter(Mandatory = $true)]
    [ValidateSet("docker", "native")]
    [string]$Backend
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PiHost -notmatch '^[A-Za-z0-9.-]+$') {
    throw "PiHost must be a hostname or IPv4 address without shell characters."
}
if ($PiUser -notmatch '^[a-z_][a-z0-9_-]*$') {
    throw "PiUser is not a safe Linux account name."
}
foreach ($commandName in @("python", "scp", "ssh")) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $commandName"
    }
}

$repoRoot = (& git rev-parse --show-toplevel 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    throw "Run this script from inside the Rosy Git repository."
}

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$tempDir = [IO.Path]::GetFullPath((Join-Path $tempRoot ("rosy-dev-" + [Guid]::NewGuid().ToString("N"))))
if (-not $tempDir.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or $tempDir -eq $tempRoot) {
    throw "Refusing to use a temporary path outside the system temp directory."
}

$archive = Join-Path $tempDir "core-dev.tar.gz"
$remote = "${PiUser}@${PiHost}"
try {
    New-Item -ItemType Directory -Path $tempDir | Out-Null
    & python -B (Join-Path $repoRoot "deploy/robot/core_dev_overlay.py") pack --repo $repoRoot --output $archive
    if ($LASTEXITCODE -ne 0) {
        throw "Allowlisted archive failed."
    }
    & scp $archive (Join-Path $repoRoot "deploy/robot/core_dev_overlay.py") (Join-Path $repoRoot "deploy/robot/apply-core-dev.sh") "${remote}:/tmp/"
    if ($LASTEXITCODE -ne 0) {
        throw "scp upload failed."
    }
    $remoteCommand = "chmod 755 /tmp/apply-core-dev.sh; /tmp/apply-core-dev.sh apply --archive /tmp/core-dev.tar.gz --backend $Backend --discover --execute"
    & ssh $remote $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Remote overlay apply failed."
    }
}
finally {
    $cleanup = [IO.Path]::GetFullPath($tempDir)
    if ((Test-Path -LiteralPath $cleanup) -and $cleanup.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and $cleanup -ne $tempRoot) {
        Remove-Item -LiteralPath $cleanup -Recurse -Force
    }
}
