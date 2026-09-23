[CmdletBinding()]
param(
    [string]$PiHost = "rosy-01.local",
    [string]$PiUser = "rosy",
    [string]$NetworkInterface = "auto",
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8080,
    [ValidateRange(1, 60)]
    [int]$ConnectTimeoutSec = 5,
    [switch]$BatchMode,
    [string]$EvidencePath = ""
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
if ($EvidencePath) {
    $EvidencePath = [IO.Path]::GetFullPath($EvidencePath)
    if (Test-Path -LiteralPath $EvidencePath) {
        throw "EvidencePath already exists; refusing to replace prior evidence."
    }
    $evidenceParent = Split-Path -Parent $EvidencePath
    if (-not $evidenceParent -or -not (Test-Path -LiteralPath $evidenceParent -PathType Container)) {
        throw "EvidencePath parent directory must already exist."
    }
}

$connectionRecord = [ordered]@{
    schema_version = 1
    captured_at = [DateTimeOffset]::UtcNow.ToString("o")
    outcome = "HOLD"
    target = [ordered]@{
        host = $PiHost
        user = $PiUser
    }
    network = [ordered]@{
        interface = $null
        address = $null
    }
    checks = @()
    failure = $null
}

function Add-ConnectionCheck {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet("GO", "HOLD")][string]$Outcome
    )

    $script:connectionRecord.checks += [ordered]@{
        name = $Name
        outcome = $Outcome
    }
}

function Set-ConnectionFailure {
    param(
        [Parameter(Mandatory)][string]$Code,
        [Parameter(Mandatory)][string]$Detail
    )

    if ($null -eq $script:connectionRecord.failure) {
        $script:connectionRecord.failure = [ordered]@{
            code = $Code
            detail = $Detail
        }
    }
}

function Write-ConnectionEvidence {
    if (-not $EvidencePath) {
        return
    }

    $parent = Split-Path -Parent $EvidencePath
    $name = Split-Path -Leaf $EvidencePath
    $temporary = Join-Path $parent ".${name}.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $json = $connectionRecord | ConvertTo-Json -Depth 8
        Set-Content -LiteralPath $temporary -Value $json -Encoding utf8
        [IO.File]::Move($temporary, $EvidencePath)
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

$verificationFailed = $false
$remoteTarget = "${PiUser}@${PiHost}"
$sshArguments = @(
    "-o", "ConnectTimeout=$ConnectTimeoutSec",
    "-o", "ConnectionAttempts=1"
)
if ($BatchMode) {
    $sshArguments += @("-o", "BatchMode=yes")
}
$sshArguments += $remoteTarget

function Invoke-RosySsh {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string]$CheckName,
        [Parameter(Mandatory)][string]$FailureCode,
        [Parameter(Mandatory)][string]$FailureDetail
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = (& ssh @sshArguments $Command 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        Add-ConnectionCheck -Name $CheckName -Outcome "HOLD"
        Set-ConnectionFailure -Code $FailureCode -Detail $FailureDetail
        throw $FailureDetail
    }
    return $output
}

function Test-RosyHttp {
    param(
        [Parameter(Mandatory)][string]$HostName,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$CheckName,
        [Parameter(Mandatory)][string]$FailureCode
    )

    $uri = [UriBuilder]::new("http", $HostName, $ApiPort, $Path).Uri
    try {
        $response = Invoke-WebRequest -Uri $uri -Method Get -TimeoutSec $ConnectTimeoutSec -UseBasicParsing
        if ($response.StatusCode -ne 200) {
            throw "HTTP $($response.StatusCode)"
        }
    }
    catch {
        Add-ConnectionCheck -Name $CheckName -Outcome "HOLD"
        Set-ConnectionFailure -Code $FailureCode -Detail "ROSY HTTP endpoint did not return 200."
        throw "Other-device HTTP check failed for ${uri}."
    }
    Add-ConnectionCheck -Name $CheckName -Outcome "GO"
    Write-Host "PASS PEER_HTTP $uri"
}

