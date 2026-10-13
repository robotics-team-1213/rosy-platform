"""D-407 rear blind zone: the CORE-issued line-follow twists (moved out of stuck_recovery.py, 2026-10-10)."""

from __future__ import annotations

import math
from collections import deque
from typing import Optional


class ForwardTrail:
    """The CORE-issued line-follow twists, to prove the space behind was just driven through.

    User decision 2026-10-02 (D-407 rear blind zone): back off into the blind band only over
    ground the robot drove forward over. ``measure`` integrates the issued twists over the
    ``window_s`` of commands that ends at the last forward command (the robot has stood still
    or backed off since): net forward metres (reverse subtracts) and total |yaw| in degrees.
    A gap in the record counts no travel; a record older than ``STALE_S`` reads as missing.
    """

    MAX_DT_S = 0.25    # one issued twist never covers more than this (nav timeout order)
    STALE_S = 1.0

    def __init__(self, maxlen: int = 4000) -> None:
        self._samples: deque = deque(maxlen=maxlen)

    def clear(self) -> None:
        self._samples.clear()

    def record(self, now: float, linear: float, angular: float) -> None:
        if self._samples and now < self._samples[-1][0]:
            self._samples.clear()            # clock went backwards: trust nothing before
        self._samples.append((float(now), float(linear), float(angular)))

    def net_since(self, since: float, now: float) -> float:
        """Net forward metres issued from ``since`` to ``now`` (gaps count no travel)."""
        samples = [sample for sample in self._samples if sample[0] >= since]
        net = 0.0
        for index, (t, lin, _) in enumerate(samples):
            end = samples[index + 1][0] if index + 1 < len(samples) else now
            net += lin * max(0.0, min(end - t, self.MAX_DT_S))
        return net

    def last_forward_at(self) -> Optional[float]:
        """Time of the newest forward (linear > 0) issued twist, or None."""
        for t, lin, _ in reversed(self._samples):
            if lin > 0.0:
                return t
        return None

    def measure(self, now: float, window_s: float) -> tuple[Optional[float], Optional[float]]:
        samples = list(self._samples)
        if not samples or now - samples[-1][0] > self.STALE_S:
            return None, None
        forward = [t for t, lin, _ in samples if lin > 0.0]
        if not forward:
            return None, None
        start = forward[-1] - window_s
        net = yaw = 0.0
        for index, (t, lin, ang) in enumerate(samples):
            if t < start:
                continue
            end = samples[index + 1][0] if index + 1 < len(samples) else now
            dt = max(0.0, min(end - t, self.MAX_DT_S))
            net += lin * dt
            yaw += abs(ang) * dt
        return net, math.degrees(yaw)
