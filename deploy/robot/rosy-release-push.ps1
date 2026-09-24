[CmdletBinding()]
param(
    [string]$Robot,
    [string]$ReleaseDir,
    [string]$Tarball,
    [switch]$Rollback,
    [switch]$PrintCommands,
    [string]$RosyUser = "rosy",
    [string]$KeyPath = "",
    [string]$KnownHosts = "",
    [string]$PublicKeyPath = "",
    [string]$ActivateWrapper = "/opt/rosy/native-runtime/activate-release.sh",
    [string]$RollbackWrapper = "/opt/rosy/native-runtime/rollback-release.sh",
    [string]$CoreReadyProbe = "/opt/rosy/native-runtime/wait-core-ready.py",
    [string]$RemoteReleasesDir = "/opt/rosy/releases",
    [string]$RemoteStagingDir = "",
    [string]$PythonExe = "python",
    [string]$SshExe = "ssh",
    [string]$ScpExe = "scp",
    [string]$TarExe = "tar"
)
# D-230 Decision 2.3: push a signed native payload release from the operator
# PC to an existing robot and activate it (or roll it back), without a card
# re-flash. This completes the payload-transition path native_release.py
# already verifies on-device: build-native-payload.sh/sign_image_release.py
# produce the signed release directory, this script gets it there.
#
# Every remote scp/ssh invocation is built once, by Get-RemoteCommandPlan, so
# -PrintCommands shows exactly what -Robot would receive and normal execution
# runs the same array of arguments. Nothing here signs or re-verifies crypto:
# the local pre-flight calls the repository's own signing.verify_release_files
# (deploy/release/signing.py), and the device-side signature/manifest checks
# remain entirely inside native_release.py via activate-release.sh /
# rollback-release.sh. This script never disables SSH host-key checking.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

if (-not $Robot) { Fail "Robot is required (hostname or IP of the target device)." }
if ($Robot -notmatch '^[A-Za-z0-9.-]+$') {
    Fail "Robot must be a hostname or IPv4 address without shell characters."
}
if ($RosyUser -notmatch '^[a-z_][a-z0-9_-]*$') {
    Fail "RosyUser is not a safe Linux account name."
}

if ($Rollback) {
    if ($ReleaseDir -or $Tarball) {
        Fail "-Rollback does not take -ReleaseDir or -Tarball; rollback reactivates the release already in /opt/rosy/previous."
    }
} else {
    if ($ReleaseDir -and $Tarball) {
        Fail "Pass exactly one of -ReleaseDir or -Tarball, not both."
    }
    if (-not $ReleaseDir -and -not $Tarball) {
        Fail "Pass -ReleaseDir <signed release directory> or -Tarball <packed release>, or use -Rollback."
    }
}

if (-not $KeyPath) {
    $KeyPath = Join-Path $env:LOCALAPPDATA "Rosy\ssh\rosy-operator-ed25519"
}
if (-not $KnownHosts) {
    $KnownHosts = Join-Path $env:LOCALAPPDATA "Rosy\known_hosts"
}
if (-not $PublicKeyPath) {
    $PublicKeyPath = Join-Path $PSScriptRoot "..\release\public-keys\rosy-release-2026-01.pem"
}
if (-not $RemoteStagingDir) {
    $RemoteStagingDir = "/home/$RosyUser/.rosy-release-push"
}
$PublicKeyPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PublicKeyPath)
$KeyPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($KeyPath)
$KnownHosts = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($KnownHosts)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).ProviderPath
$signingDir = Join-Path $repoRoot "deploy\release"
$unpackScript = Join-Path $PSScriptRoot "rosy-release-unpack.sh"

# --- local, network-free steps: resolve the release and verify its signature -

$releaseId = $null
$stagingRoot = $null
$verification = $null
$tarballPath = $null

function New-TempDirectory([string]$Prefix) {
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $path = [IO.Path]::GetFullPath((Join-Path $tempRoot ($Prefix + [Guid]::NewGuid().ToString("N"))))
    if (-not $path.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or $path -eq $tempRoot) {
        Fail "Refusing to use a temporary path outside the system temp directory."
    }
    New-Item -ItemType Directory -Path $path | Out-Null
    return $path
}

# PowerShell 5.1 turns a native command's stderr, once merged with 2>&1, into
# a terminating NativeCommandError under $ErrorActionPreference = "Stop" (this
# script's setting) -- the first stderr line (a warning, or a real rejection
# list on a controlled non-zero exit) would abort before the caller ever sees
# it. Every native call goes through here, which switches to "Continue" only
# around the call, mirroring verify-from-windows.ps1's Invoke-RosySsh.
function Invoke-NativeCapture([string]$Executable, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $lines = @(& $Executable @Arguments 2>&1 | ForEach-Object { [string]$_ })
    } finally {
        $ErrorActionPreference = $previous
    }
    return [ordered]@{ exit_code = $LASTEXITCODE; output = $lines }
}

