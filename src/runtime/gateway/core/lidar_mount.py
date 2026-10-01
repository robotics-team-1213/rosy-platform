"""One source for the LiDAR mount yaw that CORE line_follow uses (D-47 addendum 2026-10-01).

Resolution order, first hit wins (D-397: URDF nominal < accepted record < operator overlay):
  1. the operator's local overlay ``line_follow.lidar_forward_deg``
     (~/.rosy/rosy.yaml or ROSY_CONFIG), passed in as ``operator_deg``;
  2. the calibration store's current accepted ``lidar_mount`` record
     (core_common/calibration_store.py; accepted by an operator, never
     automatic), when its value is a finite real inside 150-210 deg or within
     15 deg of the hand value (check_values); otherwise it is logged and skipped;
  3. the hand value ``line_follow.lidar_forward_deg``: the robot
     package's core.yaml, which is the URDF nominal 180 deg (geometry.yaml).

Since D-400 the resolved angle is fed into the safety worker (core/safety_params.py), so
production no longer passes ``adapter_parameters``; the comparison with a bound
``lidar_yaw_offset`` (D-47) is kept for tests and legacy callers. A disagreement above
3 deg is reported in the source line and sets the warn flag, which the caller uses for
the log level. ROS-free.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from core_common.calibration_store import CalibrationStore, check_values, default_robot

DISAGREE_DEG = 3.0


def _angle_gap(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def resolve_lidar_forward_deg(line_follow: Mapping[str, Any], *, hand_default: float,
                              adapter_parameters: Optional[Mapping[str, Any]] = None,
                              store: Optional[CalibrationStore] = None,
                              robot: Optional[str] = None,
                              operator_deg: Any = None) -> tuple[float, str, bool]:
    """(forward angle in the scan frame in degrees, source line to log, warn).

    warn is True when something needs an operator's attention: an unreadable
    store, a skipped accepted record, a refused operator value, or an adapter
    disagreement. The operator overlay must pass the same plausibility window
    as a record (150-210 deg); otherwise it is refused, warned, and the record /
    hand value stands."""
    deg, source, warn = _record_or_hand(line_follow, hand_default=hand_default,
                                        adapter_parameters=adapter_parameters, store=store, robot=robot)
    if operator_deg is None:
        return deg, source, warn
    why = None
    if isinstance(operator_deg, (int, float)) and not isinstance(operator_deg, bool) and math.isfinite(operator_deg):
        why = check_values("lidar_mount", {"lidar_yaw_offset": math.radians(float(operator_deg))})
    else:
        why = f"not a finite number: {operator_deg!r}"
    if why:
        return deg, f"{source}; WARNING operator overlay lidar_forward_deg refused: {why}", True
    chosen = float(operator_deg) % 360.0
    notes = _adapter_notes(adapter_parameters, chosen, "the operator value")
    source = f"operator overlay line_follow.lidar_forward_deg (over: {source})"
    return chosen, source + ("; " + "; ".join(notes) if notes else ""), bool(notes)


def _adapter_notes(adapter_parameters, deg, what):
    bound = (adapter_parameters or {}).get("lidar_yaw_offset")
    if isinstance(bound, (int, float)) and not isinstance(bound, bool) and math.isfinite(bound):
        gap = _angle_gap(math.degrees(bound) % 360.0, deg)
        if gap > DISAGREE_DEG:
            return [f"WARNING adapter lidar_yaw_offset {math.degrees(bound) % 360.0:.1f} deg disagrees "
                    f"with {what} by {gap:.1f} deg; accept a measured lidar_mount record"]
    return []


def _record_or_hand(line_follow, *, hand_default, adapter_parameters, store, robot):
    hand = float(line_follow.get("lidar_forward_deg", hand_default))
    notes = []
    try:
        record = (store or CalibrationStore()).current(robot or default_robot(), "lidar_mount")
    except Exception as exc:  # noqa: BLE001 - CORE must start on the hand value
        record, notes = None, [f"calibration store unreadable: {exc}"]
    if record is not None:
        try:
            why = check_values("lidar_mount", record["values"], nominal={"lidar_forward_deg": hand})
            if why is None:
                deg = math.degrees(float(record["values"]["lidar_yaw_offset"])) % 360.0
                return deg, f"calibration record {record['id']} sha256 {record['sha256'][:12]}", False
        except (KeyError, TypeError, ValueError) as exc:
            why = f"malformed record: {exc}"
        notes.append(f"accepted lidar_mount record {record.get('id')} skipped: {why}")
    notes += _adapter_notes(adapter_parameters, hand, "the hand value")
    source = "line_follow lidar_forward_deg (hand value; no accepted mount)"
    return hand, source + ("; " + "; ".join(notes) if notes else ""), bool(notes)
