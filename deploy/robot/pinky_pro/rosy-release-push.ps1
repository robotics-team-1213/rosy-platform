[CmdletBinding()]
param(
    [string]$Robot,
    [string]$ReleaseDir,
    [string]$Tarball,
    [switch]$Rollback,
    [switch]$PrintCommands,
    [switch]$SkipImageLayerSync,
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
    [string]$TarExe = "tar",
    [switch]$Force,
    [string]$ApiToken = "",
    [int]$ApiPort = 8080
)
# D-225 Decision 2.3: push a signed native payload release from the operator
# PC to an existing robot and activate it (or roll it back), without a card
# re-flash. This completes the payload-transition path native_release.py
# already verifies on-device: build-native-payload.sh/sign_image_release.py
# produce the signed release directory, this script gets it there.
#
# Every remote scp/ssh invocation is built once, by Get-RemoteCommandPlan, so
# -PrintCommands shows exactly what -Robot would receive and normal execution
# runs the same array of arguments. Nothing here signs or re-verifies crypto:
# the local pre-flight calls the repository's own signing.verify_release_files
# (deploy/robot/pinky_pro/release/signing.py), and the device-side signature/manifest checks
# remain entirely inside native_release.py via activate-release.sh /
# rollback-release.sh. This script never disables SSH host-key checking.
#
# D-388: after activation (or rollback) and CORE readiness, the release that is
# now current brings the image layer (native-runtime scripts, rosy units, udev
# rules, modprobe options) up to its own copy with sync-image-layer.py, which
# ships inside the release: first a dry run that prints the plan, then the
# apply. The active units it reports as changed are restarted here, and CORE
# readiness is checked again if anything was restarted. -SkipImageLayerSync
# leaves the image layer alone.

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
    if ($ReleaseDir -and -not $PrintCommands) {
        # Windows tar cannot represent a POSIX exec bit: rebuilding the
        # tarball here would silently strip +x from every payload script and
        # activation would fail on-device with no signature-verification
        # signal pointing at why. A real push only accepts a tarball a Linux
        # build already packed (build-native-payload.sh on the payload-build
        # branch); -ReleaseDir is accepted only to preview the plan shape.
        Fail ("-ReleaseDir only works with -PrintCommands (a preview): repacking a release " +
              "directory with Windows tar loses POSIX exec bits and the pushed release would " +
              "fail to activate. Build the release tarball on Linux (build-native-payload.sh) " +
              "and pass it with -Tarball for a real push.")
    }
}

if (-not $KeyPath) {
    $KeyPath = Join-Path $env:LOCALAPPDATA "Rosy\ssh\rosy-operator-ed25519"
}
if (-not $KnownHosts) {
    $KnownHosts = Join-Path $env:LOCALAPPDATA "Rosy\known_hosts"
}
if (-not $PublicKeyPath) {
    $PublicKeyPath = Join-Path $PSScriptRoot "release\public-keys\rosy-release-2026-01.pem"
}
if (-not $RemoteStagingDir) {
    $RemoteStagingDir = "/home/$RosyUser/.rosy-release-push"
}
$PublicKeyPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PublicKeyPath)
$KeyPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($KeyPath)
$KnownHosts = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($KnownHosts)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).ProviderPath
$signingDir = Join-Path $repoRoot "deploy\robot\pinky_pro\release"
$unpackScript = Join-Path $PSScriptRoot "rosy-release-unpack.sh"

# --- local, network-free steps: resolve the release and verify its signature -

$releaseId = $null
$stagingRoot = $null
$verification = $null
$tarballPath = $null
$tempDirsToClean = New-Object System.Collections.Generic.List[string]

