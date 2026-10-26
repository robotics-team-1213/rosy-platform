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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_layout import (HashingReader, LayoutCapture, hash_image, mbr_signature,
                          raw_mbr_signature, sector_is_blank, xz_raw_size, validate_layout,
                          primary_disk_guid, inspect_device)
from media_fat import (Fat32, PartitionComparison, compare_boot_non_file_areas, compare_boot_partition,
                       fat32_boot_partition, _first_difference)


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
           stall_seconds: float | None = None,
           allowed_extras: frozenset[str] = frozenset(), layout: dict | None = None) -> dict[str, object]:
    if image.suffix != ".xz":
        raise ValueError("image must be an xz-compressed raw disk image")

    progress = progress or Progress(None, 0)
    layout_capture = LayoutCapture(layout) if layout is not None else None

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
        return _verify_open(image, actual_file, progress, stall_seconds, device_stalled, image_stalled,
                            allowed_extras, layout_capture)
    except DeviceStallError:
        stalled = True
        raise
    finally:
        # A thread still blocked reading this handle could block its close too.
        if not stalled and not _left_behind.is_set():
            actual_file.close()


def _verify_open(image: Path, actual, progress: Progress, stall_seconds, device_stalled,
                 image_stalled, allowed_extras: frozenset[str] = frozenset(),
                 layout_capture: LayoutCapture | None = None) -> dict[str, object]:
    image_hash = hashlib.sha256()
    device_hash = hashlib.sha256()
    verified = 0
    boot: tuple[int, int] | None = None
    first_chunk = True
    comparison = None
    if layout_capture is not None:
        parts = layout_capture.layout["partitions"][:3]
        comparison = PartitionComparison([(p["role"], p["start_lba"] * 512, p["size_lba"] * 512)
                                          for p in parts], allowed_extras, layout["provision_role"])
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
                        if comparison is None:
                            boot = fat32_boot_partition(expected_chunk)
                            comparison = PartitionComparison([("boot", *boot)] if boot else [], allowed_extras)
                        first_chunk = False
                    actual_chunk = device_stream.take(len(expected_chunk))
                    if len(actual_chunk) != len(expected_chunk):
                        raise ValueError(
                            f"media is shorter than the image at byte offset {verified}"
                        )
                    if layout_capture is not None:
                        layout_capture.feed(verified, expected_chunk)
                    comparison.feed(verified, expected_chunk, actual_chunk)
                    image_hash.update(expected_chunk)
                    device_hash.update(actual_chunk)
                    verified += len(expected_chunk)
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
    results = comparison.finish() if comparison is not None else {}
    if layout_capture is not None:
        evidence["layout"] = layout_capture.finish()
        evidence["verified_scope"] = "image_prefix"
        evidence["boot_partitions"] = results
    elif boot is not None:
        evidence["boot_partition"] = results["boot"]
    elif evidence["device_sha256"] != evidence["image_raw_sha256"]:
        raise ValueError("media readback digest mismatch")
    return evidence








