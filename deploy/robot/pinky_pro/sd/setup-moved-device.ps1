[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()][string]$RobotAddress,
    [string]$ReleaseDir,
    [string]$WifiProfile,
    [string]$RpiImager = "C:\Program Files\Raspberry Pi Ltd\Imager\rpi-imager.exe",
    [int]$DiskNumber,
    [string]$ConfigPath,
    [ValidateRange(1, 10)][int]$CardCount = 1,
    [switch]$Configure,
    [switch]$PrepareOnly
)

# Guided, fail-closed path for a new SD card, also used after moving a card.
# Omit RobotAddress for a new card; supply it to check a moved-card SETUP page.
# This creates a fresh card plan
# and delegates all writes to the reviewed SD writer; it never edits the robot.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sd-setup-settings.ps1")
. (Join-Path $PSScriptRoot "sd-card-completion.ps1")
. (Join-Path $PSScriptRoot "sd-batch-state.ps1")
$batch = $null

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
        Stop-Setup "저장된 ROSY Wi-Fi 프로필이 없습니다. 먼저 .\deploy\robot\pinky_pro\sd\prepare-rosy-sd.ps1 -SetWifiCredential -WifiProfile <profile> -WifiSsid <ssid> 로 현장 프로필을 저장한 뒤 다시 실행하세요. 비밀번호는 보안 입력창에서만 입력합니다."
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
    if ($PSBoundParameters.ContainsKey("RobotAddress")) {
        $parsedAddress = $null
        if (-not [System.Net.IPAddress]::TryParse($RobotAddress, [ref]$parsedAddress) -or
            $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
            Stop-Setup "RobotAddress에는 192.0.2.10 형식의 IPv4 주소를 입력하세요. 변경된 항목은 없습니다."
        }
        Write-Host "1/4: 로봇의 SETUP 화면을 확인합니다..."
        $page = Get-SetupPage $RobotAddress
        if ($page -notmatch "New device registration pending|새 로봇 등록이 필요합니다") {
            Stop-Setup "페이지에는 연결됐지만 새 장치 SETUP 상태가 아닙니다. 변경된 항목은 없습니다."
        }
        Write-Host ("  {0}에서 새 장치 SETUP을 확인했습니다. SSH 키와 장치 설정은 변경하지 않았습니다." -f $RobotAddress)
    }
    else {
        Write-Host "1/4: 새 SD 카드를 준비합니다. 로봇 연결 없이 서명된 이미지와 현장 설정을 선택합니다."
    }

    if ($Configure -and $PrepareOnly) { Stop-Setup "Configure와 PrepareOnly는 함께 사용할 수 없습니다." }
    $settings = Initialize-SdSetupSettings -ConfigPath $ConfigPath -Overrides $PSBoundParameters -ReadOnly:$PrepareOnly
    $ReleaseDir = $settings.ReleaseDir
    $WifiProfile = $settings.WifiProfile
    $CardCount = $settings.CardCount
    $RpiImager = $settings.RpiImager
    $registry = $settings.RegistryJson
    if ($Configure) {
        Write-Host "로컬 공통 설정을 준비했습니다. 카드는 기록하지 않았으며, 이미지 서명·매체 검증은 기록 시 별도로 수행합니다."
        exit 0
    }
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

    $verifyArguments = @((Join-Path $PSScriptRoot "verify-image-release.py"), "--release-root", $ReleaseDir,
        "--public-key", $publicKey, "--image", $imagePath, "--release-id", $releaseId)
    $null = @(& python @verifyArguments 2>&1)
    if ($LASTEXITCODE -ne 0) { Stop-Setup "SD 이미지의 서명·checksum 검증에 실패했습니다. 카드에는 기록하지 않았습니다." }
    $scratchRoot = if ($env:ROSY_SCRATCH) { $env:ROSY_SCRATCH } else { [IO.Path]::GetTempPath() }
    if (-not (Test-Path -LiteralPath $scratchRoot -PathType Container)) {
        Stop-Setup "임시 폴더 $scratchRoot 를 사용할 수 없습니다. ROSY_SCRATCH를 확인한 뒤 다시 시도하세요. 변경된 항목은 없습니다."
    }
    if ($CardCount -gt 1) {
        $batch = New-SdBatch -RegistryJson $registry -CardCount $CardCount -ScratchRoot $scratchRoot -ReleaseId $releaseId -ImageSha256 $hashes[0]
    }
    for ($cardIndex = 1; $cardIndex -le $CardCount; $cardIndex++) {
        Write-Host ("카드 {0}/{1}" -f $cardIndex, $CardCount)
        if ($cardIndex -gt 1) {
            $next = Read-Host ("완료한 카드를 안전하게 분리하고 다음 카드를 연결한 뒤 NEXT {0} 입력" -f $cardIndex)
            if ($next -cne ("NEXT {0}" -f $cardIndex)) { Stop-Setup "다음 카드 준비를 중단했습니다." }
        }
        if ($cardIndex -gt 1 -or -not $PSBoundParameters.ContainsKey("DiskNumber")) { $DiskNumber = Select-DiskNumber (Get-UsbDisks) }
        $disk = @(Get-UsbDisks | Where-Object { [int]$_.Number -eq $DiskNumber })
        if ($disk.Count -ne 1) { Stop-Setup "선택한 디스크가 바뀌었거나 더 이상 사용할 수 없습니다. 변경된 항목은 없습니다. 카드를 다시 연결한 뒤 시도하세요." }

        $sessionName = "rosy-device-setup-{0}" -f (Get-Date -Format "yyyyMMddTHHmmssfff")
        $sessionRoot = if ($batch) { Split-Path -Parent $batch.Path } else { $scratchRoot }
        $session = Join-Path $sessionRoot $sessionName
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
        $logPath = Join-Path $session "write.log"
        $verifiedReceipt = Join-Path $session ("receipt-{0}-{1}.json" -f $releaseId, $plan.device_name)
        if ($batch) {
            Set-SdBatchCard -Batch $batch -Plan $plan -RegistryJson $registry -PlanPath $planPath -ReceiptPath $verifiedReceipt -LogPath $logPath
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
        Write-Host "표시된 Wi-Fi 이름이 로봇을 설치할 현장의 네트워크와 같은지 확인하세요."
        if ($PrepareOnly) {
            Write-Host "계획을 저장했습니다. PrepareOnly가 지정되어 카드는 기록하지 않았습니다."
            exit 0
        }
        $confirmation = Read-Host ("계속하려면 REGISTER {0} 을 입력하세요" -f $plan.robot_number)
        if ($confirmation -cne ("REGISTER {0}" -f $plan.robot_number)) {
            Write-Host "중단했습니다. 카드에 기록하지 않았습니다. 계획은 $session 에 보관했습니다."
            if ($CardCount -gt 1) { Stop-Setup "연속 기록이 취소되었습니다. 완료된 카드의 영수증은 각 기록 폴더에 보존합니다." }
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
        if ($CardCount -gt 1) { $writeArguments += @("-LogPath", $logPath) }
        if (Test-Path -LiteralPath $operatorKey -PathType Leaf) {
            $writeArguments += @("-OperatorPublicKey", $operatorKey)
        }
        $writerOutput = Invoke-ChildPowerShell $writeArguments
        $writerOutput | ForEach-Object { Write-Host ([string]$_) }
        if ($CardCount -gt 1) {
            Wait-SdCardCompletion -LogPath $logPath -ReceiptPath $verifiedReceipt -Plan $plan -RegistryJson $registry
            Complete-SdBatchCard $batch
        }
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
        Write-Host ("첫 부팅 후 대시보드: http://{0}.local:8080/dashboard" -f $plan.device_name)
        Write-Host "자동 업데이트가 포함된 이미지에서는 timer가 기본 활성화됩니다. 신뢰 등록된 SSH로 접속한 뒤 다음 읽기 전용 명령으로 실제 상태를 확인하세요:"
        Write-Host "  systemctl is-active rosy-core.service rosy-auto-update.timer"
        Write-Host "  sudo python3 -I -B /opt/rosy/native-runtime/rosy_auto_update.py status --json"
        if ((Test-Path -LiteralPath $operatorKey -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $operatorKey) "rosy-operator-ed25519") -PathType Leaf)) {
            Write-Host "첫 SSH 접속에서는 실물 장치의 호스트 키 지문을 확인해 신뢰 등록해야 합니다. 이미 검증한 다른 별칭은 -SshHost로 지정할 수 있습니다."
            Write-Host "첫 부팅 후 현장 담당자가 로봇과 전원 차단 경로를 확인하면 모터 점검과 E-Stop 상태의 구동 준비를 한 번에 진행할 수 있습니다:"
            $commissionAddress = if ($RobotAddress) { $RobotAddress } else { "<robot-ip>" }
            Write-Host ("  .\deploy\robot\pinky_pro\sd\enable-motor-commissioning.ps1 -DeviceName {0} -RobotAddress {1} -OperatorPresent -PowerCutReady" -f $plan.device_name, $commissionAddress)
            Write-Host "이 단계는 주행 명령이나 G4 승인을 만들지 않습니다. 현장 주행 시험과 실측 기록은 별도로 수행합니다."
        }
    }
    if ($CardCount -gt 1) { Write-Host ("총 {0}장 기록·전체 readback·등록부 갱신을 확인했습니다." -f $CardCount) }
}
catch {
    if ($batch) {
        try { Stop-SdBatch $batch }
        catch { Write-Warning ("연속 기록 결과 저장에 실패했습니다. 카드별 plan.json과 영수증을 직접 확인하세요: {0}" -f $batch.Path) }
    }
    Write-Error $_
    exit 1
}
