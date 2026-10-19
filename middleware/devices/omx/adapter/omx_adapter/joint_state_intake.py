"""Preserve source age at ROS intake; this does not authenticate the publisher."""
from __future__ import annotations

import math

from .command_owner import JointStateSnapshot


class JointStateIntake:
    def __init__(self, config):
        self.config = config
        self._last_stamp_ns = 0
        self._sequence = 0
        self._last_received_at = None

    def snapshot(self, names, positions, *, stamp_ns, source_now_ns, received_at):
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
            calibration_revision=self.config.calibration_revision)
        # Variable source delay can regress the age-adjusted receipt even when both clocks advance.
        if self._last_received_at is not None and snapshot.received_at < self._last_received_at:
            raise ValueError("joint state age-adjusted receipt regressed")
        self._last_stamp_ns = stamp_ns
        self._last_received_at = snapshot.received_at
        self._sequence += 1
        return snapshot
