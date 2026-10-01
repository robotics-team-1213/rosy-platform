"""Safety-policy worker parameters from CORE's own sources (D-400 3). ROS-free.

- lidar_yaw_offset: the angle line_follow already resolved (core/lidar_mount.py:
  URDF nominal < accepted lidar_mount record < operator overlay), so lane
  following and the safety policy see one LiDAR mount.
- safety_max_linear / safety_max_angular: the largest CORE speed cap. A lower
  envelope would make every shadow verdict a "limit" and measure nothing.
- control.sensor_adapter.parameters (operator overlay): wins key by key, only
  for the keys below. lidar_yaw_offset is set through line_follow, never here.
- The other measured keys stay the worker's defaults in this plan; their
  calibration-store kinds arrive with enforcement (D-400 plan 3).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

WORKER_DEFAULT_KEYS = ("imu_roll0", "imu_pitch0", "cmd_linear_sign",
                       "cliff_mode", "cliff_raw_max", "cliff_clear_raw")
ENVELOPE_KEYS = ("safety_max_linear", "safety_max_angular")
OVERLAY_KEYS = frozenset((*WORKER_DEFAULT_KEYS, *ENVELOPE_KEYS, "cliff_enable"))


@dataclass(frozen=True)
class SafetyParams:
    parameters: dict[str, Any]
    sources: dict[str, str]
    revision: str


def _is_finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def resolve_safety_params(*, lidar_forward_deg: float, lidar_source: str,
                          caps: tuple[float, ...], overlay: Mapping[str, Any]) -> SafetyParams:
    """caps = every CORE speed cap as (linear, angular) pairs (SpeedLimits max/manual/fleet)."""
    if "lidar_yaw_offset" in overlay:
        raise ValueError("set the LiDAR mount through line_follow.lidar_forward_deg, "
                         "not the adapter")
    unknown = sorted(set(overlay) - OVERLAY_KEYS)
    if unknown:
        raise ValueError(f"not a safety policy parameter: {unknown}")
    if len(caps) == 0 or len(caps) % 2 or not all(_is_finite_number(c) for c in caps):
        raise ValueError(f"caps must be a non-empty even-length sequence of finite numbers: {caps!r}")
    if not _is_finite_number(lidar_forward_deg):
        raise ValueError(f"lidar_forward_deg must be a finite number: {lidar_forward_deg!r}")

    cap_for = {"safety_max_linear": max(caps[0::2]), "safety_max_angular": max(caps[1::2])}
    parameters: dict[str, Any] = {
        "lidar_yaw_offset": math.radians(lidar_forward_deg), **cap_for}
    sources = {"lidar_yaw_offset": "line_follow: " + lidar_source,
               **{key: "core speed caps" for key in ENVELOPE_KEYS},
               **{key: "worker default" for key in WORKER_DEFAULT_KEYS}}

    for key, value in overlay.items():
        if key in cap_for:
            if not _is_finite_number(value):
                raise ValueError(f"{key} {value!r} must be a finite number")
            if value < cap_for[key]:
                raise ValueError(
                    f"{key} {value!r} is below the CORE speed cap {cap_for[key]}")
        parameters[key] = value
        sources[key] = "operator overlay"

    body = json.dumps({"parameters": parameters, "sources": sources},
                      sort_keys=True, default=repr)
    return SafetyParams(parameters, sources, hashlib.sha256(body.encode()).hexdigest()[:16])
