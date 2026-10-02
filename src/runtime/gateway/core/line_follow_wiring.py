"""CORE line-follow config parsing and D-407 stuck-recovery wiring (split out of services.py, P6)."""
from __future__ import annotations

from typing import Any, Optional

from core_features.line_follow import LineFollowConfig
from core_features.line_follow.clearance import self_mask_from_config


def _optional_float(value) -> Optional[float]:
    return None if value is None else float(value)


def _line_follow_config(raw: dict[str, Any]) -> LineFollowConfig:
    """Parse the operator-tunable D-143 policy with validation in one place."""
    defaults = LineFollowConfig()
    return LineFollowConfig(
        cruise_speed=float(raw.get("cruise_speed", defaults.cruise_speed)),
        max_linear=float(raw.get("max_linear", defaults.max_linear)),
        steering_gain=float(raw.get("steering_gain", defaults.steering_gain)),
        max_angular=float(raw.get("max_angular", defaults.max_angular)),
        min_confidence=float(raw.get("min_confidence", defaults.min_confidence)),
        stale_after_s=float(raw.get("stale_after_s", defaults.stale_after_s)),
        lost_after_s=float(raw.get("lost_after_s", defaults.lost_after_s)),
        ir_calibration_revision=raw.get("ir_calibration_revision") or None,
        obstacle_stop_m=float(raw.get("obstacle_stop_m", defaults.obstacle_stop_m)),
        obstacle_resume_m=float(raw.get("obstacle_resume_m", defaults.obstacle_resume_m)),
        obstacle_half_angle_deg=float(raw.get("obstacle_half_angle_deg", defaults.obstacle_half_angle_deg)),
        lidar_forward_deg=float(raw.get("lidar_forward_deg", defaults.lidar_forward_deg)),
        clearance_stale_s=float(raw.get("clearance_stale_s", defaults.clearance_stale_s)),
        obstacle_mode=str(raw.get("obstacle_mode", defaults.obstacle_mode)),
        obstacle_corridor_half_width_m=float(raw.get(
            "obstacle_corridor_half_width_m", defaults.obstacle_corridor_half_width_m)),
        obstacle_path_horizon_m=float(raw.get(
            "obstacle_path_horizon_m", defaults.obstacle_path_horizon_m)),
        lidar_self_mask=self_mask_from_config(raw.get("lidar_self_mask")),
        obstacle_release_s=float(raw.get("obstacle_release_s", defaults.obstacle_release_s)),
        obstacle_escalate_s=float(raw.get("obstacle_escalate_s", defaults.obstacle_escalate_s)),
        max_angular_follows_manual=raw.get(
            "max_angular_follows_manual", defaults.max_angular_follows_manual),
        lane_auto_min_manual_angular=float(raw.get(
            "lane_auto_min_manual_angular", defaults.lane_auto_min_manual_angular)),
        ir_guard_enabled=raw.get("ir_guard_enabled", defaults.ir_guard_enabled),
        ir_guard_edge_error=float(raw.get("ir_guard_edge_error", defaults.ir_guard_edge_error)),
        ir_guard_turn=float(raw.get("ir_guard_turn", defaults.ir_guard_turn)),
        ir_guard_speed_scale=float(raw.get("ir_guard_speed_scale", defaults.ir_guard_speed_scale)),
        recovery_local_enabled=raw.get("recovery_local_enabled", defaults.recovery_local_enabled),
        recovery_ask_s=float(raw.get("recovery_ask_s", defaults.recovery_ask_s)),
        recovery_back_m=float(raw.get("recovery_back_m", defaults.recovery_back_m)),
        recovery_back_speed=float(raw.get("recovery_back_speed", defaults.recovery_back_speed)),
        recovery_rear_clear_m=float(raw.get("recovery_rear_clear_m", defaults.recovery_rear_clear_m)),
        recovery_max_attempts=raw.get("recovery_max_attempts", defaults.recovery_max_attempts),
        recovery_settle_s=float(raw.get("recovery_settle_s", defaults.recovery_settle_s)),
        recovery_trail_s=float(raw.get("recovery_trail_s", defaults.recovery_trail_s)),
        recovery_trail_yaw_deg=float(raw.get("recovery_trail_yaw_deg", defaults.recovery_trail_yaw_deg)),
        body_lidar_x_m=_optional_float(raw.get("body_lidar_x_m")),
        body_rear_x_m=_optional_float(raw.get("body_rear_x_m")),
        body_rotation_radius_m=_optional_float(raw.get("body_rotation_radius_m")),
    )


def bind_stuck_recovery(line_follow, *, safety, calibration, fleet_agent, vision) -> None:
    """D-407 inputs: console link (FleetAgent), calibration lease, D-342 linear limit, preview seq."""
    line_follow.bind_recovery(
        console_linked=lambda: bool(fleet_agent.connected),
        calibration_active=lambda: calibration.current() is not None,
        linear_ceiling=lambda: float(safety.limits.manual_linear),
        preview_seq=lambda: vision.status().get("sequence"),
    )
