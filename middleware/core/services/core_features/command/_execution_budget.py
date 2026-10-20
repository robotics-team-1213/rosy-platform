"""D-776 private restrictive arithmetic, not motion admission or a writer fence.

Claim and public mutations share a nonblocking lock. The private execution
ledger owns an adopted budget; arithmetic alone has no public capability,
native child authority or publisher, and no runtime factory installs it yet.
Profiles must eventually be backed by measured whole-device bounds, including
source-clock semantics, maximum physical rates and the downstream stop path.
Synthetic profiles establish arithmetic only.
"""

from dataclasses import dataclass, fields
import math
from threading import Lock


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _up(value):
    try:
        return math.nextafter(value, math.inf)
    except OverflowError:
        return math.inf if value > 0 else math.nextafter(-math.inf, math.inf)


def _down(value):
    try:
        return math.nextafter(value, -math.inf)
    except OverflowError:
        return math.nextafter(math.inf, -math.inf) if value > 0 else -math.inf


def _distance(first, second):
    try:
        return math.hypot(first[0] - second[0], first[1] - second[1])
    except OverflowError:
        return math.inf


@dataclass(frozen=True)
class Limits:
    revision: str
    speed_mps: float
    angular_speed_rps: float
    deceleration_mps2: float
    angular_deceleration_rps2: float
    latency_s: float
    watchdog_s: float
    footprint_m: float
    position_error_m: float
    max_pose_age_s: float
    max_pose_gap_s: float
    whole_load_w: float

    def __post_init__(self):
        if type(self.revision) is not str or not self.revision.strip():
            raise ValueError("profile revision required")
        if any(not _finite(getattr(self, f.name)) or getattr(self, f.name) <= 0
               for f in fields(self) if f.name != "revision"):
            raise ValueError("profile bounds must be positive finite numbers")


@dataclass(frozen=True)
class Pose:
    stamp_ns: int
    source_now_ns: int
    frame: str
    epoch: str
    x: float
    y: float


@dataclass(frozen=True)
class Remaining:
    """Room left; energy covers elapsed time plus stopping now, not future work."""

    duration_s: float
    path_m: float
    rotation_rad: float
    radius_m: float
    energy_upper_j: float


