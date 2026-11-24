"""2-slot POSIX mmap transport for robot camera/front frames (zero ROS imports: D-171)."""
from __future__ import annotations

from dataclasses import dataclass, field
import errno
import mmap
import os
import stat
import struct
import time

MAGIC = b"RMF2"
SLOTS = 2
DEFAULT_SHM_PATH = "/run/rosy-media/front.bgr"
DEFAULT_SLOT_BYTES = 1280 * 720 * 3
HEADER_STRUCT = struct.Struct("<4sQIIIIIIqI64s")
HEADER_SIZE = 128
_SEQ_STRUCT = struct.Struct("<Q")

try:
    import fcntl as _fcntl
except ImportError:  # Windows host tests use POSIX SHM only on Linux/ai
    _fcntl = None

_OFF_FLAGS = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def default_camera_shm_path() -> str:
    """Return configured SHM path, or '' when ROSY_CAMERA_SHM_PATH explicitly disables it."""
    raw = os.environ.get("ROSY_CAMERA_SHM_PATH")
    if raw is None:
        return DEFAULT_SHM_PATH
    cleaned = raw.strip()
    if cleaned.lower() in ("", "0", "off", "false", "none"):
        return ""
    return cleaned


def _declare_or_read_shm_path(node) -> str:
    default = default_camera_shm_path()
    try:
        has_param = node.has_parameter("camera_shm_path")
    except AttributeError:
        has_param = False
    try:
        if has_param:
            value = node.get_parameter("camera_shm_path").value
        else:
            value = node.declare_parameter("camera_shm_path", default).value
    except Exception:
        return default
    cleaned = str(value or "").strip()
    if cleaned.lower() in ("", "0", "off", "false", "none"):
        return ""
    return cleaned


def _open_regular_nofollow(path: str, flags: int, mode: int = 0o640) -> int:
    fd = os.open(path, flags | _OFF_FLAGS, mode)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(errno.EINVAL, f"{path} is not a regular file")
    except Exception:
        os.close(fd)
        raise
    return fd


