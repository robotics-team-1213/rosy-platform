#!/usr/bin/env python3
"""Compare a flashed physical device with the uncompressed image it was written from.

Every byte outside the FAT32 boot partition must match exactly: the MBR, any gap
and the whole root filesystem. The boot partition cannot be compared byte for
byte on Windows: the OS auto-mounts a freshly written USB card (removable media
cannot be set offline), rewrites FSInfo hints and FAT status bits, and creates
``System Volume Information``. So the boot partition is compared as a filesystem
instead: every file and directory of the image must exist on the card with the
same content, and the only extra tree allowed is ``System Volume Information``,
which is reported in the evidence rather than hidden.
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
WINDOWS_EXTRA_TREES = {"system volume information"}
END_OF_CHAIN = 0x0FFFFFF8


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


def fat32_boot_partition(head: bytes) -> tuple[int, int] | None:
    """Return (byte offset, byte length) of the first FAT32 partition in the MBR."""
    if len(head) < 512 or head[510:512] != b"\x55\xaa":
        return None
    for index in range(4):
        entry = head[446 + 16 * index:462 + 16 * index]
        if entry[4] not in FAT32_PARTITION_TYPES:
            continue
        start, sectors = struct.unpack_from("<II", entry, 8)
        if start and sectors:
            return start * 512, sectors * 512
    return None


class Fat32:
    """Minimal read-only FAT32 reader over one partition's bytes."""

    def __init__(self, data: bytes) -> None:
        if len(data) < 512 or data[0x52:0x5A] != b"FAT32   " or data[510:512] != b"\x55\xaa":
            raise ValueError("boot partition is not FAT32")
        self.data = data
        self.sector = struct.unpack_from("<H", data, 0x0B)[0]
        self.cluster_sectors = data[0x0D]
        reserved = struct.unpack_from("<H", data, 0x0E)[0]
        fats = data[0x10]
        fat_size = struct.unpack_from("<I", data, 0x24)[0]
        self.root = struct.unpack_from("<I", data, 0x2C)[0]
        if self.sector not in {512, 1024, 2048, 4096} or not self.cluster_sectors or not fats:
            raise ValueError("boot partition has an invalid FAT32 BPB")
        self.cluster_bytes = self.sector * self.cluster_sectors
        self.fat_offset = reserved * self.sector
        self.data_offset = (reserved + fats * fat_size) * self.sector
        self.clusters = (len(data) - self.data_offset) // self.cluster_bytes + 2

    def _next(self, cluster: int) -> int:
        return struct.unpack_from("<I", self.data, self.fat_offset + 4 * cluster)[0] & 0x0FFFFFFF

    def chain(self, cluster: int) -> list[int]:
        chain: list[int] = []
        while 2 <= cluster < END_OF_CHAIN:
            if cluster >= self.clusters or len(chain) > self.clusters:
                raise ValueError("FAT32 cluster chain is corrupt")
            chain.append(cluster)
            cluster = self._next(cluster)
        return chain

    def read(self, cluster: int, size: int | None = None) -> bytes:
        parts = []
        for item in self.chain(cluster):
            start = self.data_offset + (item - 2) * self.cluster_bytes
            parts.append(self.data[start:start + self.cluster_bytes])
        content = b"".join(parts)
        return content if size is None else content[:size]

    def entries(self, cluster: int):
        raw = self.read(cluster)
        long_parts: list[str] = []
        for offset in range(0, len(raw), 32):
            entry = raw[offset:offset + 32]
            if entry[0] == 0x00:
                break
            if entry[0] == 0xE5:
                long_parts = []
                continue
            attributes = entry[11]
            if attributes == 0x0F:
                chars = entry[1:11] + entry[14:26] + entry[28:32]
                long_parts.insert(0, chars.decode("utf-16-le", "replace").split("\x00")[0].rstrip("￿"))
                continue
            if attributes & 0x08:  # volume label
                long_parts = []
                continue
            short = entry[0:8].decode("ascii", "replace").rstrip()
            extension = entry[8:11].decode("ascii", "replace").rstrip()
            name = "".join(long_parts) or (f"{short}.{extension}" if extension else short)
            long_parts = []
            if name in {".", ".."}:
                continue
            first = (struct.unpack_from("<H", entry, 20)[0] << 16) | struct.unpack_from("<H", entry, 26)[0]
            size = struct.unpack_from("<I", entry, 28)[0]
            yield name, bool(attributes & 0x10), first, size

    def tree(self) -> dict[str, str]:
        """Map path -> "dir" or "<sha256>:<size>" for every entry."""
        result: dict[str, str] = {}
        pending = [("", self.root)]
        while pending:
            prefix, cluster = pending.pop()
            for name, is_dir, first, size in self.entries(cluster):
                path = f"{prefix}/{name}" if prefix else name
                if is_dir:
                    result[path] = "dir"
                    if first:
                        pending.append((path, first))
                else:
                    content = self.read(first, size) if first else b""
                    if len(content) != size:
                        raise ValueError(f"boot partition file is truncated: {path}")
                    result[path] = f"{hashlib.sha256(content).hexdigest()}:{size}"
        return result


def compare_boot_partition(expected: bytes, actual: bytes) -> dict[str, object]:
    want = Fat32(expected).tree()
    have = Fat32(actual).tree()
    for path, value in sorted(want.items()):
        if have.get(path) != value:
            raise ValueError(f"boot partition file differs or is missing: {path}")
    extras = sorted(path for path in have if path not in want)
    for path in extras:
        if path.split("/", 1)[0].lower() not in WINDOWS_EXTRA_TREES:
            raise ValueError(f"boot partition has an unexpected entry: {path}")
    return {"mode": "files", "entries_verified": len(want), "windows_extras": extras}


def verify(image: Path, device: str) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    image_hash = hashlib.sha256()
    device_hash = hashlib.sha256()
    verified = 0
    boot: tuple[int, int] | None = None
    first_chunk = True
    expected_boot = bytearray()
    actual_boot = bytearray()
    with lzma.open(image, "rb") as expected, open(device, "rb", buffering=0) as actual:
        while True:
            expected_chunk = expected.read(CHUNK_SIZE)
            if not expected_chunk:
                break
            if first_chunk:
                boot = fat32_boot_partition(expected_chunk)
                first_chunk = False
            actual_chunk = actual.read(len(expected_chunk))
            if len(actual_chunk) != len(expected_chunk):
                raise ValueError(
                    f"media is shorter than the image at byte offset {verified}"
                )
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
                    mismatch = next(
                        index for index in range(low, high)
                        if expected_chunk[index] != actual_chunk[index]
                    )
                    raise ValueError(
                        f"media readback mismatch at byte offset {start + mismatch}"
                    )
            image_hash.update(expected_chunk)
            device_hash.update(actual_chunk)
            verified = end

    evidence: dict[str, object] = {
        "bytes_verified": verified,
        "device_sha256": device_hash.hexdigest(),
        "image_raw_sha256": image_hash.hexdigest(),
        "verified": True,
    }
    if boot is not None:
        if expected_boot == actual_boot:
            evidence["boot_partition"] = {"mode": "bytes"}
        else:
            evidence["boot_partition"] = compare_boot_partition(bytes(expected_boot), bytes(actual_boot))
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
    except (OSError, EOFError, lzma.LZMAError, ValueError, struct.error) as exc:
        print(f"MEDIA_READBACK_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
