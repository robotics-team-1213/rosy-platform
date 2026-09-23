#!/usr/bin/env python3
"""Compare every uncompressed image byte with the flashed physical device.

Windows auto-mounts a freshly written USB card and rewrites a few FAT32 fields
(FSInfo free-cluster hints, the volume dirty flag, the FAT status bits); removable
media cannot be set offline to prevent it. Exactly those spec-defined fields, on
a FAT32 partition described by the image's own MBR and BPB, may differ. They are
reported, never hidden, and any other differing byte or bit fails the readback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import struct
import sys


CHUNK_SIZE = 4 * 1024 * 1024
FAT32_PARTITION_TYPES = {0x0B, 0x0C}


def fat32_mount_metadata(head: bytes) -> dict[int, int]:
    """Return {byte offset: mask of bits Windows may change} from the image head."""
    tolerated: dict[int, int] = {}
    if len(head) < 512 or head[510:512] != b"\x55\xaa":
        return tolerated
    for index in range(4):
        entry = head[446 + 16 * index:462 + 16 * index]
        if entry[4] not in FAT32_PARTITION_TYPES:
            continue
        part = struct.unpack_from("<I", entry, 8)[0] * 512
        boot = head[part:part + 512]
        if len(boot) < 512 or boot[0x52:0x5A] != b"FAT32   " or boot[510:512] != b"\x55\xaa":
            continue
        sector = struct.unpack_from("<H", boot, 0x0B)[0]
        reserved = struct.unpack_from("<H", boot, 0x0E)[0]
        fats = boot[0x10]
        fat_size = struct.unpack_from("<I", boot, 0x24)[0]
        fsinfo = struct.unpack_from("<H", boot, 0x30)[0]
        backup = struct.unpack_from("<H", boot, 0x32)[0]
        if sector not in {512, 1024, 2048, 4096} or not 1 <= fats <= 2:
            continue
        tolerated[part + 0x41] = 0x03  # volume dirty / surface-test flags
        for info_sector in (fsinfo, backup + fsinfo if backup else None):
            if info_sector is None:
                continue
            info = part + info_sector * sector
            block = head[info:info + 512]
            if (len(block) == 512 and struct.unpack_from("<I", block, 0)[0] == 0x41615252
                    and struct.unpack_from("<I", block, 484)[0] == 0x61417272):
                for offset in range(info + 488, info + 496):  # free count, next free
                    tolerated[offset] = 0xFF
        for fat in range(fats):
            entry_one_high = part + (reserved + fat * fat_size) * sector + 7
            tolerated[entry_one_high] = 0x0C  # clean-shutdown and hard-error bits
    return tolerated


def hash_image(image: Path) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    image_hash = hashlib.sha256()
    hashed = 0
    with lzma.open(image, "rb") as expected:
        while True:
            chunk = expected.read(CHUNK_SIZE)
            if not chunk:
                break
            image_hash.update(chunk)
            hashed += len(chunk)
    return {
        "bytes_hashed": hashed,
        "image_raw_sha256": image_hash.hexdigest(),
    }


def verify(image: Path, device: str) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    image_hash = hashlib.sha256()
    device_hash = hashlib.sha256()
    verified = 0
    tolerated: dict[int, int] | None = None
    tolerated_offsets: list[int] = []
    with lzma.open(image, "rb") as expected, open(device, "rb", buffering=0) as actual:
        while True:
            expected_chunk = expected.read(CHUNK_SIZE)
            if not expected_chunk:
                break
            if tolerated is None:
                tolerated = fat32_mount_metadata(expected_chunk)
            actual_chunk = actual.read(len(expected_chunk))
            if len(actual_chunk) != len(expected_chunk):
                raise ValueError(
                    f"media is shorter than the image at byte offset {verified}"
                )
            if actual_chunk != expected_chunk:
                for index, (want, got) in enumerate(zip(expected_chunk, actual_chunk)):
                    if want == got:
                        continue
                    offset = verified + index
                    if (want ^ got) & ~tolerated.get(offset, 0) & 0xFF:
                        raise ValueError(f"media readback mismatch at byte offset {offset}")
                    tolerated_offsets.append(offset)
            image_hash.update(expected_chunk)
            device_hash.update(actual_chunk)
            verified += len(expected_chunk)

    evidence = {
        "bytes_verified": verified,
        "device_sha256": device_hash.hexdigest(),
        "image_raw_sha256": image_hash.hexdigest(),
        "verified": True,
    }
    if tolerated_offsets:
        evidence["tolerated_fat_mount_metadata"] = tolerated_offsets
    elif evidence["device_sha256"] != evidence["image_raw_sha256"]:
        raise ValueError("media readback digest mismatch")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device")
    parser.add_argument("--image-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.image_only:
            if args.device:
                raise ValueError("--device cannot be combined with --image-only")
            evidence = hash_image(args.image)
        else:
            if not args.device:
                raise ValueError("--device is required unless --image-only is used")
            evidence = verify(args.image, args.device)
    except (OSError, EOFError, lzma.LZMAError, ValueError) as exc:
        print(f"MEDIA_READBACK_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
