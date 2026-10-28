"""Restore only the exact observed Windows capacity relocation, on file-backed media."""
import hashlib
import json
import lzma
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import pytest

from test_sd_gpt_layout import _table_image

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/sd/restore-media-gpt.py"


def relocated(header, capacity):
    header = bytearray(header)
    struct.pack_into("<Q", header, 32, capacity // 512 - 1)
    struct.pack_into("<Q", header, 48, capacity // 512 - 34)
    struct.pack_into("<I", header, 16, 0)
    struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
    return header


@pytest.fixture
def media(tmp_path):
    raw, layout = _table_image()
    image, device, snapshot = (tmp_path / name for name in ("image.xz", "device.bin", "layout.json"))
    image.write_bytes(lzma.compress(raw))
    capacity = len(raw) + 1024 * 1024
    device.write_bytes(raw + bytes(capacity - len(raw)))
    snapshot.write_text(json.dumps(layout))
    return raw, image, device, snapshot, capacity


def invoke(media, digest=None):
    raw, image, device, snapshot, capacity = media
    return subprocess.run([sys.executable, "-I", str(SCRIPT), "--image", str(image), "--fixture-device", str(device),
        "--layout-file", str(snapshot), "--image-sha256", digest or hashlib.sha256(image.read_bytes()).hexdigest(),
        "--capacity-bytes", str(capacity)], cwd=device.parent, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("relocate", [False, True])
def test_cli_restores_only_primary_sector_and_exact_media_is_a_noop(media, relocate):
    raw, _, device, _, capacity = media
    expected = device.read_bytes()
    if relocate:
        with device.open("r+b") as stream:
            stream.seek(512)
            stream.write(relocated(raw[512:1024], capacity))
    result = invoke(media)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["restored"] is relocate
    assert device.read_bytes() == expected


@pytest.mark.parametrize("drift", ["mbr", "table", "backup_header", "backup_table", "primary", "capacity", "image_hash"])
def test_cli_rejects_every_other_drift_without_writing(media, drift):
    raw, _, device, _, capacity = media
    current = bytearray(device.read_bytes())
    current[512:1024] = relocated(raw[512:1024], capacity)
    offsets = {"mbr": 446, "table": 1024, "backup_header": len(raw) - 512,
               "backup_table": len(raw) - 33 * 512, "primary": 512 + 56}
    if drift in offsets:
        current[offsets[drift]] ^= 1
    device.write_bytes(current)
    if drift == "capacity":
        media = (*media[:-1], capacity + 512)
    result = invoke(media, "0" * 64 if drift == "image_hash" else None)
    assert result.returncode != 0
    assert "GPT_RESTORE_FAILED" in result.stderr
    assert device.read_bytes() == current


def test_wrong_signed_layout_refuses_before_device_changes(media):
    _, _, device, snapshot, _ = media
    before = device.read_bytes()
    layout = json.loads(snapshot.read_text())
    layout["partitions"][0]["start_lba"] += 1
    snapshot.write_text(json.dumps(layout))
    assert invoke(media).returncode != 0
    assert device.read_bytes() == before
