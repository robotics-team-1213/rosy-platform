"""One bounded turn in place measured on odom, camera independent (D-511 rev 5; D-607 P3 REALIGN reuses it).

The sign is locked at the start; progress is the signed odom yaw change since then, accumulated tick by
tick, so a turn near 180 deg ends on progress and never on a wrapped angle. The turn ends within
``DONE_DEG``. It fails (the caller latches a HOLD) when the summed |yaw change| exceeds |angle| +
``BUDGET_PAD_DEG``, when it runs longer than |angle| / rate + ``TIME_PAD_S``, or when the odom run
(epoch, frame) changes. Pure: the caller supplies poses, clock, rate and every other gate.
"""
from __future__ import annotations

import math
from typing import Optional

DONE_DEG = 10.0
BUDGET_PAD_DEG = 30.0
TIME_PAD_S = 2.0


def wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


class OdomPivot:
    def __init__(self, *, key, yaw_at_order: float, yaw_now: float, angle_rad: float, rate: float,
                 now: float) -> None:
        """``yaw_at_order``: odom yaw when the angle was measured (the order's pose stamp); the part of
        the turn already made since then counts as progress."""
        self.key, self.sign = key, 1.0 if angle_rad > 0 else -1.0
        self.total, self.last, self.turned = abs(angle_rad), yaw_now, 0.0
        self.progress = self.sign * wrap(yaw_now - yaw_at_order)
        self.budget = abs(angle_rad) + math.radians(BUDGET_PAD_DEG)
        self.deadline = now + abs(angle_rad) / rate + TIME_PAD_S
        self.ticks = 0                     # turn commands emitted

    @property
    def remaining(self) -> float:
        return self.total - self.progress

    def step(self, now: float, pose, key) -> tuple[str, Optional[float]]:
        """("turn", sign) | ("done", None) | ("fail", reason); ``pose`` None = odom stale."""
        if pose is None or key != self.key:
            return "fail", "odom_lost"
        delta = wrap(pose.yaw - self.last)          # one tick: never near 180 deg
        self.turned += abs(delta)
        self.progress += self.sign * delta
        self.last = pose.yaw
        if self.remaining <= math.radians(DONE_DEG):
            return "done", None
        if self.turned > self.budget or now > self.deadline:
            return "fail", "budget"
        return "turn", self.sign

    def view(self) -> dict:
        return {"turned_deg": round(math.degrees(self.turned), 1),
                "remaining_deg": round(math.degrees(self.remaining), 1), "ticks": self.ticks}
