[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RobotAddress,
    [string]$ReleaseDir,
    [string]$WifiProfile,
    [string]$RpiImager = "C:\Program Files\Raspberry Pi Ltd\Imager\rpi-imager.exe",
    [int]$DiskNumber,
    [switch]$PrepareOnly
)

# Guided, fail-closed path for a moved SD card. This creates a fresh card plan
# and delegates all writes to the reviewed SD writer; it never edits the robot.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Stop-Setup([string]$Message) {
    throw $Message
}

function Select-ReleaseDirectory {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "서명 검증된 ROSY OS 이미지 릴리스 폴더를 선택하세요"
    $dialog.ShowNewFolderButton = $false
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        Stop-Setup "릴리스 폴더를 선택하지 않았습니다. 변경된 항목은 없습니다."
    }
    return $dialog.SelectedPath
}

function Select-WifiProfile([string[]]$Names) {
    if (-not $Names -or $Names.Count -eq 0) {
        Stop-Setup "저장된 ROSY Wi-Fi 프로필이 없습니다. 먼저 현장 프로필을 저장하세요."
    }
    if ($Names.Count -eq 1) {
        Write-Host ("저장된 Wi-Fi 프로필 사용: " + $Names[0])
        return $Names[0]
    }
    Write-Host "저장된 Wi-Fi 프로필 (이름만 표시):"
    for ($index = 0; $index -lt $Names.Count; $index++) {
        Write-Host ("  {0}. {1}" -f ($index + 1), $Names[$index])
    }
    $answer = Read-Host "이 현장에서 사용하는 프로필 번호를 입력하세요"
    $number = 0
    if (-not [int]::TryParse($answer, [ref]$number) -or $number -lt 1 -or $number -gt $Names.Count) {
        Stop-Setup "목록에 있는 프로필 번호를 선택하세요. 변경된 항목은 없습니다."
    }
    return $Names[$number - 1]
}

