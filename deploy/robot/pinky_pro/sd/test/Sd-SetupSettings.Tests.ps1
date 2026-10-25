param([string]$Source = (Join-Path $PSScriptRoot "..\setup-moved-device.ps1"))

# Exercise the real entry point; external writers, disks and signatures are fixtures.
$ErrorActionPreference = "Stop"
$sandbox = Join-Path ([IO.Path]::GetTempPath()) ("rosy sd settings " + [guid]::NewGuid().ToString("N"))
$sd = Join-Path $sandbox "sd"
$release = Join-Path $sandbox "release"
$local = Join-Path $sandbox "local"
foreach ($path in @($sd, $release, "$sandbox\release\public-keys", "$local\Rosy\credentials", "$sandbox\scratch")) {
    New-Item -ItemType Directory -Path $path -Force | Out-Null
}
function Save([string]$Path, [string]$Text) { [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($true))) }
Copy-Item -LiteralPath $Source -Destination "$sd\setup-moved-device.ps1"
foreach ($helper in @("sd-setup-settings.ps1", "sd-card-completion.ps1", "sd-batch-state.ps1")) {
    $path = Join-Path (Split-Path -Parent $Source) $helper
    if (Test-Path -LiteralPath $path) { Copy-Item -LiteralPath $path -Destination $sd }
}
Save "$release\manifest.json" '{"release_id":"2026.10.19-001"}'
Save "$release\SHA256SUMS.sig" "fixture signature"
Save "$release\public-keys\rosy-release-2026-01.pem" "fixture public key"
Save "$release\rosy-os-pinky-pro-2026.10.19-001-arm64.img.xz" "fixture image"
Save "$release\SHA256SUMS" (("a" * 64) + "  rosy-os-pinky-pro-2026.10.19-001-arm64.img.xz")
Save "$sandbox\imager.exe" "fixture executable, never run"
Save "$sd\verify-image-release.py" @'
import json, os, sys
from pathlib import Path
with Path(os.environ['SD_EVENTS']).open('a') as events:
    events.write('verify\n')
if os.environ.get('SD_CASE') == 'signature':
    raise SystemExit(5)
if '--expected-source-revision' in sys.argv:
    expected = sys.argv[sys.argv.index('--expected-source-revision') + 1]
    with Path(os.environ['SD_EVENTS']).open('a') as events:
        events.write('expected_revision:' + expected + '\n')
    if expected != 'c' * 40:
        raise SystemExit(6)
print(json.dumps(dict(ok='true', release_id='2026.10.19-001',
    image='rosy-os-pinky-pro-2026.10.19-001-arm64.img.xz', sha256='a' * 64,
    source_revision='c' * 40)))
'@
Save "$sd\prepare-rosy-sd.ps1" @'
param([string]$PlanPath, [string]$ReceiptPath, [string]$RegistryJson, [int]$DiskNumber,
      [string]$Preset, [string]$WifiProfile, [string]$WifiSsid, [string]$ImagePath,
      [string]$ImageSha256, [string]$ImageSignaturePath, [string]$ReleasePublicKey,
      [string]$ReleaseId, [string]$RpiImager, [switch]$PlanOnly, [switch]$SetWifiCredential)
if ($SetWifiCredential) {
    New-Item -ItemType Directory -Path "$env:LOCALAPPDATA\Rosy\credentials" -Force | Out-Null
    $secure = ConvertTo-SecureString "fixture only" -AsPlainText -Force
    New-Object Management.Automation.PSCredential($WifiSsid, $secure) |
        Export-Clixml -LiteralPath "$env:LOCALAPPDATA\Rosy\credentials\$WifiProfile.credential.xml"
    Add-Content -LiteralPath $env:SD_EVENTS -Value "wifi"
    exit 0
}
if (-not $PlanOnly -or $Preset -cne "core") { throw "expected a no-write core plan" }
$registry = Get-Content -LiteralPath $RegistryJson -Raw | ConvertFrom-Json
$number = 40 + @($registry.robot_numbers).Count
if ($env:SD_CASE -eq "duplicate-number") { $number = 40 }
Add-Content -LiteralPath $env:SD_EVENTS -Value "plan:$number"
$plan = @{mode="PLAN_ONLY";release_id=$ReleaseId;disk_number=$DiskNumber;
    device_name="rosy-pinky-test$number";device_uid="fixture-uid-$number";robot_number=$number;
    namespace="rosy_$number";wifi_ssid="fixture-site";disk_model="fixture";
    disk_serial="FIXTURE-7";disk_size=34359738368;image_sha256=$ImageSha256;registry_path=$RegistryJson}
