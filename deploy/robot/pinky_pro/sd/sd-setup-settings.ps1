function Read-SdSetupSettings([string]$ConfigPath, [Collections.IDictionary]$Overrides) {
    if (-not $ConfigPath) { $ConfigPath = Join-Path $PSScriptRoot "..\..\..\..\sd-setup.local.json" }
    if (-not [IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath = Join-Path (Get-Location).ProviderPath $ConfigPath }
    $ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
    $fields = @{
        release_dir="ReleaseDir"; wifi_profile="WifiProfile"; wifi_ssid="WifiSsid";
        registry_path="RegistryJson"; rpi_imager="RpiImager"; card_count="CardCount"; expected_image_revision="ExpectedImageRevision"
    }
    $settings = @{
        ConfigPath=$ConfigPath; ReleaseDir=""; WifiProfile=""; WifiSsid=""; CardCount=1; ExpectedImageRevision="";
        RegistryJson=(Join-Path $env:LOCALAPPDATA "Rosy\device-registry.json");
        RpiImager="C:\Program Files\Raspberry Pi Ltd\Imager\rpi-imager.exe"
    }
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        try {
            $json = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8
            if (-not $json.TrimStart().StartsWith("{")) { throw "object required" }
            $config = $json | ConvertFrom-Json
        }
        catch { Stop-Setup "SD 설정 JSON을 읽을 수 없습니다. 파일 형식을 확인하세요. 설정 내용은 표시하지 않습니다." }
        if (-not ($config -is [pscustomobject]) -or -not $config.PSObject.Properties["schema_version"] -or
            -not ($config.schema_version -is [int]) -or $config.schema_version -ne 1) {
            Stop-Setup "SD 설정 schema_version은 정수 1이어야 합니다."
        }
        foreach ($property in $config.PSObject.Properties) {
            if ($property.Name -eq "schema_version") { continue }
            if (-not $fields.ContainsKey($property.Name)) {
                Stop-Setup "지원하지 않는 SD 설정 항목이 있습니다. 비밀번호·키는 JSON에 넣지 말고 예제의 항목만 사용하세요."
            }
            if ($property.Name -eq "card_count") {
                if (-not ($property.Value -is [int]) -or $property.Value -lt 1 -or $property.Value -gt 10) {
                    Stop-Setup "card_count는 1부터 10까지의 정수여야 합니다."
                }
            }
            elseif (-not ($property.Value -is [string])) { Stop-Setup "SD 설정의 경로와 Wi-Fi 항목은 문자열이어야 합니다." }
            $settings[$fields[$property.Name]] = $property.Value
        }
    }
    foreach ($key in @("ReleaseDir", "WifiProfile", "RpiImager", "CardCount", "ExpectedImageRevision")) {
        if ($Overrides.ContainsKey($key)) { $settings[$key] = $Overrides[$key] }
    }
    if ($settings.ExpectedImageRevision -and $settings.ExpectedImageRevision -cnotmatch '^[0-9a-f]{40}$') {
        Stop-Setup "expected_image_revision은 비어 있거나 소문자 40자리 Git commit이어야 합니다. HEAD 같은 별칭은 사용할 수 없습니다."
    }
    foreach ($key in @("ReleaseDir", "RegistryJson", "RpiImager")) {
        if (-not $settings[$key]) { continue }
        $path = [Environment]::ExpandEnvironmentVariables($settings[$key])
        if ($key -eq "RpiImager" -and (Get-Command $path -ErrorAction SilentlyContinue)) {
            $path = (Get-Command $path -ErrorAction Stop).Source
        }
        elseif (-not [IO.Path]::IsPathRooted($path)) {
            $base = $(if ($Overrides.ContainsKey($key)) { (Get-Location).ProviderPath } else { Split-Path -Parent $ConfigPath })
            $path = Join-Path $base $path
        }
        $settings[$key] = [IO.Path]::GetFullPath($path)
    }
    return $settings
}

