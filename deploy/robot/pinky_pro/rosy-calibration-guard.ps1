[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Robot,
    [string]$Action = "this operation",
    [int]$ApiPort = 8080,
    [string]$ApiToken = "",
    [string]$ApiTlsHost = "",
    [string]$ApiCaFile = "",
    [string]$PythonExe = "python",
    [string]$CredentialPath = "",
    [int]$TimeoutSec = 5,
    [string]$RosyUser = "rosy",
    [string]$KeyPath = "",
    [string]$KnownHosts = "",
    [string]$SshExe = "ssh",
    [switch]$Force
)
# D-321 addendum: soft guard for operator tooling that restarts CORE (release
# push, dev overlay sync). A release push and a CORE restart once cut a
# calibration drive short; this asks CORE whether a calibration session lease
# is alive before the tool touches the robot.
#
#   exit 0  no active session, or -Force given (loud warning), or the check
#           could not be made (no token, CORE down, older CORE) -> loud warning
#   exit 3  an active session was found and -Force was not given
#   exit 2  explicit TLS check failed (including absent token); Force cannot bypass
#
# Read-only: one GET /api/v1/calibration/session. It never ends a session and
# never touches the robot otherwise. Token order: -ApiToken, $env:ROSY_API_TOKEN,
# then the DPAPI credential %LOCALAPPDATA%\Rosy\api\<Robot>.credential.xml that
# sd/rotate-core-api-credential.ps1 writes. That script names the file after
# the device hostname (rosy-pinky-9dfk.credential.xml) while pushes usually pass
# an IP, so when <Robot>.credential.xml is missing the guard asks the robot its
# hostname over the push's own non-interactive, strict-host-key ssh and uses
# <hostname>.credential.xml. It never tries other robots' files against this
# address: that would send one robot's token to another device.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Robot -notmatch '^[A-Za-z0-9.-]+$') {
    throw "Robot must be a hostname or IPv4 address without shell characters."
}

# TLS mode is explicit: both trust parameters are required, with no HTTP fallback.
$secureApi = [bool]$ApiTlsHost -or [bool]$ApiCaFile
if ($secureApi -and (-not $ApiTlsHost -or -not $ApiCaFile -or $TimeoutSec -lt 1 -or $TimeoutSec -gt 30)) {
    [Console]::Error.WriteLine("Secure calibration check failed: both TLS host and CA file are required.")
    exit 2
}

function Write-Loud([string]$Message) {
    Write-Warning ("!" * 72)
    Write-Warning $Message
    Write-Warning ("!" * 72)
}

function Read-StoredToken([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    try {
        return (Import-Clixml -LiteralPath $Path).GetNetworkCredential().Password
    } catch {
        return ""
    }
}

# --- device hostname lookup ---------------------------------------------------
# Every ssh here uses the release push's settings: key auth only (BatchMode),
# known host keys only, no stdin (-n), a connect timeout, keepalives that drop
# a dead session, and a wall-clock limit after which the process tree is
# killed, so this soft guard can never hang a push. ssh is started as a
# process (not with &) because only that can be bounded; the command line is
# built here, so an argument may hold whitespace but never a double quote.
$script:hostnameNote = ""
$script:sshPath = ""
$sshWallClockMs = ($TimeoutSec + 5) * 1000

function Format-NativeArgument([string]$Value) {
    if ($Value -notmatch '\s') { return $Value }
    return '"' + $Value + '"'
}

function Invoke-BoundedSsh([string[]]$Arguments) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $script:sshPath
    $info.Arguments = ($Arguments | ForEach-Object { Format-NativeArgument $_ }) -join " "
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::Start($info)
    try {
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        [void]$process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($sshWallClockMs)) {
            # Kill the whole tree: a wrapper (.cmd) would otherwise leave its
            # child holding the output pipes.
            $previous = $ErrorActionPreference
            try {
                $ErrorActionPreference = "Continue"
                & taskkill.exe /T /F /PID $process.Id *> $null
            } finally {
                $ErrorActionPreference = $previous
            }
            try { if (-not $process.HasExited) { $process.Kill() } } catch { }
            return @{ timed_out = $true; exit_code = $null; lines = @() }
        }
        $process.WaitForExit()
        $text = ""
        if ($stdout.Wait(2000)) { $text = $stdout.Result }
        $lines = @($text -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        return @{ timed_out = $false; exit_code = $process.ExitCode; lines = $lines }
    } finally {
        $process.Dispose()
    }
}

