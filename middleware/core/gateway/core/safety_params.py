"""Safety-policy worker parameters from CORE's own sources (D-400 3). ROS-free.

- lidar_yaw_offset: the angle line_follow resolved (core/lidar_mount.py: URDF
  nominal < accepted lidar_mount record < operator overlay). The worker uses
  the base_link<-scan TF while lidar_use_tf is True (its default) and then
  ignores lidar_yaw_offset, so the offset is only in effect when the overlay
  sets lidar_use_tf False; sources says which case applies. Unifying the TF
  with the accepted mount record is D-400 plan 2.
- safety_max_linear / safety_max_angular: the largest CORE speed cap. A lower
  envelope would make every shadow verdict a "limit" and measure nothing.
  Raising the envelope lets fast commands reach the policy, but the worker's
  stop/clear distances do not scale with speed; a shadow "allow" at speed is
  not evidence that enforcing would be safe at that speed.
- control.sensor_adapter.parameters (operator overlay): wins key by key, only
  for the keys below, with the worker's declared types (fail at CORE start,
  not inside the worker). lidar_yaw_offset is set through line_follow only.
- The other measured keys stay the worker's defaults in this plan; their
  calibration-store kinds arrive with enforcement (D-400 plan 3).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

WORKER_DEFAULT_KEYS = ("imu_roll0", "imu_pitch0", "cmd_linear_sign",
                       "cliff_mode", "cliff_raw_max", "cliff_clear_raw")
ENVELOPE_KEYS = ("safety_max_linear", "safety_max_angular")
ENVELOPE_MAX = {"safety_max_linear": 1.0, "safety_max_angular": 3.0}  # worker evidence.py bounds
FLOAT_KEYS = ("imu_roll0", "imu_pitch0", "cmd_linear_sign")
INT_KEYS = ("cliff_raw_max", "cliff_clear_raw")
BOOL_KEYS = ("cliff_enable", "lidar_use_tf")
CLIFF_MODES = ("low", "high")  # hazard.py: 'high' inverts, anything else behaves as 'low'
OVERLAY_KEYS = frozenset((*WORKER_DEFAULT_KEYS, *ENVELOPE_KEYS, *BOOL_KEYS))


@dataclass(frozen=True)
class SafetyParams:
    parameters: dict[str, Any]
    sources: dict[str, str]
    revision: str


def _is_finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _checked(key: str, value: Any) -> Any:
    """Coerce one overlay value to the worker's declared type or raise ValueError."""
    if key in FLOAT_KEYS or key in ENVELOPE_KEYS:
        if not _is_finite_number(value):
            raise ValueError(f"{key} {value!r} must be a finite number")
        return float(value)
    if key in INT_KEYS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} {value!r} must be an int")
        return value
    if key in BOOL_KEYS:
        if not isinstance(value, bool):
            raise ValueError(f"{key} {value!r} must be a bool")
        return value
    if value not in CLIFF_MODES:
        raise ValueError(f"{key} {value!r} must be one of {CLIFF_MODES}")
    return value


def _envelope(key: str, value: float, what: str) -> float:
    if not 0 < value <= ENVELOPE_MAX[key]:
        raise ValueError(f"{what} {value!r} for {key} must be in (0, {ENVELOPE_MAX[key]}]")
    return value


def resolve_safety_params(*, lidar_forward_deg: float, lidar_source: str,
                          caps: Sequence[tuple[float, float]],
                          overlay: Mapping[str, Any]) -> SafetyParams:
    """caps = every CORE speed cap as (linear, angular) (SpeedLimits max/manual/fleet)."""
    if "lidar_yaw_offset" in overlay:
        raise ValueError("set the LiDAR mount through line_follow.lidar_forward_deg, "
                         "not the adapter")
    unknown = sorted(set(overlay) - OVERLAY_KEYS)
    if unknown:
        raise ValueError(f"not a safety policy parameter: {unknown}")
    if (len(caps) == 0 or not all(
            isinstance(pair, tuple) and len(pair) == 2 and all(_is_finite_number(c) for c in pair)
            for pair in caps)):
        raise ValueError(f"caps must be a non-empty sequence of finite (linear, angular) pairs: {caps!r}")
    if not _is_finite_number(lidar_forward_deg):
        raise ValueError(f"lidar_forward_deg must be a finite number: {lidar_forward_deg!r}")
    if not isinstance(lidar_source, str) or not lidar_source:
        raise ValueError(f"lidar_source must be a non-empty str: {lidar_source!r}")

    cap_for = {key: _envelope(key, float(max(pair[i] for pair in caps)), "CORE speed cap")
               for i, key in enumerate(ENVELOPE_KEYS)}
    parameters: dict[str, Any] = {"lidar_yaw_offset": math.radians(lidar_forward_deg), **cap_for}
    sources = {"lidar_yaw_offset": "", **{key: "core speed caps" for key in ENVELOPE_KEYS},
               **{key: "worker default" for key in (*WORKER_DEFAULT_KEYS, "cliff_enable", "lidar_use_tf")}}

    for key, raw in overlay.items():
        value = _checked(key, raw)
        if key in cap_for:
            _envelope(key, value, "overlay value")
            if value < cap_for[key]:
                raise ValueError(
                    f"{key} {value!r} is below the CORE speed cap {cap_for[key]}")
        parameters[key] = value
        sources[key] = "operator overlay"

    use_tf = parameters.get("lidar_use_tf", True)  # worker default True
    sources["lidar_yaw_offset"] = (
        f"unused while lidar_use_tf (TF = URDF nominal); line_follow uses: {lidar_source}"
        if use_tf else f"line_follow: {lidar_source}")
    revision = hashlib.sha256(json.dumps(parameters, sort_keys=True, allow_nan=False)
                              .encode()).hexdigest()[:16]
    return SafetyParams(parameters, sources, revision)
