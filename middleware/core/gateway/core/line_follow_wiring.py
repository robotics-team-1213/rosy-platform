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


#: D-507 9: replaced by line_follow.site_floor_map_id. No alias: a layer that still sets one
#: refuses CORE start, so a site overlay is migrated on purpose, never read silently.
_REMOVED_SITE_KEYS = ("bridge_site_no_dropoffs", "junction_turn_site_accepted")


def _line_follow_config(raw: dict[str, Any]) -> LineFollowConfig:
    """Parse the operator-tunable D-143 policy with validation in one place."""
    removed = [key for key in _REMOVED_SITE_KEYS if key in raw]
    if removed:
        raise ValueError(f"line_follow.{', line_follow.'.join(removed)} was removed (D-507 9); "
                         "declare the walked site floor as line_follow.site_floor_map_id: <map_id>")
    defaults = LineFollowConfig()
    return LineFollowConfig(
        cruise_speed=float(raw.get("cruise_speed", defaults.cruise_speed)),
        max_linear=float(raw.get("max_linear", defaults.max_linear)),
        steering_gain=float(raw.get("steering_gain", defaults.steering_gain)),
        max_angular=float(raw.get("max_angular", defaults.max_angular)),
        min_confidence=float(raw.get("min_confidence", defaults.min_confidence)),
        stale_after_s=float(raw.get("stale_after_s", defaults.stale_after_s)),
        lost_after_s=float(raw.get("lost_after_s", defaults.lost_after_s)),
        lost_auto_resume=_flag(raw, "lost_auto_resume", defaults.lost_auto_resume),
        lost_resume_frames=_whole(raw, "lost_resume_frames", defaults.lost_resume_frames),
        lost_resume_s=float(raw.get("lost_resume_s", defaults.lost_resume_s)),
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
        ir_guard_min_linear=float(raw.get("ir_guard_min_linear", defaults.ir_guard_min_linear)),
        ir_row_x_m=_optional_float(raw.get("ir_row_x_m")),
        crosswalk_zone_max_m=float(raw.get("crosswalk_zone_max_m", defaults.crosswalk_zone_max_m)),
        crosswalk_odom_error_fraction=float(raw.get(
            "crosswalk_odom_error_fraction", defaults.crosswalk_odom_error_fraction)),
        crosswalk_range_error_fraction=float(raw.get(
            "crosswalk_range_error_fraction", defaults.crosswalk_range_error_fraction)),
        crosswalk_gate_enabled=_flag(raw, "crosswalk_gate_enabled", defaults.crosswalk_gate_enabled),
        crosswalk_look_s=float(raw.get("crosswalk_look_s", defaults.crosswalk_look_s)),
        crosswalk_look_min_scans=_whole(raw, "crosswalk_look_min_scans", defaults.crosswalk_look_min_scans),
        crosswalk_report_s=float(raw.get("crosswalk_report_s", defaults.crosswalk_report_s)),
        crosswalk_cross_speed=float(raw.get("crosswalk_cross_speed", defaults.crosswalk_cross_speed)),
        crosswalk_approach_default_m=float(raw.get(
            "crosswalk_approach_default_m", defaults.crosswalk_approach_default_m)),
        crosswalk_range_sigma_m=float(raw.get("crosswalk_range_sigma_m", defaults.crosswalk_range_sigma_m)),
        crosswalk_persist_k=_whole(raw, "crosswalk_persist_k", defaults.crosswalk_persist_k),
        crosswalk_persist_n=_whole(raw, "crosswalk_persist_n", defaults.crosswalk_persist_n),
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
        obstacle_blind_floor=_flag(raw, "obstacle_blind_floor", defaults.obstacle_blind_floor),
        bridge_enabled=_flag(raw, "bridge_enabled", defaults.bridge_enabled),
        bridge_lookahead_m=float(raw.get("bridge_lookahead_m", defaults.bridge_lookahead_m)),
        bridge_coast_m=float(raw.get("bridge_coast_m", defaults.bridge_coast_m)),
        bridge_slow_m=float(raw.get("bridge_slow_m", defaults.bridge_slow_m)),
        bridge_slow_scale=float(raw.get("bridge_slow_scale", defaults.bridge_slow_scale)),
        bridge_distance_scale=float(raw.get(
            "bridge_distance_scale", defaults.bridge_distance_scale)),
        bridge_time_margin_s=float(raw.get(
            "bridge_time_margin_s", defaults.bridge_time_margin_s)),
        bridge_arm_confidence=float(raw.get(
            "bridge_arm_confidence", defaults.bridge_arm_confidence)),
        bridge_arm_frames=_whole(raw, "bridge_arm_frames", defaults.bridge_arm_frames),
        bridge_arm_max_error=float(raw.get("bridge_arm_max_error", defaults.bridge_arm_max_error)),
        bridge_arm_max_angular=float(raw.get(
            "bridge_arm_max_angular", defaults.bridge_arm_max_angular)),
        junction_reacquire_frames=_whole(raw, "junction_reacquire_frames",
                                         defaults.junction_reacquire_frames),
        junction_turn_lead_s=float(raw.get("junction_turn_lead_s", defaults.junction_turn_lead_s)),
        junction_still_linear=float(raw.get("junction_still_linear", defaults.junction_still_linear)),
        junction_still_angular=float(raw.get("junction_still_angular", defaults.junction_still_angular)),
        site_floor_map_id=raw.get("site_floor_map_id", defaults.site_floor_map_id),
        arc_enabled=_flag(raw, "arc_enabled", defaults.arc_enabled),
        route_context_enabled=_flag(raw, "route_context_enabled", defaults.route_context_enabled),
        arc_curvature_gain=float(raw.get("arc_curvature_gain", defaults.arc_curvature_gain)),
        arc_blind_max_m=float(raw.get("arc_blind_max_m", defaults.arc_blind_max_m)),
        authority_required=_flag(raw, "authority_required", defaults.authority_required),
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


def check_bridge_floor_basis(config: LineFollowConfig, sensor_mode: str) -> None:
    """D-476 rev 1, at CORE start: an enabled bridge needs the live floor proof (effective
    control.sensor_adapter mode enforce) or the site floor declaration site_floor_map_id (D-507 9)."""
    if config.bridge_enabled and config.site_floor_map_id is None and sensor_mode != "enforce":
        raise ValueError("line_follow.bridge_enabled needs control.sensor_adapter mode enforce "
                         "or line_follow.site_floor_map_id: <map_id> (site floor declaration, D-507)")


def bind_lane_return_motion(line_follow, sensor_adapter, policy_clock=None) -> None:
    """D-468: recheck live floor policy and measured body sweep for every candidate.

    `now` is the line clock. policy_clock: the worker policy's own clock when the line
    clock differs (use_sim_time: sim seconds vs the monotonic policy window, the clock
    SafetyManager also asks it on). None = the line clock is that clock (Device).
    The worker floor proof exists only in enforce (D-400 plan 3); D-476 asks whether it is
    live so a bridge needs it then and rests on its own basis otherwise. D-468 always needs it.
    """
    def allowed(now, linear, angular) -> bool:
        try:
            sensor_now = now if policy_clock is None else policy_clock()
            return (sensor_adapter.return_sensor_allowed(sensor_now, linear, angular) is True
                    and line_follow.return_body_clear(now, linear, angular) is True)
        except Exception:  # noqa: BLE001 - missing runtime evidence denies motion
            return False

    line_follow.bind_return_motion(
        allowed, floor_proof_live=lambda: sensor_adapter.config.mode == "enforce",
        proof_configured=lambda: sensor_adapter.return_proof_configured() is True)