function Get-SetupPage([string]$Address) {
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(8)
    try {
        $uri = "http://{0}:8080/dashboard" -f $Address
        $response = $client.GetAsync($uri).GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200) {
            Stop-Setup ("장치 페이지가 HTTP {0}을 반환했습니다. 새 장치 SETUP 상태가 아닙니다. 변경된 항목은 없습니다." -f [int]$response.StatusCode)
        }
        return $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    }
    catch [System.Net.Http.HttpRequestException] {
        Stop-Setup "장치 SETUP 페이지에 연결할 수 없습니다. IP와 현장 Wi-Fi를 확인한 뒤 다시 시도하세요. 변경된 항목은 없습니다."
    }
    catch [System.Threading.Tasks.TaskCanceledException] {
        Stop-Setup "장치 SETUP 페이지 응답 시간이 초과됐습니다. IP와 현장 Wi-Fi를 확인한 뒤 다시 시도하세요. 변경된 항목은 없습니다."
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Get-UsbDisks {
    try {
        return @(Get-Disk | Where-Object {
            $_.BusType -eq "USB" -and [int64]$_.Size -gt 0 -and -not $_.IsBoot -and -not $_.IsSystem
        } | Sort-Object Number)
    }
    catch {
        Stop-Setup "Windows에서 USB 디스크 목록을 읽지 못했습니다. 카드 리더기를 다시 연결한 뒤 시도하세요. 변경된 항목은 없습니다."
    }
}

function Select-DiskNumber([object[]]$Disks) {
    if (-not $Disks -or $Disks.Count -eq 0) {
        Stop-Setup "사용 가능한 USB 디스크가 없습니다. 새 SD 카드를 넣고 다시 시도하세요. 변경된 항목은 없습니다."
    }
    Write-Host "사용 가능한 USB 디스크입니다. 작성기가 선택한 디스크를 다시 확인합니다:"
    $Disks | Select-Object Number, FriendlyName, SerialNumber,
        @{Name = "SizeGiB"; Expression = { [math]::Round($_.Size / 1GB, 1) }},
        IsBoot, IsSystem | Format-Table -AutoSize | Out-Host
    if ($Disks.Count -eq 1) {
        $suggested = [string]$Disks[0].Number
    }
    else {
        $suggested = ""
    }
    $answer = Read-Host ("새 SD 카드의 디스크 번호를 입력하세요{0}" -f $(if ($suggested) { " [$suggested]" } else { "" }))
    if ([string]::IsNullOrWhiteSpace($answer) -and $suggested) { $answer = $suggested }
    $number = 0
    if (-not [int]::TryParse($answer, [ref]$number)) {
        Stop-Setup "목록에 있는 디스크 번호를 입력하세요. 변경된 항목은 없습니다."
    }
    $selected = @($Disks | Where-Object { [int]$_.Number -eq $number })
    if ($selected.Count -ne 1) {
        Stop-Setup "해당 디스크는 현재 사용 가능한 USB 목록에 없습니다. 변경된 항목은 없습니다."
    }
    return $number
}

function Invoke-ChildPowerShell([string[]]$Arguments) {
    $powershell = (Get-Command "powershell.exe" -ErrorAction Stop).Source
    $output = @(& $powershell -NoLogo -NoProfile -ExecutionPolicy Bypass @Arguments 2>&1)
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        $detail = ($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
        Stop-Setup ("ROSY 설정 단계가 실패했습니다 (종료 코드 {0}).`n{1}" -f $code, $detail)
    }
    return $output
}

function Add-SshAlias([string]$DeviceName, [string]$PrivateKeyPath) {
    $configPath = Join-Path $env:USERPROFILE ".ssh\config"
    $configDirectory = Split-Path -Parent $configPath
    New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    $existing = ""
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        $existing = [IO.File]::ReadAllText($configPath)
    }

    $marker = [regex]::Escape($DeviceName)
    $managedPattern = "(?ms)^# BEGIN ROSY MANAGED ALIAS $marker\r?\n.*?^# END ROSY MANAGED ALIAS $marker\r?\n?"
    $withoutManaged = [regex]::Replace($existing, $managedPattern, "")
    foreach ($match in [regex]::Matches($withoutManaged, '(?im)^\s*Host\s+([^\r\n#]+)')) {
        $aliases = $match.Groups[1].Value -split '\s+'
        if ($aliases -contains $DeviceName) {
            return $false
        }
    }

    $identityPath = $PrivateKeyPath.Replace('\', '/')
    $block = @(
        "# BEGIN ROSY MANAGED ALIAS $DeviceName"
        "Host $DeviceName"
        "    HostName $DeviceName.local"
        "    User rosy"
        "    IdentityFile `"$identityPath`""
        "    IdentitiesOnly yes"
        "    StrictHostKeyChecking ask"
        "# END ROSY MANAGED ALIAS $DeviceName"
        ""
    ) -join "`n"
    $contents = $block + $withoutManaged
    [IO.File]::WriteAllText($configPath, $contents, (New-Object Text.UTF8Encoding($false)))
    return $true
}

try {
    $parsedAddress = $null
    if (-not [System.Net.IPAddress]::TryParse($RobotAddress, [ref]$parsedAddress) -or
        $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        Stop-Setup "RobotAddress에는 192.168.1.202 형식의 IPv4 주소를 입력하세요. 변경된 항목은 없습니다."
    }
    Write-Host "1/4: 로봇의 SETUP 화면을 확인합니다..."
    $page = Get-SetupPage $RobotAddress
    if ($page -notmatch "New device registration pending|새 로봇 등록이 필요합니다") {
        Stop-Setup "페이지에는 연결됐지만 새 장치 SETUP 상태가 아닙니다. 변경된 항목은 없습니다."
    }
    Write-Host ("  {0}에서 새 장치 SETUP을 확인했습니다. SSH 키와 장치 설정은 변경하지 않았습니다." -f $RobotAddress)

    if (-not $ReleaseDir) { $ReleaseDir = Select-ReleaseDirectory }
    $ReleaseDir = (Resolve-Path -LiteralPath $ReleaseDir -ErrorAction Stop).ProviderPath
    $manifestPath = Join-Path $ReleaseDir "manifest.json"
    $sumsPath = Join-Path $ReleaseDir "SHA256SUMS"
    $signaturePath = Join-Path $ReleaseDir "SHA256SUMS.sig"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $sumsPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $signaturePath -PathType Leaf)) {
        Stop-Setup "선택한 폴더에 manifest.json, SHA256SUMS 또는 SHA256SUMS.sig가 없습니다. 변경된 항목은 없습니다."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    $releaseId = [string]$manifest.release_id
    if ($releaseId -notmatch '^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$') {
        Stop-Setup "서명 릴리스 manifest의 release ID가 올바르지 않습니다. 변경된 항목은 없습니다."
    }
    $imageName = "rosy-os-pinky-pro-{0}-arm64.img.xz" -f $releaseId
    $imagePath = Join-Path $ReleaseDir $imageName
    if (-not (Test-Path -LiteralPath $imagePath -PathType Leaf)) {
        Stop-Setup ("릴리스 폴더에 {0} 파일이 없습니다. 변경된 항목은 없습니다." -f $imageName)
    }
    $escapedImageName = [regex]::Escape($imageName)
    $hashes = @(Get-Content -LiteralPath $sumsPath -Encoding ascii | ForEach-Object {
        if ($_ -match ("^(?<hash>[0-9a-fA-F]{{64}})\s+\*?{0}$" -f $escapedImageName)) { $Matches.hash.ToLowerInvariant() }
    })
    if ($hashes.Count -ne 1) {
        Stop-Setup "SHA256SUMS에서 Pinky 이미지의 정확한 체크섬 하나를 찾지 못했습니다. 변경된 항목은 없습니다."
    }
    $publicKey = Join-Path $PSScriptRoot "..\release\public-keys\rosy-release-2026-01.pem"
    $publicKey = (Resolve-Path -LiteralPath $publicKey -ErrorAction Stop).ProviderPath

    $credentialRoot = Join-Path $env:LOCALAPPDATA "Rosy\credentials"
    $profiles = @(Get-ChildItem -LiteralPath $credentialRoot -Filter "*.credential.xml" -File -ErrorAction SilentlyContinue |
        ForEach-Object { $_.BaseName -replace '\.credential$', '' } | Sort-Object -Unique)
    if (-not $WifiProfile) { $WifiProfile = Select-WifiProfile $profiles }
    if ($WifiProfile -notmatch '^[A-Za-z0-9_.-]{1,64}$' -or $profiles -cnotcontains $WifiProfile) {
        Stop-Setup "저장된 ROSY 현장 Wi-Fi 프로필 이름을 선택하세요. Wi-Fi 비밀번호는 읽거나 표시하지 않습니다."
    }

    $registry = Join-Path $env:LOCALAPPDATA "Rosy\device-registry.json"
    if (-not (Test-Path -LiteralPath $registry -PathType Leaf)) {
        Stop-Setup "로컬 장치 등록부가 없습니다. 새 번호를 만들기 전에 현장 등록부를 복원하세요."
    }
    if (-not (Test-Path -LiteralPath "X:\DevTemp" -PathType Container)) {
        Stop-Setup "X:\DevTemp를 사용할 수 없습니다. 운영용 임시 드라이브를 연결한 뒤 다시 시도하세요. 변경된 항목은 없습니다."
    }
    if (-not $PSBoundParameters.ContainsKey("DiskNumber")) { $DiskNumber = Select-DiskNumber (Get-UsbDisks) }
    $disk = @(Get-UsbDisks | Where-Object { [int]$_.Number -eq $DiskNumber })
    if ($disk.Count -ne 1) { Stop-Setup "선택한 디스크가 바뀌었거나 더 이상 사용할 수 없습니다. 변경된 항목은 없습니다. 카드를 다시 연결한 뒤 시도하세요." }

    $sessionName = "rosy-device-setup-{0}" -f (Get-Date -Format "yyyyMMddTHHmmssfff")
    $session = Join-Path "X:\DevTemp" $sessionName
    New-Item -ItemType Directory -Path $session -ErrorAction Stop | Out-Null
    $planPath = Join-Path $session "plan.json"
    $receiptPath = Join-Path $session "receipt.json"
    $preparePath = Join-Path $PSScriptRoot "prepare-rosy-sd.ps1"
    $planArguments = @(
        "-File", $preparePath,
        "-DiskNumber", [string]$DiskNumber,
        "-Preset", "core",
        "-WifiProfile", $WifiProfile,
        "-ImagePath", $imagePath,
        "-ImageSha256", $hashes[0],
        "-ImageSignaturePath", $signaturePath,
        "-ReleasePublicKey", $publicKey,
        "-ReleaseId", $releaseId,
        "-RpiImager", $RpiImager,
        "-RegistryJson", $registry,
        "-ReceiptPath", $receiptPath,
        "-PlanPath", $planPath,
        "-PlanOnly"
    )
    $operatorKey = Join-Path $env:LOCALAPPDATA "Rosy\ssh\rosy-operator-ed25519.pub"
    if (Test-Path -LiteralPath $operatorKey -PathType Leaf) {
        $planArguments += @("-OperatorPublicKey", $operatorKey)
    }

    Write-Host "2/4: 서명된 릴리스를 확인하고 카드 미기록 계획을 만듭니다..."
    $planOutput = Invoke-ChildPowerShell $planArguments
    $planText = ($planOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    try { $plan = $planText | ConvertFrom-Json }
    catch { Stop-Setup "작성기가 읽을 수 있는 계획을 반환하지 않았습니다. 카드에는 기록하지 않았습니다." }
    if ([string]$plan.mode -cne "PLAN_ONLY" -or [string]$plan.release_id -cne $releaseId -or
        [int]$plan.disk_number -ne $DiskNumber) {
        Stop-Setup "생성된 계획이 선택한 릴리스 또는 디스크와 일치하지 않습니다. 카드에는 기록하지 않았습니다."
    }

    Write-Host ""
    Write-Host "3/4: 새 등록 정보를 확인하세요 (아직 카드에 기록하지 않았습니다):"
    [pscustomobject]@{
        Robot = $RobotAddress
        Release = $plan.release_id
        DeviceName = $plan.device_name
        RobotNumber = $plan.robot_number
        Namespace = $plan.namespace
        WifiSSID = $plan.wifi_ssid
        CardModel = $plan.disk_model
        CardSerial = $plan.disk_serial
        CardSizeGiB = [math]::Round([double]$plan.disk_size / 1GB, 1)
        Plan = $planPath
    } | Format-List | Out-Host
    Write-Host "표시된 Wi-Fi 이름이 이 로봇이 현재 사용하는 현장 네트워크와 같은지 확인하세요."
    if ($PrepareOnly) {
        Write-Host "계획을 저장했습니다. PrepareOnly가 지정되어 카드는 기록하지 않았습니다."
        exit 0
    }
    $confirmation = Read-Host ("계속하려면 REGISTER {0} 을 입력하세요" -f $plan.robot_number)
    if ($confirmation -cne ("REGISTER {0}" -f $plan.robot_number)) {
        Write-Host "중단했습니다. 카드에 기록하지 않았습니다. 계획은 X:\DevTemp에 보관했습니다."
        exit 0
    }

    Write-Host "4/4: 기존 분리 실행 카드 작성기를 시작합니다."
    Write-Host "기록 전 UAC 승인과 정확한 ERASE SERIAL 확인을 요청합니다."
    $writePath = Join-Path $PSScriptRoot "write-card.ps1"
    $writeArguments = @(
        "-File", $writePath,
        "-PlanPath", $planPath,
        "-ReleaseDir", $ReleaseDir,
        "-WifiProfile", $WifiProfile,
        "-RpiImager", $RpiImager,
        "-EvidenceDir", $session,
        "-Detach"
    )
    if (Test-Path -LiteralPath $operatorKey -PathType Leaf) {
        $writeArguments += @("-OperatorPublicKey", $operatorKey)
    }
    $writerOutput = Invoke-ChildPowerShell $writeArguments
    $writerOutput | ForEach-Object { Write-Host ([string]$_) }
    if ((Test-Path -LiteralPath $operatorKey -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $operatorKey) "rosy-operator-ed25519") -PathType Leaf)) {
        $privateKey = Join-Path (Split-Path -Parent $operatorKey) "rosy-operator-ed25519"
        try {
            if (Add-SshAlias ([string]$plan.device_name) $privateKey) {
                Write-Host "SSH 별칭을 등록했습니다. 로봇 첫 부팅 후 다음처럼 접속하세요:"
                Write-Host ("  ssh {0}" -f $plan.device_name)
            }
            else {
                Write-Warning ("기존 SSH 설정에 '{0}' 별칭이 있어 덮어쓰지 않았습니다. 접속 명령: ssh -i `"{1}`" rosy@{0}.local" -f $plan.device_name, $privateKey)
            }
        }
        catch {
            Write-Warning ("SSH 별칭을 저장하지 못했습니다. 직접 접속 명령: ssh -i `"{0}`" rosy@{1}.local ({2})" -f $privateKey, $plan.device_name, $_.Exception.Message)
        }
    }
    else {
        Write-Host "저장된 rosy 운영자 SSH 키 쌍이 없어 이번 카드에 SSH 키를 넣지 않았습니다."
        Write-Host "SSH 별칭은 만들지 않았습니다. 키를 준비한 뒤 카드를 다시 등록해야 SSH 키 로그인이 가능합니다."
    }
    Write-Host "카드 기록 성공은 장치 승인과 다릅니다. 전체 readback 성공 후 같은 Pi에 넣고 첫 부팅과 대시보드의 새 장치 정보를 확인하세요."
    if ((Test-Path -LiteralPath $operatorKey -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $operatorKey) "rosy-operator-ed25519") -PathType Leaf)) {
        Write-Host "첫 SSH 접속에서는 실물 장치의 호스트 키 지문을 확인해 신뢰 등록해야 합니다. 이미 검증한 다른 별칭은 -SshHost로 지정할 수 있습니다."
        Write-Host "첫 부팅 후 현장 담당자가 로봇과 전원 차단 경로를 확인하면 모터 점검과 E-Stop 상태의 구동 준비를 한 번에 진행할 수 있습니다:"
        Write-Host ("  .\deploy\robot\pinky_pro\sd\enable-motor-commissioning.ps1 -DeviceName {0} -RobotAddress {1} -OperatorPresent -PowerCutReady" -f $plan.device_name, $RobotAddress)
        Write-Host "이 단계는 주행 명령이나 G4 승인을 만들지 않습니다. 현장 주행 시험과 실측 기록은 별도로 수행합니다."
    }
}
catch {
    Write-Error $_
    exit 1
}
