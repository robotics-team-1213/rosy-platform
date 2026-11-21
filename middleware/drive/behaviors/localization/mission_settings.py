"""Localization mission defaults and configuration validation."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class MissionConfig:
    rotate_angular: float = 0.3          # rad/s; one turn takes about 21 s
    rotate_max_rad: float = 2.0 * math.pi
    nudge_linear: float = 0.03           # m/s
    nudge_max_m: float = 0.10
    lane_linear: float = 0.04            # m/s, half the line-follow cruise
    # Without the URDF body (line_follow.body_* unset) the LiDAR-origin rules below apply.
    min_front_clearance_m: float = 0.25
    front_half_angle_deg: float = 20.0
    min_front_beams: int = 5              # valid beams the nudge sector needs
    max_blind_share: float = 0.3          # inf/NaN/below-range share that blocks a nudge
    rotate_clearance_m: float = 0.20      # nothing this close anywhere before a turn
    # D-424 with the body: rotation radius + this (the D-422 body margin); shortest nudge.
    # D-424 review H1, until device evidence: start a turn with rho + 0.03, end it at rho + 0.01.
    rotate_margin_m: float = 0.03
    rotate_stop_margin_m: float = 0.01
    # D-424 follow-up: a running turn ends on an evidence gap only after this many consecutive
    # 20 Hz ticks = 4 scans at 10 Hz (a near return still ends it at once). 43,625 real C1
    # scans (8kcn, 9dfk): longest gap run 3 scans; 4 scans -> 0 false ends observed (3 -> ~0.5 %
    # of 21 s turns). See the D-424 ADR.
    rotate_coverage_debounce_ticks: int = 8
    nudge_min_m: float = 0.02
    # D-603 rotate_to: rad/s per rad of error, the wheels' deadband floor, and how far past the asked
    # turn (odom, summed both ways) the turn may go before it aborts ("overturn").
    rotate_to_gain: float = 1.5
    rotate_to_min_angular: float = 0.15
    rotate_to_overturn_deg: float = 30.0
    stop_line_m: float = 0.12            # the traffic policy's stop distance
    max_time_s: float = 120.0
    max_distance_m: float = 1.0
    sensor_stale_s: float = 0.5


def mission_config(raw: Optional[Mapping[str, Any]]) -> MissionConfig:
    """`localization_mission:` from the CORE config; absent or empty = the defaults (D-424).
    Unknown keys are an error, not silently ignored."""
    if not raw:
        return MissionConfig()
    if not isinstance(raw, Mapping):
        raise ValueError("localization_mission must be a mapping")
    known = {f.name: f.type for f in fields(MissionConfig)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ValueError(f"unknown localization_mission keys: {unknown}")
    values = {k: (int(v) if known[k] in (int, "int") else float(v)) for k, v in raw.items()}
    config = MissionConfig(**values)
    if not all(math.isfinite(float(getattr(config, f.name))) for f in fields(config)):
        raise ValueError("localization_mission values must be finite")
    if (min(config.rotate_margin_m, config.rotate_stop_margin_m, config.nudge_min_m) < 0.0
            or config.rotate_stop_margin_m > config.rotate_margin_m or config.nudge_linear <= 0.0
            or config.rotate_coverage_debounce_ticks < 1
            or min(config.rotate_to_gain, config.rotate_to_min_angular, config.rotate_to_overturn_deg) <= 0.0):
        raise ValueError("localization_mission margins must be >= 0, nudge_linear and rotate_to_* > 0")
    return config
