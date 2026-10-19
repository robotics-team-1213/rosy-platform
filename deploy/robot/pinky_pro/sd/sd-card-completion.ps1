function Wait-SdCardCompletion([string]$LogPath, [string]$ReceiptPath, [object]$Plan, [string]$RegistryJson) {
    $exitMarker = "$LogPath.exit"
    while (-not (Test-Path -LiteralPath $exitMarker -PathType Leaf)) {
        $output = Invoke-ChildPowerShell @("-File", (Join-Path $PSScriptRoot "card-write-status.ps1"), "-LogPath", $LogPath, "-Json")
        if (Test-Path -LiteralPath $exitMarker -PathType Leaf) { break }
        try { $status = ($output -join [Environment]::NewLine) | ConvertFrom-Json }
        catch { Stop-Setup "카드 기록 상태를 읽을 수 없습니다. 다음 카드로 넘어가지 않습니다." }
        Write-Host ("카드 상태: {0}; 단계: {1}; 남은 시간(실측 초): {2}; 로그: {3}" -f
            $status.result, $status.stage, $status.job_eta_seconds, $LogPath)
        if ($status.stalled -or $status.result -in @("failed", "complete-unverified", "ended-without-result")) {
            Stop-Setup "카드 기록이 완료되지 않았습니다. 표시된 로그를 확인하세요. 다음 카드로 넘어가지 않습니다."
        }
        if (-not (Test-Path -LiteralPath $exitMarker -PathType Leaf)) { Start-Sleep -Seconds 5 }
    }
    $exitCode = -1
    if (-not [int]::TryParse((Get-Content -LiteralPath $exitMarker -Raw).Trim(), [ref]$exitCode) -or $exitCode -ne 0) {
        Stop-Setup "카드 작성기가 실패했습니다. 다음 카드로 넘어가지 않습니다."
    }
    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) { Stop-Setup "완료 영수증이 없습니다. 다음 카드로 넘어가지 않습니다." }
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($receipt.writer_exit_code -ne 0 -or $receipt.media_readback.verified -isnot [bool] -or -not $receipt.media_readback.verified) {
        Stop-Setup "카드 전체 readback 검증이 완료되지 않았습니다. 다음 카드로 넘어가지 않습니다."
    }
    foreach ($field in @("device_name", "device_uid", "robot_number", "release_id", "disk_serial", "image_sha256")) {
        if ([string]$receipt.$field -cne [string]$Plan.$field) { Stop-Setup "완료 영수증이 검토한 카드 계획과 다릅니다. 다음 카드로 넘어가지 않습니다." }
    }
    $registry = Get-Content -LiteralPath $RegistryJson -Raw -Encoding utf8 | ConvertFrom-Json
    if (@($registry.robot_numbers) -notcontains $Plan.robot_number -or
        @($registry.device_names) -cnotcontains $Plan.device_name -or @($registry.device_uids) -cnotcontains $Plan.device_uid) {
        Stop-Setup "완료한 카드의 식별자가 등록부에 없습니다. 다음 카드로 넘어가지 않습니다."
    }
    Write-Host ("검증 완료: {0}, 번호 {1}, serial {2}, 영수증 {3}" -f $Plan.device_name, $Plan.robot_number, $Plan.disk_serial, $ReceiptPath)
}
