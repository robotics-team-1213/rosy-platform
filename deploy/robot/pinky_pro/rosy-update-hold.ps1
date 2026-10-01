[CmdletBinding()]
param(
    [string]$Robot,
    [switch]$Hold,
    [switch]$Release,
    [switch]$Status,
    [string]$Reason,
    [double]$Hours = 0,
    [string]$Holder = "",
    [string]$RosyUser = "rosy",
    [string]$KeyPath = "",
    [string]$KnownHosts = "",
    [string]$SshExe = "ssh"
)
# D-406 decision 4: hold a robot's automatic update (a test, a drive or a seal
# is running), release the hold, or show the updater's status.json. The robot
# keeps staging a new release while held; it only does not apply it. A hold
# always expires (at most 168 h).
#
# Calls the device CLI over ssh:
#   sudo -n python3 /opt/rosy/native-runtime/rosy_auto_update.py hold|release-hold|status --json
# ssh joins the remote arguments into one shell line, so -Reason and -Holder
# are limited to a safe character set and travel in single quotes. No double
# quotes go into any native argument: Windows PowerShell 5.1 eats them.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

$DeviceCli = "/opt/rosy/native-runtime/rosy_auto_update.py"

if (-not $Robot) { Fail "Robot is required (hostname or IP of the target device)." }
if ($Robot -notmatch '^[A-Za-z0-9.-]+$') {
    Fail "Robot must be a hostname or IPv4 address without shell characters."
}
if ($RosyUser -notmatch '^[a-z_][a-z0-9_-]*$') {
    Fail "RosyUser is not a safe Linux account name."
}

$actions = @($Hold, $Release, $Status) | Where-Object { $_ }
if (@($actions).Count -ne 1) {
    Fail "Pass exactly one of -Hold, -Release or -Status."
}
if (-not $Hold) {
    if ($PSBoundParameters.ContainsKey("Reason") -or $PSBoundParameters.ContainsKey("Hours") -or
            $PSBoundParameters.ContainsKey("Holder")) {
        Fail "-Reason, -Hours and -Holder are only for -Hold."
    }
}

$remote = @("sudo", "-n", "python3", $DeviceCli)
if ($Hold) {
    if (-not $PSBoundParameters.ContainsKey("Reason")) { Fail "-Hold needs -Reason <text>." }
    if (-not $PSBoundParameters.ContainsKey("Hours")) { Fail "-Hold needs -Hours <n> (0 < n <= 168)." }
    # Letters, digits, space and . , : _ / ( ) + = @ - only; it starts with a
    # letter or digit so the device CLI never reads it as an option.
    if ($Reason -cnotmatch '^[A-Za-z0-9][A-Za-z0-9 .,:_/()+=@-]{0,199}\z') {
        Fail "Reason must be 1-200 characters of letters, digits, space and . , : _ / ( ) + = @ - starting with a letter or digit."
    }
    if (-not ($Hours -gt 0 -and $Hours -le 168)) {
        Fail "Hours must be greater than 0 and at most 168 (7 days)."
    }
    if (-not $Holder) {
        $Holder = "$env:USERNAME@$env:COMPUTERNAME"
        $source = "the default holder $Holder (USERNAME@COMPUTERNAME)"
    } else {
        $source = "Holder"
    }
    if ($Holder -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}\z') {
        Fail "$source is not 1-64 characters of letters, digits and . _ @ -; pass -Holder <name>."
    }
    $hoursText = $Hours.ToString([Globalization.CultureInfo]::InvariantCulture)
    $remote += @("hold", "--holder", "'$Holder'", "--reason", "'$Reason'", "--hours", $hoursText)
} elseif ($Release) {
    $remote += @("release-hold")
} else {
    $remote += @("status", "--json")
}

if (-not $KeyPath) {
    $KeyPath = Join-Path $env:LOCALAPPDATA "Rosy\ssh\rosy-operator-ed25519"
}
if (-not $KnownHosts) {
    $KnownHosts = Join-Path $env:LOCALAPPDATA "Rosy\known_hosts"
}

# ssh parses "-o Key=Value" like an ssh_config line, so the known_hosts path
# is quoted for ssh itself (same as rosy-release-push.ps1).
$arguments = @("-i", $KeyPath, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=`"$KnownHosts`"",
    "-o", "ConnectTimeout=5", "${RosyUser}@${Robot}") + $remote

$previous = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $output = @(& $SshExe @arguments 2>&1 | ForEach-Object { [string]$_ })
    $code = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previous
}
if ($code -ne 0) {
    Fail "rosy_auto_update.py $($remote[4]) failed on $Robot (exit $code): $($output -join [Environment]::NewLine)"
}

if (-not $Status) {
    if ($output) { Write-Host ($output -join [Environment]::NewLine) }
    exit 0
}

try {
    $state = ($output -join "`n") | ConvertFrom-Json
} catch {
    Fail "status --json did not print JSON: $($output -join [Environment]::NewLine)"
}

function Show([string]$Label, $Value) {
    if ($null -eq $Value -or "$Value" -eq "") { $Value = "-" }
    Write-Host ("{0,-13}: {1}" -f $Label, $Value)
}

Show "robot" "$($state.hostname) ($Robot)"
Show "current" $state.current_release
Show "candidate" $state.candidate
Show "phase" $state.phase
Show "reason" $state.reason
if ($state.last_result) {
    $last = $state.last_result
    Show "last result" "$($last.release_id) $($last.outcome) at $($last.at) - $($last.detail)"
} else {
    Show "last result" $null
}
Show "updated at" $state.updated_at
exit 0