# GNU tar reads an archive path that starts with a drive letter ("X:\...") as
# a remote "host:path" spec and tries to open an rsh connection; bsdtar (the
# tar.exe already on a stock Windows 10/11 PATH) has no --force-local to turn
# that heuristic off. The fix is to cd into the archive's own folder and pass
# a bare filename instead of ever putting a drive letter in the -f argument;
# -C with an absolute content directory is fine for a create. An extract's -C
# target came out corrupted the same way through MSYS2 Git's tar (its own
# argv path translation) even as an absolute path, so an extract additionally
# copies the archive into the (empty) destination and runs entirely relative.
function Invoke-Tar([string]$Mode, [string]$ArchivePath, [string]$ContentDir) {
    if ($Mode -eq "create") {
        $archiveDir = Split-Path -Parent $ArchivePath
        $archiveName = Split-Path -Leaf $ArchivePath
        Push-Location -LiteralPath $archiveDir
        try {
            & $TarExe -czf $archiveName -C $ContentDir "."
            return $LASTEXITCODE
        } finally {
            Pop-Location
        }
    }
    $localArchive = Join-Path $ContentDir "_rosy-release-push.tar.gz"
    Copy-Item -LiteralPath $ArchivePath -Destination $localArchive -Force
    Push-Location -LiteralPath $ContentDir
    try {
        & $TarExe -xzf "_rosy-release-push.tar.gz" -C "."
        return $LASTEXITCODE
    } finally {
        Remove-Item -LiteralPath $localArchive -Force -ErrorAction SilentlyContinue
        Pop-Location
    }
}

function Test-LocalReleaseSignature([string]$Directory, [string]$PublicKey) {
    # Reuses deploy/release/signing.py:verify_release_files exactly as
    # native_release.py does on-device (signature over SHA256SUMS first, then
    # every payload hash). No crypto is reimplemented here.
    $code = @"
import json, sys
sys.path.insert(0, r'$signingDir')
from pathlib import Path
from signing import verify_release_files
rejections = verify_release_files(Path(r'$Directory'), Path(r'$PublicKey'))
# dict(...) rather than a {"key": ...} literal: embedded double quotes do not
# survive PowerShell's argv join to a native exe on Windows (they are eaten
# before python -c ever sees them), which this line proved the hard way when
# the good-fixture case (an empty rejections list) hid it.
print(json.dumps([dict(code=r.code, field=r.field, detail=r.detail) for r in rejections]))
sys.exit(1 if rejections else 0)
"@
    $result = Invoke-NativeCapture $PythonExe @("-c", $code)
    if ($result.exit_code -ne 0 -and $result.exit_code -ne 1) {
        Fail "Local signature verifier could not run: $($result.output -join [Environment]::NewLine)"
    }
    # The rejection list is kept as the raw JSON line the verifier printed
    # (not re-parsed into PowerShell objects): PowerShell 5.1 mangles an
    # empty JSON array on the ConvertFrom-Json/ConvertTo-Json round trip.
    # A caller that needs the structured list parses rejections_json itself.
    $rejectionsJson = [string]($result.output | Select-Object -Last 1)
    return [ordered]@{ ok = ($result.exit_code -eq 0); rejections_json = $rejectionsJson }
}

if (-not $Rollback) {
    if ($Tarball) {
        $Tarball = (Resolve-Path -LiteralPath $Tarball).ProviderPath
        $stagingRoot = New-TempDirectory "rosy-release-push-"
        if ((Invoke-Tar "extract" $Tarball $stagingRoot) -ne 0) {
            Fail "Failed to extract -Tarball $Tarball for local verification."
        }
        $releaseDirResolved = $stagingRoot
        $tarballPath = $Tarball
    } else {
        $releaseDirResolved = (Resolve-Path -LiteralPath $ReleaseDir).ProviderPath
    }

    $manifestPath = Join-Path $releaseDirResolved "manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        Fail "manifest.json is missing from the release: $releaseDirResolved"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $releaseId = [string]$manifest.release_id
    if ($releaseId -notmatch '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$') {
        Fail "manifest.json release_id is not YYYY.MM.DD-NNN: $releaseId"
    }

    $verification = Test-LocalReleaseSignature $releaseDirResolved $PublicKeyPath
    if (-not $verification.ok) {
        Fail "SIGNATURE_VERIFY_FAILED: $releaseId does not verify against $PublicKeyPath -- $($verification.rejections_json)"
    }

    if (-not $tarballPath) {
        $buildDir = New-TempDirectory "rosy-release-push-"
        $tarballPath = Join-Path $buildDir "$releaseId.tar.gz"
        if ((Invoke-Tar "create" $tarballPath $releaseDirResolved) -ne 0) {
            Fail "Failed to pack -ReleaseDir $releaseDirResolved into a tarball."
        }
    }
}

