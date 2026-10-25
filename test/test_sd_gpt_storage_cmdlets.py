"""Execute the non-fixture resolver with mocked Windows Storage cmdlets."""
import json
from pathlib import Path
import subprocess

import pytest

from test_sd_writer_contract import POWERSHELL
from test_sd_gpt_layout import _table_image

HELPER = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/sd/media-layout.ps1"
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


@pytest.mark.parametrize("has_letter", [False, True])
def test_storage_cmdlet_resolver_mounts_only_signed_boot_a(tmp_path, has_letter):
    _, layout = _table_image()
    parts = [dict(DiskNumber=7, PartitionNumber=p["number"], Guid="{" + p["unique_guid"] + "}",
                  GptType="{" + p["type_guid"] + "}", Offset=p["start_lba"] * 512,
                  Size=p["size_lba"] * 512, DriveLetter="R" if has_letter else "")
             for p in reversed(layout["partitions"])]
    fixture = tmp_path / "partitions.json"
    fixture.write_text(json.dumps(dict(layout=layout, parts=parts)))
    script = tmp_path / "resolve.ps1"
    script.write_text(r'''
param($Helper, $Fixture)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. $Helper
$data = Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json
$imageLayout = $data.layout
$script:volumes = @()
$script:mounted = @()
function Fail($Message) { throw $Message }
function Update-HostStorageCache {}
function Get-Partition {
    [CmdletBinding()]param($DiskNumber)
    if ($DiskNumber -ne 7) { throw 'wrong disk query' }
    $data.parts
}
function Get-Volume {
    [CmdletBinding()]param($Partition)
    if ($Partition) {
        $script:volumes += [int]$Partition.PartitionNumber
        [pscustomobject]@{FileSystem='FAT32'; DriveLetter=$Partition.DriveLetter}
    } else { [pscustomobject]@{DriveLetter='D'} }
}
function Add-PartitionAccessPath {
    param($DiskNumber, $PartitionNumber, $DriveLetter)
    $script:mounted += [pscustomobject]@{disk=$DiskNumber; part=$PartitionNumber; letter=[string]$DriveLetter}
}
$mount = Resolve-GptProvisionMount 7 '' $false
[pscustomobject]@{mount=$mount; volumes=@($script:volumes); mounted=@($script:mounted)} | ConvertTo-Json -Depth 10 -Compress
''', encoding="utf-8")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-File", str(script), str(HELPER), str(fixture)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["volumes"] == [2]
    assert report["mount"] == ("R:\\" if has_letter else "Z:\\")
    assert report["mounted"] == ([] if has_letter else [dict(disk=7, part=2, letter="Z")])
