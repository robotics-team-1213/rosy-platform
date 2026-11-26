"""Acquisition age and continuous odometry for localization missions."""

import math


class MissionOdometry:
    """Updated under the localization mission lock."""

    def __init__(self):
        self.pose = self.at = None
        self.epoch = 0
        self._source_epoch = None
        self._stamp_ns = self._source_now_ns = 0

    def observe(self, pose, now, max_age, source=None):
        """Return whether the pose changed coordinate frames or lost continuity."""
        age = 0.0
        changed = False
        if source is not None:
            stamp_ns, source_now_ns, source_epoch = source
            age = (source_now_ns - stamp_ns) / 1e9
            if stamp_ns <= 0 or not 0 <= age <= max_age:
                return False
            changed = self._source_epoch is not None and source_epoch != self._source_epoch
            reset = changed and source_now_ns < self._source_now_ns
            self._source_epoch = source_epoch
            if changed:
                self._invalidate()
            if stamp_ns <= self._stamp_ns and not reset:
                return changed
            self._stamp_ns, self._source_now_ns = stamp_ns, source_now_ns
        observed_at = now - age
        if not all(math.isfinite(v) for v in (*pose, observed_at)) or (
                self.at is not None and observed_at < self.at):
            self._invalidate()
            return True
        if source is not None and self.at is not None and observed_at - self.at > max_age:
            self._invalidate()
            changed = True
        self.pose, self.at = pose, observed_at
        return changed

    def _invalidate(self):
        self.pose = self.at = None
        self.epoch += 1

    def fresh(self, now, max_age):
        if self.pose is not None and 0 <= now - self.at <= max_age:
            return self.pose
