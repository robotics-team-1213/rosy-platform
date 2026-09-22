#!/usr/bin/env python3
"""Run the 12 junction scenarios in headless Gazebo and score them.

Usage (WSL, sourced overlay):
  python3 junction_harness.py --mode centre --out /rosy_mapv2_ws/evidence/junctions_<id> \
      --graph src/apps/control/map/map_v2_fleet/lane_graph.yaml [--only NW]
Per scenario: launch map_v2_fleet_lane at the scenario start, wait for it to
become ready (CORE's API answering and both /odom and /line/observation
flowing) up to BOOT_S, enable CAMERA_LINE through CORE's API, record /odom
(Gazebo ground truth) until the end point or TIMEOUT_S, then stop, score,
and write results.json plus the overlay MP4 (debug_overlay:=true). A
scenario that never boots, never reaches its end point, or raises is still
recorded with a `reason` and does not abort the remaining scenarios.

ROS imports (rclpy, nav_msgs, std_msgs) are deferred into run_one() so this
module and its scenario/scoring logic can be imported and exercised on a
host without ROS 2 installed (e.g. the Windows dev host); only actually
running a scenario requires rclpy.
"""

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junction_score  # noqa: E402

TIMEOUT_S = 90.0
#: Upper bound on the readiness poll; a real boot is much faster, but this
#: is the point at which the scenario is given up on as "never came up".
BOOT_S = 45.0
READY_POLL_S = 0.5
STATUS_API = "http://127.0.0.1:8080/api/v1/line-follow"
MODE_API = "http://127.0.0.1:8080/api/v1/line-follow/mode"
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator", "Content-Type": "application/json"}
SET_MODE_RETRIES = 5
SET_MODE_RETRY_DELAY_S = 1.0
#: How long to let the launch group exit cleanly after SIGINT before SIGKILL.
LAUNCH_STOP_TIMEOUT_S = 15.0
#: How long to let the recorder exit after the launch group is gone.
RECORDER_JOIN_TIMEOUT_S = 15.0
#: Leftover Gazebo/launch processes from THIS scenario only, narrowly
#: matched so an unrelated Gazebo instance on the box is never touched.
LEFTOVER_PATTERNS = ("gz sim .*map_v2_fleet.world", "map_v2_fleet_lane.launch.py")


