#!/usr/bin/env python3
"""Compare a flashed physical device with the uncompressed image it was written from.

Every byte outside the FAT32 boot partition must match exactly: the MBR, any gap
and the whole root filesystem. The boot partition cannot be compared byte for
byte on Windows: the OS auto-mounts a freshly written USB card (removable media
cannot be set offline), rewrites FSInfo hints and FAT status bits, and creates
``System Volume Information``. So the boot partition is compared as a filesystem
instead: every file and directory of the image must exist on the card with the
same content, and the only extra tree allowed is ``System Volume Information``,
which is reported in the evidence rather than hidden. The areas that hold no
file are still compared byte for byte (D-188): the reserved region against the
image apart from the FSInfo free-cluster hints, FAT copy 2 against FAT copy 1
on the card apart from the FAT[1] shutdown/error bits, and the backup boot
sector against the primary.

The same pass also hashes every compressed byte it reads (``image_sha256``), so
the writer can prove the file it compared against is the signed one (D-187).
Exit codes: 0 verified, 1 mismatch or unusable image, 3 the device could not be
read (card removed, I/O error, or no data for ``--stall-seconds``).

``--probe`` (D-188) is the writer's pre-flight: the raw size from the xz index,
the image's MBR disk signature, and a timed sequential read of the first
``--probe-bytes`` of the device with the device's MBR disk signature. It never
fails on the device; an unreadable device is reported in ``device_error``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import lzma
import os
from pathlib import Path
import queue
import struct
import sys
import threading
import time


CHUNK_SIZE = 4 * 1024 * 1024
DEVICE_CHUNK_SIZE = CHUNK_SIZE
QUEUE_DEPTH = 4
FAT32_PARTITION_TYPES = {0x0B, 0x0C}
WINDOWS_EXTRA_TREES = {"system volume information"}
END_OF_CHAIN = 0x0FFFFFF8
XZ_HEADER_MAGIC = b"\xfd7zXZ\x00"
EXIT_DEVICE_UNREADABLE = 3
DEFAULT_STALL_SECONDS = 600.0
CLOSE_JOIN_SECONDS = 5.0
_left_behind = threading.Event()  # a reader thread still holds a device handle
PROBE_BYTES = 128 * 1024 * 1024
PROBE_MIN_TIMED_BYTES = 1024 * 1024  # a smaller read times scheduling noise, not the card
MB = 1_000_000  # rates are decimal MB/s, as Imager and card labels use
# FAT32 fields Windows rewrites on a mounted card (release 004 offset 1049576 is
# the FSInfo free count). Everything else in the non-file areas is byte-exact.
FSINFO_TOLERATED = {"fsinfo.free_count": (488, 4), "fsinfo.next_free": (492, 4)}
FAT1_STATUS_BITS = 0x0C000000  # ClnShutBitMask 0x08000000 | HrdErrBitMask 0x04000000


class DeviceReadError(OSError):
    """The card could not be opened or read (removed mid-readback, I/O error)."""


class DeviceStallError(DeviceReadError):
    """The card produced no data for the stall limit (a wedged read)."""


class HashingReader:
    """File wrapper that SHA-256s every byte handed to its consumer."""

    def __init__(self, raw) -> None:
        self._raw = raw
        self.sha256 = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        data = self._raw.read(size)
        self.sha256.update(data)
        return data

    def drain(self) -> str:
        """Hash whatever the decompressor left unread (e.g. bytes after the xz stream)."""
        while True:
            data = self.read(CHUNK_SIZE)
            if not data:
                return self.sha256.hexdigest()


class Progress:
    """Append a heartbeat line to the writer's progress file about every interval."""

    def __init__(self, path: Path | None, interval: float) -> None:
        self.path = path
        self.interval = interval
        self.last = time.monotonic()
        self.done = 0  # bytes compared so far; reported when the readback fails

    def beat(self, done: int, force: bool = False) -> None:
        self.done = done
        if self.path is None:
            return
        now = time.monotonic()
        if not force and now - self.last < self.interval:
            return
        self.last = now
        line = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "stage": "readback",
            "card_state": "written-unverified",
            "detail": "heartbeat",
            "bytes": done,
        }
        # The heartbeat is advisory. A progress file that cannot be written must
        # not fail a good card as an "image" error (D-187 review).
        try:
            with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(line, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            print(f"MEDIA_READBACK_HEARTBEAT_NOT_WRITTEN: {exc}", file=sys.stderr)


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise ValueError("xz index is corrupt")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def xz_raw_size(image: Path) -> int:
    """Uncompressed size from the xz stream indexes, without decompressing."""
    total = 0
    with open(image, "rb") as handle:
        end = handle.seek(0, os.SEEK_END)
        while end > 0:
            handle.seek(end - 4)
            if end >= 4 and handle.read(4) == b"\0\0\0\0":  # stream padding
                end -= 4
                continue
            if end < 24:
                raise ValueError("image is not an xz stream")
            handle.seek(end - 12)
            footer = handle.read(12)
            if footer[10:12] != b"YZ":
                raise ValueError("image does not end with an xz stream footer")
            index_size = (struct.unpack_from("<I", footer, 4)[0] + 1) * 4
            index_start = end - 12 - index_size
            if index_start < 12:
                raise ValueError("xz index is corrupt")
            handle.seek(index_start)
            index = handle.read(index_size)
            if index[:1] != b"\0":
                raise ValueError("xz index is corrupt")
            count, pos = _varint(index, 1)
            blocks = 0
            for _ in range(count):
                unpadded, pos = _varint(index, pos)
                size, pos = _varint(index, pos)
                total += size
                blocks += (unpadded + 3) // 4 * 4
            end = index_start - blocks - 12
            if end < 0:
                raise ValueError("xz index is corrupt")
            handle.seek(end)
            if handle.read(6) != XZ_HEADER_MAGIC:
                raise ValueError("xz stream header is missing")
    return total


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


def compare_boot_partition(expected: bytes, actual: bytes, base: int = 0) -> dict[str, object]:
    non_file = compare_boot_non_file_areas(expected, actual, base)
    want = Fat32(expected).tree()
    have = Fat32(actual).tree()
    for path, value in sorted(want.items()):
        if have.get(path) != value:
            raise ValueError(f"boot partition file differs or is missing: {path}")
    extras = sorted(path for path in have if path not in want)
    for path in extras:
        if path.split("/", 1)[0].lower() not in WINDOWS_EXTRA_TREES:
            raise ValueError(f"boot partition has an unexpected entry: {path}")
    return {"mode": "files", "entries_verified": len(want), "windows_extras": extras,
            "non_file_areas": non_file}


def _read_device(actual, size: int) -> bytes:
    try:
        return actual.read(size)
    except OSError as exc:
        raise DeviceReadError(f"device read failed: {exc}") from exc


class _Prefetch:
    """Run ``produce`` on a worker thread into a bounded queue.

    ``get()`` returns the next chunk, ``b""`` at the end, or re-raises what the
    worker raised, so a failed read is never mistaken for the end of the data.
    With ``stall_seconds``, a worker that hands over nothing for that long
    raises ``stall_error()`` instead of waiting forever on a wedged read; the
    worker is a daemon thread and is left behind.
    """

    _END = object()

    def __init__(self, name: str, produce, depth: int = QUEUE_DEPTH,
                 stall_seconds: float | None = None, stall_error=None) -> None:
        self._produce = produce
        self._queue: queue.Queue = queue.Queue(maxsize=depth)
        self._stopping = threading.Event()
        self._error: BaseException | None = None
        self._finished = False
        self._stall_seconds = stall_seconds
        self._stall_error = stall_error
        self._stalled = False
        self._thread =threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def _put(self, item) -> bool:
        while not self._stopping.is_set():
            try:
                self._queue.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _run(self) -> None:
        try:
            while not self._stopping.is_set():
                chunk = self._produce()
                if not chunk or not self._put(chunk):
                    break
        except BaseException as exc:  # handed to the consumer, never swallowed
            self._error = exc
        finally:
            self._put(self._END)

    def get(self) -> bytes:
        if self._finished:
            return b""
        try:
            item = self._queue.get(timeout=self._stall_seconds)
        except queue.Empty:
            self._stalled = True
            raise self._stall_error() from None
        if item is self._END:
            self._finished = True
            if self._error is not None:
                raise self._error
            return b""
        return item

    def close(self) -> bool:
        """Stop the worker; return True if it is still alive (wedged in a read).

        Bounded on every path (D-188 review): after a mismatch or an image error
        the device worker may be wedged too, and waiting for it would turn a
        mismatch into a hang and then an "io" failure.
        """
        self._stopping.set()
        self._thread.join(1.0 if self._stalled else CLOSE_JOIN_SECONDS)
        return self._thread.is_alive()


class _DeviceStream:
    """Hand out device bytes in the sizes the image side asks for."""

    def __init__(self, source: _Prefetch) -> None:
        self._source = source
        self._pending = b""
        self._ended = False

    def take(self, size: int) -> bytes:
        parts = [self._pending] if self._pending else []
        have = len(self._pending)
        while have < size and not self._ended:
            chunk = self._source.get()
            if not chunk:
                self._ended = True
                break
            parts.append(chunk)
            have += len(chunk)
        data = parts[0] if len(parts) == 1 else b"".join(parts)
        self._pending = data[size:]
        return data[:size]


def verify(image: Path, device: str, progress: Progress | None = None,
           stall_seconds: float | None = None) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    progress = progress or Progress(None, 0)

    def device_stalled() -> DeviceStallError:
        return DeviceStallError(
            f"device read stalled: no data for {stall_seconds:g} s after byte offset {progress.done}"
        )

    def image_stalled() -> OSError:
        return OSError(f"image decompression produced no data for {stall_seconds:g} s")

    try:
        actual_file = open(device, "rb", buffering=0)
    except OSError as exc:
        raise DeviceReadError(f"device cannot be opened: {exc}") from exc
    stalled = False
    try:
        return _verify_open(image, actual_file, progress, stall_seconds, device_stalled, image_stalled)
    except DeviceStallError:
        stalled = True
        raise
    finally:
        # A thread still blocked reading this handle could block its close too.
        if not stalled and not _left_behind.is_set():
            actual_file.close()


def _verify_open(image: Path, actual, progress: Progress, stall_seconds, device_stalled,
                 image_stalled) -> dict[str, object]:
    image_hash = hashlib.sha256()
    device_hash = hashlib.sha256()
    verified = 0
    boot: tuple[int, int] | None = None
    first_chunk = True
    expected_boot = bytearray()
    actual_boot = bytearray()
    with open(image, "rb") as compressed:
        # The compressed bytes the comparison consumes are hashed on the way in,
        # so the evidence ties the compared image to the signed SHA256SUMS entry.
        signed = HashingReader(compressed)
        with lzma.open(signed, "rb") as expected:
            # Decompression (CPU) and the card read (I/O) overlap on two threads;
            # the device is still read strictly in order, one chunk at a time.
            image_side = _Prefetch("readback-image", lambda: expected.read(CHUNK_SIZE),
                                   stall_seconds=stall_seconds, stall_error=image_stalled)
            device_side = _Prefetch("readback-device", lambda: _read_device(actual, DEVICE_CHUNK_SIZE),
                                    stall_seconds=stall_seconds, stall_error=device_stalled)
            device_stream = _DeviceStream(device_side)
            try:
                while True:
                    expected_chunk = image_side.get()
                    if not expected_chunk:
                        break
                    if first_chunk:
                        boot = fat32_boot_partition(expected_chunk)
                        first_chunk = False
                    actual_chunk = device_stream.take(len(expected_chunk))
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
                    progress.beat(verified)
            finally:
                # Every path stops both workers, with a bounded wait, before the files close.
                if image_side.close() | device_side.close():
                    _left_behind.set()
            # lzma ignores bytes after the last xz stream; the signed hash covers them.
            image_sha256 = signed.drain()

    evidence: dict[str, object] = {
        "bytes_verified": verified,
        "device_sha256": device_hash.hexdigest(),
        "image_raw_sha256": image_hash.hexdigest(),
        "image_sha256": image_sha256,
        "verified": True,
    }
    progress.beat(verified, force=True)
    if boot is not None:
        if expected_boot == actual_boot:
            evidence["boot_partition"] = {"mode": "bytes"}
        else:
            evidence["boot_partition"] = compare_boot_partition(bytes(expected_boot), bytes(actual_boot), boot[0])
    elif evidence["device_sha256"] != evidence["image_raw_sha256"]:
        raise ValueError("media readback digest mismatch")
    return evidence


def mbr_signature(sector: bytes) -> str | None:
    """The MBR disk signature (bytes 440-443) as 8 hex digits, or None if absent."""
    if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
        return None
    value = struct.unpack_from("<I", sector, 440)[0]
    return f"{value:08x}" if value else None


def raw_mbr_signature(sector: bytes) -> str | None:
    """Bytes 440-443 as 8 hex digits whenever the sector holds an MBR (0x55AA),
    "00000000" included; None when it holds none (a blank or unpartitioned card).
    Only meaningful when the sector was actually read (D-188 review)."""
    if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
        return None
    return f"{struct.unpack_from('<I', sector, 440)[0]:08x}"


def sector_is_blank(sector: bytes) -> bool:
    """True when a full first sector was read and every byte is zero.

    2026-09-24: an interrupted Imager write left sector 0 all zeros, and Get-Disk
    (which -PlanOnly reads) reports such a disk as MBR with signature 1.
    """
    return len(sector) >= 512 and not any(sector[:512])


def _probe_device(device: str, probe_bytes: int, timeout: float) -> tuple[dict[str, object], bool]:
    state: dict[str, object] = {"done": 0, "head": b""}

    def run() -> None:
        try:
            with open(device, "rb", buffering=0) as handle:
                started = time.perf_counter()
                done = 0
                head = b""
                while done < probe_bytes:
                    chunk = handle.read(min(DEVICE_CHUNK_SIZE, probe_bytes - done))
                    if not chunk:
                        break
                    if len(head) < 512:
                        head += chunk[:512 - len(head)]
                        state["head"] = head
                    done += len(chunk)
                    state["done"] = done
                state["seconds"] = time.perf_counter() - started
        except OSError as exc:
            state["error"] = str(exc)

    worker = threading.Thread(target=run, name="probe-device", daemon=True)
    worker.start()
    worker.join(timeout)
    stalled = worker.is_alive()
    done = int(state["done"])
    seconds = state.get("seconds")
    head = bytes(state["head"])
    outcome: dict[str, object] = {
        "device_bytes_read": done,
        "device_read_seconds": None if seconds is None else round(float(seconds), 3),
        "device_read_mbps": None,
        "device_mbr_read": len(head) >= 512,
        "device_mbr_signature": raw_mbr_signature(head),
        "device_mbr_blank": sector_is_blank(head),
    }
    if stalled:
        outcome["device_error"] = f"device read stalled: no data for {timeout:g} s after {done} bytes"
        # A card too slow to finish the probe in time is slow media, not unmeasured
        # media: report the rate it managed (possibly 0) so the slow-media gate applies.
        outcome["device_read_seconds"] = round(timeout, 3)
        outcome["device_read_mbps"] = round(done / MB / timeout, 2) if timeout > 0 else 0.0
    elif "error" in state:
        outcome["device_error"] = f"device cannot be read: {state['error']}"
    elif done < PROBE_MIN_TIMED_BYTES:
        # A few bytes time the open, not the card; report no rate rather than a wrong one.
        outcome["device_error"] = f"only {done} bytes could be read; too little to time"
    elif seconds:
        outcome["device_read_mbps"] = round(done / MB / float(seconds), 2)
    return outcome, stalled


def probe(image: Path, device: str | None, probe_bytes: int = PROBE_BYTES,
          timeout: float = 120.0) -> tuple[dict[str, object], bool]:
    """Pre-flight facts for the writer (D-188); never fails on the device."""
    result: dict[str, object] = {"image_raw_size": None, "image_mbr_signature": None}
    try:
        result["image_raw_size"] = xz_raw_size(image)
        with lzma.open(image, "rb") as expected:
            result["image_mbr_signature"] = mbr_signature(expected.read(512))
    except (OSError, EOFError, lzma.LZMAError, ValueError) as exc:
        result["image_error"] = str(exc)
    stalled = False
    if device:
        outcome, stalled = _probe_device(device, probe_bytes, timeout)
        result.update(outcome)
    return result, stalled


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device")
    parser.add_argument("--image-only", action="store_true")
    parser.add_argument("--raw-size", action="store_true",
                        help="print the uncompressed size from the xz index and exit")
    parser.add_argument("--progress", type=Path,
                        help="append readback heartbeat lines (JSON) to this file")
    parser.add_argument("--progress-seconds", type=float, default=60.0)
    parser.add_argument("--error-json", type=Path,
                        help="on failure write {error, kind, bytes_verified} here; Windows PowerShell "
                             "5.1 transcripts do not capture a native program's stderr")
    parser.add_argument("--stall-seconds", type=float, default=DEFAULT_STALL_SECONDS,
                        help="fail as an I/O error (exit 3) when the device gives no data for this long")
    parser.add_argument("--probe", action="store_true",
                        help="print raw size, MBR signatures and a timed read of the device start")
    parser.add_argument("--probe-bytes", type=int, default=PROBE_BYTES)
    parser.add_argument("--probe-seconds", type=float, default=120.0)
    args = parser.parse_args()
    progress = Progress(args.progress, args.progress_seconds)
    if args.probe:
        facts, stalled = probe(args.image, args.device, args.probe_bytes, args.probe_seconds)
        print(json.dumps(facts, sort_keys=True, separators=(",", ":")), flush=True)
        if stalled:
            os._exit(0)  # a thread is wedged in a device read; do not wait for it
        return 0
    try:
        if args.raw_size:
            evidence = {"image_raw_size": xz_raw_size(args.image)}
        elif args.image_only:
            if args.device:
                raise ValueError("--device cannot be combined with --image-only")
            evidence = hash_image(args.image)
        else:
            if not args.device:
                raise ValueError("--device is required unless --image-only is used")
            evidence = verify(args.image, args.device, progress, args.stall_seconds)
    except DeviceStallError as exc:
        print(f"MEDIA_READBACK_DEVICE_UNREADABLE: {exc}", file=sys.stderr, flush=True)
        _write_error(args.error_json, exc, "io", progress.done)
        os._exit(EXIT_DEVICE_UNREADABLE)  # the reader thread still holds the wedged handle
    except DeviceReadError as exc:
        print(f"MEDIA_READBACK_DEVICE_UNREADABLE: {exc}", file=sys.stderr)
        _write_error(args.error_json, exc, "io", progress.done)
        return EXIT_DEVICE_UNREADABLE
    except (OSError, EOFError, lzma.LZMAError, ValueError, struct.error) as exc:
        print(f"MEDIA_READBACK_FAILED: {exc}", file=sys.stderr, flush=True)
        _write_error(args.error_json, exc, _failure_kind(exc), progress.done)
        if _left_behind.is_set():
            os._exit(1)  # a wedged reader thread must not hold up the verdict
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


def _failure_kind(exc: BaseException) -> str:
    """io: the card ran out or could not be read; image: the .img.xz is unusable;
    mismatch: the card was read and holds the wrong data."""
    if isinstance(exc, ValueError) and str(exc).startswith("media is shorter"):
        return "io"
    if isinstance(exc, (OSError, EOFError, lzma.LZMAError)):
        return "image"
    return "mismatch"


def _write_error(path: Path | None, exc: BaseException, kind: str, done: int) -> None:
    if path is None:
        return
    record = {"error": str(exc), "kind": kind, "bytes_verified": done}
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