try {
    if (-not (Get-Command "ssh" -ErrorAction SilentlyContinue)) {
        Set-ConnectionFailure -Code "SSH_UNAVAILABLE" -Detail "Required ssh command is unavailable."
        throw "Required command is unavailable: ssh"
    }

    $interfaceWasAutomatic = $NetworkInterface -eq "auto"
    if ($interfaceWasAutomatic) {
        $routeOutput = Invoke-RosySsh `
            -Command "ip -4 route show default" `
            -CheckName "ssh_route" `
            -FailureCode "SSH_ROUTE" `
            -FailureDetail "Unable to inspect the Pi default route over SSH."
        if ($routeOutput -notmatch '\bdev\s+([A-Za-z0-9_.:-]+)') {
            Add-ConnectionCheck -Name "ssh_route" -Outcome "HOLD"
            Set-ConnectionFailure -Code "ROUTE_INTERFACE" -Detail "Pi has no default-route interface."
            throw "Pi has no default-route interface; pass -NetworkInterface explicitly."
        }
        $NetworkInterface = $Matches[1]
        Add-ConnectionCheck -Name "ssh_route" -Outcome "GO"
    }
    if ($NetworkInterface -eq "lo") {
        Add-ConnectionCheck -Name "interface_selected" -Outcome "HOLD"
        Set-ConnectionFailure -Code "INTERFACE_LOOPBACK" -Detail "Loopback cannot be peer verified."
        throw "Loopback cannot be used for peer verification."
    }
    if (-not $interfaceWasAutomatic) {
        Add-ConnectionCheck -Name "interface_selected" -Outcome "GO"
    }
    $connectionRecord.network.interface = $NetworkInterface

    $addressCommand = "ip -4 -o addr show dev $NetworkInterface scope global"
    $addressOutput = Invoke-RosySsh `
        -Command $addressCommand `
        -CheckName "ssh_address" `
        -FailureCode "SSH_ADDRESS" `
        -FailureDetail "Unable to inspect the selected Pi interface address over SSH."
    if ($addressOutput -notmatch '\binet\s+([0-9.]+)/') {
        Add-ConnectionCheck -Name "ssh_address" -Outcome "HOLD"
        Set-ConnectionFailure -Code "ADDRESS_MISSING" -Detail "Pi reported no IPv4 address on the selected interface."
        throw "Pi did not report an IPv4 address on $NetworkInterface."
    }
    $networkAddress = $Matches[1]

    $parsedAddress = [Net.IPAddress]::None
    if (-not [Net.IPAddress]::TryParse($networkAddress, [ref]$parsedAddress) -or
        $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        Add-ConnectionCheck -Name "ssh_address" -Outcome "HOLD"
        Set-ConnectionFailure -Code "ADDRESS_INVALID" -Detail "Pi reported an invalid IPv4 address."
        throw "Pi did not report a valid IPv4 address on $NetworkInterface."
    }
    $connectionRecord.network.address = $networkAddress
    Add-ConnectionCheck -Name "ssh_address" -Outcome "GO"

    Test-RosyHttp -HostName $networkAddress -Path "/api/v1" `
        -CheckName "http_api" -FailureCode "HTTP_API"
    Test-RosyHttp -HostName $networkAddress -Path "/dashboard" `
        -CheckName "http_dashboard" -FailureCode "HTTP_DASHBOARD"

    if ($PiHost -ne $networkAddress) {
        try {
            foreach ($path in @("/api/v1", "/dashboard")) {
                $uri = [UriBuilder]::new("http", $PiHost, $ApiPort, $path).Uri
                $response = Invoke-WebRequest -Uri $uri -Method Get `
                    -TimeoutSec $ConnectTimeoutSec -UseBasicParsing
                if ($response.StatusCode -ne 200) {
                    throw "HTTP $($response.StatusCode)"
                }
                Write-Host "PASS PEER_HTTP $uri"
            }
        }
        catch {
            Write-Warning "The supplied hostname is unavailable over HTTP."
            Write-Warning "Use the verified LAN address when mDNS is unavailable."
        }
    }

    $connectionRecord.outcome = "GO"
}
catch {
    $verificationFailed = $true
    if ($null -eq $connectionRecord.failure) {
        Set-ConnectionFailure -Code "VERIFY_UNEXPECTED" -Detail "Connection verification failed."
    }
}
finally {
    Write-ConnectionEvidence
}

if ($verificationFailed) {
    throw "[$($connectionRecord.failure.code)] $($connectionRecord.failure.detail)"
}

Write-Host "PASS LAN_PEER $NetworkInterface http://${networkAddress}:$ApiPort/dashboard"