# --- the one function every remote command is built by ---------------------

function ConvertTo-DisplayLine([string]$Executable, [string[]]$Arguments) {
    $quoted = $Arguments | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }
    return (@($Executable) + $quoted) -join " "
}

function Get-RemoteCommandPlan {
    param(
        [string]$Robot, [string]$RosyUser, [string]$KeyPath, [string]$KnownHosts,
        [switch]$Rollback, [string]$ReleaseId, [string]$TarballPath, [string]$UnpackScript,
        [string]$RemoteStagingDir, [string]$RemoteReleasesDir,
        [string]$ActivateWrapper, [string]$RollbackWrapper, [string]$CoreReadyProbe,
        [string]$SshExe, [string]$ScpExe
    )
    $target = "${RosyUser}@${Robot}"
    $sshOptions = @("-o", "UserKnownHostsFile=$KnownHosts", "-o", "StrictHostKeyChecking=yes")
    $plan = New-Object System.Collections.ArrayList

    function Add-Step($list, [string]$Kind, [string]$Executable, [string[]]$Arguments) {
        [void]$list.Add([ordered]@{
            kind       = $Kind
            executable = $Executable
            arguments  = $Arguments
            display    = ConvertTo-DisplayLine $Executable $Arguments
        })
    }

    if ($Rollback) {
        Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "sudo", "-n", $RollbackWrapper))
        Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "python3", "-B", $CoreReadyProbe))
        return $plan
    }

    $remoteTarball = "$RemoteStagingDir/$ReleaseId.tar.gz"
    $remoteUnpack = "$RemoteStagingDir/rosy-release-unpack.sh"

    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "mkdir", "-p", $RemoteStagingDir))
    Add-Step $plan "scp" $ScpExe (@("-i", $KeyPath) + $sshOptions + @($TarballPath, "${target}:${remoteTarball}"))
    Add-Step $plan "scp" $ScpExe (@("-i", $KeyPath) + $sshOptions + @($UnpackScript, "${target}:${remoteUnpack}"))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "chmod", "+x", $remoteUnpack))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "sudo", "-n", $remoteUnpack, $ReleaseId, $remoteTarball, $RemoteReleasesDir))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "sudo", "-n", $ActivateWrapper, $ReleaseId))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "python3", "-B", $CoreReadyProbe))
    return $plan
}

$plan = Get-RemoteCommandPlan -Robot $Robot -RosyUser $RosyUser -KeyPath $KeyPath -KnownHosts $KnownHosts `
    -Rollback:$Rollback -ReleaseId $releaseId -TarballPath $tarballPath -UnpackScript $unpackScript `
    -RemoteStagingDir $RemoteStagingDir -RemoteReleasesDir $RemoteReleasesDir `
    -ActivateWrapper $ActivateWrapper -RollbackWrapper $RollbackWrapper -CoreReadyProbe $CoreReadyProbe `
    -SshExe $SshExe -ScpExe $ScpExe

if ($PrintCommands) {
    $result = [ordered]@{
        release_id = $releaseId
        rollback   = [bool]$Rollback
        verification = $verification
        plan       = @($plan)
    }
    $result | ConvertTo-Json -Depth 8
    exit 0
}

# --- execution: run exactly the plan just built -----------------------------

foreach ($step in $plan) {
    Write-Host "+ $($step.display)"
    $result = Invoke-NativeCapture $step.executable $step.arguments
    if ($result.exit_code -ne 0) {
        Fail "$($step.kind) failed (exit $($result.exit_code)): $($step.display)`n$($result.output -join [Environment]::NewLine)"
    }
    if ($result.output) { Write-Host ($result.output -join [Environment]::NewLine) }

    $arguments = $step.arguments
    if ($arguments -contains $ActivateWrapper -or $arguments -contains $RollbackWrapper) {
        $lastLine = ($result.output | Select-Object -Last 1)
        try {
            $activation = $lastLine | ConvertFrom-Json
            Write-Host "current release: $($activation.release_id) (previous: $($activation.previous))"
        } catch {
            Write-Warning "activation wrapper did not print the expected JSON result line."
        }
    }
    if ($arguments -contains $CoreReadyProbe) {
        Write-Host "CORE readiness: PASS"
    }
}

Write-Host "done."