function New-TempDirectory([string]$Prefix) {
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $path = [IO.Path]::GetFullPath((Join-Path $tempRoot ($Prefix + [Guid]::NewGuid().ToString("N"))))
    if (-not $path.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or $path -eq $tempRoot) {
        Fail "Refusing to use a temporary path outside the system temp directory."
    }
    New-Item -ItemType Directory -Path $path | Out-Null
    $tempDirsToClean.Add($path)
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
    # Reuses deploy/robot/pinky_pro/release/signing.py:verify_release_files exactly as
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

try {

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

function Get-CoreReadyArguments([string]$CoreReadyProbe) {
    # rosy-core.service gets its API port (and everything else device-
    # specific) from /etc/rosy/runtime.env via systemd's EnvironmentFile=; a
    # plain non-login SSH command runs no unit and no shell profile, so
    # without this the probe would run with none of that and silently fall
    # back to its own hardcoded default port. Source the same file the unit
    # loads, then run the existing bounded probe unchanged.
    return @(
        "bash", "-lc",
        "'set -a; [ -f /etc/rosy/runtime.env ] && . /etc/rosy/runtime.env; set +a; exec python3 -B $CoreReadyProbe'"
    )
}

function Get-CoreReleaseCheckArguments {
    # An activator older than the fix in native_release.py stops only
    # rosy-runtime.target; CORE's stop job is then cancelled by the start and
    # CORE keeps serving the old release while readiness passes (9dfk,
    # 2026-10-01). The fixed activator reaches a robot only with the image-layer
    # sync, which runs AFTER activation, so check here: CORE's main process
    # must run from /opt/rosy/current, else restart rosy-core (the units that
    # Require it restart with it). No quotes inside: PowerShell 5.1 eats double
    # quotes and the body travels in single quotes, so the cwd (which may end
    # in " (deleted)") is compared with case, which does not split words.
    # A failed restart still exits 0 so the push can name -Rollback as the fix.
    $script = 'p=$(systemctl show -p MainPID --value rosy-core.service); ' +
        'c=$(readlink /proc/$p/cwd); w=$(readlink -f /opt/rosy/current); s=stale; ' +
        'if [ x$p != x0 ] && [ x$w != x ]; then case x$c in x$w) s=ok;; esac; fi; ' +
        'if [ $s = ok ]; then echo CORE_RELEASE_OK $w; ' +
        'else echo CORE_RELEASE_STALE pid=$p cwd=$c want=$w; ' +
        'if systemctl restart rosy-core.service; ' +
        'then echo CORE_RESTARTED $(readlink /proc/$(systemctl show -p MainPID --value rosy-core.service)/cwd); ' +
        'else echo CORE_RESTART_FAILED; fi; fi'
    return @("sudo", "-n", "sh", "-c", "'$script'")
}

function Get-ImageLayerSyncArguments([string]$ReleaseId, [switch]$DryRun) {
    # A push runs the script of the release it just activated. After a
    # rollback the release that became current may predate D-388, so fall back
    # to the copy in the release rolled away from (it still syncs from current).
    $flag = ""
    if ($DryRun) { $flag = " --dry-run" }
    if ($ReleaseId) {
        $arguments = @("sudo", "-n", "python3", "-B", "/opt/rosy/releases/$ReleaseId/deploy/robot/native/sync-image-layer.py")
        if ($DryRun) { $arguments += "--dry-run" }
        return $arguments
    }
    $candidates = "/opt/rosy/current/deploy/robot/native/sync-image-layer.py /opt/rosy/previous/deploy/robot/native/sync-image-layer.py"
    return @(
        "sudo", "-n", "sh", "-c",
        "'for s in $candidates; do if [ -f `$s ]; then exec python3 -B `$s$flag; fi; done; echo IMAGE_LAYER_SYNC_MISSING >&2; exit 3'"
    )
}

function Get-ClaimTtl([long]$TarballBytes) {
    # The claim must outlive the whole push: 1200 s for activation, readiness
    # and the image-layer sync, plus the upload at a pessimistic 0.5 MB/s.
    # Bounded to [1800, 7200] s; a crashed push frees the robot within that.
    $seconds = 1200 + 2 * [Math]::Ceiling($TarballBytes / 1MB)
    return [int][Math]::Min(7200, [Math]::Max(1800, $seconds))
}

function Get-ClaimArguments([string]$Action, [string]$Holder, [int]$ClaimTtl = 1800) {
    # D-387/D-406 claim: the push and the robot's auto-updater never run at the
    # same time. The helper ships in native-runtime from D-406 on; an older
    # robot has none, so the wrapper says so instead of failing. Single quotes
    # only: PowerShell 5.1 eats embedded double quotes.
    $helper = "/opt/rosy/native-runtime/rosy_claim.py"
    $call = "$helper $Action --holder $Holder"
    if ($Action -eq "acquire") { $call += " --purpose push --ttl-s $ClaimTtl" }
    if ($Action -eq "refresh") { $call += " --ttl-s $ClaimTtl" }
    return @(
        "sudo", "-n", "sh", "-c",
        "'if [ -f $helper ]; then exec python3 $call; fi; echo ROSY_CLAIM_HELPER_MISSING; exit 4'"
    )
}

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
        [string]$SshExe, [string]$ScpExe, [switch]$SkipImageLayerSync, [string]$ClaimHolder, [int]$ClaimTtl
    )
    $target = "${RosyUser}@${Robot}"
    # ssh parses a "-o Key=Value" argument the way it parses an ssh_config
    # line: an unquoted Value is split on whitespace. Quoting it here does not
    # help: Windows PowerShell 5.1 passes UserKnownHostsFile="C:\a b\k" on the
    # command line as is, and the C runtime strips those quotes before ssh
    # sees the value (test_known_hosts_policy.py). So a path ssh would split,
    # or one with a quote, is refused (same policy as rosy-update-hold.ps1).
    if ($KnownHosts -match "[\s`"']") {
        Fail "KnownHosts path contains a space or a quote, which ssh -o would split: $KnownHosts. Pass -KnownHosts <path without spaces>."
    }
    $sshOptions = @("-o", "UserKnownHostsFile=$KnownHosts", "-o", "StrictHostKeyChecking=yes")
    $plan = New-Object System.Collections.ArrayList

    function Add-Step($list, [string]$Kind, [string]$Executable, [string[]]$Arguments,
                      [string]$Role = "", [string]$DisplaySuffix = "") {
        [void]$list.Add([ordered]@{
            kind       = $Kind
            role       = $Role
            executable = $Executable
            arguments  = $Arguments
            display    = (ConvertTo-DisplayLine $Executable $Arguments) + $DisplaySuffix
        })
    }

    # D-388: dry run, apply, restart the active units it changed (their names
    # come from the apply's JSON, so the display names a placeholder), and
    # re-check CORE only when something was restarted. A rollback skips that
    # conditional re-check: its own readiness check always follows the sync.
    function Add-ImageLayerSteps($list, [string]$SyncReleaseId, [switch]$NoReadyCheck) {
        $ssh = @("-i", $KeyPath) + $sshOptions + @($target)
        Add-Step $list "ssh" $SshExe ($ssh + (Get-ImageLayerSyncArguments $SyncReleaseId -DryRun)) "image-layer-dry-run"
        Add-Step $list "ssh" $SshExe ($ssh + (Get-ImageLayerSyncArguments $SyncReleaseId)) "image-layer-apply"
        Add-Step $list "ssh" $SshExe ($ssh + @("sudo", "-n", "systemctl", "restart")) "image-layer-restart" " <active units the apply changed>"
        if (-not $NoReadyCheck) {
            Add-Step $list "ssh" $SshExe ($ssh + (Get-CoreReadyArguments $CoreReadyProbe)) "image-layer-core-ready"
        }
    }

    # The claim brackets every other step; the execution loop runs the release
    # in its finally block, so a failed step still lets the claim go.
    $claimSsh = @("-i", $KeyPath) + $sshOptions + @($target)
    Add-Step $plan "ssh" $SshExe ($claimSsh + (Get-ClaimArguments "acquire" $ClaimHolder $ClaimTtl)) "claim-acquire"

    if ($Rollback) {
        # D-388: sync the image layer back to the release that became current
        # BEFORE the readiness check. If the newer release's units or scripts
        # do not work with the older one, CORE is only ready after the sync.
        # The core-release check follows the sync for the same reason: a CORE
        # restarted into the older release before its units are back may fail.
        Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "sudo", "-n", $RollbackWrapper))
        if (-not $SkipImageLayerSync) { Add-ImageLayerSteps $plan "" -NoReadyCheck }
        Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target) + (Get-CoreReleaseCheckArguments)) "core-release-check"
        Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target) + (Get-CoreReadyArguments $CoreReadyProbe))
        Add-Step $plan "ssh" $SshExe ($claimSsh + (Get-ClaimArguments "release" $ClaimHolder)) "claim-release"
        return $plan
    }

    $remoteTarball = "$RemoteStagingDir/$ReleaseId.tar.gz"
    $remoteUnpack = "$RemoteStagingDir/rosy-release-unpack.sh"

    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "mkdir", "-p", $RemoteStagingDir))
    Add-Step $plan "scp" $ScpExe (@("-i", $KeyPath) + $sshOptions + @($TarballPath, "${target}:${remoteTarball}"))
    # The upload is the long part: restart the claim's TTL after it.
    Add-Step $plan "ssh" $SshExe ($claimSsh + (Get-ClaimArguments "refresh" $ClaimHolder $ClaimTtl)) "claim-refresh"
    Add-Step $plan "scp" $ScpExe (@("-i", $KeyPath) + $sshOptions + @($UnpackScript, "${target}:${remoteUnpack}"))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "chmod", "+x", $remoteUnpack))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "sudo", "-n", $remoteUnpack, $ReleaseId, $remoteTarball, $RemoteReleasesDir))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target, "sudo", "-n", $ActivateWrapper, $ReleaseId))
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target) + (Get-CoreReleaseCheckArguments)) "core-release-check"
    Add-Step $plan "ssh" $SshExe (@("-i", $KeyPath) + $sshOptions + @($target) + (Get-CoreReadyArguments $CoreReadyProbe))
    if (-not $SkipImageLayerSync) { Add-ImageLayerSteps $plan $ReleaseId }
    Add-Step $plan "ssh" $SshExe ($claimSsh + (Get-ClaimArguments "release" $ClaimHolder)) "claim-release"
    return $plan
}