function Get-SshArguments([string]$RemoteCommand, [string]$HostKeyAlias = "") {
    $arguments = @("-n", "-i", $KeyPath, "-o", "UserKnownHostsFile=$KnownHosts",
                   "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
                   "-o", "ConnectTimeout=$TimeoutSec", "-o", "ServerAliveInterval=2",
                   "-o", "ServerAliveCountMax=2")
    if ($HostKeyAlias) { $arguments += @("-o", "HostKeyAlias=$HostKeyAlias") }
    return $arguments + @("${RosyUser}@${Robot}", $RemoteCommand)
}

# Ask the robot its hostname. Returns it, or "" with $script:hostnameNote
# saying why not.
function Resolve-DeviceHostname {
    if ($RosyUser -cnotmatch '^[a-z_][a-z0-9_-]*\z') {
        $script:hostnameNote = "RosyUser '$RosyUser' is not a plain user name"
        return ""
    }
    # ssh splits an unquoted -o value on whitespace: refuse such a path.
    if ($KnownHosts -match '[\s"]') {
        $script:hostnameNote = "known_hosts path '$KnownHosts' contains whitespace or quotes"
        return ""
    }
    if ($KeyPath -match '"') {
        $script:hostnameNote = "key path '$KeyPath' contains a double quote"
        return ""
    }
    $command = Get-Command $SshExe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) {
        $script:hostnameNote = "native ssh executable '$SshExe' not found"
        return ""
    }
    $script:sshPath = $command.Path
    try {
        $reply = Invoke-BoundedSsh (Get-SshArguments "hostname")
    } catch {
        $script:hostnameNote = "ssh failed: $($_.Exception.Message)"
        return ""
    }
    if ($reply.timed_out) {
        $script:hostnameNote = "ssh timed out after $($sshWallClockMs / 1000)s and was killed"
        return ""
    }
    if ($reply.exit_code -ne 0) {
        $script:hostnameNote = "ssh exited $($reply.exit_code)"
        return ""
    }
    # Case-sensitive and anchored: Windows file names are case-insensitive, so
    # only an exact lowercase device name may pick a credential file.
    $lines = @($reply.lines)
    if ($lines.Count -ne 1 -or $lines[0] -cnotmatch '^rosy-[a-z0-9-]+\z') {
        $script:hostnameNote = "the robot's hostname answer is not a ROSY device name"
        return ""
    }
    return $lines[0]
}

