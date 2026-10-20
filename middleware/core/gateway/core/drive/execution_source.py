"""Original ROS odometry retention for future admission, never a motion permit.

The map ID here is observed metadata, not authenticated map content/revision.
No state snapshot, parent replacement or repeated header starts a fresh lease.
"""
from dataclasses import dataclass, replace
from threading import Lock

from core_common.protocol.native_receipts import BOOT_ID
from core_features.command._execution_budget import Budget, Pose, _finite, _down


@dataclass(frozen=True)
class OriginalOdometry:
    robot_id: str
    boot_id: str
    map_id: str | None
    epoch: str
    stamp_ns: int
    source_now_ns: int
    frame: str
    child_frame: str
    x: float
    y: float
    yaw: float
    linear: float
    angular: float
    before_mono: float
    after_mono: float
    captured_mono: float
    expires_mono: float


class OriginalOdometrySource:
    def __init__(self, state, ledger, limits):
        self._state, self._ledger, self._limits = state, ledger, limits
        self._lock = Lock()
        self._token = self._write = self._cache = self._sealed = None
        self._last_clock = None
        self._clock_fault = self._lost = False
        self._pending = False
        self._read_start = None
        self._read_stamp = None
        self._stamp_high = self._consumed_stamp = 0
        self._stamp_start = None

    def begin(self, stamp_ns):
        with self._lock:
            self._token = object()
            self._pending = True
            self._cache = None
            try:
                self._read_start = self._ledger._clock()
                self._clock(self._read_start)
            except Exception:
                self._read_start, self._clock_fault = None, True
            self._read_stamp = stamp_ns if type(stamp_ns) is int and 0 < stamp_ns < 2**63 else None
            if self._read_stamp is not None and self._read_stamp >= self._stamp_high:
                if self._read_stamp > self._stamp_high:
                    self._stamp_start = self._read_start
                self._stamp_high = self._read_stamp
            return self._token, self._read_start

    def _consume(self):
        if self._read_stamp is not None:
            self._consumed_stamp = max(self._consumed_stamp, self._read_stamp)

    def abort(self, token):
        with self._lock:
            if token is self._token:
                self._pending = False
                self._consume()
                self._cache, self._lost = None, True

    def _clock(self, value):
        if (not _finite(value) or value < 0
                or self._last_clock is not None and value < self._last_clock):
            self._clock_fault = True
        if not self._clock_fault:
            self._last_clock = value
        return not self._clock_fault

    def complete(self, token, *, receipt, stamp_ns, source_now_ns, frame, child_frame,
                 x, y, yaw, linear, angular, before_mono, after_mono):
        with self._lock:
            if token is not self._token or not self._pending:
                return False
            self._pending = False
            self._cache = None
            try:
                now = self._ledger._clock()
                if (not self._clock(now) or before_mono != self._read_start
                        or not all(_finite(v) for v in (before_mono, after_mono))
                        or not before_mono <= after_mono <= now):
                    self._clock_fault = True
                    raise ValueError('source monotonic clock fault')
                if (receipt is None or len(receipt) != 5 or receipt[3] != self._ledger._robot
                        or stamp_ns != self._read_stamp or stamp_ns != self._stamp_high
                        or stamp_ns <= self._consumed_stamp
                        or self._state._original_odom_scope(receipt[2]) != (receipt[3], receipt[4], receipt[1])
                        or not Budget._valid_pose(Pose(stamp_ns, source_now_ns, frame, receipt[1], x, y))
                        or not all(_finite(v) for v in (yaw, linear, angular))):
                    raise ValueError('original source scope invalid')
                capture = Budget._capture(Pose(stamp_ns, source_now_ns, frame, receipt[1], x, y),
                                          min(before_mono, self._stamp_start))
                expiry = _down(capture + self._limits.max_pose_age_s)
                current = OriginalOdometry(receipt[3], BOOT_ID, receipt[4], receipt[1],
                    stamp_ns, source_now_ns, frame, child_frame, x, y, yaw, linear, angular,
                    before_mono, after_mono, capture, expiry)
                old = self._sealed
                if old is not None:
                    if stamp_ns < old.stamp_ns or source_now_ns < old.source_now_ns:
                        raise ValueError('original source reversed')
                    if stamp_ns == old.stamp_ns:
                        def facts(r):
                            return (r.robot_id, r.map_id, r.epoch, r.frame, r.child_frame,
                                    r.x, r.y, r.yaw, r.linear, r.angular)
                        if self._lost or facts(current) != facts(old):
                            raise ValueError('original source changed or consumed')
                        current = replace(current, captured_mono=min(capture, old.captured_mono),
                                          expires_mono=min(expiry, old.expires_mono))
                if (not _finite(current.captured_mono) or not _finite(current.expires_mono)
                        or now >= current.expires_mono):
                    raise ValueError('original source expired')
                self._sealed, self._cache, self._write = current, current, receipt[2]
                self._lost = False
                return True
            except Exception:
                self._consume()
                self._lost = True
                return False

    def snapshot(self):
        with self._lock:
            try:
                if not self._clock(self._ledger._clock()):
                    raise ValueError('source clock fault')
                cached = self._cache
                if cached is None:
                    return None
                scope = self._state._original_odom_scope(self._write)
                if scope is None:  # Busy state writer: wait without renewing anything.
                    return None
                if (not self._clock(self._ledger._clock())
                        or scope != (cached.robot_id, cached.map_id, cached.epoch)
                        or self._last_clock >= cached.expires_mono):
                    raise ValueError('original source no longer current')
                return cached
            except Exception:
                self._cache, self._lost = None, True
                return None