if ($env:SD_CASE -eq "duplicate-name") { $plan.device_name = "rosy-pinky-test40" }
if ($env:SD_CASE -eq "duplicate-uid") { $plan.device_uid = "fixture-uid-40" }
if ($env:SD_CASE -eq "image-drift" -and $number -eq 41) { $plan.image_sha256 = "b" * 64 }
$plan | ConvertTo-Json | Set-Content -LiteralPath $PlanPath
$plan | ConvertTo-Json
'@
Save "$sd\write-card.ps1" @'
param([string]$PlanPath, [string]$ReleaseDir, [string]$WifiProfile, [string]$RpiImager,
      [string]$EvidenceDir, [string]$LogPath, [switch]$Detach)
if (-not $Detach -or -not $LogPath) { throw "expected the existing detached writer with a pinned log" }
Add-Content -LiteralPath $env:SD_EVENTS -Value "write"
@{plan=$PlanPath;log=$LogPath} | ConvertTo-Json | Set-Content -LiteralPath "$EvidenceDir\pending.json"
'@
Save "$sd\card-write-status.ps1" @'
param([string]$LogPath, [switch]$Json)
$pending = Get-Content -LiteralPath (Join-Path (Split-Path -Parent $LogPath) "pending.json") -Raw | ConvertFrom-Json
$plan = Get-Content -LiteralPath $pending.plan -Raw | ConvertFrom-Json
Add-Content -LiteralPath $env:SD_EVENTS -Value "wait:$($plan.robot_number)"
if ($env:SD_CASE -eq "writer") { "9" | Set-Content -LiteralPath "$LogPath.exit"; exit 0 }
$receipt = @{device_uid=$plan.device_uid;device_name=$plan.device_name;robot_number=$plan.robot_number;
    release_id=$plan.release_id;disk_serial=$plan.disk_serial;image_sha256=$plan.image_sha256;
    writer_exit_code=0;media_readback=@{verified=($env:SD_CASE -ne "readback")}}