# The claim holder travels inside a single-quoted remote shell line: keep only
# characters that need no quoting there.
$claimHolder = "push-$env:USERNAME@$env:COMPUTERNAME" -replace '[^A-Za-z0-9._@-]', '_'
$claimTtl = 1800
if ($tarballPath) { $claimTtl = Get-ClaimTtl (Get-Item -LiteralPath $tarballPath).Length }

$plan = Get-RemoteCommandPlan -Robot $Robot -RosyUser $RosyUser -KeyPath $KeyPath -KnownHosts $KnownHosts `
    -Rollback:$Rollback -ReleaseId $releaseId -TarballPath $tarballPath -UnpackScript $unpackScript `
    -RemoteStagingDir $RemoteStagingDir -RemoteReleasesDir $RemoteReleasesDir `
    -ActivateWrapper $ActivateWrapper -RollbackWrapper $RollbackWrapper -CoreReadyProbe $CoreReadyProbe `
    -SshExe $SshExe -ScpExe $ScpExe -SkipImageLayerSync:$SkipImageLayerSync -ClaimHolder $claimHolder -ClaimTtl $claimTtl

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

# --- calibration guard (D-321 addendum) -------------------------------------
# Activation restarts rosy-runtime.target, which cuts any calibration drive
# short. Ask CORE for an active calibration session first and refuse unless
# -Force. The check itself is soft: no token or no answer only warns.
$calibrationGuard = Join-Path $PSScriptRoot "rosy-calibration-guard.ps1"
& $calibrationGuard -Robot $Robot -Action "a release push/rollback (CORE restart)" `
    -ApiPort $ApiPort -ApiToken $ApiToken -Force:$Force
if ($LASTEXITCODE -eq 3) {
    Fail "Release push refused: a calibration session is active on $Robot. Wait for it to end or pass -Force."
}

# --- execution: run exactly the plan just built -----------------------------

$imageLayer = $null
$imageLayerSkipped = $false
$restartedUnits = @()

function Read-LastJsonLine($Output) {
    try {
        return (($Output | Select-Object -Last 1) | ConvertFrom-Json)
    } catch {
        return $null
    }
}

$claimed = $false

foreach ($step in $plan) {
    $arguments = $step.arguments
    if ($step.role -eq "claim-release") { continue }  # runs in the finally block below
    if ($step.role -eq "claim-refresh" -and -not $claimed) { continue }
    if ($step.role -like "image-layer-*" -and $imageLayerSkipped) { continue }
    if ($step.role -eq "image-layer-restart") {
        $restartedUnits = @($imageLayer.restart_units | Where-Object { $_ -match '^rosy-[A-Za-z0-9-]+\.(service|path|timer)$' })
        if ($restartedUnits.Count -eq 0) {
            Write-Host "image-layer sync: no active unit needs a restart"
            continue
        }
        $arguments = @($arguments) + $restartedUnits
    }
    if ($step.role -eq "image-layer-core-ready" -and $restartedUnits.Count -eq 0) { continue }

    $display = ConvertTo-DisplayLine $step.executable $arguments
    Write-Host "+ $display"
    if ($step.role -eq "claim-acquire") {
        # From here on the release in finally runs: a failed or lost answer
        # may still have taken the claim, and the release is holder-scoped.
        $claimed = $true
    }
    $result = Invoke-NativeCapture $step.executable $arguments
    if ($step.role -eq "claim-acquire") {
        $answer = $result.output -join " "
        if ($answer -match "ROSY_CLAIM_HELPER_MISSING") {
            $claimed = $false
            Write-Warning "$Robot has no rosy_claim.py (native-runtime older than D-406): pushing without the claim; its auto-updater, if any, is not excluded."
            continue
        }
        if ($result.exit_code -eq 3 -or $answer -match "CLAIM_BUSY") {
            $claimed = $false
            if ($answer.Contains('"holder": "' + $claimHolder + '"')) {
                $releaseStep = @($plan | Where-Object { $_.role -eq "claim-release" })[0]
                Fail ("Release push refused: the claim on $Robot is held by this PC ($claimHolder), probably " +
                      "left by an interrupted push. If no other push from here is running, release it with:`n" +
                      "  $($releaseStep.display)`nthen push again.")
            }
            Fail "Release push refused: $Robot is claimed by another job (D-406 claim): $answer"
        }
        if ($result.exit_code -ne 0) {
            Fail "Release push refused: the claim helper failed (exit $($result.exit_code)) on ${Robot}: $answer"
        }
        if ($result.output) { Write-Host ($result.output -join [Environment]::NewLine) }
        continue
    }
    if ($step.role -eq "claim-refresh") {
        # An older helper has no refresh; the claim then keeps its sized TTL.
        if ($result.exit_code -ne 0) {
            Write-Warning "could not refresh the claim on $Robot (exit $($result.exit_code)); it keeps its $claimTtl s TTL. $($result.output -join ' ')"
        }
        continue
    }
    if ($step.role -eq "image-layer-dry-run" -and $result.exit_code -eq 3 -and
            ($result.output -join " ") -match "IMAGE_LAYER_SYNC_MISSING") {
        Write-Warning "image-layer sync skipped: neither current nor previous release carries sync-image-layer.py."
        $imageLayerSkipped = $true
        continue
    }
    if ($result.exit_code -ne 0) {
        Fail "$($step.kind) failed (exit $($result.exit_code)): $display`n$($result.output -join [Environment]::NewLine)"
    }
    if ($result.output) { Write-Host ($result.output -join [Environment]::NewLine) }

    if ($step.role -eq "image-layer-dry-run" -or $step.role -eq "image-layer-apply") {
        $imageLayer = Read-LastJsonLine $result.output
        if ($null -eq $imageLayer -or -not $imageLayer.ok) {
            Fail "image-layer sync did not print an ok JSON result: $display"
        }
        $label = "plan"
        if ($step.role -eq "image-layer-apply") { $label = "applied" }
        Write-Host ("image-layer sync {0} ({1}): changed {2}, new {3}, unchanged {4}, skipped {5}" -f $label,
            $imageLayer.release_id, @($imageLayer.changed).Count, @($imageLayer.new).Count,
            @($imageLayer.unchanged).Count, @($imageLayer.skipped).Count)
        foreach ($path in @($imageLayer.changed) + @($imageLayer.new)) { if ($path) { Write-Host "  $path" } }
        if ($step.role -eq "image-layer-apply") {
            if ($imageLayer.backup_dir) { Write-Host "image-layer backup: $($imageLayer.backup_dir)" }
            foreach ($path in @($imageLayer.modprobe_changed)) {
                if ($path) { Write-Warning "modprobe options changed ($path): they apply at the next module load or reboot." }
            }
            foreach ($unit in @($imageLayer.active_targets_affected)) {
                if ($unit) { Write-Warning "$unit changed; its new dependencies apply at the next boot." }
            }
            foreach ($name in @("pending_parked", "pending_quarantined")) {
                if ($imageLayer.PSObject.Properties[$name] -and $imageLayer.$name) {
                    Write-Warning "image-layer sync ${name}: $($imageLayer.$name) -- read it and finish those commands by hand."
                }
            }
            if ($imageLayer.PSObject.Properties["corrupt_manifests"]) {
                foreach ($path in @($imageLayer.corrupt_manifests)) {
                    if ($path) { Write-Warning "image-layer backup manifest is unreadable and was ignored: $path" }
                }
            }
            if ($imageLayer.PSObject.Properties["next_boot_units"]) {
                foreach ($unit in @($imageLayer.next_boot_units)) {
                    if ($unit) { Write-Host "takes effect next boot (not restarted): $unit" }
                }
            }
        }
    }
    if ($step.role -eq "image-layer-restart") {
        Write-Host "restarted: $($restartedUnits -join ', ')"
    }
    if ($step.role -eq "core-release-check") {
        $checked = $result.output -join " "
        if ($checked -match "CORE_RESTART_FAILED") {
            if ($Rollback) {
                Fail "CORE did not start after the rollback restart. Read 'journalctl -u rosy-core' on $Robot."
            }
            Fail "CORE did not start on the new release after the restart; the robot has no running CORE. Run this script with -Rollback."
        } elseif ($checked -match "CORE_RESTARTED") {
            Write-Warning "CORE was still running the previous release after the switch (activator predates the fix); restarted rosy-core."
        } elseif ($checked -match "CORE_RELEASE_OK (/\S+)") {
            Write-Host "CORE runs the activated release: $($Matches[1])"
        } else {
            Fail "could not confirm that CORE runs the activated release: $display"
        }
    }

    if ($arguments -contains $ActivateWrapper -or $arguments -contains $RollbackWrapper) {
        $lastLine = ($result.output | Select-Object -Last 1)
        try {
            $activation = $lastLine | ConvertFrom-Json
            Write-Host "current release: $($activation.release_id) (previous: $($activation.previous))"
        } catch {
            Write-Warning "activation wrapper did not print the expected JSON result line."
        }
    }
    if ($arguments | Where-Object { $_ -like "*$CoreReadyProbe*" }) {
        Write-Host "CORE readiness: PASS"
    }
}

Write-Host "done."

} finally {
    # $claimed exists only once the execution loop started.
    if ((Test-Path variable:claimed) -and $claimed) {
        $claimRelease = @($plan | Where-Object { $_.role -eq "claim-release" })[0]
        Write-Host "+ $($claimRelease.display)"
        $released = Invoke-NativeCapture $claimRelease.executable $claimRelease.arguments
        if ($released.exit_code -ne 0) {
            Write-Warning "could not release the claim on $Robot (exit $($released.exit_code)); it expires after 30 min. $($released.output -join ' ')"
        }
    }
    foreach ($directory in $tempDirsToClean) {
        Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction SilentlyContinue
    }
}
