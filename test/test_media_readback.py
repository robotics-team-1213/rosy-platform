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


# --- FAT32 boot partition, compared as files (release 004 card write) ------
# Windows auto-mounts a freshly written USB card: it rewrites FSInfo hints and
# FAT status bits and creates System Volume Information. Removable media cannot
# be set offline. Everything outside the boot partition stays byte-exact; the
# boot partition is compared file by file and only that Windows tree may be extra.

import struct

SECTOR = 512
PART_LBA = 2048
PART_SECTORS = 4096
RESERVED = 32
FAT_SECTORS = 8
ROOT_CLUSTER = 2
ROOTFS_OFFSET = (PART_LBA + PART_SECTORS) * SECTOR


def _lfn_entries(name: str) -> list[bytes]:
    """VFAT long-name entries for ``name``, in on-disk order (last piece first)."""
    pieces = [name[i:i + 13] for i in range(0, len(name), 13)]
    entries = []
    for seq, piece in enumerate(pieces, start=1):
        encoded = piece.encode("utf-16-le")
        if len(piece) < 13:
            encoded += b"\x00\x00" + b"\xff\xff" * (12 - len(piece))
        entry = bytearray(32)
        entry[0] = seq | (0x40 if seq == len(pieces) else 0)
        entry[1:11] = encoded[0:10]
        entry[11] = 0x0F
        entry[14:26] = encoded[10:22]
        entry[28:32] = encoded[22:26]
        entries.append(bytes(entry))
    return list(reversed(entries))


def _dir_entry(short: bytes, attributes: int, cluster: int, size: int) -> bytes:
    entry = bytearray(32)
    entry[0:11] = short.ljust(11)
    entry[11] = attributes
    struct.pack_into("<H", entry, 20, cluster >> 16)
    struct.pack_into("<H", entry, 26, cluster & 0xFFFF)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


class _Card:
    def __init__(self) -> None:
        self.image = bytearray(ROOTFS_OFFSET + 64 * 1024)
        entry = bytes([0x80, 0, 0, 0, 0x0C, 0, 0, 0]) + struct.pack("<II", PART_LBA, PART_SECTORS)
        self.image[446:462] = entry
        self.image[462 + 4] = 0x83
        struct.pack_into("<II", self.image, 462 + 8, PART_LBA + PART_SECTORS, 128)
        self.image[510:512] = b"\x55\xaa"
        self.part = PART_LBA * SECTOR
        boot = bytearray(SECTOR)
        struct.pack_into("<H", boot, 0x0B, SECTOR)
        boot[0x0D] = 1
        struct.pack_into("<H", boot, 0x0E, RESERVED)
        boot[0x10] = 2
        struct.pack_into("<I", boot, 0x24, FAT_SECTORS)
        struct.pack_into("<I", boot, 0x2C, ROOT_CLUSTER)
        struct.pack_into("<H", boot, 0x30, 1)
        boot[0x52:0x5A] = b"FAT32   "
        boot[510:512] = b"\x55\xaa"
        self.image[self.part:self.part + SECTOR] = boot
        info = self.part + SECTOR
        struct.pack_into("<I", self.image, info, 0x41615252)
        struct.pack_into("<I", self.image, info + 484, 0x61417272)
        struct.pack_into("<II", self.image, info + 488, 1000, 3)
        self.fat_entries = {0: 0x0FFFFFF8, 1: 0x0FFFFFFF}
        self.image[ROOTFS_OFFSET + 100] = 0x5A  # root filesystem content

    def cluster_offset(self, cluster: int) -> int:
        return self.part + (RESERVED + 2 * FAT_SECTORS) * SECTOR + (cluster - 2) * SECTOR

    def put(self, buffer: bytearray, cluster: int, content: bytes) -> None:
        start = self.cluster_offset(cluster)
        buffer[start:start + len(content)] = content
        for fat in range(2):
            fat_start = self.part + (RESERVED + fat * FAT_SECTORS) * SECTOR
            struct.pack_into("<I", buffer, fat_start + 4 * cluster, 0x0FFFFFFF)
        for index, value in self.fat_entries.items():
            for fat in range(2):
                fat_start = self.part + (RESERVED + fat * FAT_SECTORS) * SECTOR
                struct.pack_into("<I", buffer, fat_start + 4 * index, value)

    def build(self) -> bytearray:
        image = self.image
        config = b"arm_64bit=1\n"
        dtbo = b"\x01dtbo-bytes"
        root = b"".join(_lfn_entries("config.txt")) + _dir_entry(b"CONFIG  TXT", 0x20, 3, len(config))
        root += b"".join(_lfn_entries("overlays")) + _dir_entry(b"OVERLAYS", 0x10, 4, 0)
        overlays = _dir_entry(b".", 0x10, 4, 0) + _dir_entry(b"..", 0x10, 0, 0)
        overlays += b"".join(_lfn_entries("rpi-overlay.dtbo")) + _dir_entry(b"RPI-OV~1DTB", 0x20, 5, len(dtbo))
        self.put(image, 2, root)
        self.put(image, 3, config)
        self.put(image, 4, overlays)
        self.put(image, 5, dtbo)
        return image


