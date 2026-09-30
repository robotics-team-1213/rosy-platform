[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Robot,
    [string]$Action = "this operation",
    [int]$ApiPort = 8080,
    [string]$ApiToken = "",
    [string]$CredentialPath = "",
    [int]$TimeoutSec = 5,
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
#
# Read-only: one GET /api/v1/calibration/session. It never ends a session and
# never touches the robot otherwise. Token order: -ApiToken, $env:ROSY_API_TOKEN,
# then the DPAPI credential %LOCALAPPDATA%\Rosy\api\<Robot>.credential.xml that
# sd/rotate-core-api-credential.ps1 writes.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Robot -notmatch '^[A-Za-z0-9.-]+$') {
    throw "Robot must be a hostname or IPv4 address without shell characters."
}

function Write-Loud([string]$Message) {
    Write-Warning ("!" * 72)
    Write-Warning $Message
    Write-Warning ("!" * 72)
}

$token = $ApiToken
if (-not $token -and $env:ROSY_API_TOKEN) { $token = $env:ROSY_API_TOKEN }
if (-not $token) {
    if (-not $CredentialPath -and $env:LOCALAPPDATA) {
        $CredentialPath = Join-Path $env:LOCALAPPDATA ("Rosy\api\{0}.credential.xml" -f $Robot)
    }
    if ($CredentialPath -and (Test-Path -LiteralPath $CredentialPath)) {
        try {
            $token = (Import-Clixml -LiteralPath $CredentialPath).GetNetworkCredential().Password
        } catch {
            $token = ""
        }
    }
}
if (-not $token) {
    Write-Loud ("CALIBRATION CHECK SKIPPED for ${Robot}: no CORE API token (pass -ApiToken, set " +
                "ROSY_API_TOKEN, or store the device credential). Make sure nobody is calibrating " +
                "before $Action.")
    exit 0
}

$url = "http://${Robot}:${ApiPort}/api/v1/calibration/session"
try {
    $reply = Invoke-RestMethod -Uri $url -Headers @{ Authorization = "Bearer $token" } `
        -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
} catch {
    Write-Loud ("CALIBRATION CHECK FAILED for ${Robot} ($($_.Exception.Message)). CORE may be down " +
                "or older than API Ref v1.67. Make sure nobody is calibrating before $Action.")
    exit 0
}

$session = $null
if ($null -ne $reply -and $reply.PSObject.Properties.Name -contains "session") {
    $session = $reply.session
}
if ($null -eq $session) {
    Write-Host "calibration check: no active calibration session on $Robot"
    exit 0
}

$owner = $session.owner.label
if (-not $owner) { $owner = $session.owner.role }
$summary = ("calibration session '{0}' (kind {1}, owner {2}, {3}s left of lease) is ACTIVE on {4}" -f `
    $session.label, $session.kind, $owner, $session.remaining_s, $Robot)
if ($Force) {
    Write-Loud "-Force: proceeding with $Action although a $summary. The calibration will be interrupted."
    exit 0
}
[Console]::Error.WriteLine("REFUSED: $Action would interrupt a running calibration: $summary. " +
                           "Wait for it to end (or ask its owner to end it), or pass -Force.")
exit 3
