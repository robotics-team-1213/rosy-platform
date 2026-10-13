"""core_features.localization.rotate_to — D-603 CORE rotate-to-heading: the request bounds and the turn law.

Safety-tagged (D-430 §1, `safety_modules`): this decides how far, how fast and for how long CORE
turns the robot in place for `POST /api/v1/motion/rotate_to`. The mission (`mission.py`, kind
`rotate_to`) runs it with the `rotate_in_place` guards: up-front and running RobotBody/LiDAR
clearance (D-424), odometry and LiDAR staleness, E-stop and every mode change out of NAVIGATION.
Its twist goes through the CommandManager nav slot, so `select_output` still applies E-stop, the
readiness HOLD, the Safety clip and the D-400 policy. The loop is closed on the robot's own odom
yaw: Fleet converts a map heading error to `delta_deg`; odom over-rotates 6–11 % on real turns
(D-598), so Fleet re-checks from a fresh camera sighting and may ask once more (D-603 3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

MAX_DELTA_DEG = 180.0       # D-550 rule M: one bounded turn, never a spin
MAX_RATE_DPS = 30.0
MAX_TIMEOUT_S = 15.0
TOL_RANGE_DEG = (1.0, 20.0)
DEFAULT_TOL_DEG = 5.0
DEFAULT_RATE_DPS = 20.0
DEFAULT_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class RotateGoal:
    delta_rad: float        # signed turn to make, measured from the start yaw
    tol_rad: float
    max_rate: float         # rad/s
    timeout_s: float


def rotate_goal(yaw_now: float, *, delta_deg: Optional[float] = None, yaw_odom: Optional[float] = None,
                tol_deg: float = DEFAULT_TOL_DEG, max_rate_dps: float = DEFAULT_RATE_DPS,
                timeout_s: float = DEFAULT_TIMEOUT_S) -> RotateGoal:
    """The bounded goal, or ValueError (400). Exactly one of `delta_deg` / `yaw_odom` (rad, odom frame)."""
    if (delta_deg is None) == (yaw_odom is None):
        raise ValueError("give exactly one of delta_deg or yaw_odom")
    values = [v for v in (delta_deg, yaw_odom, tol_deg, max_rate_dps, timeout_s, yaw_now) if v is not None]
    if not all(math.isfinite(float(v)) for v in values):
        raise ValueError("rotate_to values must be finite")
    if delta_deg is not None:
        if abs(delta_deg) > MAX_DELTA_DEG:
            raise ValueError(f"|delta_deg| must be at most {MAX_DELTA_DEG}")
        delta = math.radians(delta_deg)
    else:
        delta = math.atan2(math.sin(yaw_odom - yaw_now), math.cos(yaw_odom - yaw_now))
    if not TOL_RANGE_DEG[0] <= tol_deg <= TOL_RANGE_DEG[1]:
        raise ValueError(f"tol_deg must be in [{TOL_RANGE_DEG[0]}, {TOL_RANGE_DEG[1]}]")
    if not 0.0 < max_rate_dps <= MAX_RATE_DPS:
        raise ValueError(f"max_rate_dps must be in (0, {MAX_RATE_DPS}]")
    if not 0.0 < timeout_s <= MAX_TIMEOUT_S:
        raise ValueError(f"timeout_s must be in (0, {MAX_TIMEOUT_S}]")
    return RotateGoal(delta, math.radians(tol_deg), math.radians(max_rate_dps), float(timeout_s))


def turn_rate(goal: RotateGoal, turned_rad: float, *, gain: float, min_rate: float) -> Optional[float]:
    """Signed angular rate toward the goal for the signed odom turn so far; None = within tolerance.

    Proportional, never above the goal's `max_rate` and never below `min_rate` (the wheels' deadband),
    so the last degrees come in slowly and a small overshoot is turned back."""
    err = goal.delta_rad - turned_rad
    if abs(err) <= goal.tol_rad:
        return None
    rate = min(goal.max_rate, max(min_rate, gain * abs(err)))
    return math.copysign(rate, err)
