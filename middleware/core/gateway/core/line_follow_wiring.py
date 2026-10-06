"""CORE line-follow config parsing and D-407 stuck-recovery wiring (split out of services.py, P6)."""
from __future__ import annotations

from typing import Any, Optional

from core_features.line_follow import LineFollowConfig
from core_features.line_follow.clearance import self_mask_from_config
from core_features.traffic_policy import TrafficPolicyMode
from core_features.traffic_policy.manager import APPROACH_MIN_SCALE


def _optional_float(value) -> Optional[float]:
    return None if value is None else float(value)


def _flag(raw: dict, key: str, default: bool) -> bool:
    """A YAML boolean only: a quoted "true" or a 1 is an operator typo, not a yes."""
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"line_follow.{key} must be true or false (unquoted YAML boolean), "
                         f"got {value!r}")
    return value


def _whole(raw: dict, key: str, default: int) -> int:
    """A whole number; an integral float from an overlay (2.0) is accepted as 2."""
    value = raw.get(key, default)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"line_follow.{key} must be a whole number, got {value!r}")
    return value


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
        # D-422: unset = derived (path + URDF body) or the pre-D-422 LiDAR-origin defaults.
        obstacle_stop_m=_optional_float(raw.get("obstacle_stop_m")),
        obstacle_resume_m=_optional_float(raw.get("obstacle_resume_m")),
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
        recovery_local_enabled=_flag(raw, "recovery_local_enabled", defaults.recovery_local_enabled),
        recovery_ask_s=float(raw.get("recovery_ask_s", defaults.recovery_ask_s)),
        recovery_back_m=float(raw.get("recovery_back_m", defaults.recovery_back_m)),
        recovery_back_speed=float(raw.get("recovery_back_speed", defaults.recovery_back_speed)),
        recovery_rear_clear_m=float(raw.get("recovery_rear_clear_m", defaults.recovery_rear_clear_m)),
        recovery_max_attempts=_whole(raw, "recovery_max_attempts", defaults.recovery_max_attempts),
        recovery_settle_s=float(raw.get("recovery_settle_s", defaults.recovery_settle_s)),
        recovery_trail_s=float(raw.get("recovery_trail_s", defaults.recovery_trail_s)),
        recovery_trail_yaw_deg=float(raw.get("recovery_trail_yaw_deg", defaults.recovery_trail_yaw_deg)),
        recovery_trail_max_age_s=float(raw.get(
            "recovery_trail_max_age_s", defaults.recovery_trail_max_age_s)),
        recovery_console_grace_s=float(raw.get(
            "recovery_console_grace_s", defaults.recovery_console_grace_s)),
        recovery_restuck_s=float(raw.get("recovery_restuck_s", defaults.recovery_restuck_s)),
        recovery_restuck_m=float(raw.get("recovery_restuck_m", defaults.recovery_restuck_m)),
        recovery_rear_lateral_margin_m=float(raw.get(
            "recovery_rear_lateral_margin_m", defaults.recovery_rear_lateral_margin_m)),
        body_lidar_x_m=_optional_float(raw.get("body_lidar_x_m")),
        body_rear_x_m=_optional_float(raw.get("body_rear_x_m")),
        body_rotation_radius_m=_optional_float(raw.get("body_rotation_radius_m")),
        body_half_width_m=_optional_float(raw.get("body_half_width_m")),
        body_front_x_m=_optional_float(raw.get("body_front_x_m")),
        body_ultrasonic_x_m=_optional_float(raw.get("body_ultrasonic_x_m")),
        obstacle_body_margin_m=float(raw.get("obstacle_body_margin_m", defaults.obstacle_body_margin_m)),
        obstacle_latency_s=float(raw.get("obstacle_latency_s", defaults.obstacle_latency_s)),
        obstacle_decel_mps2=float(raw.get("obstacle_decel_mps2", defaults.obstacle_decel_mps2)),
        obstacle_resume_hysteresis_m=float(raw.get(
            "obstacle_resume_hysteresis_m", defaults.obstacle_resume_hysteresis_m)),
        obstacle_ultrasonic_half_angle_deg=float(raw.get(
            "obstacle_ultrasonic_half_angle_deg", defaults.obstacle_ultrasonic_half_angle_deg)),
        obstacle_ultrasonic_stale_s=float(raw.get(
            "obstacle_ultrasonic_stale_s", defaults.obstacle_ultrasonic_stale_s)),
        bridge_enabled=_flag(raw, "bridge_enabled", defaults.bridge_enabled),
        bridge_lookahead_m=float(raw.get("bridge_lookahead_m", defaults.bridge_lookahead_m)),
        bridge_coast_m=float(raw.get("bridge_coast_m", defaults.bridge_coast_m)),
        bridge_slow_m=float(raw.get("bridge_slow_m", defaults.bridge_slow_m)),
        bridge_slow_scale=float(raw.get("bridge_slow_scale", defaults.bridge_slow_scale)),
        bridge_distance_scale=float(raw.get(
            "bridge_distance_scale", defaults.bridge_distance_scale)),
        bridge_time_margin_s=float(raw.get(
            "bridge_time_margin_s", defaults.bridge_time_margin_s)),
        lane_return_body_margin_m=float(raw.get(
            "lane_return_body_margin_m", defaults.lane_return_body_margin_m)),
        lane_return_checkpoint_fraction=float(raw.get(
            "lane_return_checkpoint_fraction", defaults.lane_return_checkpoint_fraction)),
    )