# The hostname answer comes from the robot's rosy account; a compromised one
# could name another robot to receive its token. Accept the name only when
# this address also proves that robot's host key: an ssh with HostKeyAlias
# set to the known_hosts entry for the name. Entries carry a suffix in
# practice (rosy-pinky-9dfk.local), so the alias is the first plain entry of
# <name>, <name>.local, <name>.lan. Hashed entries are not matched (skip).
function Test-DeviceHostKey([string]$DeviceHost) {
    $names = @()
    if (Test-Path -LiteralPath $KnownHosts) {
        foreach ($line in [IO.File]::ReadAllLines($KnownHosts)) {
            $fields = $line.Trim() -split '\s+'
            if ($fields.Count -lt 3 -or $fields[0].StartsWith("#") -or $fields[0].StartsWith("@")) { continue }
            $names += @($fields[0] -split ',')
        }
    }
    $alias = $null
    foreach ($candidate in @($DeviceHost, "$DeviceHost.local", "$DeviceHost.lan")) {
        if ($names -ccontains $candidate) { $alias = $candidate; break }
    }
    if (-not $alias) {
        $script:hostnameNote = ("known_hosts has no entry for $DeviceHost, $DeviceHost.local or " +
                                "$DeviceHost.lan to prove the claimed hostname")
        return $false
    }
    try {
        $reply = Invoke-BoundedSsh (Get-SshArguments "true" $alias)
    } catch {
        $script:hostnameNote = "host key check for ${alias} failed: $($_.Exception.Message)"
        return $false
    }
    if ($reply.timed_out -or $reply.exit_code -ne 0) {
        $result = "timed out"
        if (-not $reply.timed_out) { $result = "ssh exited $($reply.exit_code)" }
        $script:hostnameNote = ("host key of $Robot does not match the known_hosts entry for " +
                                "$alias ($result); the claimed hostname $DeviceHost is not trusted")
        return $false
    }
    return $true
}

$token = $ApiToken
if (-not $token -and $env:ROSY_API_TOKEN) { $token = $env:ROSY_API_TOKEN }
$lookedFor = New-Object System.Collections.Generic.List[string]
if (-not $token) {
    $explicitCredential = [bool]$CredentialPath
    if (-not $CredentialPath -and $env:LOCALAPPDATA) {
        $CredentialPath = Join-Path $env:LOCALAPPDATA ("Rosy\api\{0}.credential.xml" -f $Robot)
    }
    if ($CredentialPath) {
        $lookedFor.Add($CredentialPath)
        $token = Read-StoredToken $CredentialPath
    }
    if (-not $token -and -not $explicitCredential -and $env:LOCALAPPDATA) {
        if (-not $KeyPath) { $KeyPath = Join-Path $env:LOCALAPPDATA "Rosy\ssh\rosy-operator-ed25519" }
        if (-not $KnownHosts) { $KnownHosts = Join-Path $env:LOCALAPPDATA "Rosy\known_hosts" }
        $deviceHost = Resolve-DeviceHostname
        if ($deviceHost -and $deviceHost -ne $Robot) {
            $byHostname = Join-Path $env:LOCALAPPDATA ("Rosy\api\{0}.credential.xml" -f $deviceHost)
            $lookedFor.Add($byHostname)
            if (-not (Test-Path -LiteralPath $byHostname)) {
                $script:hostnameNote = "the robot answered $deviceHost, which has no stored credential"
            } elseif (Test-DeviceHostKey $deviceHost) {
                $token = Read-StoredToken $byHostname
            }
        }
    }
}
if (-not $token -and $secureApi) {
    [Console]::Error.WriteLine("Secure calibration check failed: no device credential.")
    exit 2
}
if (-not $token) {
    $where = "looked for: none"
    if ($lookedFor.Count -gt 0) { $where = "looked for: " + ($lookedFor -join ", ") }
    if ($script:hostnameNote) { $where += "; device hostname lookup: " + $script:hostnameNote }
    Write-Loud ("CALIBRATION CHECK SKIPPED for ${Robot}: no CORE API token ($where). Pass -ApiToken, " +
                "set ROSY_API_TOKEN, or store the device credential. Make sure nobody is calibrating " +
                "before $Action.")
    exit 0
}

