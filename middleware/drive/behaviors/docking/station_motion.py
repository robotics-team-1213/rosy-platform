"""Measured body twist leased by original odom header time and odometry epoch."""
import math
import threading

_READ_NOW = object()


class StationMotionFeed:
    def __init__(self, *, clock, source_clock, max_age_s):
        if isinstance(max_age_s, bool) or not isinstance(max_age_s, (int, float)) or not math.isfinite(max_age_s) or max_age_s <= 0:
            raise ValueError('STATION_MOTION_AGE_REQUIRED')
        self.clock, self.source_clock, self.max_age_s = clock, source_clock, max_age_s
        self._latest, self._last_source, self._epoch = None, None, None
        self._lock = threading.Lock()

    def _read_clocks(self):
        """Bracket one UTC read. Later decisions use these values without rereading."""
        try:
            before, source, after = self.clock(), self.source_clock(), self.clock()
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (before, source, after))
                    or not 0 <= before <= after or source < 0):
                return None
            span = math.nextafter(after-before, math.inf)
            lower = math.nextafter(source-span, -math.inf)
            upper = math.nextafter(source+span, math.inf)
            if not math.isfinite(lower) or not math.isfinite(upper) or lower < 0:
                return None
            return before, source, after, lower, upper
        except Exception:
            return None

    def _read_start(self):
        times = self._read_clocks()
        if times is None:
            raise ValueError('STATION_MOTION_CLOCK_REQUIRED')
        return times[0], times[3]

    def observe(self, *, stamp_ns, source_now_ns, frame_id, child_frame_id, odom_epoch,
                measured_linear_m_s, measured_angular_rad_s,
                received_at=_READ_NOW, source_received_at=_READ_NOW):
        """Explicit read bounds include adapter delay; omitted bounds mean an immediate read."""
        with self._lock:
            self._latest = None
            if (type(stamp_ns) is not int or type(source_now_ns) is not int
                    or not 0 <= stamp_ns <= source_now_ns < 2**63
                    or frame_id != 'odom' or child_frame_id not in ('base_link', 'base_footprint')
                    or not isinstance(odom_epoch, str) or not odom_epoch):
                return False
            if odom_epoch != self._epoch:
                self._epoch, self._last_source = odom_epoch, None
            if self._last_source is not None and stamp_ns <= self._last_source:
                return False
            age = (source_now_ns-stamp_ns)/1e9
            times = self._read_clocks()
            if times is None:
                return False
            before, source_now, local_now, source_lower, source_upper = times
            if received_at is _READ_NOW and source_received_at is _READ_NOW:
                received_at, source_received_at = before, source_lower
            values = (measured_linear_m_s, measured_angular_rad_s, local_now, source_now,
                      received_at, source_received_at)
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)
                    or not 0 <= age <= self.max_age_s
                    or not 0 <= received_at <= before or not 0 <= source_received_at <= source_now):
                return False
            local_at = math.nextafter(received_at-age, -math.inf)
            source_at = math.nextafter(source_received_at-age, -math.inf)
            if (min(local_at, source_at) < 0 or not 0 <= local_now-local_at <= self.max_age_s
                    or not 0 <= source_upper-source_at <= self.max_age_s):
                return False
            self._last_source = stamp_ns
            self._latest = (dict(odom_epoch=odom_epoch, captured_at=source_at,
                                 measured_linear_m_s=measured_linear_m_s, measured_angular_rad_s=measured_angular_rad_s),
                            local_at)
            return True

    def snapshot(self):
        if not self._lock.acquire(blocking=False):
            return None
        try:
            sample = self._latest
            if sample is None:
                return None
            value, local_at = sample
            times = self._read_clocks()
            if times is None:
                self._latest = None
                return None
            _, source, after, _, upper = times
            local_age = math.nextafter(after-local_at, math.inf)
            if (not 0 <= local_age <= self.max_age_s
                    or not 0 <= upper-value['captured_at'] <= self.max_age_s):
                self._latest = None
                return None
            until = math.nextafter(min(value['captured_at']+self.max_age_s,
                source+(self.max_age_s-local_age)), -math.inf)
            if until <= upper:
                self._latest = None
                return None
            return dict(value, valid_until=until)
        finally:
            self._lock.release()

    def clear(self):
        with self._lock:
            self._latest = None