def _probe_device(device: str, probe_bytes: int, timeout: float, layout: dict | None = None,
                  check_layout: bool = False) -> tuple[dict[str, object], bool]:
    state: dict[str, object] = {"done": 0, "head": b""}

    def run() -> None:
        try:
            with open(device, "rb", buffering=0) as handle:
                started = time.perf_counter()
                done = 0
                head = b""
                head_size = 1024 if layout is not None else 512
                read_size = max(probe_bytes, head_size) if layout is not None else probe_bytes
                while done < read_size:
                    chunk = handle.read(min(DEVICE_CHUNK_SIZE, read_size - done))
                    if not chunk:
                        break
                    if len(head) < head_size:
                        head += chunk[:head_size - len(head)]
                        state["head"] = head
                    done += len(chunk)
                    state["done"] = done
                state["seconds"] = time.perf_counter() - started
                if layout is not None:
                    state["guid"] = primary_disk_guid(head)
                if check_layout:
                    state["layout"] = inspect_device(handle, layout)
        except (OSError, ValueError, struct.error) as exc:
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
        "device_mbr_signature": raw_mbr_signature(head[:512]),
        "device_mbr_blank": sector_is_blank(head[:512]),
    }
    if stalled:
        outcome["device_error"] = f"device read stalled: no data for {timeout:g} s after {done} bytes"
        # A card too slow to finish the probe in time is slow media, not unmeasured
        # media: report the rate it managed (possibly 0) so the slow-media gate applies.
        outcome["device_read_seconds"] = round(timeout, 3)
        outcome["device_read_mbps"] = round(done / MB / timeout, 2) if timeout > 0 else 0.0
    elif "error" in state:
        outcome["device_error"] = f"device cannot be read: {state['error']}"
    elif done < PROBE_MIN_TIMED_BYTES and not check_layout:
        # A few bytes time the open, not the card; report no rate rather than a wrong one.
        outcome["device_error"] = f"only {done} bytes could be read; too little to time"
    elif seconds and not check_layout:
        outcome["device_read_mbps"] = round(done / MB / float(seconds), 2)
    if layout is not None:
        outcome["device_disk_guid"] = state.get("guid")
    if check_layout:
        outcome["device_layout_verified"] = not stalled and "layout" in state and "error" not in state
        outcome["device_read_mbps"] = None
        if outcome["device_layout_verified"]:
            outcome["device_layout"] = state["layout"]
    return outcome, stalled


def probe(image: Path, device: str | None, probe_bytes: int = PROBE_BYTES,
          timeout: float = 120.0, layout: dict | None = None,
          check_layout: bool = False) -> tuple[dict[str, object], bool]:
    """Pre-flight facts for the writer (D-188); never fails on the device."""
    result: dict[str, object] = {"image_raw_size": None, "image_mbr_signature": None}
    if layout is not None:
        layout = validate_layout(layout)
        result["image_disk_guid"] = layout["disk_guid"]
    if check_layout and (layout is None or not device):
        raise ValueError("LAYOUT: --verify-layout requires --layout-file and --device")
    try:
        result["image_raw_size"] = xz_raw_size(image)
        if layout is not None and result["image_raw_size"] != layout["raw_size_bytes"]:
            raise ValueError("LAYOUT: image raw size differs")
        with lzma.open(image, "rb") as expected:
            result["image_mbr_signature"] = mbr_signature(expected.read(512))
    except (OSError, EOFError, lzma.LZMAError, ValueError) as exc:
        result["image_error"] = str(exc)
    stalled = False
    if device:
        outcome, stalled = _probe_device(device, probe_bytes, timeout, layout, check_layout)
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
    parser.add_argument("--layout-file", type=Path, help="validated layout snapshot from the signed release verifier")
    parser.add_argument("--verify-layout", action="store_true", help="inspect both device GPT copies before personalization; metadata only")
    parser.add_argument("--allow-boot-extra", action="append", default=[], metavar="NAME",
                        help="a top-level boot-partition entry the writer added after the image "
                             "(rosy-provision, rosy-config.yaml); D-389 emergency follow-up only")
    args = parser.parse_args()
    progress = Progress(args.progress, args.progress_seconds)
    try:
        layout = validate_layout(json.loads(args.layout_file.read_text(encoding="utf-8-sig"))) if args.layout_file else None
        if args.probe or args.verify_layout:
            facts, stalled = probe(args.image, args.device, 0 if args.verify_layout else args.probe_bytes,
                                   args.probe_seconds, layout, args.verify_layout)
            print(json.dumps(facts, sort_keys=True, separators=(",", ":")), flush=True)
            if stalled:
                os._exit(0)  # a thread is wedged in a device read; do not wait for it
            return 0
        if args.raw_size:
            evidence = {"image_raw_size": xz_raw_size(args.image)}
        elif args.image_only:
            if args.device:
                raise ValueError("--device cannot be combined with --image-only")
            evidence = hash_image(args.image)
        else:
            if not args.device:
                raise ValueError("--device is required unless --image-only is used")
            evidence = verify(args.image, args.device, progress, args.stall_seconds,
                              frozenset(name.lower() for name in args.allow_boot_extra), layout=layout)
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
