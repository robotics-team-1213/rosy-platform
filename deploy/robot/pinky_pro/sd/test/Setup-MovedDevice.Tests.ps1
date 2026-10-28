param([string]$Source = (Join-Path $PSScriptRoot "..\setup-moved-device.ps1"))

# Orchestration self-check: every disk, credential and child writer is a fixture.
$ErrorActionPreference = "Stop"
$sandbox = Join-Path ([IO.Path]::GetTempPath()) ("rosy-sd-guided-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $sandbox | Out-Null
$sd = Join-Path $sandbox "sd"
$release = Join-Path $sandbox "release"
$local = Join-Path $sandbox "local"
$scratch = Join-Path $sandbox "scratch"
foreach ($directory in @($sd, $release, $local, $scratch, (Join-Path $sandbox "release\public-keys"))) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$utf8 = New-Object Text.UTF8Encoding($true)
function Save-Fixture([string]$Path, [string]$Text) { [IO.File]::WriteAllText($Path, $Text, $utf8) }
Copy-Item -LiteralPath $Source -Destination (Join-Path $sd "setup-moved-device.ps1")
foreach ($helper in @("sd-setup-settings.ps1", "sd-card-completion.ps1", "sd-batch-state.ps1")) {
    Copy-Item -LiteralPath (Join-Path (Split-Path -Parent $Source) $helper) -Destination $sd
}
Save-Fixture (Join-Path $sd "verify-image-release.py") @'
import json
print(json.dumps(dict(ok='true', release_id='2026.10.18-001',
    image='rosy-os-pinky-pro-2026.10.18-001-arm64.img.xz', sha256='a' * 64,
    source_revision='c' * 40)))
'@
Save-Fixture (Join-Path $sd "imager.exe") "fixture executable, never run"
Save-Fixture (Join-Path $sandbox "release\public-keys\rosy-release-2026-01.pem") "fixture public key"
Save-Fixture (Join-Path $release "manifest.json") '{"release_id":"2026.10.18-001"}'
Save-Fixture (Join-Path $release "SHA256SUMS.sig") "fixture signature"
$image = "rosy-os-pinky-pro-2026.10.18-001-arm64.img.xz"
Save-Fixture (Join-Path $release $image) "fixture image"
Save-Fixture (Join-Path $release "SHA256SUMS") (("a" * 64) + "  " + $image)
$credentials = Join-Path $local "Rosy\credentials"
New-Item -ItemType Directory -Path $credentials -Force | Out-Null
$operatorDirectory = Join-Path $local "Rosy\ssh"
New-Item -ItemType Directory -Path $operatorDirectory -Force | Out-Null
$operatorPrivate = Join-Path $operatorDirectory "rosy-operator-ed25519"
$operatorPublic = $operatorPrivate + ".pub"
Save-Fixture $operatorPrivate "fixture private key, never read"
Save-Fixture $operatorPublic "fixture public key, only passed to the fixture writer"
$profile = Join-Path $credentials "site.credential.xml"
function Save-WifiFixture {
    $secure = ConvertTo-SecureString "fixture only" -AsPlainText -Force
    New-Object Management.Automation.PSCredential("fixture-site", $secure) | Export-Clixml -LiteralPath $profile
}
Save-WifiFixture
$registry = Join-Path $local "Rosy\device-registry.json"
Save-Fixture $registry '{"robot_numbers":[],"device_names":[],"device_uids":[]}'
$planMarker = Join-Path $sandbox "planned.json"
$writerMarker = Join-Path $sandbox "written.json"
Save-Fixture (Join-Path $sd "prepare-rosy-sd.ps1") @'
param([string]$PlanPath, [string]$ReceiptPath, [string]$RegistryJson,
      [string]$DiskNumber, [string]$Preset, [string]$WifiProfile,
      [string]$ImagePath, [string]$ImageSha256, [string]$ImageSignaturePath,
      [string]$ReleasePublicKey, [string]$ReleaseId, [string]$RpiImager, [string]$OperatorPublicKey,
      [switch]$PlanOnly)
if (-not $PlanOnly -or $Preset -cne "core") { throw "expected a no-write core plan" }
$PSBoundParameters | ConvertTo-Json | Set-Content -LiteralPath $env:PLAN_MARKER
$plan = @{mode="PLAN_ONLY";release_id="2026.10.18-001";disk_number=7;
    device_name="rosy-pinky-test";robot_number=40;namespace="rosy_40";
    wifi_ssid="fixture-site";disk_model="fixture";disk_serial="FIXTURE-7";disk_size=34359738368}
$json = $plan | ConvertTo-Json
$json | Set-Content -LiteralPath $PlanPath
$json
'@
Save-Fixture (Join-Path $sd "write-card.ps1") @'
param([string]$PlanPath, [string]$ReleaseDir, [string]$WifiProfile,
      [string]$RpiImager, [string]$EvidenceDir, [string]$OperatorPublicKey, [switch]$Detach)
if (-not $Detach) { throw "expected the existing detached writer" }
$PSBoundParameters | ConvertTo-Json | Set-Content -LiteralPath $env:WRITER_MARKER
'@
$driver = Join-Path $sandbox "driver.ps1"
Save-Fixture $driver @'
param([switch]$WriteCard, [string]$Address)
$ErrorActionPreference = "Stop"
$env:LOCALAPPDATA = $env:FIXTURE_LOCAL
$env:ROSY_SCRATCH = $env:FIXTURE_SCRATCH
$env:USERPROFILE = $env:FIXTURE_SCRATCH
function Get-Disk {
    [pscustomobject]@{Number=7;BusType="USB";Size=34359738368;
        IsBoot=$false;IsSystem=$false;FriendlyName="fixture";SerialNumber="FIXTURE-7"}
}
function Read-Host { "REGISTER 40" }
$arguments = @{ReleaseDir=$env:FIXTURE_RELEASE;WifiProfile="site";DiskNumber=7;
    RpiImager=(Join-Path $env:FIXTURE_SD "imager.exe");ConfigPath=(Join-Path $env:FIXTURE_SCRATCH "sd-setup.local.json")}
if (-not $WriteCard) { $arguments.PrepareOnly = $true }
if ($PSBoundParameters.ContainsKey("Address")) { $arguments.RobotAddress = $Address }
& (Join-Path $env:FIXTURE_SD "setup-moved-device.ps1") @arguments
exit $LASTEXITCODE
'@
$env:FIXTURE_LOCAL = $local
$env:FIXTURE_SCRATCH = $scratch
$env:FIXTURE_RELEASE = $release
$env:FIXTURE_SD = $sd
$env:PLAN_MARKER = $planMarker
$env:WRITER_MARKER = $writerMarker
$powershell = (Get-Command powershell.exe).Source
function Invoke-Case([string[]]$Extra = @()) {
    $ErrorActionPreference = "Continue"
    $output = @(& $powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $driver @Extra 2>&1)
    [pscustomobject]@{Code=$LASTEXITCODE;Text=($output | Out-String)}
}
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }

