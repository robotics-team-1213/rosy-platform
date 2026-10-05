<# Install a reviewed fixed signing coordinator; main/artifacts stay data. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ConfigPath,
    [string]$TaskName = "RosyRobotCD",
    [int]$IntervalMinutes = 5,
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$configFile = (Resolve-Path -LiteralPath $ConfigPath).Path
if ($configFile.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Robot addresses/configuration must stay outside the repository."
}
if ($IntervalMinutes -lt 2 -or $IntervalMinutes -gt 1440) { throw "Invalid interval." }
if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
$revision = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[0-9a-f]{40}$') { throw "No source revision." }
$files = @(
    "tools/release/robot_cd.py",
    "tools/release/prepare_payload_release.py",
    "tools/release/publish_payload_release.py",
    "tools/release/download_artifact.py",
    "deploy/robot/pinky_pro/release/signing.py",
    "deploy/robot/pinky_pro/release/sign_image_release.py",
    "deploy/robot/pinky_pro/release/build_payload_release.py"
)
$keyFiles = @(& git -C $repo ls-files "deploy/robot/pinky_pro/release/public-keys/*.pem")
if ($LASTEXITCODE -ne 0 -or $keyFiles.Count -eq 0) { throw "No tracked public release keys." }
$files += $keyFiles
$dirty = & git -C $repo status --porcelain -- @files
if ($LASTEXITCODE -ne 0 -or $dirty) { throw "Commit/review the coordinator and helper files before installing." }
$base = Join-Path $env:LOCALAPPDATA "Rosy/robot-cd"
$snapshot = Join-Path $base "versions/$revision"
if (Test-Path -LiteralPath $snapshot) { throw "An installation for this revision already exists; preserve it." }
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null
$hashes = @{}
foreach ($file in $files) {
    $target = Join-Path $snapshot $file
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo $file) -Destination $target
    $hashes[$file] = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $snapshot "trusted-snapshot.json"), (@{source_revision=$revision;files=$hashes} | ConvertTo-Json -Depth 5), $utf8)
$config = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 | ConvertFrom-Json
$config | Add-Member -NotePropertyName trusted_root -NotePropertyValue $snapshot -Force
New-Item -ItemType Directory -Path $base -Force | Out-Null
$installedConfig = Join-Path $base "config.json"
[IO.File]::WriteAllText($installedConfig, ($config | ConvertTo-Json -Depth 8), $utf8)
$entry = Join-Path $snapshot "tools/release/robot_cd.py"
$action = New-ScheduledTaskAction -Execute $Python -Argument ('-B "{0}" --config "{1}"' -f $entry, $installedConfig) -WorkingDirectory $snapshot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 60) -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "ROSY robot CD: successful main CI, unsigned ARM64 build, local signing, guarded rollout" | Out-Null
Write-Host "Installed approved snapshot $revision; task $TaskName checks every $IntervalMinutes minutes while logged on."
Write-Host "Private release keys remain in the existing local signing store."
