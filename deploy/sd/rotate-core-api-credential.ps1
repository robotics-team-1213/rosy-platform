<#
.SYNOPSIS
Rotates one robot's CORE API administrator credential (D-193 5, D-191 US-009).

.DESCRIPTION
Order, as D-193 5 fixes it: add a new administrator token -> store it in the
operator's DPAPI store -> confirm it with GET /api/v1/auth/whoami -> delete the
old id. Every step talks to CORE's API; nothing is changed on the device by SSH.

The store is the file write-card.ps1 created,
%LOCALAPPDATA%\Rosy\api\<device>.credential.xml, user name "<CORE token id>|<device_uid>".
The new value exists in plaintext only in this process and in CORE's one
response; it is never printed, logged or put on a command line. Read it back
with the command this script prints.

If the new token cannot be stored or confirmed, the old store is put back and
the new token is deleted again, so the robot keeps exactly the credential the
operator already holds. If only the last step (deleting the old id) fails, the
new credential is already the stored one and the old id is named for manual
removal.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DeviceName,
    # Default http://<DeviceName>.local:8080. Scheme, host and port only.
    [string]$BaseUrl,
    [string]$Label,
    [int]$TimeoutSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    [Console]::Error.WriteLine("ROTATION FAILED: $Message")
    exit 1
}

if ($DeviceName -cnotmatch '^rosy-pinky-[a-hj-km-np-z2-9]{4}$') { Fail "DeviceName is invalid" }
if (-not $BaseUrl) { $BaseUrl = "http://$DeviceName.local:8080" }
if ($BaseUrl -notmatch '^https?://[A-Za-z0-9.\-\[\]:]+$') { Fail "BaseUrl must be scheme://host[:port] with no path" }
if ($TimeoutSeconds -lt 1 -or $TimeoutSeconds -gt 120) { Fail "TimeoutSeconds must be 1-120" }
if (-not $Label) { $Label = "card (rotated $([DateTime]::UtcNow.ToString('yyyy-MM-dd')))" }
if ($Label.Length -gt 64) { Fail "Label must be at most 64 characters" }
if (-not $env:LOCALAPPDATA) { Fail "LOCALAPPDATA is unavailable" }

$storeFile = Join-Path $env:LOCALAPPDATA "Rosy\api\$DeviceName.credential.xml"
$pendingFile = "$storeFile.rotating"
$backupFile = "$storeFile.previous"
if (-not (Test-Path -LiteralPath $storeFile -PathType Leaf)) {
    Fail "no stored CORE API credential for $DeviceName at $storeFile (write-card.ps1 creates it)"
}
foreach ($leftover in @($pendingFile, $backupFile)) {
    if (Test-Path -LiteralPath $leftover) {
        Fail "$leftover is left from an interrupted rotation; check which credential works, keep that one as $storeFile, remove the other file, then re-run"
    }
}

$stored = Import-Clixml -LiteralPath $storeFile
$storedParts = ([string]$stored.UserName).Split([char]"|", 2)
$oldId = $storedParts[0]
$uidSuffix = if ($storedParts.Count -eq 2) { "|$($storedParts[1])" } else { "" }
$oldValue = $stored.GetNetworkCredential().Password
if ($oldId -cnotmatch '^[A-Za-z0-9_-]{1,64}$' -or -not $oldValue) { Fail "the store $storeFile does not hold a CORE token id and value" }

# HttpClient, not Invoke-RestMethod: no system proxy may see the Bearer header,
# no redirect may carry it elsewhere, and error bodies are parsed, not echoed.
Add-Type -AssemblyName System.Net.Http
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.UseProxy = $false
$handler.AllowAutoRedirect = $false
$client = New-Object System.Net.Http.HttpClient($handler)
$client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)

function Invoke-Core([string]$Method, [string]$Path, [string]$Token, [string]$Json) {
    $request = New-Object System.Net.Http.HttpRequestMessage((New-Object System.Net.Http.HttpMethod($Method)), "$BaseUrl$Path")
    $request.Headers.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $Token)
    if ($Json) { $request.Content = New-Object System.Net.Http.StringContent($Json, [Text.Encoding]::UTF8, "application/json") }
    try {
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    }
    catch {
        return [pscustomobject]@{ Status = 0; Body = $null; Error = $_.Exception.GetBaseException().GetType().Name }
    }
    $body = $null
    if ($text) {
        try { $body = $text | ConvertFrom-Json } catch { $body = $null }
    }
    return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = $body; Error = "" }
}

