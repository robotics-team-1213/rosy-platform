"""Original CORE map observations, not Nav2 consumer adoption or admission.

Static latched source timestamps have no odometry TTL. Generation and lifecycle
epoch are local observations, never a backend instance ID or approved revision.
"""
from dataclasses import dataclass
import hashlib
import math
import struct
from threading import Lock
from uuid import UUID

MAX_CELLS = 4_194_304


def _stamp(value):
    return type(value) is int and 0 <= value < 2**63


@dataclass(frozen=True)
class GridContent:
    frame: str
    width: int
    height: int
    resolution: float
    origin: tuple
    data: tuple
    stamp_ns: int
    load_time_ns: int

    def __post_init__(self):
        if (self.frame != 'map' or type(self.frame) is not str
                or any(type(v) is not int or v <= 0 for v in (self.width, self.height))
                or self.width*self.height > MAX_CELLS
                or type(self.resolution) not in (int, float)
                or not math.isfinite(self.resolution) or self.resolution <= 0
                or type(self.origin) is not tuple or len(self.origin) != 7
                or not all(type(v) in (int, float) and math.isfinite(v) for v in self.origin)
                or any(abs(v) > 1e-6 for v in self.origin[2:5])
                or abs(sum(v*v for v in self.origin[3:])-1.) > 1e-6
                or type(self.data) is not tuple or len(self.data) != self.width*self.height
                or any(type(v) is not int or not -1 <= v <= 100 for v in self.data)
                or not _stamp(self.stamp_ns) or not _stamp(self.load_time_ns)
                or self.load_time_ns > self.stamp_ns):
            raise ValueError('invalid original planar occupancy grid')


def content_digest(content):
    """Versioned, full SHA256; header time is identity metadata, not content."""
    if type(content) is not GridContent:
        raise ValueError('exact original grid required')
    frame = content.frame.encode('utf-8')
    digest = hashlib.sha256(b'ROSY-GRID-v1\0')
    digest.update(struct.pack('<I', len(frame)) + frame)
    digest.update(struct.pack('<II8d', content.width, content.height,
                              content.resolution, *content.origin))
    digest.update(bytes(v & 255 for v in content.data))
    return digest.hexdigest()


@dataclass(frozen=True)
class MapObservation:
    robot_id: str
    boot_id: UUID
    generation: int
    lifecycle_epoch: int
    digest: str
    frame: str
    width: int
    height: int
    resolution: float
    origin: tuple
    stamp_ns: int
    load_time_ns: int


class MapEvidence:
    def __init__(self, *, robot_id, boot_id):
        if type(robot_id) is not str or not robot_id.strip() or type(boot_id) is not UUID:
            raise ValueError('map observation owner identity required')
        self._robot, self._boot = robot_id, boot_id
        self._lock = Lock()
        self._generation = self._epoch = 0
        self._token = self._current = self._last = None
        self._source_high = self._load_high = self._consumed = -1
        self._read_stamp = self._read_load = None
        self._pending = False
        self._active = None

    def begin(self, stamp_ns, load_time_ns):
        with self._lock:
            self._token, self._current, self._pending = object(), None, True
            self._read_stamp, self._read_load = stamp_ns, load_time_ns
            if _stamp(stamp_ns): self._source_high = max(self._source_high, stamp_ns)
            if _stamp(load_time_ns): self._load_high = max(self._load_high, load_time_ns)
            return self._token

    def _discard(self):
        if _stamp(self._read_stamp): self._consumed = max(self._consumed, self._read_stamp)
        self._generation += 1
        self._current = self._last = None
        self._pending = False

    def abort(self, token):
        with self._lock:
            if token is self._token:
                self._discard()

    def complete(self, token, content):
        with self._lock:
            if token is not self._token or not self._pending:
                return False
        try:
            digest = content_digest(content)  # Full copy/hash NEVER holds the owner lock.
        except Exception:
            self.abort(token)
            return False
        with self._lock:
            if token is not self._token or not self._pending:
                return False
            old = self._last
            if (self._active is False or self._generation >= 2**63-1
                    or (content.stamp_ns, content.load_time_ns) != (self._read_stamp, self._read_load)
                    or content.stamp_ns != self._source_high or content.load_time_ns != self._load_high
                    or content.stamp_ns <= self._consumed
                    or old is not None and content.stamp_ns == old.stamp_ns
                        and (digest != old.digest or content.load_time_ns != old.load_time_ns)):
                self._discard()
                return False
            if old is None or (content.stamp_ns, content.load_time_ns, digest) != (
                    old.stamp_ns, old.load_time_ns, old.digest):
                self._generation += 1
            self._current = self._last = MapObservation(self._robot, self._boot,
                self._generation, self._epoch, digest, content.frame, content.width,
                content.height, content.resolution, content.origin, content.stamp_ns, content.load_time_ns)
            self._pending = False
            return True

    def lifecycle(self, active):
        with self._lock:
            self._active = active if type(active) is bool else False
            self._epoch += 1
            self._generation += 1
            self._token = self._current = self._last = None
            self._pending = False
            self._source_high = self._load_high = self._consumed = -1

    def snapshot(self):
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return self._current
        finally:
            self._lock.release()
