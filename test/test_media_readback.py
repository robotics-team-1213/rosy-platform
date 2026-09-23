"""Byte-for-byte verification of a flashed compressed disk image."""

from __future__ import annotations

import hashlib
import json
import lzma
from pathlib import Path
import subprocess
import sys

import pytest


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
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "verified": True,
    }


# --- D-181: the compared file is the signed one; liveness; unreadable card ---


def test_image_sha256_covers_the_whole_compressed_file_even_after_the_xz_stream(tmp_path):
    # Review MEDIUM-1: lzma stops at the end of the xz data and ignores what
    # follows, so the hash must drain the rest or a changed file would pass.
    raw = (b"rosy-signed-image\0" * 300_000) + b"end"
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    image.write_bytes(lzma.compress(raw) + b"bytes appended after signing")
    device.write_bytes(raw)

    completed = _run(image, device)

    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence["image_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    assert evidence["image_sha256"] != hashlib.sha256(lzma.compress(raw)).hexdigest()


def test_readback_appends_heartbeats_to_the_progress_file(tmp_path):
    raw = b"heartbeat" * 1_000_000  # more than two 4 MiB chunks
    image = tmp_path / "rosy.img.xz"
    device = tmp_path / "physical-drive.fixture"
    progress = tmp_path / "write.log.progress.jsonl"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw)

    completed = subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--device", str(device),
         "--progress", str(progress), "--progress-seconds", "0"],
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stderr
    lines = [json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()]
    assert len(lines) >= 3
    assert {(line["stage"], line["card_state"], line["detail"]) for line in lines} == {
        ("readback", "written-unverified", "heartbeat")}
    assert [line["bytes"] for line in lines] == sorted(line["bytes"] for line in lines)
    assert lines[-1]["bytes"] == len(raw)
    assert all(line["ts"].endswith("Z") for line in lines)


def test_an_unreadable_device_exits_3_so_the_writer_can_say_reinsert(tmp_path):
    image = tmp_path / "rosy.img.xz"
    image.write_bytes(lzma.compress(b"card" * 4096))

    completed = _run(image, tmp_path / "removed-card")

    assert completed.returncode == 3
    assert "MEDIA_READBACK_DEVICE_UNREADABLE" in completed.stderr


def _run_with_error_file(image: Path, device: Path, error: Path):
    return subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--device", str(device), "--error-json", str(error)],
        capture_output=True, text=True, check=False,
    )


def test_a_mismatch_is_written_to_the_error_file_with_the_bytes_verified(tmp_path):
    raw = b"x" * (9 * 1024 * 1024)
    different = bytearray(raw)
    different[5 * 1024 * 1024 + 3] ^= 0x01
    image, device, error = tmp_path / "rosy.img.xz", tmp_path / "device.bin", tmp_path / "error.json"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(bytes(different))

    completed = _run_with_error_file(image, device, error)

    assert completed.returncode == 1
    assert json.loads(error.read_text(encoding="utf-8")) == {
        "error": f"media readback mismatch at byte offset {5 * 1024 * 1024 + 3}",
        "kind": "mismatch",
        "bytes_verified": 4 * 1024 * 1024,  # the first chunk matched
    }


@pytest.mark.parametrize("case", ["short-card", "missing-card"])
def test_a_card_that_ends_or_cannot_be_read_is_an_io_error(tmp_path, case):
    raw = b"y" * (6 * 1024 * 1024)
    image, device, error = tmp_path / "rosy.img.xz", tmp_path / "device.bin", tmp_path / "error.json"
    image.write_bytes(lzma.compress(raw))
    if case == "short-card":
        device.write_bytes(raw[:5 * 1024 * 1024])

    completed = _run_with_error_file(image, device, error)

    record = json.loads(error.read_text(encoding="utf-8"))
    assert record["kind"] == "io"
    if case == "short-card":
        assert completed.returncode == 1
        assert record == {"error": f"media is shorter than the image at byte offset {4 * 1024 * 1024}",
                          "kind": "io", "bytes_verified": 4 * 1024 * 1024}
    else:
        assert completed.returncode == 3
        assert record["error"].startswith("device cannot be opened") and record["bytes_verified"] == 0


