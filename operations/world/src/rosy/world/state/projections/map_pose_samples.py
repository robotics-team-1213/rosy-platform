"""Pure value types and helpers of the map pose tracker (split from map_pose.py for the size cap).

`map_pose` re-exports every public name here, so `rosy.world.state.projections.map_pose` stays the import path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional

SIGHTING = "sighting"

Pose = tuple[float, float, float]


def _finite(*values) -> bool:
    try:
        return all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
                   for v in values)
    except (OverflowError, ValueError, TypeError):
        return False


@dataclass(frozen=True)
class OdomSample:
    x: float
    y: float
    yaw: float
    stamp: float
    #: D-758 0: CORE's odom epoch (snapshot `odom_pose.epoch`); None from a CORE before v1.234.
    epoch: Optional[int] = None


@dataclass(frozen=True)
class Sighting:
    robot_id: str
    x: float
    y: float
    yaw: Optional[float]   # None only for a TRACK without a motion heading: it keeps the odometry-bridged yaw
    captured_at: float
    quality: Optional[float] = None
    map_id: Optional[str] = None
    kind: str = SIGHTING


def wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


_wrap = wrap_angle


def relative(a: Pose, b: Pose) -> Pose:
    """`b` in the frame of `a` (a^-1 * b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    c, s = math.cos(a[2]), math.sin(a[2])
    return c * dx + s * dy, -s * dx + c * dy, _wrap(b[2] - a[2])


def compose(a: Pose, d: Pose) -> Pose:
    c, s = math.cos(a[2]), math.sin(a[2])
    return a[0] + c * d[0] - s * d[1], a[1] + s * d[0] + c * d[1], _wrap(a[2] + d[2])


def camera_residual(ref_map: Pose, ref_odom: Pose, seen: Pose, odom: Pose, heading: bool) -> tuple[float, Optional[float]]:
    """(metres, degrees) the camera fix `seen` lies from the prediction ref_map + (odom since ref_odom); None deg without a camera heading."""
    predicted = compose(ref_map, relative(ref_odom, odom))
    return math.dist(predicted[:2], seen[:2]), math.degrees(_wrap(seen[2] - predicted[2])) if heading else None


RESIDUAL_FIELDS = ("camera_residual_m", "camera_residual_deg", None, "camera_x", "camera_y", "camera_yaw")


def residual_fields(resid: Optional[tuple], now: float, max_age_s: float) -> dict:
    """MapPose's camera fields from the newest residual (metres, degrees, taken at, camera x, y, yaw); all None when stale."""
    fresh = resid is not None and 0.0 <= now - resid[2] <= max_age_s
    return {name: resid[i] if fresh else None for i, name in enumerate(RESIDUAL_FIELDS) if name}


def body_heading(travel: Optional[float], odom, since: Optional[float], at: float) -> Optional[float]:
    """The body yaw for a travel direction the camera saw: the opposite one when odometry says the robot backed up."""
    if travel is None:
        return None
    span = [s for s in odom if (since is None or s.stamp >= since) and s.stamp <= at]
    if len(span) >= 2:
        (ax, ay, ayaw), (bx, by, _) = span[0].pose, span[-1].pose
        if (bx - ax) * math.cos(ayaw) + (by - ay) * math.sin(ayaw) < 0.0:
            travel += math.pi
    return _wrap(travel)


def parse_utc(text) -> Optional[float]:
    """Epoch seconds of a UTC ISO stamp (`captured_at` format); None when not one."""
    if not isinstance(text, str):
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return stamp.timestamp() if stamp.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def odom_from_snapshot(state: Optional[Mapping]) -> Optional[OdomSample]:
    """The snapshot's D-494 2 `odom_pose {x, y, yaw, stamp}`; None when absent or malformed.

    `stamp` is UTC epoch seconds (float, same as sighting `captured_at`); a UTC ISO string is
    accepted for robustness."""
    raw = state.get("odom_pose") if isinstance(state, Mapping) else None
    if not isinstance(raw, Mapping):
        return None
    x, y, yaw, stamp = raw.get("x"), raw.get("y"), raw.get("yaw"), raw.get("stamp")
    stamp = float(stamp) if _finite(stamp) else parse_utc(stamp)
    if stamp is None or not _finite(x, y, yaw):
        return None
    epoch = raw.get("epoch")  # D-758 0: anything but a count is no epoch (today's rule)
    return OdomSample(float(x), float(y), float(yaw), stamp,
                      epoch if type(epoch) is int and epoch >= 0 else None)


def sighting_from_row(row: Optional[Mapping]) -> Optional[Sighting]:
    """An accepted sighting row (`SightingService.accept`); None when malformed."""
    if not isinstance(row, Mapping):
        return None
    robot_id, quality, map_id = row.get("robot_id"), row.get("quality"), row.get("map_id")
    values = (row.get("x"), row.get("y"), row.get("yaw"), row.get("captured_at"))
    if (not isinstance(robot_id, str) or not _finite(*values)
            or not (quality is None or _finite(quality)) or not (map_id is None or isinstance(map_id, str))):
        return None
    return Sighting(robot_id, *(float(v) for v in values),
                    quality=None if quality is None else float(quality), map_id=map_id)
