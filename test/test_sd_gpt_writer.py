"""Real PowerShell execution against files and an explicit fake disk inventory."""
import hashlib
import json
import lzma

import pytest

from test_sd_gpt_layout import _table_image
from test_sd_writer_contract import (POWERSHELL, IMAGE_METADATA, _disk, _run, writer_case,
                                     build_sha256sums, sign_checksums, _err)

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


@pytest.fixture
def gpt_writer(writer_case, tmp_path):
    raw, layout = _table_image(with_files=True)
    case = writer_case
    case["image"].write_bytes(lzma.compress(raw))
    case["readback"].write_bytes(raw)
    manifest = case["image"].parent / "manifest.json"
    data = json.loads(manifest.read_text())
    data.update(schema_version=2, layout=layout)
    data["image"]["sha256"] = hashlib.sha256(case["image"].read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    sums = build_sha256sums(manifest.parent, [*IMAGE_METADATA, case["image"].name])
    (manifest.parent / "SHA256SUMS").write_bytes(sums)
    case["signature"].write_text(sign_checksums(sums, case["private_key"]), encoding="utf-8")
    parts = []
    for part in layout["partitions"]:
        mount = tmp_path / part["role"]
        mount.mkdir()
        parts.append(dict(DiskNumber=7, PartitionNumber=part["number"],
                          Guid="{" + part["unique_guid"] + "}", GptType="{" + part["type_guid"] + "}",
                          Offset=part["start_lba"] * 512, Size=part["size_lba"] * 512,
                          FileSystem="FAT32" if part["number"] <= 3 else "ext4", MountPath=str(mount)))
    case["inventory"].write_text(json.dumps([_disk(Partitions=list(reversed(parts)))]), encoding="utf-8")
    case["layout"], case["parts"] = layout, parts
    return case


def _write(case, *extra, **kwargs):
    return _run(case, "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
                *extra, plan_only=False, switches=("-AcceptSlowMedia",), **kwargs)


def test_gpt_writer_selects_boot_a_independently_of_inventory_order(gpt_writer):
    case = gpt_writer
    result = _write(case)
    assert result.returncode == 0, result.stderr
    from pathlib import Path
    for part in case["parts"]:
        assert (Path(part["MountPath"]) / "rosy-provision/provision.json").exists() is (part["PartitionNumber"] == 2)
    report = json.loads(case["receipt"].read_text(encoding="utf-8-sig"))
    assert report["media_readback"]["layout"] == case["layout"]
    assert report["media_readback"]["verified"] is True


@pytest.mark.parametrize("wrong", ["bootstrap", "boot_b"])
def test_explicit_gpt_mount_cannot_select_another_fat(gpt_writer, wrong):
    case = gpt_writer
    part = next(p for p in case["parts"] if p["PartitionNumber"] == (1 if wrong == "bootstrap" else 3))
    result = _write(case, "-BootMountPath", part["MountPath"])
    assert result.returncode != 0
    assert "provision partition" in result.stderr
    assert not case["receipt"].exists()
    assert json.loads(case["registry"].read_text())["device_names"] == []


def test_gpt_emergency_is_refused_before_the_writer(gpt_writer):
    case = gpt_writer
    result = _run(case, "-EmergencyReason", "fixture emergency investigation", plan_only=False, switches=("-Emergency",))
    assert result.returncode != 0
    assert "GPT emergency" in result.stderr
    assert not case["marker"].exists()


def test_wrong_backup_gpt_stops_before_personalization(gpt_writer):
    case = gpt_writer
    raw = bytearray(case["readback"].read_bytes())
    raw[-512 + 16] ^= 1
    case["readback"].write_bytes(raw)
    result = _write(case)
    assert result.returncode != 0
    assert "readback" in result.stderr.lower()
    assert not case["receipt"].exists()


@pytest.mark.parametrize("field,value", [("DiskNumber", 8), ("PartitionNumber", 3),
    ("Guid", "{00000000-0000-0000-0000-000000000001}"),
    ("GptType", "{0fc63daf-8483-4772-8e79-3d69d8477de4}"),
    ("Offset", 512), ("Size", 512), ("FileSystem", "NTFS")])
def test_windows_partition_identity_must_match_signed_snapshot(gpt_writer, field, value):
    case = gpt_writer
    case["parts"][1][field] = value
    case["inventory"].write_text(json.dumps([_disk(Partitions=case["parts"])]))
    result = _write(case)
    assert result.returncode != 0
    assert "provision partition" in result.stderr
    assert not case["receipt"].exists()


@pytest.mark.parametrize("earlier", [False, True])
def test_gpt_resume_needs_plan_history_and_still_reads_every_byte(gpt_writer, tmp_path, earlier):
    case = gpt_writer
    plan = tmp_path / "plan.json"
    planned = _run(case, "-PlanPath", plan)
    assert planned.returncode == 0, planned.stderr
    if earlier:
        (tmp_path / "earlier.progress.jsonl").write_text(
            json.dumps(dict(stage="verify-signature", plan=str(plan.resolve()), ts="2026-10-25T01:00:00Z")) + "\n"
            + json.dumps(dict(stage="write", card_state="writing", ts="2026-10-25T01:01:00Z")) + "\n")
    result = _run(case, "-PlanPath", plan, "-Confirmation", "ERASE SERIAL FIXTURE-SD-0007 rosy-pinky-k7m4",
                  plan_only=False, switches=("-ResumeAfterWrite", "-AcceptSlowMedia"))
    assert not case["marker"].exists()
    if earlier:
        assert result.returncode == 0, result.stderr
        receipt = json.loads(case["receipt"].read_text(encoding="utf-8-sig"))
        assert receipt["media_readback"]["bytes_verified"] == case["layout"]["raw_size_bytes"]
        assert receipt["media_readback"]["verified"] is True
    else:
        assert result.returncode != 0
        assert "earlier write" in _err(result)
        assert not case["receipt"].exists()