def bind_motion_envelope(line_follow, *, safety, traffic_policy) -> None:
    """D-422 review M1: what the lane twist can still become downstream. The nav safety clip
    limits each axis; an ENFORCED traffic gate scales linear (APPROACH down to
    APPROACH_MIN_SCALE, PROCEED by proceed_speed_scale) but not angular."""
    def envelope() -> tuple[float, float, float]:
        floor = 1.0
        if traffic_policy.mode is TrafficPolicyMode.ENFORCED:
            proceed = float(traffic_policy.configuration()["active"]["proceed_speed_scale"])
            floor = min(APPROACH_MIN_SCALE, proceed)
        return float(safety.limits.max_linear), float(safety.limits.max_angular), floor

    line_follow.bind_motion_envelope(envelope)


def bind_stuck_recovery(line_follow, *, safety, calibration, fleet_agent, vision) -> None:
    """D-407 inputs: console link (FleetAgent), calibration lease, D-342 linear limit, preview seq."""
    line_follow.bind_recovery(
        # A brief agent reconnect does not read as "no console" mid-ASKING (D-407 2026-10-02),
        # nor does a hub heard within the D-419 link freshness (heartbeat + reply deadline).
        console_linked=lambda: (fleet_agent.linked_within(line_follow.config.recovery_console_grace_s)
                                or fleet_agent.recently_heard()),
        calibration_active=lambda: calibration.current() is not None,
        linear_ceiling=lambda: float(safety.limits.manual_linear),
        preview_seq=lambda: vision.status().get("sequence"),
    )


def bind_lane_return_motion(line_follow, sensor_adapter, policy_clock=None) -> None:
    """D-468: recheck live floor policy and measured body sweep for every candidate.

    `now` is the line clock. policy_clock: the worker policy's own clock when the line
    clock differs (use_sim_time: sim seconds vs the monotonic policy window, the clock
    SafetyManager also asks it on). None = the line clock is that clock (Device).
    """
    def allowed(now, linear, angular) -> bool:
        try:
            sensor_now = now if policy_clock is None else policy_clock()
            return (sensor_adapter.return_sensor_allowed(sensor_now, linear, angular) is True
                    and line_follow.return_body_clear(now, linear, angular) is True)
        except Exception:  # noqa: BLE001 - missing runtime evidence denies motion
            return False

    line_follow.bind_return_motion(allowed)