class CameraShmWriter:
    """Single-owner 2-slot seqlock mmap writer for BGR8 camera frames."""

    def __init__(self, path: str, *, slot_bytes: int = DEFAULT_SLOT_BYTES):
        self.path = str(path)
        self.slot_bytes = max(4096, int(slot_bytes))
        self.total_size = HEADER_SIZE + SLOTS * self.slot_bytes
        self._owner_fd: int | None = None
        self._fd: int | None = None
        self._mm: mmap.mmap | None = None
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent:
            os.makedirs(parent, mode=0o755, exist_ok=True)
        owner_path = f"{self.path}.owner"
        try:
            self._owner_fd = _open_regular_nofollow(owner_path, os.O_CREAT | os.O_RDWR)
            if _fcntl is not None:
                _fcntl.flock(self._owner_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            self._fd = _open_regular_nofollow(self.path, os.O_CREAT | os.O_RDWR)
            os.ftruncate(self._fd, self.total_size)
            self._mm = mmap.mmap(self._fd, self.total_size, access=mmap.ACCESS_WRITE)
            self._seq = ((time.monotonic_ns() & 0x0FFF_FFFF_FFFF_FFFE) or 2)
            self._active_slot = 0
            self._mm[0:HEADER_SIZE] = b"\x00" * HEADER_SIZE
            HEADER_STRUCT.pack_into(self._mm, 0, MAGIC, self._seq, 0, 0, 0, 3, 0, self.slot_bytes, 0, 0, b"")
        except Exception:
            self.close()
            raise

    def write(self, bgr, capture_stamp_s: float, *, frame_id: str = "") -> int:
        if self._mm is None:
            raise OSError(errno.EBADF, "CameraShmWriter is closed")
        height = int(bgr.shape[0])
        width = int(bgr.shape[1])
        channels = int(bgr.shape[2]) if getattr(bgr, "ndim", 3) >= 3 else 1
        raw = memoryview(bgr) if getattr(bgr.flags, "c_contiguous", False) else bgr.tobytes()
        payload_len = len(raw) if isinstance(raw, (bytes, bytearray)) else raw.nbytes
        if payload_len > self.slot_bytes:
            raise ValueError(f"frame payload {payload_len} exceeds slot_bytes {self.slot_bytes}")
        next_slot = 1 - self._active_slot
        slot_offset = HEADER_SIZE + next_slot * self.slot_bytes
        self._mm[slot_offset : slot_offset + payload_len] = raw
        odd_seq = self._seq + 1
        even_seq = odd_seq + 1
        frame_bytes = str(frame_id or "").encode("utf-8")[:64]
        stamp_ns = int(float(capture_stamp_s) * 1_000_000_000)
        _SEQ_STRUCT.pack_into(self._mm, 4, odd_seq)
        HEADER_STRUCT.pack_into(
            self._mm,
            0,
            MAGIC,
            odd_seq,
            next_slot,
            width,
            height,
            channels,
            payload_len,
            self.slot_bytes,
            stamp_ns,
            len(frame_bytes),
            frame_bytes.ljust(64, b"\x00"),
        )
        _SEQ_STRUCT.pack_into(self._mm, 4, even_seq)
        self._seq = even_seq
        self._active_slot = next_slot
        return even_seq

    def close(self) -> None:
        if self._mm is not None:
            try:
                self._mm.close()
            finally:
                self._mm = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        if self._owner_fd is not None:
            try:
                if _fcntl is not None:
                    try:
                        _fcntl.flock(self._owner_fd, _fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(self._owner_fd)
            finally:
                self._owner_fd = None


class CameraShmReader:
    """Lock-free 2-slot seqlock mmap reader with inode-change detection."""

    def __init__(self, path: str):
        self.path = str(path)
        self._fd: int | None = None
        self._mm: mmap.mmap | None = None
        self._dev_ino: tuple[int, int] | None = None
        self._reopened = False

    def _ensure_open(self) -> bool:
        try:
            st = os.lstat(self.path)
        except OSError:
            return False
        if not stat.S_ISREG(st.st_mode) or st.st_size < HEADER_SIZE:
            return False
        dev_ino = (st.st_dev, st.st_ino)
        if self._mm is not None and self._dev_ino == dev_ino:
            return True
        self.close()
        try:
            fd = _open_regular_nofollow(self.path, os.O_RDONLY)
            mm = mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
        except OSError:
            return False
        self._fd = fd
        self._mm = mm
        self._dev_ino = dev_ino
        self._reopened = True
        return True

    def read_latest(self, last_seq: int = 0):
        """Return `(seq, width, height, channels, stamp_ns, frame_id, payload)` or None."""
        if not self._ensure_open() or self._mm is None:
            return None
        mm = self._mm
        for _ in range(3):
            magic, seq1, active_slot, width, height, channels, payload_len, slot_bytes, stamp_ns, fid_len, fid_raw = (
                HEADER_STRUCT.unpack_from(mm, 0)
            )
            if magic != MAGIC or seq1 == 0 or (seq1 & 1) or (not self._reopened and seq1 == last_seq):
                return None
            if active_slot not in (0, 1) or payload_len <= 0 or payload_len > slot_bytes:
                return None
            offset = HEADER_SIZE + active_slot * slot_bytes
            if offset + payload_len > mm.size():
                return None
            payload = bytes(mm[offset : offset + payload_len])
            seq2 = _SEQ_STRUCT.unpack_from(mm, 4)[0]
            if seq1 == seq2:
                self._reopened = False
                frame_id = fid_raw[: min(fid_len, 64)].decode("utf-8", errors="replace")
                return seq2, width, height, channels, stamp_ns, frame_id, payload
        return None

    def close(self) -> None:
        if self._mm is not None:
            try:
                self._mm.close()
            finally:
                self._mm = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
        self._dev_ino = None


@dataclass
class ShmStamp:
    sec: int = 0
    nanosec: int = 0


@dataclass
class ShmHeader:
    stamp: ShmStamp = field(default_factory=ShmStamp)
    frame_id: str = ""


@dataclass
class ShmImageFrame:
    """Fallback ROS-free Image carrier when image_cls is omitted in host unit tests."""

    header: ShmHeader = field(default_factory=ShmHeader)
    height: int = 0
    width: int = 0
    encoding: str = "bgr8"
    is_bigendian: int = 0
    step: int = 0
    data: bytes = b""


def _build_image_msg(image_cls, width: int, height: int, channels: int, stamp_ns: int, frame_id: str, payload: bytes):
    msg = ShmImageFrame() if image_cls is None else image_cls()
    sec, nsec = divmod(max(0, int(stamp_ns)), 1_000_000_000)
    msg.header.stamp.sec = sec
    msg.header.stamp.nanosec = nsec
    msg.header.frame_id = frame_id
    msg.height = height
    msg.width = width
    msg.encoding = "mono8" if channels == 1 else "bgr8"
    msg.is_bigendian = 0
    msg.step = width * channels
    msg.data = payload
    return msg


class CameraFrontSource:
    """Timer-polled SHM subscriber with automatic DDS fallback for Gazebo/test publishers."""

    def __init__(
        self,
        node,
        callback,
        create_dds_sub,
        *,
        image_cls=None,
        shm_path: str | None = None,
        poll_hz: float = 16.0,
        fallback_after_s: float = 1.5,
        stale_after_s: float = 2.0,
        clock=time.monotonic,
    ):
        self._node = node
        self._callback = callback
        self._create_dds_sub = create_dds_sub
        self._image_cls = image_cls
        self._clock = clock
        self._fallback_after_s = fallback_after_s
        self._stale_after_s = stale_after_s
        resolved = _declare_or_read_shm_path(node) if shm_path is None else shm_path
        self._shm_path = resolved
        self._dds_sub = None
        self._timer = None
        self._reader: CameraShmReader | None = None
        self._last_seq = 0
        self._shm_hits = 0
        self._last_shm_mono = float(clock())
        if not resolved:
            self._dds_sub = create_dds_sub()
            return
        self._reader = CameraShmReader(resolved)
        self._timer = node.create_timer(1.0 / max(1.0, float(poll_hz)), self._poll)

    @property
    def dds_active(self) -> bool:
        return self._dds_sub is not None

    def _poll(self) -> None:
        if self._reader is None:
            return
        now = float(self._clock())
        sample = self._reader.read_latest(self._last_seq)
        if sample is not None:
            seq, width, height, channels, stamp_ns, frame_id, payload = sample
            self._last_seq = seq
            self._last_shm_mono = now
            self._shm_hits += 1
            if self._dds_sub is not None and self._shm_hits >= 2:
                try:
                    self._node.destroy_subscription(self._dds_sub)
                finally:
                    self._dds_sub = None
            msg = _build_image_msg(self._image_cls, width, height, channels, stamp_ns, frame_id, payload)
            self._callback(msg)
            return
        wait_limit = self._stale_after_s if self._shm_hits > 0 else self._fallback_after_s
        if self._dds_sub is None and (now - self._last_shm_mono) >= wait_limit:
            self._dds_sub = self._create_dds_sub()
            self._shm_hits = 0

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None


def attach_camera_front_source(
    node,
    callback,
    create_dds_sub,
    *,
    image_cls=None,
    shm_path: str | None = None,
    poll_hz: float = 16.0,
    fallback_after_s: float = 1.5,
    stale_after_s: float = 2.0,
) -> CameraFrontSource:
    """Attach a camera/front source preferring POSIX SHM and falling back to DDS automatically."""
    return CameraFrontSource(
        node,
        callback,
        create_dds_sub,
        image_cls=image_cls,
        shm_path=shm_path,
        poll_hz=poll_hz,
        fallback_after_s=fallback_after_s,
        stale_after_s=stale_after_s,
    )


def open_camera_shm_writer(node) -> CameraShmWriter | None:
    """Best-effort SHM writer initialization on camera_detect_node (keeps D-766 node < 600 lines)."""
    shm_path = _declare_or_read_shm_path(node)
    if not shm_path:
        return None
    try:
        return CameraShmWriter(shm_path)
    except OSError as exc:
        node.get_logger().warn(f"camera SHM disabled ({shm_path}: {exc}); using DDS camera/front")
        return None


def publish_camera_front_frame(node, bgr, capture_stamp, *, image_cls, compressed_cls, encode_jpeg_fn) -> None:
    """Write BGR8 frame to SHM, skip zero-subscriber DDS raw copy, and preserve JPEG copy header."""
    if capture_stamp is None:
        capture_stamp = node.get_clock().now().nanoseconds * 1e-9
    stamp_sec = int(capture_stamp)
    stamp_nsec = int((capture_stamp - stamp_sec) * 1_000_000_000)
    frame_id = str(node.get_parameter("camera_frame").value)
    writer = getattr(node, "_shm_writer", None)
    if writer is not None:
        try:
            writer.write(bgr, capture_stamp, frame_id=frame_id)
        except OSError as exc:
            node.get_logger().warn(f"camera SHM write failed ({exc}); reverting to DDS camera/front")
            writer.close()
            node._shm_writer = writer = None
    try:
        has_dds_subs = node.img_pub.get_subscription_count() > 0
    except AttributeError:
        has_dds_subs = True
    if writer is None or has_dds_subs:
        msg = _build_image_msg(image_cls, int(bgr.shape[1]), int(bgr.shape[0]), 3,
                               stamp_sec * 1_000_000_000 + stamp_nsec, frame_id, bgr.tobytes()
                               if not getattr(bgr.flags, "c_contiguous", False) else bytes(memoryview(bgr)))
        node.img_pub.publish(msg)
    pub = node.jpeg_pub
    if pub is not None:
        try:
            data, fmt = encode_jpeg_fn(bgr, node._jpeg_quality)
        except (ValueError, RuntimeError) as exc:
            node.get_logger().warn(f"compressed frame skipped: {exc}", throttle_duration_sec=5.0)
            return
        jpeg = compressed_cls()
        jpeg.header.stamp.sec = stamp_sec
        jpeg.header.stamp.nanosec = stamp_nsec
        jpeg.header.frame_id = frame_id
        jpeg.format = fmt
        jpeg.data = data
        pub.publish(jpeg)
