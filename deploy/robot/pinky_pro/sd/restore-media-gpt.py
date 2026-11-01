#!/usr/bin/env python3
"""Restore only an exact capacity-only relocation of an authenticated GPT primary header."""
from __future__ import annotations

import argparse
import json
import lzma
import os
from pathlib import Path
import re
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_layout import CHUNK_SIZE, ENTRY_SIZE, HashingReader, LayoutCapture, SECTOR


def authenticate(image: Path, capture: LayoutCapture, digest: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid authenticated image checksum")
    with image.open("rb") as compressed:
        signed = HashingReader(compressed)
        with lzma.open(signed, "rb") as raw:
            while chunk := raw.read(CHUNK_SIZE):
                capture.feed(capture.position, chunk)
        if signed.drain() != digest:
            raise ValueError("consumed image differs from authenticated checksum")
    capture.finish()


def restore(image: Path, device: str, layout: dict, digest: str, capacity: int) -> dict:
    capture = LayoutCapture(layout)
    if capacity < capture.size or capacity > 2**63 - 1 or capacity % SECTOR:
        raise ValueError("device capacity differs from the selected disk")
    # Pin the selected object before the long image pass; never reopen a reused device number.
    with open(device, "r+b", buffering=0) as disk:
        authenticate(image, capture, digest)
        head, tail = bytes(capture.head), bytes(capture.tail)
        original = head[SECTOR:2 * SECTOR]
        relocated = bytearray(original)
        count = struct.unpack_from("<I", original, 80)[0]
        table_sectors = (count * ENTRY_SIZE + SECTOR - 1) // SECTOR
        struct.pack_into("<Q", relocated, 32, capacity // SECTOR - 1)
        struct.pack_into("<Q", relocated, 48, capacity // SECTOR - 2 - table_sectors)
        struct.pack_into("<I", relocated, 16, 0)
        struct.pack_into("<I", relocated, 16, zlib.crc32(relocated[:92]))
        current = disk.read(len(head))
        disk.seek(capture.size - len(tail))
        if (len(current) != len(head) or current[:SECTOR] != head[:SECTOR]
                or current[2 * SECTOR:] != head[2 * SECTOR:] or disk.read(len(tail)) != tail):
            raise ValueError("device GPT metadata differs from the authenticated image")
        changed = current[SECTOR:2 * SECTOR] != original
        if changed:
            if current[SECTOR:2 * SECTOR] != relocated:
                raise ValueError("primary GPT is not the exact capacity-only relocation")
            disk.seek(SECTOR)
            if disk.write(original) != SECTOR:
                raise OSError("short GPT header write")
            disk.flush()
            os.fsync(disk.fileno())
        disk.seek(0)
        if disk.read(len(head)) != head:
            raise ValueError("GPT changed after restoration")
        disk.seek(capture.size - len(tail))
        if disk.read(len(tail)) != tail:
            raise ValueError("backup GPT changed after restoration")
    return dict(restored=changed, bytes_written=SECTOR if changed else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--device")
    target.add_argument("--fixture-device", type=Path, help="file-backed test media only")
    parser.add_argument("--layout-file", required=True, type=Path)
    parser.add_argument("--image-sha256", required=True)
    parser.add_argument("--capacity-bytes", required=True, type=int)
    args = parser.parse_args()
    if args.device is not None and not re.fullmatch(r"\\\\\.\\PhysicalDrive[0-9]+", args.device):
        parser.error("--device requires a Windows physical drive")
    if args.fixture_device is not None and (args.fixture_device.is_symlink() or not args.fixture_device.is_file()):
        parser.error("fixture media must be an existing regular file")
    try:
        layout = json.loads(args.layout_file.read_text(encoding="utf-8-sig"))
        result = restore(args.image, str(args.fixture_device or args.device), layout,
                         args.image_sha256, args.capacity_bytes)
    except (ValueError, OSError, lzma.LZMAError) as exc:
        print(f"GPT_RESTORE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
