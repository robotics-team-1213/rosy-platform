#!/usr/bin/env python3
"""Gazebo multi-robot verification of the Two-Layer Road-Nav2 & Sequential Bay Departure Pipeline.

Spawns/controls 3 Pinky Pro robots in ``map_world_261026.world`` at ``C1``, ``C2``, ``C3``:
  - ``rosy_01`` at ``C1 (-0.414, 0.470, yaw=-pi/2)`` — 0.783 m to exit ``S1`` (Rank 1)
  - ``rosy_02`` at ``C2 (-0.190, 0.470, yaw=-pi/2)`` — 1.007 m to exit ``S1`` (Rank 2)
  - ``rosy_03`` at ``C3 ( 0.032, 0.470, yaw=-pi/2)`` — 1.229 m to exit ``S1`` (Rank 3)

Verifies in Gazebo physics (``/rosy_0X/odom`` + ``/rosy_0X/cmd_vel``):
  1. All 3 robots finish charging simultaneously (even with ``rosy_03`` connected earliest).
  2. Regional Rule (``charge_bay_corridor``, ``exit_place="S1"``, ``order="exit_nearest"``) +
     General Rule (``arbitrate_corridor_departure`` + ``plan_road_path``) releases ONLY
     ``rosy_01`` (``C1``) first while holding ``rosy_02`` and ``rosy_03`` (``queued_for_exit``).
  3. While ``rosy_01`` drives along the road polyline ``C1 -> P1 -> S1``, ``rosy_02`` and
     ``rosy_03`` remain held with ``corridor_busy``.
  4. Once ``rosy_01`` clears ``S1`` onto ``J_out -> S3``, ``rosy_02`` (``C2``) is granted
     ``leave`` and drives ``C2 -> P2 -> P1 -> S1`` while ``rosy_03`` waits.
  5. Once ``rosy_02`` clears ``S1``, ``rosy_03`` (``C3``) is granted ``leave`` and drives
     ``C3 -> P3 -> P2 -> P1 -> S1 -> J_out``.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _rel in (
    "operations/fleet",
    "operations/world/src",
    "deploy/robot/omx",
    "middleware/devices/omx/adapter",
    "contracts/foundation",
    "contracts/motion/src",
    "contracts/learning/src",
):
    _p = str(_REPO_ROOT / _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fleet._source_layout import bootstrap_sources  # noqa: E402

bootstrap_sources()

from fleet.charge_bays import Bay, ChargeBays, RobotView, bays_from_map  # noqa: E402
from fleet.routing.cost import wrap
from fleet.routing.graph import Graph, build_graph
from fleet.routing.road_path import plan_road_path
from fleet.site_map import SiteMap
from fleet.site_rules import SiteRules

SPAWNS: dict[str, tuple[float, float, float]] = {
    "rosy_01": (-0.4197, 0.4700, -math.pi / 2),
    "rosy_02": (-0.1861, 0.4700, -math.pi / 2),
    "rosy_03": (0.0351, 0.4700, -math.pi / 2),
}

POST_EXIT_GOALS: dict[str, str | tuple[float, float]] = {
    "rosy_01": "S3",
    "rosy_02": "S5",
    "rosy_03": "S4",
}


def build_world_261026_site_map() -> tuple[SiteMap, Graph, list[Bay]]:
    site = SiteMap.model_validate(
        {
            "schema": "rosy.site_map/1",
            "map_id": "world_261026",
            "places": [
                {"id": "S1", "kind": "stop", "name": "S1 주차장 출구·수동 적재 정지선", "x": -0.6763, "y": -0.1383},
                {"id": "S2", "kind": "stop", "name": "S2 주차장 입구 정지선", "x": 0.3088, "y": -0.1377},
                {"id": "S3", "kind": "stop", "name": "S3 상단 하역 정지선 (cell_s)", "x": 0.6987, "y": -0.2512},
                {"id": "S4", "kind": "stop", "name": "S4 하단 중앙 대기 정지선", "x": 0.1562, "y": -0.4754},
                {"id": "S5", "kind": "stop", "name": "S5 하단 U턴 전 대기 정지선", "x": 0.9212, "y": -0.4776},
                {"id": "J_in", "kind": "junction", "name": "주차장 입구 분기", "x": 0.3088, "y": -0.2518},
                {"id": "J_out", "kind": "junction", "name": "주차장 출구 합류", "x": -0.6763, "y": -0.2505},
                {"id": "P1", "kind": "junction", "name": "칸 1 앞", "x": -0.4184, "y": 0.0264},
                {"id": "P2", "kind": "junction", "name": "칸 2 앞", "x": -0.1896, "y": 0.0256},
                {"id": "P3", "kind": "junction", "name": "칸 3 앞", "x": 0.0322, "y": 0.0249},
                {"id": "C1", "kind": "charge", "name": "충전 칸 1", "x": -0.4197, "y": 0.47, "yaw": -1.5708},
                {"id": "C2", "kind": "charge", "name": "충전 칸 2", "x": -0.1861, "y": 0.47, "yaw": -1.5708},
                {"id": "C3", "kind": "charge", "name": "충전 칸 3", "x": 0.0351, "y": 0.47, "yaw": -1.5708},
            ],
            "edges": [
                {"direction": "one_way", "drive_mode": "lane", "from": "S5", "id": "loop_right", "name": "오른쪽 U턴",
                 "polyline": [[0.9212, -0.4776], [0.926, -0.4777], [0.9599, -0.4739], [0.9915, -0.4627], [1.0186, -0.4449], [1.0394, -0.4216], [1.0525, -0.3946], [1.057, -0.3656], [1.0525, -0.3366], [1.0394, -0.3095], [1.0186, -0.2863], [0.9915, -0.2685], [0.9599, -0.2573], [0.926, -0.2535], [0.6987, -0.2512]],
                 "speed_cap_mps": 0.15, "to": "S3", "width_m": 0.2},
                {"direction": "one_way", "drive_mode": "lane", "from": "S3", "id": "upper_east", "name": "위 차선 (하역 후 분기)",
                 "polyline": [[0.6987, -0.2512], [0.6207, -0.2513], [0.5427, -0.2514], [0.4648, -0.2516], [0.3868, -0.2517], [0.3088, -0.2518]],
                 "speed_cap_mps": 0.15, "to": "J_in", "width_m": 0.2},
                {"direction": "one_way", "drive_mode": "lane", "from": "J_in", "id": "upper_west", "name": "위 차선 (주차장 앞 순환)",
                 "polyline": [[0.3088, -0.2518], [0.1993, -0.2516], [0.0899, -0.2514], [-0.0196, -0.2512], [-0.129, -0.251], [-0.2385, -0.2509], [-0.3479, -0.2508], [-0.4574, -0.2506], [-0.5668, -0.2506], [-0.6763, -0.2505]],
                 "speed_cap_mps": 0.15, "to": "J_out", "width_m": 0.2},
                {"direction": "one_way", "drive_mode": "lane", "from": "J_out", "id": "loop_left", "name": "왼쪽 U턴·아래 서쪽 차선 (S4 정지선까지)",
                 "polyline": [[-0.6763, -0.2505], [-0.926, -0.2505], [-0.9599, -0.2543], [-0.9915, -0.2656], [-1.0186, -0.2834], [-1.0394, -0.3067], [-1.0525, -0.3338], [-1.057, -0.3629], [-1.0525, -0.392], [-1.0394, -0.4191], [-1.0186, -0.4424], [-0.9915, -0.4602], [-0.9599, -0.4715], [-0.926, -0.4753], [-0.85, -0.4752], [-0.7242, -0.475], [-0.5985, -0.4749], [-0.4727, -0.4749], [-0.3469, -0.4749], [-0.2211, -0.475], [-0.0954, -0.4751], [0.0304, -0.4753], [0.1562, -0.4754]],
                 "speed_cap_mps": 0.15, "to": "S4", "width_m": 0.2},
                {"direction": "one_way", "drive_mode": "lane", "from": "S4", "id": "lower_east", "name": "아래 동쪽 차선 (S4 -> S5 정지선)",
                 "polyline": [[0.1562, -0.4754], [0.2837, -0.4757], [0.4112, -0.476], [0.5387, -0.4763], [0.6662, -0.4767], [0.7937, -0.4771], [0.9212, -0.4776]],
                 "speed_cap_mps": 0.15, "to": "S5", "width_m": 0.2},
                {"direction": "one_way", "drive_mode": "lane", "from": "J_in", "id": "park_gate_in", "name": "주차장 진입",
                 "polyline": [[0.3088, -0.2518], [0.3088, -0.1377]], "speed_cap_mps": 0.08, "to": "S2", "width_m": 0.15},
                {"direction": "one_way", "drive_mode": "lane", "from": "S2", "id": "park_in", "name": "분홍 유도선 (입구)",
                 "polyline": [[0.3088, -0.1377], [0.2636, -0.048], [0.2279, 0.0242], [0.0322, 0.0249]], "speed_cap_mps": 0.08, "to": "P3", "width_m": 0.15},
                {"direction": "one_way", "drive_mode": "lane", "from": "P3", "id": "bar_32", "name": "분홍 유도선",
                 "polyline": [[0.0322, 0.0249], [-0.1896, 0.0256]], "speed_cap_mps": 0.08, "to": "P2", "width_m": 0.15},
                {"direction": "one_way", "drive_mode": "lane", "from": "P2", "id": "bar_21", "name": "분홍 유도선",
                 "polyline": [[-0.1896, 0.0256], [-0.4184, 0.0264]], "speed_cap_mps": 0.08, "to": "P1", "width_m": 0.15},
                {"direction": "one_way", "drive_mode": "lane", "from": "P1", "id": "park_out", "name": "분홍 유도선 (출구)",
                 "polyline": [[-0.4184, 0.0264], [-0.5969, 0.0271], [-0.6344, -0.048], [-0.6763, -0.1383]], "speed_cap_mps": 0.08, "to": "S1", "width_m": 0.15},
                {"direction": "one_way", "drive_mode": "lane", "from": "S1", "id": "park_gate_out", "name": "주차장 합류",
                 "polyline": [[-0.6763, -0.1383], [-0.6763, -0.2505]], "speed_cap_mps": 0.08, "to": "J_out", "width_m": 0.15},
                {"direction": "two_way", "drive_mode": "lane", "from": "P1", "id": "bay_1", "name": "칸 1 (후진 진입)",
                 "polyline": [[-0.4184, 0.0264], [-0.4188, 0.1728], [-0.4193, 0.3236], [-0.4197, 0.47]], "speed_cap_mps": 0.05, "to": "C1", "width_m": 0.18},
                {"direction": "two_way", "drive_mode": "lane", "from": "P2", "id": "bay_2", "name": "칸 2 (후진 진입)",
                 "polyline": [[-0.1896, 0.0256], [-0.1884, 0.1723], [-0.1873, 0.3233], [-0.1861, 0.47]], "speed_cap_mps": 0.05, "to": "C2", "width_m": 0.18},
                {"direction": "two_way", "drive_mode": "lane", "from": "P3", "id": "bay_3", "name": "칸 3 (후진 진입)",
                 "polyline": [[0.0322, 0.0249], [0.0332, 0.1718], [0.0341, 0.3231], [0.0351, 0.47]], "speed_cap_mps": 0.05, "to": "C3", "width_m": 0.18},
            ],
        }
    )
    graph = build_graph(site, version=119)
    return site, graph, bays_from_map(site)


def pure_pursuit_cmd(
    pose: tuple[float, float, float],
    waypoints: list[dict[str, Any]],
    wp_idx: int,
    *,
    v_max: float = 0.22,
    w_max: float = 2.0,
) -> tuple[float, float, int, bool]:
    x, y, yaw = pose
    while wp_idx < len(waypoints) - 1:
        wp = waypoints[wp_idx]
        if math.dist((x, y), (wp["x"], wp["y"])) < 0.075:
            wp_idx += 1
        else:
            break
    target = waypoints[wp_idx]
    dist_final = math.dist((x, y), (waypoints[-1]["x"], waypoints[-1]["y"]))
    if dist_final < 0.055 and wp_idx >= len(waypoints) - 1:
        return 0.0, 0.0, wp_idx, True
    desired_yaw = math.atan2(target["y"] - y, target["x"] - x)
    err = wrap(desired_yaw - yaw)
    if abs(err) > 0.45:
        return 0.0, max(-w_max, min(w_max, 2.5 * err)), wp_idx, False
    v = min(v_max, max(0.08, 0.85 * math.dist((x, y), (target["x"], target["y"])))) * math.cos(err)
    w = max(-w_max, min(w_max, 2.2 * err))
    return v, w, wp_idx, False


def min_road_distance(graph: Graph, x: float, y: float) -> float:
    return min(arc.project(x, y)[0] for arc in graph.arcs.values())


def run_s3_cell_contract_handoff(
    site: SiteMap,
    graph: Graph,
    bays: list[Bay],
    robot_id: str = "rosy_01",
    work_dir: str = "/tmp/rosy_sim_handoff",
    fleet_r_url: str | None = None,
    fleet_r_token: str = "",
    request_fn: Any = None,
) -> dict[str, Any]:
    from types import SimpleNamespace

    from fleet.pipeline.orchestrator import evaluate_fleet_pipeline

    route = plan_road_path(graph, (-0.6763, -0.1383, -math.pi / 2), "S3", step_m=0.10)
    assert ["park_gate_out", "loop_left", "lower_east", "loop_right"] == list(route.edges), route.edges
    assert ["J_out", "S4", "S5", "S3"] == list(route.places), route.places

    # 3-robot orange stop-line formation during S3 unloading:
    # rosy_01 at S3 (0.6987, -0.2512), rosy_02 waiting at S5 (0.9212, -0.4776), rosy_03 waiting at S4 (0.1562, -0.4754)
    robot = SimpleNamespace(robot_id=robot_id, kind="pinky", online=True,
                             pose=(0.6987, -0.2512), yaw=3.14159, percent=76.0, voltage=7.44)
    r2_s5 = SimpleNamespace(robot_id="rosy_02", kind="pinky", online=True,
                            pose=(0.9212, -0.4776), yaw=0.0, percent=12.0, voltage=6.82)
    r3_s4 = SimpleNamespace(robot_id="rosy_03", kind="pinky", online=True,
                            pose=(0.1562, -0.4754), yaw=0.0, percent=14.0, voltage=6.88)
    held = evaluate_fleet_pipeline(
        site, graph, [robot, r2_s5, r3_s4], bays,
        cell_states={"cell_s": {"phase": "ARM_IN_BED_ZONE", "robot_id": robot_id}},
    )
    cell = held["omx_cell_layer"]["cells"]["cell_s"]
    entry = held["robot_layer"]["robots"][0]
    assert cell["gate"]["amr_motion_inhibited"] is True
    assert entry["road_command"]["blocked_by_cell"] is True
    assert entry["road_command"]["v_cmd_mps"] == 0.0

    omx_path = Path(__file__).resolve().parents[2] / "deploy" / "robot" / "omx"
    sys.path.insert(0, str(omx_path)) if str(omx_path) not in sys.path else None
    from cell_fleet_pipeline import FleetModelPipeline

    omx_result = FleetModelPipeline(Path(work_dir)).run_contract_handoff_stage(
        held["contract_layer"]["active_handoffs"][0], stage_id="sim-s3-pinky-to-belt"
    )
    receipt = omx_result["receipt"]
    assert receipt["phase"] == "RELEASED", receipt
    assert receipt["amr_motion_inhibited"] is False, receipt
    assert receipt["goal_evidence_digest"].startswith("sha256:"), receipt

    # Selective Pit-In vs Continuous Loop at J_in (0.3088, -0.2518):
    # - rosy_01 (76% > 15%) continues circulating on main loop (J_in -> J_out -> S1 manual load zone -> S4 -> S5 -> S3)
    # - rosy_02 (12% <= 15%) & rosy_03 (14% <= 15%) are routed by ChargeBays into J_in -> S2 -> P_i -> C_i
    cb = ChargeBays()
    r1_jin = SimpleNamespace(robot_id=robot_id, kind="pinky", online=True,
                             pose=(0.3088, -0.2518), yaw=3.14159, percent=76.0, voltage=7.44)
    r2_jin = SimpleNamespace(robot_id="rosy_02", kind="pinky", online=True,
                             pose=(0.3088, -0.2518), yaw=3.14159, percent=12.0, voltage=6.82)
    released = evaluate_fleet_pipeline(
        site, graph, [r1_jin, r2_jin], bays,
        charge_bays=cb,
        goals_by_robot={robot_id: "J_out"},
        cell_states={"cell_s": {"phase": "RELEASED", "robot_id": robot_id}},
    )
    released_cell = released["omx_cell_layer"]["cells"]["cell_s"]
    released_entry = released["robot_layer"]["robots"][0]
    pit_in_entry = released["robot_layer"]["robots"][1]
    assert released_cell["gate"]["amr_motion_inhibited"] is False
    assert released_entry["road_command"]["v_cmd_mps"] > 0.0
    assert released_entry["road_trip"]["places"] == ["J_in", "J_out"]
    assert pit_in_entry["bay_decision"]["action"] == "go"
    assert "S2" in pit_in_entry["road_trip"]["places"]
    result = {
        "s3_route_edges": list(route.edges),
        "s3_route_places": list(route.places),
        "stop_lines": held["site_layer"]["stop_lines"],
        "inhibited_gate": cell["gate"],
        "omx_receipt": receipt,
        "released_v_cmd_mps": released_entry["road_command"]["v_cmd_mps"],
        "selective_pit_in": {
            "circulating_robot": {
                "robot_id": robot_id,
                "percent": 76.0,
                "places": released_entry["road_trip"]["places"],
                "next_manual_load_stop": "S1",
            },
            "pit_in_robot": {
                "robot_id": "rosy_02",
                "percent": 12.0,
                "bay": pit_in_entry["bay_decision"]["bay"],
                "places": pit_in_entry["road_trip"]["places"],
            },
        },
    }
    if fleet_r_url or request_fn is not None:
        result["remote_fleet_r_handoff"] = FleetModelPipeline(Path(work_dir)).execute_remote_fleet_r_handoff(
            fleet_r_url=fleet_r_url or "https://rosy-fleet-r:8443",
            token=fleet_r_token, robot_id=robot_id, request_fn=request_fn,
        )
    return result


def run_gazebo_simulation(timeout_s: float = 75.0) -> dict[str, Any]:
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry

    _site, graph, bays = build_world_261026_site_map()
    rules = SiteRules.model_validate({"departure": {"order": "exit_nearest"}, "return": {"exit_place": "S1"}})
    charge_bays = ChargeBays(rate_pct_per_min=15.0)

    rclpy.init()
    node = rclpy.create_node("bay_departure_sim_verifier")
    poses: dict[str, tuple[float, float, float]] = dict(SPAWNS)
    odom_ready: set[str] = set()
    pubs: dict[str, Any] = {}

    def make_cb(rid: str, sx: float, sy: float, syaw: float):
        mode: list[str] = []

        def _cb(msg: Odometry) -> None:
            p = msg.pose.pose.position
            q = msg.pose.pose.orientation
            lyaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
            if not mode:
                mode.append("world" if math.dist((p.x, p.y), (sx, sy)) < 0.12 else "local")
            if mode[0] == "world":
                poses[rid] = (float(p.x), float(p.y), wrap(lyaw))
            else:
                c, s = math.cos(syaw), math.sin(syaw)
                wx = sx + c * p.x - s * p.y
                wy = sy + s * p.x + c * p.y
                poses[rid] = (wx, wy, wrap(syaw + lyaw))
            odom_ready.add(rid)
        return _cb

    for rid, (sx, sy, syaw) in SPAWNS.items():
        node.create_subscription(Odometry, f"/{rid}/odom", make_cb(rid, sx, sy, syaw), 10)
        pubs[rid] = node.create_publisher(Twist, f"/{rid}/cmd_vel", 10)

    t0 = time.monotonic()
    while len(odom_ready) < 3 and time.monotonic() - t0 < 15.0:
        rclpy.spin_once(node, timeout_sec=0.05)
    if len(odom_ready) < 3:
        raise RuntimeError(f"Gazebo odom not ready for all 3 robots: {sorted(odom_ready)}")

    # Pre-seed charging state so all 3 reach >= 80% simultaneously (rosy_03 connected earliest)
    base_views = [
        RobotView(rid, True, 50.0, 7.40, (poses[rid][0], poses[rid][1]), False, poses[rid][2])
        for rid in sorted(SPAWNS)
    ]
    charge_bays.observe(0.0, base_views, bays)
    for idx, rid in enumerate(["rosy_03", "rosy_02", "rosy_01"], start=1):
        step_views = [
            RobotView(
                r,
                True,
                50.0,
                7.50 if r in ("rosy_03", "rosy_02", "rosy_01")[:idx] else 7.40,
                (poses[r][0], poses[r][1]),
                False,
                poses[r][2],
            )
            for r in sorted(SPAWNS)
        ]
        charge_bays.observe(float(idx), step_views, bays)

    sim_clock = 300.0  # 300s elapsed -> all 3 at 100% charge
    active_routes: dict[str, list[dict[str, Any]]] = {}
    wp_indices: dict[str, int] = {}
    finished: set[str] = set()
    depart_order: list[str] = []
    depart_snapshots: list[dict[str, Any]] = []
    max_cross_track_m = 0.0
    min_pair_dist_m = 999.0

    loop_start = time.monotonic()
    while len(finished) < 3 and time.monotonic() - loop_start < timeout_s:
        for _ in range(4):
            rclpy.spin_once(node, timeout_sec=0.01)
        sim_clock += 0.25
        views = [
            RobotView(
                rid,
                True,
                85.0,
                7.48,
                (poses[rid][0], poses[rid][1]),
                rid in active_routes and rid not in finished,
                poses[rid][2],
            )
            for rid in sorted(SPAWNS)
        ]
        charge_bays.observe(sim_clock, views, bays)
        plan = charge_bays.plan(views, bays, graph=graph, site_rules=rules)
        act_map = {a["robot_id"]: a for a in plan["actions"]}

        # Grant check: only start a robot when ChargeBays arbiter grants action == "leave"
        for rid, act in act_map.items():
            if act.get("action") == "leave" and rid not in active_routes:
                road_plan = plan_road_path(graph, poses[rid], POST_EXIT_GOALS[rid], step_m=0.10)
                active_routes[rid] = [dict(w) for w in road_plan.waypoints_site]
                wp_indices[rid] = 0
                depart_order.append(rid)
                depart_snapshots.append(
                    {
                        "robot_id": rid,
                        "bay": act.get("bay"),
                        "exit_rank": act.get("exit_rank"),
                        "exit_distance_m": act.get("exit_distance_m"),
                        "edges": list(road_plan.edges),
                        "places": list(road_plan.places),
                        "other_actions": {
                            k: {"action": v.get("action"), "reason": v.get("reason"), "ahead": v.get("ahead")}
                            for k, v in act_map.items()
                            if k != rid
                        },
                        "poses_at_release": {k: [round(poses[k][0], 3), round(poses[k][1], 3)] for k in sorted(SPAWNS)},
                    }
                )

        # Drive active robots along their road polylines; hold waiting robots stationary
        for rid in sorted(SPAWNS):
            msg = Twist()
            if rid in active_routes and rid not in finished:
                v, w, nxt_idx, done = pure_pursuit_cmd(poses[rid], active_routes[rid], wp_indices[rid])
                wp_indices[rid] = nxt_idx
                if done:
                    finished.add(rid)
                else:
                    msg.linear.x = float(v)
                    msg.angular.z = float(w)
                ct = min_road_distance(graph, poses[rid][0], poses[rid][1])
                max_cross_track_m = max(max_cross_track_m, ct)
            pubs[rid].publish(msg)

        rids = sorted(SPAWNS)
        for i in range(len(rids)):
            for j in range(i + 1, len(rids)):
                d = math.dist(poses[rids[i]][:2], poses[rids[j]][:2])
                min_pair_dist_m = min(min_pair_dist_m, d)

    for pub in pubs.values():
        pub.publish(Twist())
    node.destroy_node()
    rclpy.shutdown()

    result = {
        "depart_order": depart_order,
        "finished": sorted(finished),
        "max_cross_track_m": round(max_cross_track_m, 4),
        "min_pair_dist_m": round(min_pair_dist_m, 4),
        "final_poses": {k: [round(v[0], 3), round(v[1], 3), round(v[2], 3)] for k, v in poses.items()},
        "depart_snapshots": depart_snapshots,
    }
    assert depart_order == ["rosy_01", "rosy_02", "rosy_03"], f"Expected C1->C2->C3 order, got {depart_order}"
    assert len(finished) == 3, f"Not all robots finished road route: {result}"
    assert max_cross_track_m <= 0.09, f"Robot left road corridor: max_cross_track_m={max_cross_track_m}"
    result["cell_contract_handoff"] = run_s3_cell_contract_handoff(
        _site,
        graph,
        bays,
        fleet_r_url=os.environ.get("FLEET_R_URL") or None,
        fleet_r_token=os.environ.get("FLEET_R_TOKEN", ""),
    )
    return result


if __name__ == "__main__":
    if "--pure" in sys.argv:
        _site, _graph, _bays = build_world_261026_site_map()
        out = run_s3_cell_contract_handoff(
            _site, _graph, _bays,
            fleet_r_url=os.environ.get("FLEET_R_URL") or None,
            fleet_r_token=os.environ.get("FLEET_R_TOKEN", ""),
        )
    else:
        out = run_gazebo_simulation()
    print(json.dumps(out, ensure_ascii=False, indent=2))