class Budget:
    """One original window; stop is irreversible and no renewal operation exists.

    Remaining values are observations, never a reusable permission to submit.
    Whole-window rate*time bounds count waiting, ZERO load, backtracking and
    complete turns invisible between pose samples. Chords and wrapped yaw cannot
    establish a physical path/rotation upper bound.
    """

    def __init__(self, *, limits, initial, before_mono, after_mono, now_utc,
                 captured_utc, admit_until_utc, duration_s, path_m,
                 rotation_rad, radius_m):
        values = (before_mono, after_mono, now_utc, captured_utc, admit_until_utc,
                  duration_s, path_m, rotation_rad, radius_m)
        if (type(limits) is not Limits or not all(_finite(v) for v in values)
                or min(before_mono, after_mono) < 0 or before_mono > after_mono
                or not captured_utc <= now_utc < admit_until_utc
                or _up(now_utc + _up(after_mono - before_mono)) >= admit_until_utc
                or min(duration_s, path_m, rotation_rad, radius_m) <= 0
                or not self._valid_pose(initial)):
            raise ValueError("invalid original budget admission")
        self._limits = limits
        self._duration = duration_s
        self._path = path_m
        self._rotation = rotation_rad
        self._radius = radius_m
        self._start = before_mono  # Slow admission does not start a fresh window.
        self._admit_deadline = _down(before_mono + _down(admit_until_utc - now_utc))
        self._last_mono = after_mono
        self._last_read_end = after_mono
        self._pose = initial
        self._center = (initial.x, initial.y)
        self._capture_mono = self._capture(initial, before_mono)
        self._last_received = before_mono
        self._reason = None
        self._owner = None
        self._lock = Lock()
        if not self._fresh(after_mono):
            raise ValueError("initial pose is stale")

    @staticmethod
    def _valid_pose(pose):
        return (type(pose) is Pose
                and type(pose.stamp_ns) is int and 0 < pose.stamp_ns < 2**63
                and type(pose.source_now_ns) is int
                and pose.stamp_ns <= pose.source_now_ns < 2**63
                and type(pose.frame) is str and bool(pose.frame.strip())
                and type(pose.epoch) is str and bool(pose.epoch.strip())
                and _finite(pose.x) and _finite(pose.y))

    @staticmethod
    def _capture(pose, before_mono):
        # Original source age uses its own clock domain; never compare ROS to UTC.
        try:
            age = _up((pose.source_now_ns - pose.stamp_ns) / 1e9)
            return _down(before_mono - age)
        except OverflowError:
            return -math.inf

    @property
    def reason(self):
        return self._reason

    @property
    def scope(self):
        return self._limits.revision, self._pose.frame, self._pose.epoch

    def _claim(self, owner):
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._owner is not None:
                return False
            self._owner = owner
            return True
        finally:
            self._lock.release()

    def _authorized(self, owner):
        return self._owner is None or owner is self._owner

    def _call(self, owner, denied, operation, *args, **kwargs):
        # Claim and the WHOLE operation share one nonblocking lock. An old
        # unclaimed call cannot pass authorization, pause, then mutate after
        # adoption. Contention denies instead of delaying the final writer.
        if not self._lock.acquire(blocking=False):
            return denied
        try:
            if not self._authorized(owner):
                return denied
            return operation(*args, **kwargs)
        finally:
            self._lock.release()

    def adoption_open(self, *, now_mono, _owner=None):
        """Initial adoption only; this observation grants no motion authority."""
        return self._call(_owner, False, self._adoption_open, now_mono)

    def _adoption_open(self, now_mono):
        if (not _finite(now_mono) or not _finite(self._admit_deadline)
                or now_mono >= self._admit_deadline):
            self._stop("initial-admission-expired")
            return False
        return self._remaining(now_mono) is not None

    def stop(self, reason, *, _owner=None):
        return self._call(_owner, False, self._stop, reason)

    def _stop(self, reason):
        if self._reason is None:
            self._reason = reason if type(reason) is str and reason else "stopped"
        return True

    def _clock(self, now):
        if not _finite(now) or now < self._last_mono:
            self._stop("monotonic-clock")
            return False
        self._last_mono = now
        return True

    def _fresh(self, now):
        age = _up(now - self._capture_mono)
        return _finite(age) and 0 <= age < self._limits.max_pose_age_s

    def observe(self, pose, *, before_mono, after_mono, _owner=None):
        return self._call(_owner, False, self._observe, pose, before_mono, after_mono)

    def _observe(self, pose, before_mono, after_mono):
        if self._reason is not None:
            return False
        if (not _finite(before_mono) or not _finite(after_mono)
                or before_mono > after_mono or before_mono < self._last_read_end
                or not self._clock(max(after_mono, self._last_mono)) or not self._valid_pose(pose)):
            self._stop("invalid-observation")
            return False
        # A source read may start before a writer's latest clock check. Keep
        # its original lower bound for capture; never roll the writer clock back.
        self._last_read_end = after_mono
        old = self._pose
        if (pose.frame != old.frame or pose.epoch != old.epoch
                or pose.stamp_ns < old.stamp_ns or pose.source_now_ns < old.source_now_ns
                or _up(after_mono - self._last_received) >= self._limits.max_pose_gap_s):
            self._stop("source-discontinuity")
            return False
        capture = self._capture(pose, before_mono)
        if pose.stamp_ns == old.stamp_ns:
            if (pose.x, pose.y) != (old.x, old.y):
                self._stop("changed-original-pose")
                return False
            # Receiving the same source again cannot refresh the original lease.
            self._capture_mono = min(self._capture_mono, capture)
        else:
            gap = _up((pose.stamp_ns - old.stamp_ns) / 1e9)
            if not _finite(gap) or gap >= self._limits.max_pose_gap_s:
                self._stop("source-gap")
                return False
            # Current capture cannot be later than this read; the old original
            # capture lower bound includes its source age and read uncertainty.
            elapsed = _up(after_mono - self._capture_mono)
            possible = _up(_up(self._limits.speed_mps * elapsed)
                           + _up(2 * self._limits.position_error_m))
            displacement = _down(_distance((pose.x, pose.y), (old.x, old.y)))
            if not _finite(possible) or not _finite(displacement) or displacement >= possible:
                self._stop("impossible-pose-step")
                return False
            self._capture_mono = capture
            self._last_received = before_mono
        self._pose = pose
        if not self._fresh(self._last_mono):
            self._stop("stale-pose")
            return False
        return True

    @staticmethod
    def _tail(speed, deceleration, delay):
        distance = _up(_up(speed * delay) + _up(_up(speed * speed) / _down(2 * deceleration)))
        seconds = _up(delay + _up(speed / deceleration))
        return distance, seconds

    def remaining(self, *, now_mono, _owner=None):
        return self._call(_owner, None, self._remaining, now_mono)

    def _remaining(self, now_mono):
        if self._reason is not None or not self._clock(now_mono):
            return None
        if not self._fresh(now_mono):
            self._stop("stale-pose")
            return None
        p = self._limits
        delay = _up(p.latency_s + p.watchdog_s)
        stop_path, linear_s = self._tail(p.speed_mps, p.deceleration_mps2, delay)
        stop_angle, angular_s = self._tail(p.angular_speed_rps, p.angular_deceleration_rps2, delay)
        elapsed = _up(now_mono - self._start)
        duration = _up(elapsed + max(linear_s, angular_s))
        path = _up(_up(p.speed_mps * elapsed) + stop_path)
        rotation = _up(_up(p.angular_speed_rps * elapsed) + stop_angle)
        age = _up(now_mono - self._capture_mono)
        displacement = _up(_distance((self._pose.x, self._pose.y), self._center))
        margin = _up(_up(p.footprint_m + p.position_error_m) + _up(p.speed_mps * age))
        radius = _up(_up(displacement + margin) + stop_path)
        energy = _up(p.whole_load_w * duration)
        remaining = Remaining(_down(self._duration - duration), _down(self._path - path),
                              _down(self._rotation - rotation), _down(self._radius - radius), energy)
        if (not all(_finite(v) for v in (duration, path, rotation, radius, energy))
                or min(remaining.duration_s, remaining.path_m,
                       remaining.rotation_rad, remaining.radius_m) <= 0):
            self._stop("execution-limit")
            return None
        return remaining
