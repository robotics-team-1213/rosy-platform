"""Pinky Pro robot-kind policy, independent of site topology and graph routing."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from core_common.robot_body import NOMINAL_BODY
from fleet.localization.lane_compliance import evaluate_bay_dock
from fleet.routing.cost import wrap
from fleet.routing.graph import Graph


@dataclass(frozen=True)
class RobotKindProfile:
    kind: str = "pinky"
    half_width_m: float = NOMINAL_BODY.half_width_m
    front_x_m: float = NOMINAL_BODY.front_x_m
    rear_x_m: float = abs(NOMINAL_BODY.rear_x_m)
    reverse_dock_speed_mps: float = 0.05
    max_dock_omega_rad_s: float = 0.50
    dock_stop_window_m: float = 0.05
    dock_lat_tol_m: float = 0.025
    dock_rear_tol_m: float = 0.045
    dock_yaw_tol_deg: float = 8.0
    dock_fusion_weight: float = 0.35
    road_lookahead_m: float = 0.28
    road_step_m: float = 0.12
    road_v_max_mps: float = 0.15
    road_w_max_rad_s: float = 1.60
    turn_in_place_rad: float = 0.42
    charge_rise_v: float = 0.08
    charge_rise_window_s: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PINKY_PROFILE = RobotKindProfile()


def get_robot_profile(robot_id_or_kind: str | None = None) -> RobotKindProfile:
    if robot_id_or_kind is None or robot_id_or_kind == "pinky" or robot_id_or_kind.startswith(("rosy_", "pinky_")):
        return PINKY_PROFILE
    return RobotKindProfile(kind=str(robot_id_or_kind))


def evaluate_pinky_dock_step(
    x: float, y: float, yaw: float | None, graph: Graph, *,
    entry_yaw: float | None = None, onboard_lat_m: float | None = None,
    onboard_head_rad: float | None = None, profile: RobotKindProfile = PINKY_PROFILE,
) -> dict[str, Any] | None:
    result = evaluate_bay_dock(x, y, yaw, entry_yaw, graph)
    if result is None:
        return None
    weight = profile.dock_fusion_weight
    fleet_lat = float(result.get("offset_m", 0.0))
    fleet_head = math.radians(float(result.get("yaw_err_deg", 0.0)))
    fused_lat = (1.0 - weight) * fleet_lat + weight * onboard_lat_m if onboard_lat_m is not None else fleet_lat
    fused_head = (1.0 - weight) * fleet_head + weight * onboard_head_rad if onboard_head_rad is not None else fleet_head
    verdict = result["verdict"]
    if verdict == "CONTACT_STOP":
        v_cmd = omega_cmd = 0.0
    elif verdict == "RETRY_FROM_P":
        v_cmd, omega_cmd = profile.reverse_dock_speed_mps, 0.0
    else:
        v_cmd = -profile.reverse_dock_speed_mps
        omega_cmd = max(-profile.max_dock_omega_rad_s,
                        min(profile.max_dock_omega_rad_s, -(8.0 * fused_lat + 0.6 * fused_head)))
    return {
        **result, "robot_kind": profile.kind,
        "fused_offset_m": round(fused_lat, 4),
        "fused_yaw_err_deg": round(math.degrees(fused_head), 2),
        "v_cmd_mps": round(v_cmd, 4), "omega_cmd_rad_s": round(omega_cmd, 4),
    }


def compute_pinky_road_command(
    pose: tuple[float, float, float | None], waypoints: Sequence[Mapping[str, Any]],
    wp_idx: int = 0, *, profile: RobotKindProfile = PINKY_PROFILE,
) -> dict[str, Any]:
    x, y, yaw = pose
    if not waypoints:
        return {"robot_kind": profile.kind, "wp_index": 0, "done": True,
                "v_cmd_mps": 0.0, "omega_cmd_rad_s": 0.0, "next_goal": None}
    idx = min(max(wp_idx, 0), len(waypoints) - 1)
    while idx < len(waypoints) - 1 and math.dist((x, y), (waypoints[idx]["x"], waypoints[idx]["y"])) < 0.065:
        idx += 1
    chosen = waypoints[-1]
    for waypoint in waypoints[idx:]:
        if math.dist((x, y), (waypoint["x"], waypoint["y"])) >= profile.road_lookahead_m:
            chosen = waypoint
            break
    dx, dy = chosen["x"] - x, chosen["y"] - y
    distance = math.hypot(dx, dy)
    done = idx == len(waypoints) - 1 and distance < 0.065
    heading = math.atan2(dy, dx)
    error = wrap(heading - (yaw if yaw is not None else heading))
    if done:
        v, omega = 0.0, 0.0
    elif abs(error) > profile.turn_in_place_rad:
        v, omega = 0.0, max(-profile.road_w_max_rad_s, min(profile.road_w_max_rad_s, error * 2.0))
    else:
        v = min(profile.road_v_max_mps, float(chosen.get("speed_cap_mps", profile.road_v_max_mps)))
        omega = max(-profile.road_w_max_rad_s, min(profile.road_w_max_rad_s, v * 2.0 * math.sin(error) / max(distance, 1e-9)))
    return {"robot_kind": profile.kind, "wp_index": idx, "done": done,
            "v_cmd_mps": round(v, 4), "omega_cmd_rad_s": round(omega, 4),
            "next_goal": {"x": chosen["x"], "y": chosen["y"], "yaw": chosen.get("yaw")}}