$result = Invoke-Case
Assert ($result.Code -eq 0) ("new SD preparation must work without a robot address: " + $result.Text)
Assert (Test-Path -LiteralPath $planMarker) "PrepareOnly must create a plan"
Assert (-not (Test-Path -LiteralPath $writerMarker)) "PrepareOnly must never launch the writer"
Remove-Item -LiteralPath $planMarker
Write-Output "PASS: fresh-card PrepareOnly creates a core plan without launching a writer"

foreach ($address in @("not-an-ip", "")) {
    $result = Invoke-Case @("-Address", $address)
    Assert ($result.Code -ne 0) "an explicitly invalid address must fail"
    Assert (-not (Test-Path -LiteralPath $planMarker)) "invalid address must fail before planning"
}
Write-Output "PASS: explicitly invalid and empty addresses cannot enter fresh-card preparation"

Remove-Item -LiteralPath $registry
$result = Invoke-Case
Assert ($result.Code -ne 0) "missing registry must fail"
Assert (-not (Test-Path -LiteralPath $planMarker)) "missing registry must not allocate an identity"
Save-Fixture $registry '{"robot_numbers":[],"device_names":[],"device_uids":[]}'
Write-Output "PASS: missing registry cannot allocate a new identity"

Remove-Item -LiteralPath $profile
$result = Invoke-Case
Assert ($result.Code -ne 0) "missing Wi-Fi profile must fail"
Assert (-not (Test-Path -LiteralPath $planMarker)) "missing Wi-Fi profile must fail before planning"
Save-WifiFixture
Write-Output "PASS: missing Wi-Fi profile cannot produce a card plan"

