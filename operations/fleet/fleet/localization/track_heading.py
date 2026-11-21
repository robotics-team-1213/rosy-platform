"""Heading of a blob track that has none: the direction it moved while the robot's odometry says it moves.

Pure, one instance per robot. The blob tracker reports no heading, so while `moving` and the track has moved more than
`min_m` since its last reference point, that direction is the heading, kept while the track stays fresh (a skipped frame
repeats the position). Before the first such move there is none. Shared by lane compliance (D-511) and the track anchor.
"""

from __future__ import annotations

import math
from typing import Optional


class TrackHeading:
    def __init__(self, min_m: float) -> None:
        self.min_m = min_m
        self._from: Optional[tuple[float, float]] = None   # last track point beyond the deadband
        self._yaw: Optional[float] = None
        self.fresh = False   # the last update measured a new heading (a kept one says nothing about a turn in place)

    def reset(self) -> None:
        self._from = self._yaw = None
        self.fresh = False

    def update(self, x: float, y: float, moving: bool) -> Optional[float]:
        """The motion heading (radians) after this track point, or None before the first one."""
        last = self._from
        self.fresh = False
        if last is None or math.hypot(x - last[0], y - last[1]) > self.min_m:
            self._from = (x, y)
            if last is not None and moving:
                self._yaw = math.atan2(y - last[1], x - last[0])
                self.fresh = True
        return self._yaw
