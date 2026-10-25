"""FAT32 file checks and bounded per-partition comparison for SD readback."""
from __future__ import annotations

import hashlib
import struct


class PartitionComparison:
    """Compare every gap exactly and retain only the currently visited FAT."""

    def __init__(self, partitions, allowed_extras=frozenset(), provision_role="boot"):
        self.partitions = partitions
        self.allowed_extras = allowed_extras
        self.provision_role = provision_role
        self.role = None
        self.base = 0
        self.expected = bytearray()
        self.actual = bytearray()
        self.results = {}

    @staticmethod
    def _exact(expected, actual, low, high, base):
        if expected[low:high] != actual[low:high]:
            mismatch = next(i for i in range(low, high) if expected[i] != actual[i])
            raise ValueError(f"media readback mismatch at byte offset {base + mismatch}")

    def _finish(self):
        if self.expected == self.actual:
            result = {"mode": "bytes"}
        else:
            extras = self.allowed_extras if self.role == self.provision_role else frozenset()
            result = compare_boot_partition(bytes(self.expected), bytes(self.actual), self.base, extras)
        self.results[self.role] = result
        self.role = None
        self.expected = bytearray()
        self.actual = bytearray()

    def feed(self, offset, expected, actual):
        cursor = 0
        end = offset + len(expected)
        for role, base, length in self.partitions:
            start_inside, end_inside = max(offset, base), min(end, base + length)
            if start_inside >= end_inside:
                continue
            low, high = start_inside - offset, end_inside - offset
            self._exact(expected, actual, cursor, low, offset)
            self.role, self.base = role, base
            self.expected += expected[low:high]
            self.actual += actual[low:high]
            if end_inside == base + length:
                self._finish()
            cursor = high
        self._exact(expected, actual, cursor, len(expected), offset)

    def finish(self):
        if self.role is not None:
            self._finish()
        # Preserve the v1 report even for a legacy MBR extent beyond the image.
        for role, _, _ in self.partitions:
            self.results.setdefault(role, {"mode": "bytes"})
        return self.results

FAT32_PARTITION_TYPES = {0x0B, 0x0C}
WINDOWS_EXTRA_TREES = {"system volume information"}
END_OF_CHAIN = 0x0FFFFFF8
FSINFO_TOLERATED = {"fsinfo.free_count": (488, 4), "fsinfo.next_free": (492, 4)}
FAT1_STATUS_BITS = 0x0C000000


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



def _first_difference(want: bytes, have: bytes, skip: set[int]) -> int | None:
    if want == have:
        return None
    for index in range(min(len(want), len(have))):
        if index not in skip and want[index] != have[index]:
            return index
    return None if len(want) == len(have) else min(len(want), len(have))



def compare_boot_non_file_areas(expected: bytes, actual: bytes, base: int = 0) -> dict[str, object]:
    """Byte-compare the FAT32 areas that hold no file (D-188, review MEDIUM-2).

    Tolerated, and only these: the FSInfo free-cluster count and next-free hint
    against the image, and the FAT[1] clean-shutdown and hard-error bits between
    the two FAT copies. ``base`` is the partition's byte offset on the device,
    used only to report device offsets.
    """
    image, card = Fat32(expected), Fat32(actual)
    for field in ("sector", "fat_offset", "data_offset"):
        if getattr(image, field) != getattr(card, field):
            raise ValueError(f"boot partition layout differs from the image: {field}")
    sector = card.sector
    reserved = card.fat_offset
    fats = actual[0x10]
    fat_bytes = struct.unpack_from("<I", actual, 0x24)[0] * sector

    # 1. Backup boot sector against the primary, on the card.
    backup = struct.unpack_from("<H", actual, 0x32)[0]
    backup_sector = None
    if 0 < backup < 0xFFFF and (backup + 1) * sector <= reserved:
        backup_sector = backup
        at = _first_difference(actual[:sector], actual[backup * sector:(backup + 1) * sector], set())
        if at is not None:
            raise ValueError(
                f"boot partition backup boot sector differs from the primary at byte offset "
                f"{base + backup * sector + at}"
            )

    # 2. Reserved region against the image, apart from the FSInfo hints.
    info = struct.unpack_from("<H", actual, 0x30)[0]
    skip: set[int] = set()
    tolerated: list[str] = []
    if 0 < info < 0xFFFF and (info + 1) * sector <= reserved:
        for name, (offset, size) in FSINFO_TOLERATED.items():
            start = info * sector + offset
            skip.update(range(start, start + size))
            if expected[start:start + size] != actual[start:start + size]:
                tolerated.append(name)
    at = _first_difference(expected[:reserved], actual[:reserved], skip)
    if at is not None:
        raise ValueError(f"boot partition reserved region differs at byte offset {base + at}")

    # 3. Every further FAT copy against FAT copy 1, on the card. FAT 1 itself is
    # not compared with the image: Windows allocates System Volume Information.
    for fat in range(1, fats):
        first = actual[reserved:reserved + fat_bytes]
        other = actual[reserved + fat * fat_bytes:reserved + (fat + 1) * fat_bytes]
        if len(first) >= 8 and len(other) >= 8:
            a, b = struct.unpack_from("<I", first, 4)[0], struct.unpack_from("<I", other, 4)[0]
            if (a ^ b) & ~FAT1_STATUS_BITS & 0xFFFFFFFF:
                raise ValueError(
                    f"boot partition FAT copy {fat + 1} differs from FAT copy 1 at byte offset "
                    f"{base + reserved + fat * fat_bytes + 4}"
                )
            if a != b:
                tolerated.append("fat[1].status_bits")
        at = _first_difference(first, other, {4, 5, 6, 7})
        if at is not None:
            raise ValueError(
                f"boot partition FAT copy {fat + 1} differs from FAT copy 1 at byte offset "
                f"{base + reserved + fat * fat_bytes + at}"
            )
    return {
        "reserved_bytes": reserved,
        "fat_copies_compared": fats,
        "fat_bytes": fat_bytes,
        "backup_boot_sector": backup_sector,
        "tolerated_fields": sorted(FSINFO_TOLERATED) + ["fat[1].status_bits"],
        "tolerated_differences": sorted(set(tolerated)),
    }



def compare_boot_partition(expected: bytes, actual: bytes, base: int = 0,
                           allowed_extras: frozenset[str] = frozenset()) -> dict[str, object]:
    non_file = compare_boot_non_file_areas(expected, actual, base)
    want = Fat32(expected).tree()
    have = Fat32(actual).tree()
    for path, value in sorted(want.items()):
        if have.get(path) != value:
            raise ValueError(f"boot partition file differs or is missing: {path}")
    extras = sorted(path for path in have if path not in want)
    provisioning = []
    for path in extras:
        top = path.split("/", 1)[0].lower()
        if top in allowed_extras:
            provisioning.append(path)
        elif top not in WINDOWS_EXTRA_TREES:
            raise ValueError(f"boot partition has an unexpected entry: {path}")
    evidence: dict[str, object] = {"mode": "files", "entries_verified": len(want),
                                   "windows_extras": [path for path in extras if path not in provisioning],
                                   "non_file_areas": non_file}
    if allowed_extras:
        # D-389: a provisioned card (the emergency follow-up) also carries the
        # bundle and settings file the writer added; they are named, not hidden.
        evidence["provisioning_extras"] = provisioning
    return evidence