def _windows_mounted(card: _Card, image: bytearray) -> bytearray:
    device = bytearray(image)
    info = card.part + SECTOR
    struct.pack_into("<II", device, info + 488, 998, 7)
    device[card.part + RESERVED * SECTOR + 7] = 0xFF
    root = card.cluster_offset(2)
    used = 4 * 32  # config.txt and overlays: one LFN + one short entry each
    svi = b"".join(_lfn_entries("System Volume Information")) + _dir_entry(b"SYSTEM~1", 0x16, 6, 0)
    device[root + used:root + used + len(svi)] = svi
    inside = _dir_entry(b".", 0x10, 6, 0) + _dir_entry(b"..", 0x10, 0, 0)
    inside += b"".join(_lfn_entries("WPSettings.dat")) + _dir_entry(b"WPSETT~1DAT", 0x20, 7, 12)
    card.put(device, 6, inside)
    card.put(device, 7, b"windows-data")
    return device


def _card_pair(tmp_path: Path, mutate=None):
    card = _Card()
    image = card.build()
    device = _windows_mounted(card, image)
    if mutate is not None:
        mutate(card, device)
    return _write(tmp_path, image, device), card


def _write(tmp_path: Path, image: bytearray, device: bytearray):
    compressed = tmp_path / "image.img.xz"
    compressed.write_bytes(lzma.compress(bytes(image)))
    raw_device = tmp_path / "device.bin"
    raw_device.write_bytes(bytes(device))
    return compressed, raw_device


def test_windows_mount_changes_to_the_boot_partition_are_verified_as_files(tmp_path):
    (compressed, raw_device), _card = _card_pair(tmp_path)

    completed = _run(compressed, raw_device)

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["verified"] is True
    assert evidence["boot_partition"] == {
        "mode": "files",
        "entries_verified": 3,
        "windows_extras": ["System Volume Information", "System Volume Information/WPSettings.dat"],
    }


def test_an_untouched_boot_partition_is_reported_as_byte_exact(tmp_path):
    card = _Card()
    image = card.build()

    completed = _run(*_write(tmp_path, image, bytearray(image)))

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["boot_partition"] == {"mode": "bytes"}


def test_a_changed_boot_file_fails(tmp_path):
    def corrupt(card, device):
        device[card.cluster_offset(5)] ^= 0x01

    (compressed, raw_device), _card = _card_pair(tmp_path, corrupt)
    completed = _run(compressed, raw_device)

    assert completed.returncode == 1
    assert "overlays/rpi-overlay.dtbo" in completed.stderr


def test_an_unexpected_extra_boot_entry_fails(tmp_path):
    def plant(card, device):
        root = card.cluster_offset(2) + 7 * 32  # after the System Volume Information entries
        extra = b"".join(_lfn_entries("autorun.inf")) + _dir_entry(b"AUTORUN INF", 0x20, 8, 4)
        device[root:root + len(extra)] = extra
        card.put(device, 8, b"evil")

    (compressed, raw_device), _card = _card_pair(tmp_path, plant)
    completed = _run(compressed, raw_device)

    assert completed.returncode == 1
    assert "unexpected entry: autorun.inf" in completed.stderr


def test_the_root_filesystem_is_still_byte_exact(tmp_path):
    def corrupt(card, device):
        device[ROOTFS_OFFSET + 100] ^= 0x01

    (compressed, raw_device), _card = _card_pair(tmp_path, corrupt)
    completed = _run(compressed, raw_device)

    assert completed.returncode == 1
    assert f"byte offset {ROOTFS_OFFSET + 100}" in completed.stderr


def test_the_partition_table_is_still_byte_exact(tmp_path):
    def corrupt(card, device):
        device[462 + 12] ^= 0x01  # second partition length

    (compressed, raw_device), _card = _card_pair(tmp_path, corrupt)
    completed = _run(compressed, raw_device)

    assert completed.returncode == 1
    assert "byte offset 474" in completed.stderr