def test_a_truncated_image_is_an_image_error(tmp_path):
    raw = b"z" * (6 * 1024 * 1024)
    compressed = lzma.compress(raw)
    image, device, error = tmp_path / "rosy.img.xz", tmp_path / "device.bin", tmp_path / "error.json"
    image.write_bytes(compressed[:len(compressed) // 2])
    device.write_bytes(raw)

    completed = _run_with_error_file(image, device, error)

    assert completed.returncode == 1
    assert json.loads(error.read_text(encoding="utf-8"))["kind"] == "image"


def test_raw_size_comes_from_the_xz_index_of_every_stream(tmp_path):
    first, second = b"a" * 100_003, b"b" * 7
    image = tmp_path / "rosy.img.xz"
    image.write_bytes(lzma.compress(first) + lzma.compress(second) + b"\0" * 8)

    completed = subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--raw-size"],
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"image_raw_size": len(first) + len(second)}


def test_raw_size_refuses_a_file_that_does_not_end_in_an_xz_footer(tmp_path):
    image = tmp_path / "rosy.img.xz"
    image.write_bytes(lzma.compress(b"a" * 1000) + b"trailing")

    completed = subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--raw-size"],
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 1


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
        # D-182: the areas without files are still compared and reported.
        "non_file_areas": {
            "reserved_bytes": RESERVED * SECTOR,
            "fat_copies_compared": 2,
            "fat_bytes": FAT_SECTORS * SECTOR,
            "backup_boot_sector": None,
            "tolerated_fields": ["fsinfo.free_count", "fsinfo.next_free", "fat[1].status_bits"],
            "tolerated_differences": ["fsinfo.free_count", "fsinfo.next_free"],
        },
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


# --- Pipelined readback: decompression and the card read overlap -----------
# Release 005 read back at about 3.4 MB/s with decompression and the device read
# taking turns. The pipeline must not change a single verdict, and a failure on
# either worker thread must fail the readback, never end it early as a pass.

import functools
import importlib.util
import threading

import pytest

MIB = 1024 * 1024


def _module():
    spec = importlib.util.spec_from_file_location("verify_media_readback_under_test", VERIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sequential_reference(module, image: Path, device: str) -> dict[str, object]:
    """The single-threaded loop from before the pipeline, kept as the oracle."""
    image_hash = hashlib.sha256()
    device_hash = hashlib.sha256()
    verified = 0
    boot = None
    first_chunk = True
    expected_boot = bytearray()
    actual_boot = bytearray()
    with lzma.open(image, "rb") as expected, open(device, "rb", buffering=0) as actual:
        while True:
            expected_chunk = expected.read(module.CHUNK_SIZE)
            if not expected_chunk:
                break
            if first_chunk:
                boot = module.fat32_boot_partition(expected_chunk)
                first_chunk = False
            actual_chunk = actual.read(len(expected_chunk))
            if len(actual_chunk) != len(expected_chunk):
                raise ValueError(f"media is shorter than the image at byte offset {verified}")
            start, end = verified, verified + len(expected_chunk)
            inside_from = inside_to = start
            if boot is not None:
                inside_from = max(start, boot[0])
                inside_to = min(end, boot[0] + boot[1])
            if inside_to > inside_from:
                a, b = inside_from - start, inside_to - start
                expected_boot += expected_chunk[a:b]
                actual_boot += actual_chunk[a:b]
                outside = ((0, a), (b, len(expected_chunk)))
            else:
                outside = ((0, len(expected_chunk)),)
            for low, high in outside:
                if expected_chunk[low:high] != actual_chunk[low:high]:
                    mismatch = next(i for i in range(low, high) if expected_chunk[i] != actual_chunk[i])
                    raise ValueError(f"media readback mismatch at byte offset {start + mismatch}")
            image_hash.update(expected_chunk)
            device_hash.update(actual_chunk)
            verified = end
    evidence = {
        "bytes_verified": verified,
        "device_sha256": device_hash.hexdigest(),
        "image_raw_sha256": image_hash.hexdigest(),
        "verified": True,
    }
    if boot is not None:
        if expected_boot == actual_boot:
            evidence["boot_partition"] = {"mode": "bytes"}
        else:
            evidence["boot_partition"] = module.compare_boot_partition(bytes(expected_boot), bytes(actual_boot))
    elif evidence["device_sha256"] != evidence["image_raw_sha256"]:
        raise ValueError("media readback digest mismatch")
    return evidence


def _outcome(verify, image: Path, device: Path):
    try:
        evidence = dict(verify(image, str(device)))
    except Exception as exc:  # the verdict is the exception type and message
        return ("failed", type(exc).__name__, str(exc))
    evidence.pop("image_sha256", None)  # D-181 addition, checked separately
    return ("verified", evidence)


def _raw_multi_chunk() -> bytes:
    return bytes(range(256)) * (9 * MIB // 256) + b"tail-of-image"  # 9 MiB + 13: three chunks


@functools.lru_cache(maxsize=1)
def _pipeline_cases() -> dict[str, tuple[bytes, bytes]]:
    raw = _raw_multi_chunk()
    xz = lzma.compress(raw)
    flipped = bytearray(raw)
    flipped[5 * MIB + 17] ^= 0x40
    card = _Card()
    image = card.build()
    mounted = _windows_mounted(card, image)
    changed = bytearray(mounted)
    changed[card.cluster_offset(5)] ^= 0x01
    card_xz = lzma.compress(bytes(image))
    return {
        "exact": (xz, raw),
        "longer-card": (xz, raw + b"\0" * MIB),
        "flipped-byte-second-chunk": (xz, bytes(flipped)),
        "short-mid-chunk": (xz, raw[:6 * MIB + 5]),
        "short-by-one-byte": (xz, raw[:-1]),
        "truncated-xz": (xz[:len(xz) // 2], raw),
        "boot-partition-as-files": (card_xz, bytes(mounted)),
        "boot-file-changed": (card_xz, bytes(changed)),
        "boot-partition-bytes": (card_xz, bytes(image)),
    }


def _no_readback_threads() -> bool:
    return not [thread for thread in threading.enumerate() if thread.name.startswith("readback-")]


@pytest.mark.parametrize("device_chunk", [None, 3 * MIB + 7, 8 * MIB], ids=["4MiB", "unaligned", "8MiB"])
@pytest.mark.parametrize("name", list(_pipeline_cases()))
def test_the_pipelined_readback_gives_the_sequential_verdict(tmp_path, name, device_chunk):
    module = _module()
    if device_chunk is not None:
        module.DEVICE_CHUNK_SIZE = device_chunk
    compressed, device_bytes = _pipeline_cases()[name]
    image = tmp_path / "image.img.xz"
    device = tmp_path / "device.bin"
    image.write_bytes(compressed)
    device.write_bytes(device_bytes)

    pipelined = _outcome(module.verify, image, device)
    sequential = _outcome(lambda i, d: _sequential_reference(module, i, d), image, device)

    assert pipelined == sequential
    if pipelined[0] == "verified":
        assert pipelined[1]["bytes_verified"] == len(lzma.decompress(compressed))
    assert _no_readback_threads()


def test_a_device_read_error_on_the_worker_fails_the_readback(tmp_path, monkeypatch):
    module = _module()
    raw = _raw_multi_chunk()
    image = tmp_path / "image.img.xz"
    device = tmp_path / "device.bin"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw)
    calls = []

    def failing_read(actual, size):
        calls.append(size)
        if len(calls) == 2:
            raise module.DeviceReadError("device read failed: simulated removal")
        return actual.read(size)

    monkeypatch.setattr(module, "_read_device", failing_read)

    with pytest.raises(module.DeviceReadError, match="simulated removal"):
        module.verify(image, str(device))
    assert _no_readback_threads()


def test_a_decompression_error_on_the_worker_fails_the_readback_run(tmp_path):
    raw = _raw_multi_chunk()
    compressed = lzma.compress(raw)
    image = tmp_path / "image.img.xz"
    device = tmp_path / "device.bin"
    image.write_bytes(compressed[:len(compressed) // 2])
    device.write_bytes(raw)

    completed = _run(image, device)

    assert completed.returncode == 1
    assert completed.stdout == ""  # no evidence, not a shorter pass
    assert "MEDIA_READBACK_FAILED" in completed.stderr


def test_an_error_past_the_end_of_the_image_is_not_part_of_the_verdict(tmp_path, monkeypatch):
    # The device worker reads ahead; bytes beyond the image were never compared
    # before the pipeline either, so a read error there cannot fail the card.
    module = _module()
    raw = _raw_multi_chunk()
    image = tmp_path / "image.img.xz"
    device = tmp_path / "device.bin"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw + b"\0" * (16 * MIB))
    served = [0]

    def read_then_fail(actual, size):
        if served[0] >= len(raw):
            raise module.DeviceReadError("device read failed: past the image")
        data = actual.read(size)
        served[0] += len(data)
        return data

    monkeypatch.setattr(module, "_read_device", read_then_fail)

    evidence = module.verify(image, str(device))

    assert evidence["verified"] is True and evidence["bytes_verified"] == len(raw)
    assert _no_readback_threads()


def test_the_prefetch_worker_hands_over_its_exception_after_its_chunks():
    module = _module()
    produced = iter([b"one", b"two"])

    def produce():
        try:
            return next(produced)
        except StopIteration:
            raise RuntimeError("worker failed") from None

    prefetch = module._Prefetch("readback-test", produce)
    try:
        assert prefetch.get() == b"one"
        assert prefetch.get() == b"two"
        with pytest.raises(RuntimeError, match="worker failed"):
            prefetch.get()
        assert prefetch.get() == b""
    finally:
        prefetch.close()
    assert _no_readback_threads()


# --- D-182: boot partition areas that hold no file (review MEDIUM-2) ------
# The file-level fallback alone would miss a changed byte in the reserved
# region, FAT copy 2 or the backup boot sector. Only the FSInfo free-cluster
# hints and the FAT[1] shutdown/error bits Windows toggles are tolerated.

BACKUP_SECTOR = 6


def _card_with_backup_boot_sector():
    card = _Card()
    image = card.build()
    struct.pack_into("<H", image, card.part + 0x32, BACKUP_SECTOR)
    primary = bytes(image[card.part:card.part + SECTOR])
    image[card.part + BACKUP_SECTOR * SECTOR:card.part + (BACKUP_SECTOR + 1) * SECTOR] = primary
    device = _windows_mounted(card, image)
    # A dirty mount clears the clean-shutdown bit in FAT[1] of the first FAT only.
    fat1_entry1 = card.part + RESERVED * SECTOR + 4
    struct.pack_into("<I", device, fat1_entry1, 0x0FFFFFFF & ~0x08000000)
    return card, image, device


def test_the_windows_fields_are_tolerated_and_every_other_non_file_byte_is_compared(tmp_path):
    _card, image, device = _card_with_backup_boot_sector()

    completed = _run(*_write(tmp_path, image, device))

    assert completed.returncode == 0, completed.stderr
    areas = json.loads(completed.stdout)["boot_partition"]["non_file_areas"]
    assert areas["backup_boot_sector"] == BACKUP_SECTOR
    assert areas["tolerated_differences"] == ["fat[1].status_bits", "fsinfo.free_count", "fsinfo.next_free"]


def _flip_at(where):
    def offset(card):
        part = card.part
        return {
            "reserved-region": part + 3 * SECTOR + 17,
            "fsinfo-signature": part + SECTOR,  # the FSInfo sector, but not a tolerated field
            "backup-boot-sector": part + BACKUP_SECTOR * SECTOR + 0x40,
            "fat-copy-2": part + (RESERVED + FAT_SECTORS) * SECTOR + 4 * 20,
            "fat-copy-2-entry-1-low-bits": part + (RESERVED + FAT_SECTORS) * SECTOR + 4,
        }[where]
    return offset


@pytest.mark.parametrize(
    ("where", "message"),
    [
        ("reserved-region", "boot partition reserved region differs"),
        ("fsinfo-signature", "boot partition reserved region differs"),
        ("backup-boot-sector", "boot partition backup boot sector differs from the primary"),
        ("fat-copy-2", "boot partition FAT copy 2 differs from FAT copy 1"),
        ("fat-copy-2-entry-1-low-bits", "boot partition FAT copy 2 differs from FAT copy 1"),
    ],
)
def test_a_flipped_byte_outside_the_files_fails_the_boot_partition(tmp_path, where, message):
    card, image, device = _card_with_backup_boot_sector()
    offset = _flip_at(where)(card)
    device[offset] ^= 0x01

    completed = _run(*_write(tmp_path, image, device))

    assert completed.returncode == 1
    assert message in completed.stderr
    assert f"byte offset {offset}" in completed.stderr


# --- D-182: pre-flight probe, stalled reads, advisory heartbeat ------------

import time

from sd_pipe_card import PipeCard


def _mbr_image(signature: int, size: int = 5 * MIB) -> bytes:
    raw = bytearray(bytes(range(256)) * (size // 256))
    struct.pack_into("<I", raw, 440, signature)
    raw[510:512] = b"\x55\xaa"
    return bytes(raw)


def _probe(image: Path, device, *extra):
    return subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--device", str(device), "--probe", *map(str, extra)],
        capture_output=True, text=True, check=False,
    )


def test_the_probe_times_a_read_of_the_card_start_and_reads_both_signatures(tmp_path):
    raw = _mbr_image(0xAABBCCDD)
    image, device = tmp_path / "rosy.img.xz", tmp_path / "card.bin"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw)

    completed = _probe(image, device, "--probe-bytes", 2 * MIB)

    assert completed.returncode == 0, completed.stderr
    facts = json.loads(completed.stdout)
    assert facts["image_raw_size"] == len(raw)
    assert facts["image_mbr_signature"] == facts["device_mbr_signature"] == "aabbccdd"
    assert facts["device_bytes_read"] == 2 * MIB  # read-only, and no further than asked
    assert facts["device_read_mbps"] > 0 and facts["device_read_seconds"] >= 0
    assert "device_error" not in facts


def test_the_probe_reports_an_unreadable_card_instead_of_failing(tmp_path):
    image = tmp_path / "rosy.img.xz"
    image.write_bytes(lzma.compress(b"no partition table" * 1000))

    completed = _probe(image, tmp_path / "removed-card")

    assert completed.returncode == 0, completed.stderr
    facts = json.loads(completed.stdout)
    assert facts["device_error"].startswith("device cannot be read")
    assert facts["device_read_mbps"] is None
    assert facts["device_mbr_read"] is False and facts["device_mbr_signature"] is None
    assert facts["image_mbr_signature"] is None  # no 0x55AA: a blank or unpartitioned image


def test_the_probe_does_not_time_a_read_too_short_to_mean_anything(tmp_path):
    # A 20-byte read times the open, not the card, and would look like slow media.
    image, device = tmp_path / "rosy.img.xz", tmp_path / "card.bin"
    image.write_bytes(lzma.compress(b"x" * 4096))
    device.write_bytes(b"wrong media contents")

    facts = json.loads(_probe(image, device).stdout)

    assert facts["device_bytes_read"] == 20
    assert facts["device_read_mbps"] is None
    assert "too little to time" in facts["device_error"]


def test_a_wedged_card_read_fails_as_io_instead_of_hanging(tmp_path):
    # D-181 review: queue.get() and join() without a timeout waited forever.
    raw = _raw_multi_chunk()
    image, error = tmp_path / "rosy.img.xz", tmp_path / "error.json"
    image.write_bytes(lzma.compress(raw))
    card = PipeCard(raw, ["hang"])
    try:
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, str(VERIFY), "--image", str(image), "--device", card.path,
             "--stall-seconds", "1.5", "--error-json", str(error)],
            capture_output=True, text=True, check=False, timeout=60,
        )
    finally:
        card.close()

    assert completed.returncode == 3
    assert time.monotonic() - started < 30
    record = json.loads(error.read_text(encoding="utf-8"))
    assert record["kind"] == "io" and record["error"].startswith("device read stalled")


def test_a_slow_card_that_keeps_moving_is_not_a_stall(tmp_path):
    raw = _raw_multi_chunk()
    image = tmp_path / "rosy.img.xz"
    image.write_bytes(lzma.compress(raw))
    card = PipeCard(raw, [("slow", 0.6)])  # three pieces, 1.8 s in all, each gap under the limit
    try:
        completed = subprocess.run(
            [sys.executable, str(VERIFY), "--image", str(image), "--device", card.path, "--stall-seconds", "1.5"],
            capture_output=True, text=True, check=False, timeout=60,
        )
    finally:
        card.close()

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["bytes_verified"] == len(raw)


def test_a_progress_file_that_cannot_be_written_does_not_fail_a_good_card(tmp_path):
    # D-181 review: a heartbeat OSError was reported as kind "image".
    raw = b"heartbeat" * 1_000_000
    image, device = tmp_path / "rosy.img.xz", tmp_path / "card.bin"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw)
    unwritable = tmp_path / "progress-is-a-directory"
    unwritable.mkdir()

    completed = subprocess.run(
        [sys.executable, str(VERIFY), "--image", str(image), "--device", str(device),
         "--progress", str(unwritable), "--progress-seconds", "0"],
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["verified"] is True
    assert "MEDIA_READBACK_HEARTBEAT_NOT_WRITTEN" in completed.stderr


# --- D-182 review ---------------------------------------------------------------


def test_the_probe_says_whether_it_read_the_sector_and_keeps_a_zero_signature(tmp_path):
    raw = _mbr_image(0)
    image, device = tmp_path / "rosy.img.xz", tmp_path / "card.bin"
    image.write_bytes(lzma.compress(raw))
    device.write_bytes(raw)

    facts = json.loads(_probe(image, device).stdout)

    assert facts["device_mbr_read"] is True
    assert facts["device_mbr_signature"] == "00000000"  # read and zero, not "unknown"
    assert facts["image_mbr_signature"] is None  # the image side still means "none"


def test_a_probe_that_times_out_reports_the_rate_it_managed(tmp_path):
    raw = _raw_multi_chunk()
    image = tmp_path / "rosy.img.xz"
    image.write_bytes(lzma.compress(raw))
    card = PipeCard(raw, ["hang"])
    try:
        completed = _probe(image, card.path, "--probe-seconds", 1)
    finally:
        card.close()

    facts = json.loads(completed.stdout)
    assert facts["device_error"].startswith("device read stalled")
    assert facts["device_read_mbps"] == 0 and facts["device_read_seconds"] == 1
    assert facts["device_mbr_read"] is False


def test_closing_a_wedged_worker_is_bounded_on_every_path(monkeypatch):
    # D-182 review: after a mismatch the device worker was still joined without a timeout.
    module = _module()
    monkeypatch.setattr(module, "CLOSE_JOIN_SECONDS", 0.3)
    release = threading.Event()
    handed = iter([b"one"])

    def produce():
        try:
            return next(handed)
        except StopIteration:
            release.wait()  # wedged, like a read on a card that stopped answering
            return b""

    prefetch = module._Prefetch("readback-wedged", produce)
    try:
        assert prefetch.get() == b"one"
        started = time.monotonic()
        assert prefetch.close() is True  # still alive, and not waited for
        assert time.monotonic() - started < 3
    finally:
        release.set()
