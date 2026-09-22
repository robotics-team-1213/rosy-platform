#!/usr/bin/env python3
"""Run the 12 junction scenarios in headless Gazebo and score them.

Usage (WSL, sourced overlay):
  python3 junction_harness.py --mode centre --out /rosy_mapv2_ws/evidence/junctions_<id> \
      --graph src/apps/control/map/map_v2_fleet/lane_graph.yaml [--only NW]
Per scenario: launch map_v2_fleet_lane at the scenario start, enable
CAMERA_LINE through CORE's API, record /odom (Gazebo ground truth) until the
end point or TIMEOUT_S, then stop, score, and write results.json plus the
overlay MP4 (debug_overlay:=true).

ROS imports (rclpy, nav_msgs) are deferred into run_one() so this module and
its scenario/scoring logic can be imported and exercised on a host without
ROS 2 installed (e.g. the Windows dev host); only actually running a
scenario requires rclpy.
"""

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junction_score  # noqa: E402

TIMEOUT_S = 90.0
BOOT_S = 45.0
API = "http://127.0.0.1:8080/api/v1/line-follow/mode"
OPERATOR = {"Authorization": "Bearer rosy-dev-operator", "Content-Type": "application/json"}


def set_mode(mode):
    req = urllib.request.Request(API, data=json.dumps({"mode": mode}).encode(), method="PUT",
                                 headers=OPERATOR)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def run_one(scenario, graph, mode, out_dir, domain):
    """ROS-only: launches Gazebo, records ground-truth odometry, scores it."""
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
    try:
        time.sleep(BOOT_S)
        recorder = subprocess.Popen(
            ["python3", str(Path(__file__).with_name("record_debug.py")), "--out", str(out_dir),
             "--seconds", str(TIMEOUT_S + 5)], env=env)
        os.environ["ROS_DOMAIN_ID"] = str(domain)
        rclpy.init()
        node = Node("junction_harness")
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
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if track and math.dist(track[-1], end_point) < 0.05:
                break
        set_mode("OFF")
        node.destroy_node()
        rclpy.shutdown()
        result = junction_score.score(graph, scenario, track or [scenario["start"][:2]])
        (out_dir / "track.json").write_text(json.dumps(track))
        return result
    finally:
        if recorder is not None:
            recorder.wait(timeout=TIMEOUT_S + 30)
        os.killpg(launch.pid, signal.SIGINT)
        try:
            launch.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(launch.pid, signal.SIGKILL)


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
