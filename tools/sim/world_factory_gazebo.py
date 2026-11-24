"""Isolated Gazebo + CORE + Fleet + Cell prefix testbed (Stages 1-4 + negative gates)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
for _rel in (
    "tools/sim", "operations/fleet", "operations/world/src", "deploy/robot/omx",
    "middleware/devices/omx/adapter", "contracts/foundation", "contracts/motion/src",
    "contracts/learning/src", "contracts/skill/src",
):
    _p = str(REPO / _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fleet._source_layout import bootstrap_sources  # noqa: E402

bootstrap_sources()

from fleet.charge_bays import bays_from_map  # noqa: E402
from fleet.pipeline.orchestrator import evaluate_fleet_pipeline  # noqa: E402
from fleet.routing.cost import wrap  # noqa: E402
from fleet.routing.graph import build_graph  # noqa: E402
from fleet.routing.road_path import plan_road_path  # noqa: E402
from fleet.site_map import SiteMap  # noqa: E402
from fleet.traffic.block_types import BlockRules, Robot as TrafficRobot, TableState  # noqa: E402
from fleet.traffic.blocks import build_layout, step as traffic_step  # noqa: E402
from fleet_trips import call, until  # noqa: E402
from factory_flow_receipts import SCHEMA as RECEIPT_SCHEMA, STAGES  # noqa: E402
from factory_isaac_handoff import prepare as prepare_isaac_handoff  # noqa: E402
from route_drive import nav2_active, nav_state  # noqa: E402

ROBOT = "rosy_01"
TOKEN = "rosy-dev-operator"
SCHEMA_S3_OBS = "rosy.factory-s3-stop-observation.v1"
SCHEMA_CELL_CLAIM = "rosy.factory-sim-cell-claim.v1"


class PoseOdomTrace:
    """Subscribe to ``/<ns>/odom`` and record (sim_time_s, x, y, yaw, v, w)."""

    def __init__(self, ns: str):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.qos import QoSProfile, ReliabilityPolicy

        rclpy.init()
        self.rclpy = rclpy
        self.samples: list[tuple[float, float, float, float, float, float]] = []
        self.lock = threading.Lock()
        self.node = rclpy.create_node("world_factory_odom_trace")
        self.node.create_subscription(
            Odometry, f"/{ns}/odom", self._on_odom,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT),
        )
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def _on_odom(self, msg) -> None:
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        v = math.hypot(msg.twist.twist.linear.x, msg.twist.twist.linear.y)
        w = msg.twist.twist.angular.z
        with self.lock:
            self.samples.append((t, float(p.x), float(p.y), wrap(yaw), float(v), float(w)))

    def _spin(self) -> None:
        while not self.stopping.is_set():
            self.rclpy.spin_once(self.node, timeout_sec=0.05)

    def latest(self) -> tuple[float, float, float, float, float, float] | None:
        with self.lock:
            return self.samples[-1] if self.samples else None

    def mark(self) -> int:
        with self.lock:
            return len(self.samples)

    def since(self, idx: int) -> list[tuple[float, float, float, float, float, float]]:
        with self.lock:
            return list(self.samples[idx:])

    def close(self) -> None:
        self.stopping.set()
        self.thread.join()
        self.node.destroy_node()
        self.rclpy.shutdown()


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _within_s3_box(pose: tuple[float, float, float], limits: dict) -> bool:
    rx, ry, ryaw = limits["reference_pose"]
    xy_err = limits["position_uncertainty_m"]
    yaw_err = limits["heading_uncertainty_rad"]
    dx, dy = pose[0] - rx, pose[1] - ry
    lon = abs(dx * math.cos(ryaw) + dy * math.sin(ryaw))
    lat = abs(-dx * math.sin(ryaw) + dy * math.cos(ryaw))
    head = abs(wrap(pose[2] - ryaw))
    return lon + xy_err <= limits["longitudinal_m"] and lat + xy_err <= limits["lateral_m"] and head + yaw_err <= limits["heading_rad"]


def _drive_waypoints(base: str, points: list[dict], api_log, budget_s: float = 120.0) -> str:
    code, resp = call(f"{base}/api/v1/navigation/route", TOKEN, "POST", {"points": points}, api_log)
    if code != 200:
        raise RuntimeError(f"CORE refused route ({code}): {resp}")
    end = time.monotonic() + budget_s
    nav = None
    while time.monotonic() < end:
        nav = nav_state(base, TOKEN).get("navigation")
        if nav in ("ARRIVED", "FAILED", "CANCELED"):
            break
        time.sleep(0.5)
    if nav != "ARRIVED":
        raise RuntimeError(f"navigation ended in {nav}")
    return nav


def _align_via_core(base: str, trace: PoseOdomTrace, target: tuple[float, float, float], limits: dict, api_log) -> None:
    """Close final Nav2 cm error into S3 box via CORE MANUAL teleop (slow, bounded)."""
    if call(f"{base}/api/v1/mode", TOKEN, "POST", {"mode": "MANUAL"}, api_log)[0] != 200:
        raise RuntimeError("CORE refused MANUAL mode for S3 alignment")
    try:
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            cur = trace.latest()
            if cur is None:
                time.sleep(0.1)
                continue
            pose = (cur[1], cur[2], cur[3])
            if _within_s3_box(pose, limits):
                break
            dx, dy = target[0] - pose[0], target[1] - pose[1]
            dist = math.hypot(dx, dy)
            if dist > 0.015:
                fwd_proj = dx * math.cos(pose[2]) + dy * math.sin(pose[2])
                sign = 1.0 if fwd_proj >= 0.0 else -1.0
                goal_yaw = math.atan2(dy, dx) if sign > 0 else wrap(math.atan2(dy, dx) + math.pi)
                err = wrap(goal_yaw - pose[2])
                if abs(err) > 0.14:
                    v, w = 0.0, max(-0.45, min(0.45, 1.5 * err))
                else:
                    v, w = sign * min(0.045, max(0.02, 0.5 * dist)), max(-0.35, min(0.35, 1.2 * err))
            else:
                err = wrap(target[2] - pose[2])
                v, w = 0.0, max(-0.40, min(0.40, 1.4 * err))
            call(f"{base}/api/v1/teleop", TOKEN, "POST", {"linear": v, "angular": w})
            time.sleep(0.12)
        cur = trace.latest()
        if cur is None or not _within_s3_box((cur[1], cur[2], cur[3]), limits):
            raise RuntimeError(f"S3 alignment did not reach measured box: {cur}")
    finally:
        call(f"{base}/api/v1/teleop", TOKEN, "POST", {"linear": 0.0, "angular": 0.0})
        call(f"{base}/api/v1/mode", TOKEN, "POST", {"mode": "IDLE"}, api_log)


def _collect_stationary_s3(trace: PoseOdomTrace, bindings: dict, hold_s: float = 1.6) -> dict:
    time.sleep(0.6)
    mark = trace.mark()
    time.sleep(hold_s)
    raw = trace.since(mark)
    samples = []
    last_t = -1.0
    for t, x, y, yaw, v, w in raw:
        if last_t < 0 or t - last_t >= 0.18:
            samples.append({
                "sim_time_s": round(t, 4),
                "pose_xy_yaw": [round(x, 5), round(y, 5), round(yaw, 5)],
                "linear_m_s": round(v, 5),
                "angular_rad_s": round(w, 5),
            })
            last_t = t
    if len(samples) < 4:
        raise RuntimeError(f"insufficient stationary S3 samples ({len(samples)})")
    return {
        "schema": SCHEMA_S3_OBS, **bindings,
        "source_kind": "gazebo_odom", "pose_frame": "site_map", "place_id": "S3",
        "samples": samples,
    }


def _evaluate_s1_block(graph, deny: bool) -> dict:
    layout = build_layout(graph, BlockRules(body_length_m=0.22, uncertainty_m=0.02, stop_gap=lambda _v: 0.08))
    exit_plan = plan_road_path(graph, graph.place_xy("S1"), "S3", step_m=0.12)
    arcs = tuple(f"{e}:fwd" for e in exit_plan.edges)
    spans = layout.route(graph, arcs)
    robots = [TrafficRobot(id=ROBOT, spans=spans, d=0.04, lookahead_m=0.08, uncertainty_m=0.02,
                           body_length_m=0.17, route_id="s1_to_s3")]
    if deny:
        # Second robot sits on the exit arc holding its block -> Fleet must deny S1 departure.
        block_arcs = ("park_gate_out:fwd", "loop_left:fwd")
        robots.insert(0, TrafficRobot(id="rosy_02", spans=layout.route(graph, block_arcs), d=0.10,
                                      lookahead_m=0.08, uncertainty_m=0.02, body_length_m=0.17, route_id="blocker"))
    tick = traffic_step(layout, robots, TableState(), 0.0)
    return {
        "denied": ROBOT in tick.waiting_for and bool(tick.waiting_for[ROBOT]),
        "waiting_for": list(tick.waiting_for.get(ROBOT, ())),
        "authority_end_m": round(tick.authority_end.get(ROBOT, 0.0), 4),
        "route_edges": list(exit_plan.edges),
    }


def _receipt_entry(bindings: dict, stage: str, rel_path: str, sha: str) -> dict:
    return {"schema": RECEIPT_SCHEMA, **bindings, "stage": stage, "status": "pass",
            "evidence": [{"path": rel_path, "sha256": sha}]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task-id", default="task-world-e2e-001")
    parser.add_argument("--cargo-id", default="cargo-r08-001")
    parser.add_argument("--mode", choices=("nominal", "deny-s1-yield", "s3-out-of-bounds"), default="nominal")
    args = parser.parse_args()

    run_id = os.environ.get("GZ_PARTITION", "")
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    if (not run_id.startswith("sim-") or not domain.isdecimal() or not 0 < int(domain) <= 232
            or os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST"
            or os.environ.get("GZ_IP") != "127.0.0.1"):
        parser.error("run inside isolated remote_sim.py")
    os.environ["RMW_IMPLEMENTATION"] = "rmw_cyclonedds_cpp"

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    map_bytes = args.site_map.read_bytes()
    map_sha = hashlib.sha256(map_bytes).hexdigest()
    (out / "site-map.json").write_bytes(map_bytes)
    envelope = json.loads(map_bytes)
    site_map = SiteMap.model_validate(envelope["map"])
    graph = build_graph(site_map, version=envelope["version"])
    bays = bays_from_map(site_map)
    places = {p.id: p for p in site_map.places}
    c2 = (float(places["C2"].x), float(places["C2"].y), float(places["C2"].yaw))
    s3_limits = next(p["precision_stop"] for p in envelope["map"]["places"] if p["id"] == "S3")
    bindings = {
        "run_id": run_id, "task_id": args.task_id, "robot_id": ROBOT,
        "cargo_id": args.cargo_id, "site_map_sha256": map_sha,
    }

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    cmd = [
        "ros2", "launch", "gz_sim", "gz_multi.launch.py", "robots:=1",
        "world_name:=map_world_261026.world", "headless:=true", "mode:=nav", "core:=true",
        "loc_assist:=false", "seed_initialpose:=false", f"api_port_base:={port}",
        "spawn_poses:=" + ",".join(map(str, c2)),
    ]
    result: dict = {"run_id": run_id, "mode": args.mode, "pass": False, "downstream_started": False}
    trace = None
    with (out / "launch.log").open("w") as launch_log, (out / "api-log.jsonl").open("w") as api_log:
        launch = subprocess.Popen(cmd, stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            if not until(120, lambda: launch.poll() is None and call(f"{base}/api/v1/robot/state", TOKEN)[1].get("robot_id") == ROBOT, 2):
                raise RuntimeError("simulated CORE did not become ready")
            trace = PoseOdomTrace(ROBOT)
            if not until(30, lambda: trace.latest() is not None, 0.5):
                raise RuntimeError("Gazebo odom did not arrive")
            if not until(90, lambda: nav2_active(ROBOT, os.environ), 2):
                raise RuntimeError("Nav2 bt_navigator did not activate")
            if not until(60, lambda: call(f"{base}/api/v1/localization/initialpose", TOKEN, "POST",
                                          dict(zip(("x", "y", "yaw"), c2)), api_log)[0] == 200, 3):
                raise RuntimeError("CORE refused C2 initialpose")
            if not until(90, lambda: (nav_state(base, TOKEN).get("readiness") or {}).get("ready") is True, 2):
                raise RuntimeError("CORE navigation readiness stayed false")
            pubs = [f"{p.node_namespace}/{p.node_name}" for p in trace.node.get_publishers_info_by_topic(f"/{ROBOT}/cmd_vel")]
            if pubs != [f"/{ROBOT}/core"]:
                raise RuntimeError(f"unexpected cmd_vel publishers: {pubs}")

            # Stage 1: C2 -> S1 via Fleet road planner + CORE route
            r_c2_s1 = plan_road_path(graph, c2, "S1", step_m=0.12)
            pts1 = [{"x": w["x"], "y": w["y"], "kind": w["kind"], **({"yaw": w["yaw"]} if w["kind"] == "stop" else {})}
                    for w in r_c2_s1.waypoints_site]
            _drive_waypoints(base, pts1, api_log)
            time.sleep(0.5)
            p_s1 = trace.latest()
            assert p_s1 is not None
            if math.dist((p_s1[1], p_s1[2]), (places["S1"].x, places["S1"].y)) > 0.16:
                raise RuntimeError(f"did not arrive near S1: {p_s1}")
            ev1_sha = _write_json(out / "ev/c2_departure.json", {
                **bindings, "stage": "c2_departure", "edges": list(r_c2_s1.edges),
                "places": list(r_c2_s1.places), "arrived_pose": list(p_s1[1:4]),
            })

            # Stage 2: S1 Fleet traffic arbitration
            s1_gate = _evaluate_s1_block(graph, deny=(args.mode == "deny-s1-yield"))
            if args.mode == "deny-s1-yield":
                if not s1_gate["denied"]:
                    raise RuntimeError(f"expected S1 block denial, got {s1_gate}")
                time.sleep(1.5)
                ev2_sha = _write_json(out / "ev/s1_yield_denied.json", {**bindings, **s1_gate})
                result["pass"] = True
                result.update(s1_gate=s1_gate, ev_s1=ev2_sha)
                _write_json(out / "result.json", result)
                return 0
            if s1_gate["denied"]:
                raise RuntimeError(f"unexpected S1 block in {args.mode}: {s1_gate}")
            ev2_sha = _write_json(out / "ev/s1_yield.json", {**bindings, **s1_gate})

            # Stage 3: S1 -> S3 (or intentional out-of-bounds lateral offset)
            r_s1_s3 = plan_road_path(graph, (p_s1[1], p_s1[2], p_s1[3]), "S3", step_m=0.12)
            pts3 = [{"x": w["x"], "y": w["y"], "kind": w["kind"], **({"yaw": w["yaw"]} if w["kind"] == "stop" else {})}
                    for w in r_s1_s3.waypoints_site]
            _drive_waypoints(base, pts3, api_log)
            cur = trace.latest()
            assert cur is not None
            result["raw_s3_pose"] = list(cur[1:4])
            if args.mode == "s3-out-of-bounds":
                # Differential-drive robot: if Nav2 happened to stop inside S3, drive straight past longitudinal bound.
                if _within_s3_box((cur[1], cur[2], cur[3]), s3_limits):
                    oob_target = (s3_limits["reference_pose"][0] - 0.065, s3_limits["reference_pose"][1], s3_limits["reference_pose"][2])
                    oob_box = {**s3_limits, "reference_pose": list(oob_target), "longitudinal_m": 0.02, "lateral_m": 0.03}
                    _align_via_core(base, trace, oob_target, oob_box, api_log)
            elif not _within_s3_box((cur[1], cur[2], cur[3]), s3_limits):
                _align_via_core(base, trace, tuple(s3_limits["reference_pose"]), s3_limits, api_log)

            s3_obs = _collect_stationary_s3(trace, bindings)
            ev3_sha = _write_json(out / "ev/s3_stop.json", s3_obs)

            # Stage 4: Cell S claim + contract verification
            s3_pose = s3_obs["samples"][-1]["pose_xy_yaw"]
            sim_robot = SimpleNamespace(robot_id=ROBOT, kind="pinky", online=True,
                                        pose=(s3_pose[0], s3_pose[1]), yaw=s3_pose[2], percent=80.0, voltage=7.5)
            held = evaluate_fleet_pipeline(
                site_map, graph, [sim_robot], bays,
                cell_states={"cell_s": {"phase": "ARM_IN_BED_ZONE", "robot_id": ROBOT}},
            )
            if not held["omx_cell_layer"]["cells"]["cell_s"]["gate"]["amr_motion_inhibited"]:
                raise RuntimeError("Fleet did not inhibit AMR motion during ARM_IN_BED_ZONE")
            from cell_fleet_pipeline import FleetModelPipeline

            sim_handoff = {**held["contract_layer"]["active_handoffs"][0], "wheel_brake_locked": True, "bed_ready": True}
            omx_res = FleetModelPipeline(out / "cell_work").run_contract_handoff_stage(sim_handoff, stage_id="sim-s3-pinky-to-belt")
            if omx_res["receipt"]["phase"] != "RELEASED":
                raise RuntimeError(f"OMX contract handoff did not reach RELEASED: {omx_res}")

            claim = {
                "schema": SCHEMA_CELL_CLAIM, **bindings, "scope": "isolated_sim", "cell_id": "cell_s",
                "stop_sha256": ev3_sha,
                "claimed_sim_time_s": round(s3_obs["samples"][-1]["sim_time_s"] + 0.5, 4),
                "fleet_cell_gate": held["omx_cell_layer"]["cells"]["cell_s"]["gate"],
                "omx_contract_receipt": omx_res["receipt"],
            }
            ev4_sha = _write_json(out / "ev/cell_claim.json", claim)
            prefix = [
                _receipt_entry(bindings, STAGES[0], "ev/c2_departure.json", ev1_sha),
                _receipt_entry(bindings, STAGES[1], "ev/s1_yield.json", ev2_sha),
                _receipt_entry(bindings, STAGES[2], "ev/s3_stop.json", ev3_sha),
                _receipt_entry(bindings, STAGES[3], "ev/cell_claim.json", ev4_sha),
            ]
            _write_json(out / "prefix_receipts.json", prefix)

            if args.mode == "s3-out-of-bounds":
                try:
                    prepare_isaac_handoff(out / "prefix_receipts.json", out / "site-map.json")
                except ValueError as exc:
                    if "outside measured stop bounds" not in str(exc):
                        raise
                    result["pass"] = True
                    result.update(handoff_rejected=True, rejection_reason=str(exc), s3_pose=s3_pose)
                    _write_json(out / "result.json", result)
                    return 0
                raise RuntimeError("s3-out-of-bounds was unexpectedly accepted by factory_isaac_handoff")

            intake = prepare_isaac_handoff(out / "prefix_receipts.json", out / "site-map.json")
            _write_json(out / "isaac-intake.json", intake)
            result["pass"] = True
            result.update(s3_pose=s3_pose, intake_schema=intake["schema"])
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            if trace is not None:
                trace.close()
            if launch.poll() is None:
                os.killpg(launch.pid, signal.SIGINT)
                try:
                    launch.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(launch.pid, signal.SIGTERM)
            _write_json(out / "result.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
