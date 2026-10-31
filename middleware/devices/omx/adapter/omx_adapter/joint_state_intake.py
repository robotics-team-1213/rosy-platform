"""Preserve source age at ROS intake; this does not authenticate the publisher."""
from __future__ import annotations

import math
import time

from .command_owner import JointStateSnapshot

_MAX_COUNT = 2**63 - 1
_REJECTIONS = {
    "joint state requires an advancing, nonfuture source stamp": "STAMP_REJECTED",
    "joint state source is stale": "SOURCE_STALE",
    "joint state arrays must be complete and unambiguous": "ARRAY_SHAPE",
    "joint state positions must be finite": "NONFINITE",
}


def _stamp(value):
    return value if type(value) is int and 0 <= value <= _MAX_COUNT else None


def _time(value):
    return value if type(value) in (int, float) and abs(value) <= _MAX_COUNT else None


class JointStateIntake:
    def __init__(self, config):
        self.config = config
        self._last_stamp_ns = 0
        self._sequence = 0
        self._last_received_at = None
        self.last_attempt = self.last_rejection = None
        self.attempt_count = self.accepted_count = self.rejected_count = 0

    def snapshot(self, names, positions, *, stamp_ns, source_now_ns, received_at):
        # Observations are bounded, non-atomic facts; validation below remains authoritative.
        facts = dict(stamp_ns=_stamp(stamp_ns), source_now_ns=_stamp(source_now_ns),
                     received_at=_time(received_at), prior_accepted_stamp_ns=_stamp(self._last_stamp_ns),
                     wall_received_at=time.monotonic(), accepted=False)
        self.attempt_count = min(self.attempt_count + 1, _MAX_COUNT)
        try:
            snapshot = self._snapshot(names, positions, stamp_ns=stamp_ns,
                                      source_now_ns=source_now_ns, received_at=received_at)
        except (TypeError, ValueError, OverflowError) as error:
            message = error.args[0] if error.args else None
            code = (_REJECTIONS.get(message, "INPUT_INVALID")
                    if type(message) is str and len(message) <= 128 else "INPUT_INVALID")
            facts.update(rejection_code=code, error_type=type(error).__name__[:80])
            self.rejected_count = min(self.rejected_count + 1, _MAX_COUNT)
            self.last_attempt = self.last_rejection = facts
            raise
        self.accepted_count = min(self.accepted_count + 1, _MAX_COUNT)
        facts["accepted"] = True
        self.last_attempt = facts
        return snapshot

    def _snapshot(self, names, positions, *, stamp_ns, source_now_ns, received_at):
        if (type(stamp_ns) is not int or type(source_now_ns) is not int
                or stamp_ns <= self._last_stamp_ns or stamp_ns > source_now_ns):
            raise ValueError("joint state requires an advancing, nonfuture source stamp")
        age_s = (source_now_ns - stamp_ns) / 1e9
        if age_s > self.config.max_joint_state_age_s:
            raise ValueError("joint state source is stale")
        if (len(names) != len(positions) or len(set(names)) != len(names)
                or not set(self.config.joint_names) <= set(names)):
            raise ValueError("joint state arrays must be complete and unambiguous")
        reported = dict(zip(names, positions))
        values = {name: reported[name] for name in self.config.joint_names}
        if any(isinstance(value, bool) or not math.isfinite(value) for value in values.values()):
            raise ValueError("joint state positions must be finite")
        snapshot = JointStateSnapshot(
            positions=values, sequence=self._sequence + 1, received_at=received_at - age_s,
            calibration_revision=self.config.calibration_revision,
            source_stamp_ns=stamp_ns, source_now_ns=source_now_ns)
        # Variable source delay can regress the age-adjusted receipt even when both clocks advance.
        if self._last_received_at is not None and snapshot.received_at < self._last_received_at:
            raise ValueError("joint state age-adjusted receipt regressed")
        self._last_received_at = snapshot.received_at
        self._last_stamp_ns = stamp_ns
        self._sequence += 1
        return snapshot