# Replace only the external HTTP boundary in the disposable script copy.
$copy = Join-Path $sd "setup-moved-device.ps1"
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($copy, [ref]$tokens, [ref]$errors)
Assert ($errors.Count -eq 0) "guided script must parse"
$http = $ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq "Get-SetupPage"}, $true)
$original = [IO.File]::ReadAllText($copy)
foreach ($page in @("New device registration pending", "ordinary dashboard")) {
    $replacement = 'function Get-SetupPage([string]$Address) { "' + $page + '" }'
    Save-Fixture $copy ($original.Substring(0, $http.Extent.StartOffset) + $replacement + $original.Substring($http.Extent.EndOffset))
    $result = Invoke-Case @("-Address", "192.0.2.10")
    if ($page -eq "New device registration pending") {
        Assert ($result.Code -eq 0 -and (Test-Path -LiteralPath $planMarker)) ("valid moved-card SETUP must still prepare: " + $result.Text)
        Remove-Item -LiteralPath $planMarker
    }
    else {
        Assert ($result.Code -ne 0 -and -not (Test-Path -LiteralPath $planMarker)) "ordinary dashboard must not pass the moved-card gate"
    }
}
Save-Fixture $copy $original
Write-Output "PASS: explicit moved-card address retains the SETUP-page gate"

$result = Invoke-Case @("-WriteCard")
Assert ($result.Code -eq 0) ("guided write must delegate to existing writer: " + $result.Text)
Assert (Test-Path -LiteralPath $writerMarker) "confirmed plan must reach the fixture writer"
$written = Get-Content -LiteralPath $writerMarker -Raw | ConvertFrom-Json
Assert ($written.Detach -and $written.WifiProfile -ceq "site") "writer must retain the selected profile and detached mode"
$planned = Get-Content -LiteralPath $planMarker -Raw | ConvertFrom-Json
Assert ($planned.OperatorPublicKey -ceq $operatorPublic -and $written.OperatorPublicKey -ceq $operatorPublic) "the reviewed operator key must reach both plan and writer"
Assert ($result.Text -match "rosy-auto-update.timer" -and $result.Text -match "rosy_auto_update.py status") "completion must explain how to check automatic updates"
Assert ($result.Text -notmatch '-RobotAddress\s+-OperatorPresent') "fresh-card instructions must not contain an empty address"
Write-Output "PASS: confirmed new-card plan delegates to the existing writer and shows update checks"
Remove-Item -LiteralPath $planMarker, $writerMarker
foreach ($missing in @($operatorPrivate, $operatorPublic)) {
    Remove-Item -LiteralPath $missing
    $result = Invoke-Case @("-WriteCard")
    Assert ($result.Code -ne 0) "a missing operator key pair must fail"
    Assert (-not (Test-Path -LiteralPath $planMarker) -and -not (Test-Path -LiteralPath $writerMarker)) "a missing SSH key must fail before identity planning and media writes"
    Save-Fixture $missing "fixture key, never read"
}
Write-Output "PASS: missing private or public operator key cannot create an inaccessible card"
Write-Output "All 7 guided SD self-checks passed. Fixture files: $sandbox"