function Get-Field($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

# A reply in words that never include a request header or a token.
function Format-Reply($Reply) {
    if ($Reply.Status -eq 0) { return "no answer ($($Reply.Error))" }
    $problem = Get-Field $Reply.Body "error"
    $code = Get-Field $problem "code"
    $message = Get-Field $problem "message"
    if ($code) { return "HTTP $($Reply.Status) ${code}: $message" }
    return "HTTP $($Reply.Status)"
}

# 1. The stored credential is this robot's non-expiring administrator.
$me = Invoke-Core "GET" "/api/v1/auth/whoami" $oldValue ""
if ($me.Status -ne 200) { Fail "the stored credential is not accepted by $BaseUrl ($(Format-Reply $me)); nothing was changed" }
if ((Get-Field $me.Body "id") -cne $oldId) {
    Fail "CORE at $BaseUrl knows the stored credential as id $(Get-Field $me.Body 'id'), the store says $oldId; is -BaseUrl the robot named ${DeviceName}? Nothing was changed"
}
if ((Get-Field $me.Body "role") -ne "administrator" -or $null -ne (Get-Field $me.Body "expires_at")) {
    Fail "the stored credential is not a non-expiring administrator (role $(Get-Field $me.Body 'role')); nothing was changed"
}

# 2. Add the new administrator. Its value is in this response only.
$request = @{ role = "administrator"; label = $Label } | ConvertTo-Json -Compress
$created = Invoke-Core "POST" "/api/v1/system/tokens" $oldValue $request
$newId = Get-Field $created.Body "id"
$newValue = Get-Field $created.Body "token"
if ($created.Status -ne 201 -or $newId -cnotmatch '^[0-9a-f]{12}$' -or $newValue -cnotmatch '^[A-Za-z0-9_-]{43}$') {
    if ($newId -and $created.Status -eq 201) { [void](Invoke-Core "DELETE" "/api/v1/system/tokens/$newId" $oldValue "") }
    Fail "CORE did not create a new administrator credential ($(Format-Reply $created)); the stored credential is unchanged"
}

function Undo-NewToken([string]$Why) {
    $undo = Invoke-Core "DELETE" "/api/v1/system/tokens/$newId" $oldValue ""
    if ($undo.Status -eq 204) { Fail "$Why; the new id $newId was deleted again and the stored credential (id $oldId) is unchanged" }
    Fail "$Why; the stored credential (id $oldId) is unchanged, but the new id $newId could not be deleted ($(Format-Reply $undo)): delete it in the dashboard token settings"
}

# 3. Store it: write beside the store, then swap with a backup of the old one.
try {
    $secure = ConvertTo-SecureString $newValue -AsPlainText -Force
    New-Object System.Management.Automation.PSCredential("$newId$uidSuffix", $secure) | Export-Clixml -LiteralPath $pendingFile
    [IO.File]::Replace($pendingFile, $storeFile, $backupFile)
}
catch {
    Remove-Item -LiteralPath $pendingFile -Force -ErrorAction SilentlyContinue
    Undo-NewToken "the new credential could not be stored in $storeFile ($($_.Exception.GetType().Name))"
}

# 4. Confirm what the store now holds, read back the way the operator will.
$readBack = (Import-Clixml -LiteralPath $storeFile).GetNetworkCredential().Password
$check = Invoke-Core "GET" "/api/v1/auth/whoami" $readBack ""
if ($check.Status -ne 200 -or (Get-Field $check.Body "id") -cne $newId -or (Get-Field $check.Body "role") -ne "administrator") {
    [IO.File]::Replace($backupFile, $storeFile, [NullString]::Value)
    Undo-NewToken "the stored new credential was not confirmed by whoami ($(Format-Reply $check))"
}
Remove-Item -LiteralPath $backupFile -Force

# 5. Retire the old id with the new credential.
$deleted = Invoke-Core "DELETE" "/api/v1/system/tokens/$oldId" $readBack ""
$readBackCommand = "(Import-Clixml `"`$env:LOCALAPPDATA\Rosy\api\$DeviceName.credential.xml`").GetNetworkCredential().Password"
if ($deleted.Status -ne 204) {
    Write-Output "New CORE API administrator for ${DeviceName}: id $newId, stored in $storeFile"
    Write-Output "Read it back: $readBackCommand"
    Fail "the old id $oldId is still valid on the robot ($(Format-Reply $deleted)): delete it in the dashboard token settings"
}
Write-Output "Rotated the CORE API administrator for ${DeviceName}: old id $oldId deleted, new id $newId stored in $storeFile"
Write-Output "Read it back: $readBackCommand"
exit 0