if ($secureApi) {
    $process = $null
    try {
        $helper = Join-Path $PSScriptRoot "calibration_tls_read.py"
        $command = Get-Command $PythonExe -CommandType Application -ErrorAction Stop | Select-Object -First 1
        foreach ($value in @($helper, $Robot, $ApiTlsHost, $ApiCaFile)) {
            if ($value -match '["\r\n]' -or $value.EndsWith('\')) { throw "Unsupported argument." }
        }
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $command.Path
        $arguments = @("-I", $helper, "--address", $Robot, "--hostname", $ApiTlsHost,
                       "--port", "$ApiPort", "--ca-file", $ApiCaFile, "--timeout", "$TimeoutSec")
        $info.Arguments = ($arguments | ForEach-Object { Format-NativeArgument $_ }) -join " "
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardInput = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $process = [System.Diagnostics.Process]::Start($info)
        $stdout = $process.StandardOutput.ReadToEndAsync()
        [void]$process.StandardError.ReadToEndAsync()
        # The bearer exists only in the private child stdin, never its argv or logs.
        $process.StandardInput.Write((@{ token = $token } | ConvertTo-Json -Compress))
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(($TimeoutSec + 5) * 1000)) {
            & taskkill.exe /T /F /PID $process.Id *> $null
            try { if (-not $process.HasExited) { $process.Kill() } } catch { }
            throw "Probe timed out."
        }
        if ($process.ExitCode -ne 0 -or -not $stdout.Wait(2000)) { throw "Probe failed." }
        $reply = $stdout.Result | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $reply -or -not ($reply.PSObject.Properties.Name -contains "session")) { throw "Invalid probe reply." }
    } catch {
        [Console]::Error.WriteLine("Secure calibration check failed; operation refused.")
        exit 2
    } finally {
        if ($null -ne $process) { $process.Dispose() }
    }
} else {
$url = "http://${Robot}:${ApiPort}/api/v1/calibration/session"
try {
    $reply = Invoke-RestMethod -Uri $url -Headers @{ Authorization = "Bearer $token" } `
        -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
} catch {
    $status = $null
    try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = $null }
    if ($status -eq 401 -or $status -eq 403) {
        # The robot answered: this is a credential problem, not a dead CORE.
        Write-Loud ("CALIBRATION CHECK REJECTED by ${Robot}: HTTP $status - the API token was not " +
                    "accepted (revoked, expired or wrong robot). Fix the token; make sure nobody is " +
                    "calibrating before $Action.")
    } elseif ($null -ne $status) {
        Write-Loud ("CALIBRATION CHECK FAILED for ${Robot}: HTTP $status. CORE may be older than " +
                    "API Ref v1.68. Make sure nobody is calibrating before $Action.")
    } else {
        Write-Loud ("CALIBRATION CHECK UNREACHABLE for ${Robot} ($($_.Exception.Message)). CORE may " +
                    "be down. Make sure nobody is calibrating before $Action.")
    }
    exit 0
}

}

# Read the reply defensively: StrictMode throws on a missing property, and an
# unexpected shape must warn, not abort the calling tool.
function Get-Field($Object, [string]$Name) {
    if ($null -eq $Object -or -not ($Object.PSObject.Properties.Name -contains $Name)) { return $null }
    return $Object.$Name
}
if ($null -eq $reply -or -not ($reply.PSObject.Properties.Name -contains "session")) {
    Write-Loud ("CALIBRATION CHECK GOT AN UNEXPECTED REPLY from ${Robot} (no 'session' field). " +
                "Make sure nobody is calibrating before $Action.")
    exit 0
}
$session = $reply.session
if ($null -eq $session) {
    Write-Host "calibration check: no active calibration session on $Robot"
    exit 0
}

$ownerInfo = Get-Field $session "owner"
$owner = Get-Field $ownerInfo "label"
if (-not $owner) { $owner = Get-Field $ownerInfo "role" }
if (-not $owner) { $owner = "unknown" }
$summary = ("calibration session '{0}' (kind {1}, owner {2}, {3}s left of lease) is ACTIVE on {4}" -f `
    (Get-Field $session "label"), (Get-Field $session "kind"), $owner,
    (Get-Field $session "remaining_s"), $Robot)
if ($Force) {
    Write-Loud "-Force: proceeding with $Action although a $summary. The calibration will be interrupted."
    exit 0
}
[Console]::Error.WriteLine("REFUSED: $Action would interrupt a running calibration: $summary. " +
                           "Wait for it to end (or ask its owner to end it), or pass -Force.")
exit 3
