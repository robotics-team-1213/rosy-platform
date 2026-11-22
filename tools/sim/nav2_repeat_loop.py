#!/usr/bin/env python3
"""Gazebo bench: continuous Nav2 road-following repeat loop over lane-tagged edges (robot frame != site frame)."""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_trips as ft  # noqa: E402


def activate_nav2_lane_map(fleet: str, operator: str, log) -> list[dict]:
    """Activate rotated site map via Fleet HTTP API while keeping edges ``drive_mode='lane'``."""
    raw = yaml.safe_load(ft.GRAPH.read_text(encoding="utf-8"))
    code, active = ft.call(f"{fleet}/site-map/active", operator, log=log)
    if code != 200 or not isinstance(active.get("map"), dict):
        raise RuntimeError(f"GET /site-map/active failed: {code} {active}")
    base = active["map"]
    turn = lambda a: None if a is None else ft.to_site((0.0, 0.0, a), True)[2]  # noqa: E731
    places = [
        dict(p, x=ft.to_site((p["x"], p["y"]), True)[0], y=ft.to_site((p["x"], p["y"]), True)[1],
             yaw=turn(p.get("yaw")), exit_yaw=turn(p.get("exit_yaw")))
        for p in base["places"]
    ]
    stops = {
        "loop_e": ft.to_site(ft.lane_pose(raw, "east", "rev", 2.40), True),
        "loop_r": ft.to_site(ft.lane_pose(raw, "ring_w", "fwd", 0.18), True),
    }
    places += [
        {"id": pid, "name": pid, "kind": "stop", "x": pose[0], "y": pose[1], "yaw": pose[2]}
        for pid, pose in stops.items()
    ]
    edges = [dict(e, polyline=[list(ft.to_site(q, True)) for q in e["polyline"]]) for e in base["edges"]]
    raw_walls = json.loads((ft.REPO / "deploy/site/site-maps/map_v2_fleet-v5.json").read_text(encoding="utf-8"))["walls"]
    walls = [dict(w, face=[list(ft.to_site(p, True)) for p in w["face"]]) for w in raw_walls]
    rotated = {**base, "places": places, "edges": edges, "crosswalks": [], "walls": walls}
    code, draft = ft.call(f"{fleet}/site-map/draft", operator, "PUT", {"map": rotated}, log)
    if code != 200 or not draft.get("revision"):
        raise RuntimeError(f"PUT /site-map/draft failed: {code} {draft}")
    code, activated = ft.call(f"{fleet}/site-map/activate", operator, "POST",
                              {"expected_revision": draft["revision"]}, log)
    if code != 200:
        raise RuntimeError(f"POST /site-map/activate failed: {code} {activated}")
    return edges


def _seg_dist(x: float, y: float, a: list[float], b: list[float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    len2 = dx * dx + dy * dy
    if len2 <= 0.0:
        return math.hypot(x - a[0], y - a[1])
    t = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / len2))
    return math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy))


def max_off_lane_m(edges: list[dict], x: float, y: float) -> float:
    return min(
        max(0.0, min(_seg_dist(x, y, a, b) for a, b in zip(e["polyline"], e["polyline"][1:]))
            - float(e.get("width_m", 0.30)) / 2.0)
        for e in edges if len(e.get("polyline") or ()) >= 2
    )


