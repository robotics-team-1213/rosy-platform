"""D-986: the pure floor-motion check of an approval trial (a scan must move with the odometry) and its refusal.

Moved out of core_features/command/approval_trials.py to keep that package under its D-766 unit limit (D-1005).
"""
from __future__ import annotations

import math
import statistics

from core_common.robot_body import inside_body

# Floor trials: spinning wheels move odometry but not the scan (b8xy, 2026-11-07: odom -3.11 m, clearances unchanged).
# Per-beam noise is 0.6-3.4 mm standing still (D-573). The sector median's spread on real moving C1 scans is about
# 3 mm (1.25 * 0.020 m / sqrt(72)), so the 10 mm tolerance leaves about three times the noise.
MIN_LINEAR_CHECK_M = 0.02
LINEAR_TOLERANCE_M = 0.01
LINEAR_SECTOR_RAD = math.radians(20)
SCAN_RANGE_CAP_M = 4.0
BEAM_JUMP_M = 0.2  # a beam that jumps this far changed target: no use as a distance difference
MIN_PAIRED_BEAMS = 20
# Shifting a real scan onto itself lands exactly; real neighbouring scans differ by up to 2 beams (0.0175 rad).
MIN_TURN_CHECK_RAD = 0.06
TURN_TOLERANCE_RAD = 0.035
TURN_SEARCH_BEAMS = 60
MIN_TURN_BEAMS = 100
RELATIVE_TOLERANCE = 0.5


class TrialRefused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _scan_outside(sample, config) -> list:
    """(robot-frame angle, distance) per beam, None where the beam sees no return or the robot itself."""
    start = float(sample["angle_min"])
    ranges = sample["ranges"]
    step = (float(sample["angle_max"]) - start) / (len(ranges) - 1)
    forward = math.radians(float(config.lidar_forward_deg))
    low = float(sample["range_min"])
    beams = []
    for index, value in enumerate(ranges):
        angle = start + index * step - forward
        angle = math.atan2(math.sin(angle), math.cos(angle))
        distance = float(value)
        beams.append((angle, distance) if math.isfinite(distance) and distance >= low and not inside_body(
            distance * math.cos(angle) + config.body_lidar_x_m, distance * math.sin(angle), config.body_front_x_m,
            config.body_rear_x_m, config.body_half_width_m, config.body_rotation_radius_m, strict=True) else None)
    return beams


def _scan_travel_m(first, last) -> float:
    """Signed travel along the body axis: what lies ahead comes closer, what lies behind goes away."""
    changes = []
    for before, after in zip(first, last):
        if before is None or after is None or max(before[1], after[1]) > SCAN_RANGE_CAP_M \
                or abs(before[1] - after[1]) > BEAM_JUMP_M:
            continue
        if abs(before[0]) <= LINEAR_SECTOR_RAD:
            changes.append(before[1] - after[1])
        elif math.pi - abs(before[0]) <= LINEAR_SECTOR_RAD:
            changes.append(after[1] - before[1])
    if len(changes) < MIN_PAIRED_BEAMS:
        raise TrialRefused("SCAN_UNUSABLE", "too few LiDAR beams ahead or behind to check the travel")
    return statistics.median(changes)


def _scan_turn_rad(first, last, step: float) -> float:
    """Signed turn: the shift that best lays the second scan over the first. Scene turning left moves beams right."""
    count = len(first)
    best = None
    for shift in sorted(range(-TURN_SEARCH_BEAMS, TURN_SEARCH_BEAMS + 1), key=abs):
        differences = [abs(before[1] - after[1]) for before, after in
                       ((first[index], last[(index + shift) % count]) for index in range(count))
                       if before is not None and after is not None]
        if len(differences) < MIN_TURN_BEAMS:
            continue
        score = statistics.median(differences)
        if best is None or score < best[0]:
            best = (score, shift)
    if best is None:
        raise TrialRefused("SCAN_UNUSABLE", "too few LiDAR beams to check the turn")
    return -best[1] * step


def check_floor_motion(start, end, config, direction: str, odom: float) -> dict:
    """Raises unless the room moved as odometry says. odom: signed metres along the axis, or radians for a turn."""
    linear = direction in ("forward", "reverse")
    if abs(odom) < (MIN_LINEAR_CHECK_M if linear else MIN_TURN_CHECK_RAD):
        raise TrialRefused("TRIAL_TOO_SHORT", "hold the button longer: too little motion to check against the LiDAR")
    try:
        if len(start["ranges"]) != len(end["ranges"]) or start["angle_min"] != end["angle_min"]:
            raise TrialRefused("SCAN_UNUSABLE", "the two LiDAR scans do not line up")
        first, last = _scan_outside(start, config), _scan_outside(end, config)
        step = (float(end["angle_max"]) - float(end["angle_min"])) / (len(end["ranges"]) - 1)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise TrialRefused("SCAN_UNUSABLE", f"the LiDAR scan is unreadable: {exc}") from exc
    seen = _scan_travel_m(first, last) if linear else _scan_turn_rad(first, last, step)
    tolerance = max(LINEAR_TOLERANCE_M if linear else TURN_TOLERANCE_RAD, RELATIVE_TOLERANCE * abs(odom))
    if abs(seen - odom) > tolerance:
        raise TrialRefused("WHEELS_NOT_MOVING_BODY",
                           f"odometry says {odom:+.3f} but the LiDAR saw {seen:+.3f}: the wheels may be slipping")
    return {"odom": round(odom, 4), "scan": round(seen, 4), "tolerance": round(tolerance, 4),
            "unit": "m" if linear else "rad"}
