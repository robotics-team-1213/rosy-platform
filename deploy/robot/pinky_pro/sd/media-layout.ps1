# Consumes only the layout snapshot returned by verify-image-release.py.
function Assert-SameMediaLayout([object]$Actual) {
    if ($null -eq $Actual -or ($Actual | ConvertTo-Json -Depth 20 -Compress) -cne
            ($imageLayout | ConvertTo-Json -Depth 20 -Compress)) {
        Fail "media layout differs from the signed snapshot"
    }
}

function Assert-DeviceMediaLayout {
    $output = & $PythonExe $readbackVerifier --image $ImagePath --device $readbackTarget `
        --layout-file $layoutSnapshotPath --verify-layout --probe-seconds $ProbeSeconds.ToString($invariant)
    if ($LASTEXITCODE -ne 0) { Fail "device GPT inspection failed" }
    $facts = ($output | Out-String) | ConvertFrom-Json
    if ($facts.PSObject.Properties["image_error"] -or -not $facts.device_layout_verified) {
        Fail "device GPT does not match the signed layout"
    }
    Assert-SameMediaLayout $facts.device_layout
}

function Resolve-GptProvisionMount([int]$Number, [string]$ExplicitPath, [bool]$FixtureMode) {
    $expected = @($imageLayout.partitions | Where-Object { $_.role -ceq $imageLayout.provision_role })
    if ($expected.Count -ne 1) { Fail "signed provision partition is ambiguous" }
    $expected = $expected[0]
    if ($FixtureMode) {
        $inventory = Read-DiskInventory $DiskInventoryJson
        $disk = Select-SafeDisk $inventory $Number
        if (-not $disk.PSObject.Properties["Partitions"]) { Fail "fixture provision partition inventory missing" }
        $partitions = @($disk.Partitions)
    }
    else {
        Update-HostStorageCache
        $partitions = @(Get-Partition -DiskNumber $Number -ErrorAction Stop)
    }
    $matches = @($partitions | Where-Object {
        [int]$_.DiskNumber -eq $Number -and [int]$_.PartitionNumber -eq [int]$expected.number -and
        ([string]$_.Guid).Trim('{', '}').ToLowerInvariant() -ceq $expected.unique_guid -and
        ([string]$_.GptType).Trim('{', '}').ToLowerInvariant() -ceq $expected.type_guid -and
        [int64]$_.Offset -eq ([int64]$expected.start_lba * 512) -and
        [int64]$_.Size -eq ([int64]$expected.size_lba * 512)
    })
    if ($matches.Count -ne 1) { Fail "signed provision partition was not found on the selected physical disk" }
    $partition = $matches[0]
    if ($FixtureMode) {
        if ([string]$partition.FileSystem -cne "FAT32") { Fail "provision partition is not FAT32" }
        $mount = (Resolve-Path -LiteralPath $partition.MountPath -ErrorAction Stop).Path
        if ($ExplicitPath -and (Resolve-Path -LiteralPath $ExplicitPath -ErrorAction Stop).Path -cne $mount) {
            Fail "explicit boot mount is not the signed provision partition"
        }
        return $mount
    }
    $volume = Get-Volume -Partition $partition -ErrorAction Stop
    if ($null -eq $volume -or [string]$volume.FileSystem -cne "FAT32") { Fail "provision partition is not FAT32" }
    if ($ExplicitPath) {
        $resolved = (Resolve-Path -LiteralPath $ExplicitPath -ErrorAction Stop).Path
        $root = [IO.Path]::GetPathRoot($resolved)
        if ($resolved.TrimEnd('\') -cne $root.TrimEnd('\')) { Fail "provision partition path must be its volume root" }
        $letter = (Split-Path -Qualifier $resolved).TrimEnd('\').TrimEnd(':')
        $mounted = @(Get-Partition -DriveLetter $letter -ErrorAction Stop)
        if ($mounted.Count -ne 1 -or [int]$mounted[0].DiskNumber -ne $Number -or
                [int]$mounted[0].PartitionNumber -ne [int]$expected.number -or
                ([string]$mounted[0].Guid).Trim('{', '}').ToLowerInvariant() -cne $expected.unique_guid) {
            Fail "explicit boot mount is not the signed provision partition"
        }
        return $resolved
    }
    if ($partition.DriveLetter) { return "$($partition.DriveLetter):\" }
    $used = @((Get-Volume).DriveLetter | Where-Object { $_ })
    $letter = [char[]]([char]'Z'..[char]'D') | Where-Object { $used -notcontains $_ } | Select-Object -First 1
    if (-not $letter) { Fail "no drive letter is available for the provision partition" }
    Add-PartitionAccessPath -DiskNumber $Number -PartitionNumber $expected.number -DriveLetter $letter
    return "${letter}:\"
}