def run(args) -> int:
    sys.path.insert(0, str(ft.REPO / "tools/validation/fleet_gazebo"))
    from preflight import Reservations

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    partition = os.environ.get("GZ_PARTITION") or f"nav2loop-{secrets.token_hex(3)}"
    run_id = partition.lower()
    reservations = Reservations.derive(run_id, len(ft.ROBOTS), started_at=time.time())
    for port in (*reservations.api_ports, reservations.console_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    jobs = Path.home() / "rosy-jobs"
    lock = None if (jobs / f"{partition}.lock").exists() else jobs / f"nav2-loop-{os.getpid()}.lock"
    if lock is not None:
        jobs.mkdir(exist_ok=True)
        lock.write_text(f"{os.getpid()} sim 6 8\n", encoding="utf-8")

    root = Path(tempfile.mkdtemp(prefix="nav2-loop-"))
    operator = ft.write_run(root, run_id, partition, reservations, args.stall_s, nav=True)
    # Remove traffic zones/signals and speed up stall_s tolerance only if requested; keep site lease required.
    site = yaml.safe_load((root / "site.yaml").read_text(encoding="utf-8"))
    site["fleet"]["traffic"] = {"authority": False}
    (root / "site.yaml").write_text(yaml.safe_dump(site), encoding="utf-8")

    manifest = yaml.safe_load((root / "robots.yaml").read_text(encoding="utf-8"))["robots"]
    rest = {r["robot_id"]: r["token"] for r in manifest}
    cores = {r["robot_id"]: r["base_url"] for r in manifest}
    fleet = f"http://127.0.0.1:{reservations.console_port}/api/fleet"
    raw_graph = yaml.safe_load(ft.GRAPH.read_text(encoding="utf-8"))
    spawns, _, _ = ft.layout(raw_graph, True)
    spawns["rosy_01"] = ft.lane_pose(raw_graph, "east", "rev", 2.40)
    spawns["rosy_02"] = (1.288, 0.498, 0.0)  # Verified free floor >=0.11m from walls and 0.51m > YIELD_KEEP_OUT_M from loop.

    env = dict(
        os.environ, GZ_PARTITION=partition, ROS_DOMAIN_ID=str(reservations.ros_domain_id), GZ_IP="127.0.0.1",
        ROS_AUTOMATIC_DISCOVERY_RANGE="LOCALHOST", RMW_IMPLEMENTATION="rmw_cyclonedds_cpp",
        CYCLONEDDS_URI="file://" + str(ft.cyclone_profile(root, True)), **ft.RENDER[args.render], **{ft.MARK: run_id},
    )
    launch = [
        "ros2", "launch", "gz_sim", "map_v2_fleet_multi_real.launch.py", "map_variant:=.",
        f"run_spec:={root / 'run_spec.yaml'}",
        "spawn_poses:=" + ";".join("%.5f,%.5f,%.6f" % tuple(spawns[ns]) for ns in ft.ROBOTS),
        "nav_mode:=nav",
    ]
    fleet_cmd = [
        sys.executable, str(Path(ft.__file__)), "fleet", str(root / "binding.json"), "console",
        "--robots", str(root / "robots.yaml"), "--host", "127.0.0.1", "--port", str(reservations.console_port),
        "--token-env", "FLEET_TRIPS_TOKEN", "--tasks-db", str(root / "tasks.sqlite"),
        "--site-map-import", str(ft.GRAPH), "--site-config", str(root / "site.yaml"),
        "--users-file", str(root / "users.yaml"),
    ]
    result = {"run_id": run_id, "target_laps": args.target_laps, "samples": 0, "max_off_lane_m": 0.0, "max_lap": 0}
    log = (out / "api-log.jsonl").open("w", buffering=1)
    try:
        with (out / "launch.log").open("w") as launch_log, (out / "fleet.log").open("w") as fleet_log:
            subprocess.Popen(launch, env=env, stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True)
            result["core_ready"] = ft.until(args.boot_s, lambda: all(
                ft.call(f"{cores[ns]}/api/v1/robot/state", rest[ns])[1].get("robot_id") == ns for ns in ft.ROBOTS), 2.0)
            if result["core_ready"]:
                subprocess.Popen(fleet_cmd, env=dict(env, FLEET_TRIPS_TOKEN=secrets.token_urlsafe(24)),
                                 stdout=fleet_log, stderr=subprocess.STDOUT, start_new_session=True)
                fleet_ready = ft.until(60, lambda: ft.call(f"{fleet}/site-map/active", operator)[0] == 200, 1.0)
                if not fleet_ready:
                    raise RuntimeError("Fleet HTTP did not become ready in time")
                edges = activate_nav2_lane_map(fleet, operator, log)
                result["localized"] = ft.until(180, lambda: all(
                    ft.call(f"{fleet}/robots/{ns}/map-pose", operator)[1].get("state") == "LOCALIZED"
                    for ns in ft.ROBOTS), 2.0)
                result["nav2_active"] = result["localized"] and ft.until(180, lambda: all(
                    nav2_active(ns, env) for ns in ft.ROBOTS), 2.0)
                # Let seed_initialpose finish before D-395 decision so its cov=0.25 never scatters AMCL afterwards.
                result["seed_done"] = result["nav2_active"] and ft.until(120, lambda: seed_done(env), 1.0)
                result["core_localized"] = result["seed_done"] and ft.until(180, lambda: all(
                    localize_nav(cores[ns], rest[ns], spawns[ns], log) for ns in ft.ROBOTS), 2.0)
                if result["core_localized"]:
                    time.sleep(args.settle_s)
                    req = {"to": "loop_e", "via": ["loop_r"], "repeat": True, "drive_mode": "nav2"}
                    code, plan = ft.call(f"{fleet}/robots/rosy_01/trip", operator, "POST", req, log)
                    result["plan_status"] = code
                    if code == 200:
                        sc, start_view = ft.call(f"{fleet}/trips/{plan['plan_id']}/start", operator, "POST", {}, log)
                        result["start_status"] = sc
                        if sc == 200:
                            trace = []
                            def done():
                                _, v = ft.call(f"{fleet}/trips/{plan['plan_id']}", operator)
                                _, mp = ft.call(f"{fleet}/robots/rosy_01/map-pose", operator)
                                _, ns = ft.call(f"{cores['rosy_01']}/api/v1/navigation/state", rest["rosy_01"])
                                lap = v.get("lap") or 0
                                result["max_lap"] = max(result["max_lap"], lap)
                                result["last_state"] = v.get("state")
                                result["last_reason"] = v.get("reason")
                                result["last_detail"] = v.get("detail")
                                if isinstance(mp.get("x"), (int, float)) and isinstance(mp.get("y"), (int, float)):
                                    off = max_off_lane_m(edges, mp["x"], mp["y"])
                                    result["max_off_lane_m"] = max(result["max_off_lane_m"], round(off, 4))
                                    result["samples"] += 1
                                    trace.append({"lap": lap, "state": v.get("state"), "hold": v.get("hold") is not None,
                                                  "x": round(mp["x"], 3), "y": round(mp["y"], 3), "off": round(off, 4),
                                                  "nav": ns.get("navigation"), "route_pts": (v.get("detail") or {}).get("nav2_route")})
                                return v.get("state") not in ("started", "running", "link_wait") or (
                                    lap >= args.target_laps + 1 and (ns.get("route") or {}).get("active") is True)
                            ft.until(args.budget_s, done, 1.5)
                            result["trace_tail"] = trace[-20:]
                            _, ev = ft.call(f"{cores['rosy_01']}/api/v1/events?limit=60", rest["rosy_01"])
                            _, st = ft.call(f"{cores['rosy_01']}/api/v1/robot/state", rest["rosy_01"])
                            result["core_events"] = ev.get("events", ev)
                            result["core_state"] = {
                                k: st.get(k) for k in (
                                    "mode", "navigation", "localization", "pose", "trip_lease", "trip_lease_ended", "safety"
                                )
                            }
                            cc, cview = ft.call(f"{fleet}/trips/{plan['plan_id']}/cancel", operator, "POST", {}, log)
                            result["cancel_status"] = cc
                            result["canceled_state"] = cview.get("state")
    finally:
        log.close()
        result["left_running"] = ft.stop(run_id)
        if lock is not None:
            lock.unlink(missing_ok=True)
    result["pass"] = (
        result.get("start_status") == 200
        and result["max_lap"] >= args.target_laps + 1
        and result.get("last_state") == "running"
        and result.get("canceled_state") == "canceled"
        and result["samples"] >= 10
        and result["max_off_lane_m"] <= 0.15
    )
    (out / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("[nav2-repeat-loop]", "PASS" if result["pass"] else "FAIL", json.dumps({
        k: result.get(k) for k in ("max_lap", "samples", "max_off_lane_m", "last_state", "last_reason", "canceled_state")
    }), flush=True)
    return 0 if result["pass"] else 1


def nav2_active(ns, run_env):
    out = subprocess.run(["ros2", "lifecycle", "get", f"/{ns}/bt_navigator"], env=run_env,
                         capture_output=True, text=True, timeout=15)
    return out.stdout.strip().startswith("active")


def seed_done(run_env):
    out = subprocess.run(["ros2", "node", "list"], env=run_env, capture_output=True, text=True, timeout=15)
    return out.returncode == 0 and "seed_initialpose" not in out.stdout


def localize_nav(core, token, pose, log):
    _, st = ft.call(f"{core}/api/v1/robot/state", token)
    loc = st.get("localization") or {}
    if loc.get("state") == "LOCALIZED" and loc.get("pose_frame") == "map":
        _, ns = ft.call(f"{core}/api/v1/navigation/state", token)
        return (ns.get("readiness") or {}).get("ready") is True
    if loc.get("state") == "CANDIDATES" and loc.get("request_id"):
        code, report = ft.call(f"{core}/api/v1/localization/candidates", token)
        cands = (report.get("candidates") or []) if code == 200 else []
        best = min(
            ((i, math.hypot(c["x"] - pose[0], c["y"] - pose[1]),
              abs(math.atan2(math.sin(c["yaw"] - pose[2]), math.cos(c["yaw"] - pose[2]))))
             for i, c in enumerate(cands)),
            key=lambda row: (row[1], row[2]), default=None,
        )
        if best is not None and best[1] <= 0.20 and best[2] <= 0.35:
            ft.call(f"{core}/api/v1/localization/decision", token, "POST", {
                "request_id": loc["request_id"], "source": "candidate", "candidate_index": best[0], "cues": ["square"],
            }, log)
            return False
    ft.localize(core, token, pose, log)
    return False


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", required=True)
    p.add_argument("--render", choices=sorted(ft.RENDER), default="cpu")
    p.add_argument("--boot-s", type=float, default=300)
    p.add_argument("--settle-s", type=float, default=8)
    p.add_argument("--budget-s", type=float, default=660)
    p.add_argument("--stall-s", type=float, default=60.0)
    p.add_argument("--target-laps", type=int, default=2)
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