def _api_ok(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def set_mode(mode):
    """PUT the CAMERA_LINE/OFF mode, retrying a refused connection (the API
    server may not be listening yet on the very first calls after boot)."""
    req_body = json.dumps({"mode": mode}).encode()
    last_error = None
    for attempt in range(SET_MODE_RETRIES):
        try:
            req = urllib.request.Request(MODE_API, data=req_body, method="PUT", headers=OPERATOR)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            if attempt < SET_MODE_RETRIES - 1:
                time.sleep(SET_MODE_RETRY_DELAY_S)
    raise last_error


def wait_ready(node, rclpy_module, deadline):
    """Poll CORE's status API and spin `node` until an /odom message and a
    /line/observation message have both arrived, or `deadline` passes.
    Returns True once ready, False on timeout (a "boot_timeout")."""
    seen = {"odom": False, "line": False}

    def mark(key):
        def _cb(_msg):
            seen[key] = True
        return _cb

    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String

    node.create_subscription(Odometry, "odom", mark("odom"), qos_profile_sensor_data)
    node.create_subscription(String, "line/observation", mark("line"), 10)

    next_poll = 0.0
    api_ready = False
    while time.monotonic() < deadline:
        rclpy_module.spin_once(node, timeout_sec=0.1)
        now = time.monotonic()
        if not api_ready and now >= next_poll:
            api_ready = _api_ok(STATUS_API, VIEWER)
            next_poll = now + READY_POLL_S
        if api_ready and seen["odom"] and seen["line"]:
            return True
    return False


def _kill_leftover_processes(out_dir):
    """Best-effort cleanup of any process from this scenario's launch group
    that survived the group kill (a grandchild that detached into its own
    session). Logs what it found so a leak is visible in launch.log."""
    log_lines = []
    for pattern in LEFTOVER_PATTERNS:
        try:
            found = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        except FileNotFoundError:
            log_lines.append(f"leftover-check: pgrep unavailable, skipped {pattern!r}")
            continue
        pids = found.stdout.split()
        if pids:
            log_lines.append(f"leftover: killing {pattern!r} pids={pids}")
            subprocess.run(["pkill", "-f", pattern])
        else:
            log_lines.append(f"leftover: none for {pattern!r}")
    if out_dir is not None:
        with (out_dir / "launch.log").open("a") as fh:
            fh.write("\n".join(log_lines) + "\n")


def run_one(scenario, graph, mode, out_dir, domain):
    """ROS-only: launches Gazebo, records ground-truth odometry, scores it.

    Always returns a result dict with at least `pass` and `reason`; never
    raises (`main` relies on that so one bad scenario does not abort the
    rest of the run).
    """
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data

    x, y, yaw = scenario["start"]
    env = dict(os.environ, ROS_DOMAIN_ID=str(domain))
    launch = subprocess.Popen(
        ["ros2", "launch", "gz_sim", "map_v2_fleet_lane.launch.py",
         f"spawn_x:={x}", f"spawn_y:={y}", f"spawn_yaw:={yaw}",
         f"camera_lane_mode:={mode}", "debug_overlay:=true"],
        env=env, stdout=(out_dir / "launch.log").open("w"), stderr=subprocess.STDOUT,
        start_new_session=True)
    recorder = None
    rclpy_started = False
    try:
        os.environ["ROS_DOMAIN_ID"] = str(domain)
        rclpy.init()
        rclpy_started = True
        node = Node("junction_harness")
        try:
            boot_deadline = time.monotonic() + BOOT_S
            if not wait_ready(node, rclpy, boot_deadline):
                return {"pass": False, "reason": "boot_timeout"}

            recorder = subprocess.Popen(
                ["python3", str(Path(__file__).with_name("record_debug.py")), "--out", str(out_dir),
                 "--seconds", str(TIMEOUT_S + 5)], env=env)

            track = []
            node.create_subscription(
                Odometry, "odom",
                lambda m: track.append((m.pose.pose.position.x, m.pose.pose.position.y)),
                qos_profile_sensor_data)
            set_mode("CAMERA_LINE")
            end = junction_score.directed_points(graph, scenario["out"])
            s = junction_score._arc_length(end)
            end_point = end[int(s.searchsorted(junction_score.END_AFTER_M))]
            deadline = time.monotonic() + TIMEOUT_S
            reached = False
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
                if track and math.dist(track[-1], end_point) < 0.05:
                    reached = True
                    break
            set_mode("OFF")
            result = junction_score.score(graph, scenario, track or [scenario["start"][:2]])
            result["reason"] = "reached" if reached else "timeout"
            (out_dir / "track.json").write_text(json.dumps(track))
            return result
        finally:
            node.destroy_node()
    except Exception as exc:  # noqa: BLE001 - one scenario's failure must not abort the rest
        return {"pass": False, "reason": f"error:{type(exc).__name__}"}
    finally:
        if rclpy_started:
            rclpy.shutdown()
        # Stop the launch group first, then join the recorder, then make
        # sure nothing from this scenario survives.
        os.killpg(launch.pid, signal.SIGINT)
        try:
            launch.wait(timeout=LAUNCH_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            os.killpg(launch.pid, signal.SIGKILL)
        if recorder is not None:
            try:
                recorder.wait(timeout=RECORDER_JOIN_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                recorder.kill()
        _kill_leftover_processes(out_dir)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="centre")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--domain", type=int, default=57)
    args = parser.parse_args(argv)
    graph = yaml.safe_load(args.graph.read_text(encoding="utf-8"))
    results = []
    for k, scenario in enumerate(junction_score.scenarios(graph)):
        if args.only and scenario["node"] != args.only:
            continue
        out_dir = args.out / f"{k:02d}_{scenario['node']}_{scenario['into']}_to_{scenario['out']}".replace(":", "")
        out_dir.mkdir(parents=True, exist_ok=True)
        result = dict(scenario, **run_one(scenario, graph, args.mode, out_dir, args.domain))
        results.append(result)
        print(json.dumps(result), flush=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    passed = sum(r["pass"] for r in results)
    print(f"{passed}/{len(results)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
