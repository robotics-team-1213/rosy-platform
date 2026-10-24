function New-SdBatch([string]$RegistryJson, [int]$CardCount, [string]$ScratchRoot,
                     [string]$ReleaseId, [string]$ImageSha256) {
    $registry = Get-Content -LiteralPath $RegistryJson -Raw -Encoding utf8 | ConvertFrom-Json
    # D-562: automatic numbers are also ceiling marker IDs, limited to 40-49.
    $free = @(40..49 | Where-Object { @($registry.robot_numbers) -notcontains $_ })
    if ($free.Count -lt $CardCount) {
        throw ("연속 기록에 필요한 로봇 번호가 부족합니다: 요청 {0}장, 사용 가능한 40–49 번호 {1}개. 카드에는 기록하지 않았습니다." -f $CardCount, $free.Count)
    }
    $directory = Join-Path $ScratchRoot ("rosy-sd-batch-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $directory -ErrorAction Stop | Out-Null
    $batch = @{
        Path=(Join-Path $directory "batch.json")
        Report=[ordered]@{schema_version=1;status="in_progress";release_id=$ReleaseId;
            image_sha256=$ImageSha256;requested_count=$CardCount;completed_count=0;
            remaining_count=$CardCount;cards=@();active_card=$null}
    }
    Save-SdBatch $batch
    Write-Host ("연속 기록: {0}장, 사용 가능한 번호 {1}개. 결과: {2}" -f $CardCount, $free.Count, $batch.Path)
    return $batch
}

function Save-SdBatch([Collections.IDictionary]$Batch) {
    $temporary = $Batch.Path + ".tmp"
    $Batch.Report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding utf8 -ErrorAction Stop
    Move-Item -LiteralPath $temporary -Destination $Batch.Path -Force -ErrorAction Stop
}

function Set-SdBatchCard([Collections.IDictionary]$Batch, $Plan, [string]$RegistryJson,
                         [string]$PlanPath, [string]$ReceiptPath, [string]$LogPath) {
    $registry = Get-Content -LiteralPath $RegistryJson -Raw -Encoding utf8 | ConvertFrom-Json
    if (-not ($Plan.robot_number -is [int]) -or $Plan.robot_number -lt 40 -or $Plan.robot_number -gt 49 -or
        [string]::IsNullOrWhiteSpace([string]$Plan.device_name) -or [string]::IsNullOrWhiteSpace([string]$Plan.device_uid)) {
        throw "연속 기록 계획의 장치 식별자가 올바르지 않습니다. 카드에는 기록하지 않았습니다."
    }
    foreach ($field in @("robot_number", "device_name", "device_uid")) {
        $used = @($registry.($field + "s")) + @($Batch.Report.cards | ForEach-Object { $_[$field] })
        if ($used -contains $Plan.$field) { throw "이미 사용된 장치 식별자가 계획에 있습니다. 다음 카드 기록을 중단합니다." }
    }
    if ([string]$Plan.image_sha256 -cne $Batch.Report.image_sha256) { throw "연속 기록 이미지 checksum이 변경되었습니다." }
    $Batch.Report.active_card = [ordered]@{
        robot_number=$Plan.robot_number;device_name=$Plan.device_name;device_uid=$Plan.device_uid;
        plan_path=$PlanPath;receipt_path=$ReceiptPath;log_path=$LogPath
    }
    Save-SdBatch $Batch
}

function Complete-SdBatchCard([Collections.IDictionary]$Batch) {
    # Only called after the existing receipt, readback and registry checks pass.
    $Batch.Report.cards += $Batch.Report.active_card
    $Batch.Report.active_card = $null
    $Batch.Report.completed_count = $Batch.Report.cards.Count
    $Batch.Report.remaining_count = $Batch.Report.requested_count - $Batch.Report.completed_count
    if ($Batch.Report.remaining_count -eq 0) { $Batch.Report.status = "completed" }
    Save-SdBatch $Batch
}

function Stop-SdBatch([Collections.IDictionary]$Batch) {
    if ($Batch.Report.status -ne "completed") { $Batch.Report.status = "stopped" }
    Save-SdBatch $Batch
    Write-Host ("연속 기록 중단: 확인 완료 {0}장, 미확인/남은 카드 {1}장. 결과: {2}" -f
        $Batch.Report.completed_count, $Batch.Report.remaining_count, $Batch.Path)
    Write-Host "진행 중이던 작성기는 분리 실행 중일 수 있습니다. 로그와 영수증을 확인한 뒤 다음 작업을 시작하세요. 자동으로 다시 기록하지 않습니다."
}
