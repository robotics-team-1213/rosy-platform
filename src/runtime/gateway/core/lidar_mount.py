"""One source for the LiDAR mount yaw that CORE line_follow uses (D-47 addendum 2026-10-01).

Resolution order, first hit wins:
  1. the calibration store's current accepted ``lidar_mount`` record
     (core_common/calibration_store.py; accepted by an operator, never automatic);
  2. ``lidar_yaw_offset`` bound through the control sensor adapter (D-47:
     required calibration snapshot or explicit sensor parameters);
  3. the hand value ``line_follow.lidar_forward_deg`` (fallback only).

The caller logs the returned source line so the log says which value drives
the obstacle sector/path. ROS-free.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from core_common.calibration_store import CalibrationStore, default_robot


def resolve_lidar_forward_deg(line_follow: Mapping[str, Any], *, hand_default: float,
                              adapter_parameters: Optional[Mapping[str, Any]] = None,
                              store: Optional[CalibrationStore] = None,
                              robot: Optional[str] = None) -> tuple[float, str]:
    """(forward angle in the scan frame, degrees in [0, 360), source line)."""
    try:
        record = (store or CalibrationStore()).current(robot or default_robot(), "lidar_mount")
    except (OSError, ValueError):
        record = None
    if record is not None:
        value = float(record["values"]["lidar_yaw_offset"])
        return (math.degrees(value) % 360.0,
                f"calibration record {record['id']} sha256 {record['sha256'][:12]}")
    bound = (adapter_parameters or {}).get("lidar_yaw_offset")
    if isinstance(bound, (int, float)) and not isinstance(bound, bool) and math.isfinite(bound):
        return math.degrees(float(bound)) % 360.0, "control sensor adapter lidar_yaw_offset (D-47 binding)"
    hand = float(line_follow.get("lidar_forward_deg", hand_default))
    return hand, "line_follow lidar_forward_deg (hand value; no calibrated mount)"