function Test-SdSetupRegistry([string]$Path) {
    try { $registry = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { Stop-Setup "장치 등록부 JSON을 읽을 수 없습니다. 현장 원본을 확인하세요." }
    foreach ($key in @("robot_numbers", "device_names", "device_uids")) {
        if (-not $registry.PSObject.Properties[$key] -or $registry.$key -isnot [Array]) {
            Stop-Setup "장치 등록부에는 robot_numbers, device_names, device_uids 배열이 필요합니다."
        }
    }
}

function Initialize-SdSetupSettings([string]$ConfigPath, [Collections.IDictionary]$Overrides, [switch]$ReadOnly) {
    $settings = Read-SdSetupSettings $ConfigPath $Overrides
    if ($ReadOnly -and $settings.CardCount -gt 1) {
        Stop-Setup "PrepareOnly는 한 장만 계획할 수 있습니다. 앞 카드의 검증·등록부 갱신 후 다음 번호를 배정해야 합니다."
    }
    if (-not $settings.ReleaseDir) { $settings.ReleaseDir = Select-ReleaseDirectory }
    $credentialRoot = Join-Path $env:LOCALAPPDATA "Rosy\credentials"
    $profiles = @(Get-ChildItem -LiteralPath $credentialRoot -Filter "*.credential.xml" -File -ErrorAction SilentlyContinue |
        ForEach-Object { $_.BaseName -replace '\.credential$', '' } | Sort-Object -Unique)
    if (-not $settings.WifiProfile) {
        if ($profiles.Count -gt 0 -or $ReadOnly) { $settings.WifiProfile = Select-WifiProfile $profiles }
        else { $settings.WifiProfile = Read-Host "새 현장 Wi-Fi 프로필 이름 (예: site)" }
    }
    if ($settings.WifiProfile -notmatch '^[A-Za-z0-9_.-]{1,64}$') { Stop-Setup "Wi-Fi 프로필 이름이 올바르지 않습니다." }
    $credentialPath = Join-Path $credentialRoot ($settings.WifiProfile + ".credential.xml")
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) {
        if ($ReadOnly) { Stop-Setup "저장된 ROSY 현장 Wi-Fi 프로필이 없습니다. 일반 실행으로 먼저 설정하세요." }
        if (-not $settings.WifiSsid) { $settings.WifiSsid = Read-Host "현장 Wi-Fi 이름 (SSID)" }
        Write-Host "Wi-Fi 비밀번호를 보안 입력으로 저장합니다. JSON에는 저장하지 않습니다."
        Invoke-ChildPowerShell @("-File", (Join-Path $PSScriptRoot "prepare-rosy-sd.ps1"),
            "-SetWifiCredential", "-WifiProfile", $settings.WifiProfile, "-WifiSsid", $settings.WifiSsid) |
            ForEach-Object { Write-Host ([string]$_) }
    }
    if (-not $ReadOnly -or $settings.WifiSsid) {
        try { $credential = Import-Clixml -LiteralPath $credentialPath }
        catch { Stop-Setup "현재 Windows 사용자로 Wi-Fi 프로필을 읽을 수 없습니다. 보안 입력으로 다시 저장하세요." }
        if ($settings.WifiSsid -and $settings.WifiSsid -cne $credential.UserName) {
            Stop-Setup "설정의 SSID와 저장된 Wi-Fi 프로필이 다릅니다. 현장 프로필을 확인하세요."
        }
        $settings.WifiSsid = [string]$credential.UserName
    }
    if (-not (Test-Path -LiteralPath $settings.RegistryJson -PathType Leaf)) {
        if ($ReadOnly) { Stop-Setup "로컬 장치 등록부가 없습니다. 현장 등록부를 복원하세요." }
        $answer = Read-Host "기존 현장 등록부의 전체 경로를 입력하세요. 현장의 첫 등록일 때만 NEW SITE 입력"
        if ([string]::IsNullOrWhiteSpace($answer)) { Stop-Setup "장치 등록부를 선택하지 않았습니다." }
        New-Item -ItemType Directory -Path (Split-Path -Parent $settings.RegistryJson) -Force | Out-Null
        if ($answer -ceq "NEW SITE") {
            $stream = [IO.File]::Open($settings.RegistryJson, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $writer = New-Object IO.StreamWriter($stream, (New-Object Text.UTF8Encoding($false)))
            try { $writer.Write('{"robot_numbers":[],"device_names":[],"device_uids":[]}') }
            finally { $writer.Dispose() }
        }
        else {
            $source = (Resolve-Path -LiteralPath $answer -ErrorAction Stop).ProviderPath
            Test-SdSetupRegistry $source
            [IO.File]::Copy($source, $settings.RegistryJson, $false)
        }
    }
    Test-SdSetupRegistry $settings.RegistryJson
    if (-not $ReadOnly) {
        $config = [ordered]@{schema_version=1;release_dir=$settings.ReleaseDir;wifi_profile=$settings.WifiProfile;
            wifi_ssid=$settings.WifiSsid;registry_path=$settings.RegistryJson;rpi_imager=$settings.RpiImager;card_count=$settings.CardCount;
            expected_image_revision=$settings.ExpectedImageRevision}
        $temporary = $settings.ConfigPath + ".tmp-" + [guid]::NewGuid().ToString("N")
        try {
            $config | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding utf8
            Move-Item -LiteralPath $temporary -Destination $settings.ConfigPath -Force
        }
        finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
        Write-Host ("공통 SD 설정 저장: " + $settings.ConfigPath)
        if (-not (Test-Path -LiteralPath $settings.RpiImager -PathType Leaf)) {
            Stop-Setup "Raspberry Pi Imager가 없습니다. winget install --id RaspberryPiFoundation.RaspberryPiImager --exact 로 설치하거나 JSON의 rpi_imager 경로를 수정한 뒤 다시 실행하세요."
        }
    }
    return $settings
}
