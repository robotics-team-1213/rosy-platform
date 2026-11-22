"""Where a pose sits relative to a stop target, in the target's own frame.

One definition for every "did it stop inside the box" check (Fleet named stops, CORE fine re-park,
bay docking): forward is along the target heading, left is 90 degrees counter-clockwise from it.
"""

from __future__ import annotations

import math

#: CORE fine re-park caps (D-1051): the one place CORE (drive/behaviors/localization/repark.py) and Fleet read them from.
REPARK_MAX_FORWARD_M = 0.10
REPARK_MAX_LEFT_M = 0.06


def repark_within_limits(forward_m: float, left_m: float = 0.0) -> bool:
    return abs(forward_m) <= REPARK_MAX_FORWARD_M and abs(left_m) <= REPARK_MAX_LEFT_M


def offset_in_frame(origin, point) -> tuple[float, float]:
    """(forward, left) of point (x, y) seen from origin (x, y, yaw)."""
    c, s = math.cos(origin[2]), math.sin(origin[2])
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    return c * dx + s * dy, -s * dx + c * dy


def stop_error(target, pose) -> dict:
    """How far the target still is from pose, in the target's frame.

    longitudinal_m > 0: the target is ahead along its heading (the robot stopped short);
    lateral_m > 0: the target lies to the left; heading_rad: pose yaw minus target yaw, wrapped to [-pi, pi]."""
    longitudinal, lateral = offset_in_frame((pose[0], pose[1], target[2]), target)
    return {"longitudinal_m": longitudinal, "lateral_m": lateral,
            "heading_rad": math.remainder(pose[2] - target[2], math.tau)}
