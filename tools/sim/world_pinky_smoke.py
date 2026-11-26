"""Run a single Pinky CORE/Nav2 smoke from archived C2 to its front staging point P2."""

import argparse
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from fleet_trips import call, until
from route_drive import OdomTrace, nav2_active, nav_state

ROBOT = "rosy_01"
C2 = (-0.190, 0.470, -math.pi / 2)
P2 = (-0.190, 0.022)
CAD_SHA256 = "dd91457a4a8d17d7fbb4fbfdb12dff9c2ae98e92e74760231c9ec08aa377f3cc"
REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    run_id = os.environ.get("GZ_PARTITION", "")
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    if not run_id.startswith("sim-") or not domain.isdecimal() or not 0 < int(domain) <= 232 or (
        os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST"
        or os.environ.get("GZ_IP") != "127.0.0.1"
    ):
        parser.error("run in the isolated remote_sim Gazebo job")
    os.environ["RMW_IMPLEMENTATION"] = "rmw_cyclonedds_cpp"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    token = "rosy-dev-operator"  # Existing gz_multi throwaway loopback credential.
    cmd = [
        "ros2", "launch", "gz_sim", "gz_multi.launch.py",
        "robots:=1", "world_name:=map_world_261026.world", "headless:=true",
        # The smoke submits one explicit initial pose after Nav2 activates.
        "mode:=nav", "core:=true", "loc_assist:=false", "seed_initialpose:=false", f"api_port_base:={port}",
        "spawn_poses:=" + ",".join(map(str, C2)),
    ]
    result = {"run_id": run_id, "stage": "C2-to-P2-core-smoke", "source_revision": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(), "goal_xy_m": P2, "pass": False}
    trace = None
    observer = None
    with (out / "launch.log").open("w") as launch_log, (out / "api-log.jsonl").open("w") as api_log:
        launch = subprocess.Popen(cmd, stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            def core_ready():
                if launch.poll() is not None:
                    raise RuntimeError("Gazebo launch terminated")
                return call(f"{base}/api/v1/robot/state", token)[1].get("robot_id") == ROBOT

            if not until(120, core_ready, 2):
                raise RuntimeError("simulated CORE did not become ready")
            trace = OdomTrace(ROBOT)
            if not until(30, trace.mark, 0.5):
                raise RuntimeError("Gazebo odometry did not arrive")
            if not until(90, lambda: nav2_active(ROBOT, os.environ), 2):
                raise RuntimeError("Nav2 navigator did not become active")
            endpoint = f"{base}/api/v1/localization/initialpose"
            if not until(60, lambda: call(endpoint, token, "POST", dict(zip(("x", "y", "yaw"), C2)), api_log)[0] == 200, 3):
                raise RuntimeError("CORE refused the simulated initial pose")
            if not until(90, lambda: (nav_state(base, token).get("readiness") or {}).get("ready") is True, 2):
                raise RuntimeError("CORE did not report navigation readiness")
            publishers = trace.node.get_publishers_info_by_topic(f"/{ROBOT}/cmd_vel")
            result["cmd_vel_publishers"] = [f"{p.node_namespace}/{p.node_name}" for p in publishers]
            if result["cmd_vel_publishers"] != [f"/{ROBOT}/core"]:
                raise RuntimeError("CORE is not the sole simulated cmd_vel publisher")
            binding = out / "pinky-binding.json"
            binding.write_text(json.dumps({
                "run_id": run_id, "robot_id": ROBOT, "odom_topic": f"/{ROBOT}/odom",
                "odom_frame_id": f"{ROBOT}/odom", "site_cad_sha256": CAD_SHA256, "site_from_odom": [0, 0, 0],
            }), encoding="utf-8")
            snapshot = out / "data" / "pinky-sim.json"
            snapshot.parent.mkdir()
            observer = subprocess.Popen([
                sys.executable, str(REPO / "applications/world/observe_pinky.py"),
                "--binding", str(binding), "--out", str(snapshot),
            ])
            if not until(15, snapshot.is_file, 0.2):
                raise RuntimeError("Pinky observation bridge produced no snapshot")
            start_pose = json.loads(snapshot.read_bytes())["pose_m"]
            result["start_pose_m"] = start_pose
            if math.dist(start_pose[:2], C2[:2]) > 0.05:
                raise RuntimeError("Gazebo odometry origin differs from the archived C2 frame")
            def localized_pose():
                robot = call(f"{base}/api/v1/robot/state", token)[1]
                loc = robot.get("localization") or {}
                return {"pose": robot.get("pose"), "state": loc.get("state"), "frame": loc.get("pose_frame")}

            def seeded_at_c2():
                state = localized_pose()
                estimate = state["pose"] or {}
                x, y = estimate.get("x"), estimate.get("y")
                if (isinstance(x, (int, float)) and isinstance(y, (int, float))
                        and math.dist((x, y), C2[:2]) <= 0.075):
                    result["start_localization"] = state
                    return True
                return False

            if not until(20, seeded_at_c2, 0.25):
                raise RuntimeError("CORE pose does not reflect the C2 seed")
            start = trace.mark()
            code, response = call(f"{base}/api/v1/navigation/goal", token, "POST",
                                  {"x": P2[0], "y": P2[1], "yaw": C2[2]}, api_log)
            result["goal_status"] = code
            if code != 200:
                raise RuntimeError(f"CORE refused P2: {response.get('error')}")
            def terminal():
                state = nav_state(base, token).get("navigation")
                return state if state in ("ARRIVED", "FAILED", "CANCELED") else None

            result["navigation"] = terminal() if until(100, terminal, 0.5) else None
            result["last_navigation_state"] = nav_state(base, token).get("navigation")
            time.sleep(2)
            samples = trace.since(start)
            result["end_pose_m"] = json.loads(snapshot.read_bytes())["pose_m"]
            result["end_localization"] = localized_pose()
            result["position_error_m"] = math.dist(result["end_pose_m"][:2], P2)
            result["moved"] = any(v > 0.02 for _, v, _ in samples)
            result["stopped"] = len(samples) >= 2 and all(abs(v) < 0.01 and abs(w) < 0.02 for _, v, w in samples[-2:])
            result["pass"] = (result["navigation"] == "ARRIVED" and result["position_error_m"] <= 0.15
                              and result["stopped"] and result["moved"])
        except (OSError, RuntimeError, ValueError) as error:
            result["error"] = str(error)
        finally:
            if observer is not None and observer.poll() is None:
                observer.send_signal(signal.SIGINT)
                try:
                    observer.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    observer.kill()
                    observer.wait()
            if trace is not None:
                trace.close()
            if launch.poll() is None:
                os.killpg(launch.pid, signal.SIGINT)
            (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
