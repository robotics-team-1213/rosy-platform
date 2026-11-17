from __future__ import annotations

from typing import Any, Mapping, Sequence

from fleet.charge_bays import Bay, ChargeBays, RobotView
from fleet.routing.graph import Graph
from fleet.routing.road_path import arbitrate_corridor_departure, plan_road_path
from fleet.routing.snap import PlanError
from fleet.site_map import SiteMap
from fleet.site_rules import SiteRules
from fleet.pipeline.pinky_policy import (
    RobotKindProfile, compute_pinky_road_command, evaluate_pinky_dock_step,
    get_robot_profile,
)
from fleet.pipeline.site_policy import SiteZonePolicy, plan_site_road_trip, resolve_site_policy
from fleet.pipeline.omx_cell_policy import resolve_omx_cells, evaluate_omx_cell_station
from fleet.pipeline.cell_fleet_contract import CONTRACT_VERSION, validate_boundary_separation


def evaluate_fleet_pipeline(
    site_map: SiteMap | None,
    graph: Graph | None,
    robots: Sequence[Any],
    bays: Sequence[Bay],
    *,
    charge_bays: ChargeBays | None = None,
    site_rules: SiteRules | None = None,
    goals_by_robot: Mapping[str, str | tuple[float, float] | tuple[float, float, float | None]] | None = None,
    cell_states: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    site_policy = resolve_site_policy(site_map, graph, site_rules=site_rules)
    bay_views = [
        RobotView(
            r.robot_id,
            bool(getattr(r, "online", False)),
            getattr(r, "percent", None),
            getattr(r, "voltage", None),
            (float(r.pose[0]), float(r.pose[1])) if getattr(r, "pose", None) is not None else None,
            bool(getattr(r, "on_trip", False)),
            getattr(r, "yaw", None),
        )
        for r in robots
    ]
    bay_plan = (charge_bays.plan(bay_views, list(bays), graph=graph, site_rules=site_rules)
                if charge_bays is not None and graph is not None else
                {"bays": [], "actions": [], "corridor": None, "docking": {}})
    action_by_robot = {a["robot_id"]: a for a in bay_plan.get("actions", [])}
    stations = resolve_omx_cells(site_map, graph)
    robot_entries = []
    for r in robots:
        rid = r.robot_id
        profile = get_robot_profile(getattr(r, "kind", None) or rid)
        raw_pose = getattr(r, "pose", None)
        pose = (float(raw_pose[0]), float(raw_pose[1]), getattr(r, "yaw", None)) if raw_pose is not None else None
        docking = (evaluate_pinky_dock_step(*pose, graph, profile=profile)
                   if pose is not None and graph is not None else None)
        action = action_by_robot.get(rid, {})
        target_goal = (goals_by_robot[rid] if goals_by_robot and rid in goals_by_robot else
                       site_policy.exit_gate_place if action.get("action") == "leave" and site_policy.exit_gate_place else
                       action["bay"] if action.get("action") == "go" and action.get("bay") else None)
        road_trip = road_cmd = None
        if pose is not None and graph is not None and target_goal is not None:
            try:
                road_trip = plan_site_road_trip(site_policy, graph, pose, target_goal, step_m=profile.road_step_m)
                road_cmd = compute_pinky_road_command(pose, road_trip["waypoints_site"], 0, profile=profile)
            except PlanError as exc:
                road_trip = {"error": exc.code, "detail": exc.detail}
        robot_entries.append({
            "robot_id": rid, "robot_kind": profile.kind, "online": bool(getattr(r, "online", False)),
            "pose": {"x": pose[0], "y": pose[1], "yaw": pose[2]} if pose else None,
            "profile": profile.to_dict(), "bay_decision": action_by_robot.get(rid), "docking": docking,
            "road_trip": road_trip, "road_command": road_cmd,
        })
    cell_evals = {}
    for cid, station in stations.items():
        state = (cell_states or {}).get(cid, {})
        docked = next((r for r in robots if
                       (state.get("robot_id") == r.robot_id) or
                       (getattr(r, "pose", None) is not None and
                        ((float(r.pose[0]) - station.station_xy[0]) ** 2 +
                         (float(r.pose[1]) - station.station_xy[1]) ** 2) ** 0.5 <= 0.18)), None)
        if docked is not None:
            pose = docked.pose
            docked_view = {"robot_id": docked.robot_id, "robot_kind": get_robot_profile(
                getattr(docked, "kind", None) or docked.robot_id).kind,
                "pose": {"x": float(pose[0]), "y": float(pose[1]),
                         "yaw": getattr(docked, "yaw", None)}}
        else:
            docked_view = None
        cell_evals[cid] = evaluate_omx_cell_station(
            station, docked_robot=docked_view, cell_state=state,
            map_version=getattr(graph, "version", None))
    for entry in robot_entries:
        inhibit = next(((cid, cell) for cid, cell in cell_evals.items()
                        if cell["gate"]["amr_motion_inhibited"] and
                        cell["gate"]["robot_id"] == entry["robot_id"]), None)
        entry["cell_inhibit"] = inhibit is not None
        if inhibit:
            cid, cell = inhibit
            entry["road_command"] = {"robot_kind": entry["robot_kind"], "wp_index": 0,
                "done": False, "v_cmd_mps": 0.0, "omega_cmd_rad_s": 0.0,
                "blocked_by_cell": True, "cell_id": cid}
    boundary = validate_boundary_separation(
        ["site_map", "lane_graph", "road_nav2", "corridor_arbitration", "charge_bays"],
        ["omx_arm_ik", "wrist_servo_vision", "area_xyz_directive", "pallet_tier_stacking"])
    return {
        "general_layer": {"planner": "dijkstra_road_snap", "corridor_arbiter": "arbitrate_corridor_departure",
                          "map_version": getattr(graph, "version", None), "corridor_state": bay_plan.get("corridor")},
        "site_layer": site_policy.to_dict(graph),
        "robot_layer": {"default_kind": "pinky", "robots": robot_entries},
        "bays": bay_plan.get("bays", []),
        "omx_cell_layer": {"cells": cell_evals},
        "contract_layer": {"contract_version": CONTRACT_VERSION, "boundary_check": boundary,
            "active_handoffs": [c["handoff"] for c in cell_evals.values() if c["handoff"] is not None],
            "active_receipts": [c["receipt"] for c in cell_evals.values() if c["receipt"] is not None],
            "gates": {cid: c["gate"] for cid, c in cell_evals.items()}},
    }