if ($env:SD_CASE -eq "identity") { $receipt.device_uid = "wrong fixture identity" }
$receiptPath = Join-Path (Split-Path -Parent $LogPath) "receipt-$($plan.release_id)-$($plan.device_name).json"
$receipt | ConvertTo-Json | Set-Content -LiteralPath $receiptPath
if ($env:SD_CASE -ne "registry") {
    $registry = Get-Content -LiteralPath $plan.registry_path -Raw | ConvertFrom-Json
    $registry.robot_numbers = @($registry.robot_numbers) + $plan.robot_number
    $registry.device_names = @($registry.device_names) + $plan.device_name
    $registry.device_uids = @($registry.device_uids) + $plan.device_uid
    $registry | ConvertTo-Json | Set-Content -LiteralPath $plan.registry_path
}
"0" | Set-Content -LiteralPath "$LogPath.exit"
@{result="complete";stage="done";stalled=$false;job_eta_seconds=0} | ConvertTo-Json
'@
$driver = "$sandbox\driver.ps1"
Save $driver @'
param([switch]$PrepareOnly, [switch]$Configure, [int]$CardCount, [string]$ReleaseDir, [string]$ExpectedImageRevision)
$ErrorActionPreference = "Stop"
$env:LOCALAPPDATA = "$env:SD_SANDBOX\local"
$env:ROSY_SCRATCH = "$env:SD_SANDBOX\scratch"
function Get-Disk {
    Add-Content -LiteralPath $env:SD_EVENTS -Value "disk"
    [pscustomobject]@{Number=7;BusType="USB";Size=34359738368;IsBoot=$false;IsSystem=$false;FriendlyName="fixture";SerialNumber="FIXTURE-7"}
}
function Read-Host([string]$Prompt) {
    if ($Prompt -match '\[7\]') { return "7" }
    if ($Prompt -match 'REGISTER (\d+)') {
        if ($env:SD_CASE -eq "cancel-card-two" -and $Matches[1] -eq "41") { return "" }
        return "REGISTER $($Matches[1])"
    }
    if ($Prompt -match 'NEXT (\d+)') { return "NEXT $($Matches[1])" }
    if ($Prompt -match 'NEW SITE') { if ($env:SD_CASE -eq "cancel-registry") { return "" }; return "NEW SITE" }
    throw "unexpected prompt: $Prompt"
}
$arguments = @{ConfigPath="$env:SD_SANDBOX\sd-setup.local.json"}
if ($PrepareOnly) { $arguments.PrepareOnly = $true }
if ($Configure) { $arguments.Configure = $true }
if ($PSBoundParameters.ContainsKey("CardCount")) { $arguments.CardCount = $CardCount }
if ($PSBoundParameters.ContainsKey("ReleaseDir")) { $arguments.ReleaseDir = $ReleaseDir }
if ($PSBoundParameters.ContainsKey("ExpectedImageRevision")) { $arguments.ExpectedImageRevision = $ExpectedImageRevision }
& "$env:SD_SANDBOX\sd\setup-moved-device.ps1" @arguments
exit $LASTEXITCODE
'@
$env:SD_SANDBOX = $sandbox
$env:SD_EVENTS = "$sandbox\events.txt"
$registry = "$local\Rosy\device-registry.json"
$configPath = "$sandbox\sd-setup.local.json"
function Reset-Fixture {
    foreach ($directory in @(Get-ChildItem -LiteralPath "$sandbox\scratch" -Directory)) {
        if (-not $directory.FullName.StartsWith(([IO.Path]::GetFullPath($sandbox) + "\"), [StringComparison]::OrdinalIgnoreCase)) { throw "fixture cleanup escaped sandbox" }
        Remove-Item -LiteralPath $directory.FullName -Recurse -Force
    }
    Save $registry '{"robot_numbers":[],"device_names":[],"device_uids":[]}'
    $secure = ConvertTo-SecureString "fixture only" -AsPlainText -Force
    New-Object Management.Automation.PSCredential("fixture-site", $secure) |
        Export-Clixml -LiteralPath "$local\Rosy\credentials\site.credential.xml"
    $config = @{schema_version=1;release_dir="release";wifi_profile="site";wifi_ssid="fixture-site";
        registry_path="local/Rosy/device-registry.json";rpi_imager="imager.exe";card_count=3}
    Save $configPath ($config | ConvertTo-Json)
    Save $env:SD_EVENTS ""
    $env:SD_CASE = "success"
}
function Run-Fixture([string[]]$Extra = @()) {
    $ErrorActionPreference = "Continue"
    $output = @(& powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $driver @Extra 2>&1)
    [pscustomobject]@{Code=$LASTEXITCODE;Text=($output | Out-String)}
}
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Read-BatchReport {
    $reports = @(Get-ChildItem -LiteralPath "$sandbox\scratch" -Filter batch.json -Recurse)
    Assert ($reports.Count -eq 1) "one batch report must survive the run"
    $text = Get-Content -LiteralPath $reports[0].FullName -Raw
    Assert ($text -notmatch 'fixture only|fixture-site|password|credential|FIXTURE-7') "batch report must only contain identity and evidence references"
    $text | ConvertFrom-Json
}
Reset-Fixture
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$config | Add-Member -NotePropertyName expected_image_revision -NotePropertyValue ("c" * 40)
Save $configPath ($config | ConvertTo-Json)
$result = Run-Fixture @("-PrepareOnly", "-CardCount", "1")
Assert ($result.Code -eq 0) ("configured source pin must permit its exact image: " + $result.Text)
Assert ((Get-Content -LiteralPath $env:SD_EVENTS) -contains ("expected_revision:" + ("c" * 40))) "source pin must reach the cryptographic verifier"
$proof = @(Get-ChildItem -LiteralPath "$sandbox\scratch" -Filter verified-image.json -Recurse)
Assert ($proof.Count -eq 1) "single-card planning must preserve verified image source evidence"
Assert ((Get-Content -LiteralPath $proof[0].FullName -Raw | ConvertFrom-Json).source_revision -ceq ("c" * 40)) "image source must come from the verified release"
Save $env:SD_EVENTS ""
$result = Run-Fixture @("-PrepareOnly", "-CardCount", "1", "-ExpectedImageRevision", ("b" * 40))
Assert ($result.Code -ne 0) "a CLI source mismatch must override config and fail"
Assert (-not ((Get-Content -LiteralPath $env:SD_EVENTS) -match '^disk$|^write$')) "source mismatch must stop before any disk discovery"
Write-Output "PASS: signed source evidence is preserved and an exact source pin fails before media access"
Reset-Fixture
Save $registry '{"robot_numbers":[40,41,42,43,44,45,46,47],"device_names":[],"device_uids":[]}'
$result = Run-Fixture
Assert ($result.Code -ne 0) "three cards with only two free numbers must fail"
Assert (-not ((Get-Content -LiteralPath $env:SD_EVENTS) -match '^disk$|^write$')) "capacity shortage must stop before discovering or writing any card"
Write-Output "PASS: batch capacity is checked before any media access"
Reset-Fixture
Save $registry '{"robot_numbers":[40,41,42,43,44,45,46,47],"device_names":[],"device_uids":[]}'
$result = Run-Fixture @("-CardCount", "2")
Assert ($result.Code -eq 0) ("exact available capacity must work: " + $result.Text)
$report = Read-BatchReport
Assert (($report.cards.robot_number -join ',') -ceq '48,49') "batch must preserve the available automatic-number range"
Reset-Fixture
$result = Run-Fixture
Assert ($result.Code -eq 0) ("root settings must prepare three cards: " + $result.Text)
$events = @(Get-Content -LiteralPath $env:SD_EVENTS | Where-Object { $_ -match '^(plan|wait):' })
Assert (($events -join ',') -ceq 'plan:40,wait:40,plan:41,wait:41,plan:42,wait:42') "each next plan must wait for verified completion and registry update"
Assert (@(Get-Content -LiteralPath $env:SD_EVENTS | Where-Object { $_ })[0] -ceq "verify") "signature verification must precede disk discovery"
$report = Read-BatchReport
Assert ($report.status -ceq "completed" -and $report.completed_count -eq 3 -and $report.remaining_count -eq 0) "batch report must account for all verified cards"
Assert ($report.source_revision -ceq ("c" * 40)) "batch results must identify the verified image source"
Assert (($report.cards.robot_number -join ',') -ceq '40,41,42') "report must bind each verified card to its identity"
foreach ($card in $report.cards) { Assert (Test-Path -LiteralPath $card.receipt_path) "verified card evidence must exist" }
Write-Output "PASS: root settings resolve relative paths and register three distinct cards in order"
foreach ($failure in @("duplicate-number", "duplicate-name", "duplicate-uid", "image-drift")) {
    Reset-Fixture
    $env:SD_CASE = $failure
    $result = Run-Fixture
    Assert ($result.Code -ne 0) "$failure must fail the batch"
    Assert (@(Get-Content -LiteralPath $env:SD_EVENTS | Where-Object { $_ -eq 'write' }).Count -eq 1) "$failure must stop before the second writer"
    $report = Read-BatchReport
    Assert ($report.status -ceq "stopped" -and $report.completed_count -eq 1 -and $report.remaining_count -eq 2) "duplicate failure must preserve first-card success"
}
Write-Output "PASS: repeated identities stop before another writer"
foreach ($failure in @("writer", "readback", "identity", "registry")) {
    Reset-Fixture
    $env:SD_CASE = $failure
    $result = Run-Fixture
    Assert ($result.Code -ne 0) "$failure must fail the batch"
    $plans = @(Get-Content -LiteralPath $env:SD_EVENTS | Where-Object { $_ -match '^plan:' })
    Assert ($plans.Count -eq 1) "$failure must stop before planning card two"
    $report = Read-BatchReport
    Assert ($report.status -ceq "stopped" -and $report.completed_count -eq 0 -and $report.remaining_count -eq 3) "unverified media must never count as completed"
    Assert (Test-Path -LiteralPath $report.active_card.plan_path) "interrupted card must retain a plan reference for investigation"
}
Write-Output "PASS: writer, readback, identity and registry failures stop before the next card"
foreach ($bad in @(@{password="<fixture-secret-not-allowed>"}, @{card_count=2.5}, @{card_count=0}, @{schema_version=2}, @{expected_image_revision="HEAD"})) {
    Reset-Fixture
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    foreach ($key in $bad.Keys) { $config | Add-Member -NotePropertyName $key -NotePropertyValue $bad[$key] -Force }
    Save $configPath ($config | ConvertTo-Json)
    $result = Run-Fixture
    Assert ($result.Code -ne 0) "invalid or secret-bearing settings must be rejected"
    Assert (-not ((Get-Content -LiteralPath $env:SD_EVENTS) -match '^disk$')) "invalid settings must fail before disk discovery"
    Assert ($result.Text -notmatch "<fixture-secret-not-allowed>") "settings rejection must not echo a secret value"
}
Write-Output "PASS: secret fields, invalid counts and unknown schemas fail before disk discovery"
Reset-Fixture
$env:SD_CASE = "signature"
$result = Run-Fixture
Assert ($result.Code -ne 0) "invalid signature must fail"
Assert (-not ((Get-Content -LiteralPath $env:SD_EVENTS) -match '^disk$')) "invalid signature must fail before disk discovery"
Reset-Fixture
$result = Run-Fixture @("-PrepareOnly")
Assert ($result.Code -ne 0) "multiple no-write plans must not allocate duplicate identities"
Assert (-not ((Get-Content -LiteralPath $env:SD_EVENTS) -match '^write$')) "PrepareOnly must never launch a writer"
Write-Output "PASS: signature failure and multiple PrepareOnly cards never reach a writer"
Reset-Fixture
$result = Run-Fixture @("-PrepareOnly", "-CardCount", "1")
Assert ($result.Code -eq 0) ("explicit arguments must override config: " + $result.Text)
Assert ((Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json).card_count -eq 3) "PrepareOnly must not update saved settings"
Assert (-not ((Get-Content -LiteralPath $env:SD_EVENTS) -match '^write$')) "single PrepareOnly must not launch a writer"
Write-Output "PASS: explicit arguments override config without changing it during PrepareOnly"
Reset-Fixture
Remove-Item -LiteralPath "$local\Rosy\credentials\site.credential.xml", $registry
$result = Run-Fixture @("-Configure")
Assert ($result.Code -eq 0) ("missing local settings must be guided without writing a card: " + $result.Text)
Assert (Test-Path -LiteralPath "$local\Rosy\credentials\site.credential.xml") "guided setup must use the existing encrypted credential store"
Assert (Test-Path -LiteralPath $registry) "explicit NEW SITE must create the initial registry"
Assert (-not ((Get-Content -LiteralPath $env:SD_EVENTS) -match '^disk$|^write$')) "Configure must never discover or write media"
$saved = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
Assert (-not $saved.PSObject.Properties["password"]) "saved root config must not contain a password"
Write-Output "PASS: Configure fills missing credentials and explicitly creates a first-site registry without touching media"
Reset-Fixture
Remove-Item -LiteralPath $registry
$env:SD_CASE = "cancel-registry"
$result = Run-Fixture @("-Configure")
Assert ($result.Code -ne 0 -and -not (Test-Path -LiteralPath $registry)) "missing registry must never silently become an empty registry"
Write-Output "PASS: cancelling registry setup preserves the missing registry and stops"
Reset-Fixture
$env:SD_CASE = "cancel-card-two"
$result = Run-Fixture
Assert ($result.Code -ne 0) "cancelling card two must not report batch success"
Assert (@(Get-Content -LiteralPath $env:SD_EVENTS | Where-Object { $_ -eq 'write' }).Count -eq 1) "cancelled card two must not launch its writer"
$report = Read-BatchReport
Assert ($report.status -ceq "stopped" -and $report.completed_count -eq 1 -and $report.remaining_count -eq 2) "cancellation must preserve verified progress"
Reset-Fixture
$configText = Get-Content -LiteralPath $configPath -Raw
Save $configPath ("[" + $configText + "]")
$result = Run-Fixture
Assert ($result.Code -ne 0) "a root JSON array must not be treated as a settings object"
Write-Output "PASS: card cancellation and a JSON array cannot report a successful batch"
Reset-Fixture
Push-Location $sd
try { $result = Run-Fixture @("-PrepareOnly", "-CardCount", "1", "-ReleaseDir", "../release") }
finally { Pop-Location }
Assert ($result.Code -eq 0) ("explicit relative paths must retain the caller's working-directory semantics: " + $result.Text)
Write-Output "PASS: explicit relative paths use the caller directory instead of the saved config directory"
Reset-Fixture
Save $registry '{"robot_numbers":40,"device_names":[],"device_uids":[]}'
$result = Run-Fixture @("-Configure")
Assert ($result.Code -ne 0) "an invalid registry must not be reported as configured"
Write-Output "PASS: invalid registry structure cannot be accepted as ready"
Write-Output "SD settings and three-card fixture checks passed. Fixtures: $sandbox"
