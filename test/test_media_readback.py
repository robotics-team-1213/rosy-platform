"""Byte-for-byte verification of a flashed compressed disk image."""

from __future__ import annotations

import hashlib
import json
import lzma
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "deploy" / "sd" / "verify-media-readback.py"


def _run(image: Path, device: Path):
    return subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--device", str(device)],
        capture_output=True,
        text=True,
        check=False,
    )


def _hash_image(image: Path):
    return subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--image-only"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_image_only_hashes_the_decompressed_raw_image(tmp_path):
    raw = (b"rosy-raw-image-hash\0" * 8192) + b"end"
    image = tmp_path / "rosy.img.xz"
    image.write_bytes(lzma.compress(raw))

    completed = _hash_image(image)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "bytes_hashed": len(raw),
        "image_raw_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_readback_accepts_exact_decompressed_image_prefix(tmp_path):
    raw = (b"rosy-media-readback\0" * 8192) + b"end"
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw + b"unused-card-tail")

    completed = _run(image, device)

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence == {
        "bytes_verified": len(raw),
        "device_sha256": hashlib.sha256(raw).hexdigest(),
        "image_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "verified": True,
    }


def test_readback_rejects_first_different_byte(tmp_path):
    raw = b"expected bytes" * 4096
    different = bytearray(raw)
    different[len(different) // 2] ^= 0xFF
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(different)

    completed = _run(image, device)

    assert completed.returncode != 0
    assert "mismatch" in completed.stderr.lower()


def test_readback_rejects_truncated_device(tmp_path):
    raw = b"expected bytes" * 4096
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw[:-1])

    completed = _run(image, device)

    assert completed.returncode != 0
    assert "shorter" in completed.stderr.lower()


# --- FAT32 mount metadata (release 004 card write) -------------------------
# Windows auto-mounts a freshly written USB card and rewrites FSInfo hints and
# dirty bits; removable media cannot be set offline. Only those spec-defined
# fields may differ, and only on a real FAT32 partition described by the image.

import struct

SECTOR = 512
PART_LBA = 2048                      # 1 MiB, as in the Ubuntu Pi image
RESERVED = 32
FAT_SECTORS = 8
FSINFO = 1
BACKUP_BOOT = 6


def _fat32_image(size: int = 3 * 1024 * 1024) -> bytearray:
    image = bytearray(size)
    entry = bytes([0x80, 0, 0, 0, 0x0C, 0, 0, 0]) + struct.pack("<II", PART_LBA, 4096)
    image[446:462] = entry
    image[510:512] = b"\x55\xaa"
    part = PART_LBA * SECTOR
    for boot in (part, part + BACKUP_BOOT * SECTOR):
        bs = bytearray(SECTOR)
        struct.pack_into("<H", bs, 0x0B, SECTOR)
        bs[0x0D] = 1
        struct.pack_into("<H", bs, 0x0E, RESERVED)
        bs[0x10] = 2
        struct.pack_into("<I", bs, 0x24, FAT_SECTORS)
        struct.pack_into("<H", bs, 0x30, FSINFO)
        struct.pack_into("<H", bs, 0x32, BACKUP_BOOT)
        bs[0x52:0x5A] = b"FAT32   "
        bs[510:512] = b"\x55\xaa"
        image[boot:boot + SECTOR] = bs
    for info in (part + FSINFO * SECTOR, part + (BACKUP_BOOT + FSINFO) * SECTOR):
        struct.pack_into("<I", image, info, 0x41615252)
        struct.pack_into("<I", image, info + 484, 0x61417272)
        struct.pack_into("<II", image, info + 488, 1000, 3)
        struct.pack_into("<I", image, info + 508, 0xAA550000)
    for fat in range(2):
        start = part + (RESERVED + fat * FAT_SECTORS) * SECTOR
        struct.pack_into("<II", image, start, 0x0FFFFFF8, 0x0FFFFFFF)
    image[part + (RESERVED + 2 * FAT_SECTORS) * SECTOR + 100] = 0x42  # some data
    return image


def _write(tmp_path: Path, image: bytearray, device: bytearray):
    compressed = tmp_path / "image.img.xz"
    compressed.write_bytes(lzma.compress(bytes(image)))
    raw_device = tmp_path / "device.bin"
    raw_device.write_bytes(bytes(device))
    return compressed, raw_device


def test_windows_mount_metadata_on_fat32_is_tolerated_and_reported(tmp_path):
    image = _fat32_image()
    device = bytearray(image)
    part = PART_LBA * SECTOR
    struct.pack_into("<II", device, part + FSINFO * SECTOR + 488, 997, 9)  # free count, next free
    device[part + 0x41] |= 0x01                                            # volume dirty flag
    fat1_entry1_high = part + RESERVED * SECTOR + 7
    device[fat1_entry1_high] &= ~0x08 & 0xFF                               # clean-shutdown bit
    compressed, raw_device = _write(tmp_path, image, device)

    completed = _run(compressed, raw_device)

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["verified"] is True
    differing = [i for i, (a, b) in enumerate(zip(image, device)) if a != b]
    assert evidence["tolerated_fat_mount_metadata"] == differing
    assert set(differing) <= set(range(part + FSINFO * SECTOR + 488, part + FSINFO * SECTOR + 496)) | {
        part + 0x41, fat1_entry1_high}
    assert evidence["device_sha256"] != evidence["image_raw_sha256"]


def test_other_fsinfo_bytes_still_fail(tmp_path):
    image = _fat32_image()
    device = bytearray(image)
    device[PART_LBA * SECTOR + FSINFO * SECTOR + 500] ^= 0xFF  # reserved area, not a hint

    completed = _run(*_write(tmp_path, image, device))

    assert completed.returncode == 1
    assert "media readback mismatch" in completed.stderr


def test_other_bits_of_the_same_bytes_still_fail(tmp_path):
    image = _fat32_image()
    device = bytearray(image)
    device[PART_LBA * SECTOR + 0x41] ^= 0x80                    # not the dirty flag
    device[PART_LBA * SECTOR + RESERVED * SECTOR + 7] ^= 0x01   # cluster bits, not status bits

    completed = _run(*_write(tmp_path, image, device))

    assert completed.returncode == 1


def test_data_changes_on_the_fat32_partition_still_fail(tmp_path):
    image = _fat32_image()
    device = bytearray(image)
    device[PART_LBA * SECTOR + (RESERVED + 2 * FAT_SECTORS) * SECTOR + 100] ^= 0x01

    completed = _run(*_write(tmp_path, image, device))

    assert completed.returncode == 1


def test_without_a_fat32_partition_nothing_is_tolerated(tmp_path):
    image = _fat32_image()
    image[446 + 4] = 0x83  # Linux partition type: no FAT32 rules apply
    device = bytearray(image)
    struct.pack_into("<I", device, PART_LBA * SECTOR + FSINFO * SECTOR + 488, 997)

    completed = _run(*_write(tmp_path, image, device))

    assert completed.returncode == 1
