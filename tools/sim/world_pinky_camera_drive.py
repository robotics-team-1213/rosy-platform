"""Exercise the Pinky C2 camera-line controller in an isolated Gazebo lab run."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

import yaml

from fleet_trips import call, until

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "integrations/simulation/gazebo/config/map_261026_core.yaml"
C2 = (-0.19, 0.47)
P2 = (-0.19, 0.022)
S1 = (-0.687, -0.126)  # 261026 archived graph; v261 field tolerances are a separate test.
OPERATOR = "rosy-dev-operator"


def topic_sample(topic, type_name, *, full=False):
    data = subprocess.check_output([
        "ros2", "topic", "echo", topic, type_name, "--once",
        "--qos-reliability", "best_effort", *(["--full-length"] if full else []),
    ], text=True, timeout=7)
    return yaml.safe_load(next(line for line in data.split("\n---") if line.startswith("header:")))


def odom():
    msg = topic_sample("/odom", "nav_msgs/msg/Odometry")
    assert msg["header"]["frame_id"] == "odom"
    pose = msg["pose"]["pose"]["position"]
    speed = msg["twist"]["twist"]
    return {
        "xy": [pose["x"], pose["y"]], "linear": speed["linear"]["x"], "angular": speed["angular"]["z"],
        "stamp": msg["header"]["stamp"],
    }


def inspect_camera(out, result):
    frame = topic_sample("/camera/preview/compressed", "sensor_msgs/msg/CompressedImage", full=True)
    jpeg = bytes(frame["data"])
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("expected a complete Gazebo JPEG preview")
    (out / "front.jpg").write_bytes(jpeg)
    result["camera"] = {"stamp": frame["header"]["stamp"], "format": frame["format"], "bytes": len(jpeg)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pink-centerline", action="store_true")
    parser.add_argument("--world-bundle", type=Path, help="use a generated Gazebo scene and its bound map")
    task = parser.add_mutually_exclusive_group()
    task.add_argument("--request-p2-turn", action="store_true", help="request the westbound turn at observed P2")
    task.add_argument("--expect-p2-hold", action="store_true", help="prove stationary junction wait without a grant")
    task.add_argument("--inspect-y", type=float, help="capture at a fixed C2–P2 spawn without a drive command")
    args = parser.parse_args()
    run_id = os.environ.get("GZ_PARTITION", "")
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    if (not run_id.startswith("sim-") or not domain.isdecimal() or not 0 < int(domain) <= 232
            or os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST"
            or os.environ.get("GZ_IP") != "127.0.0.1"):
        parser.error("requires an isolated remote_sim Gazebo job")
    c2, p2, s1, version, launch_args = C2, P2, S1, 7, []
    if args.world_bundle is not None:
        bundle = args.world_bundle.resolve()
        manifest = json.loads((bundle / "manifest.json").read_bytes())
        world = "worlds/map_world_261026.world"
        if manifest.get("schema") != "rosy.world.gazebo-scene.v1" or not all(
            hashlib.sha256((bundle / name).read_bytes()).hexdigest() == manifest["sha256"][name]
            for name in (world, "site-map.json")
        ):
            parser.error("world bundle and map identities differ")
        envelope = json.loads((bundle / "site-map.json").read_bytes())
        if envelope["version"] != manifest["map_version"]:
            parser.error("world bundle map versions differ")
        places = {place["id"]: (place["x"], place["y"]) for place in envelope["map"]["places"]}
        c2, p2, s1, version = places["C2"], places["P2"], places["S1"], envelope["version"]
        launch_args = [f"world:={bundle / world}"]
    if args.inspect_y is not None and not p2[1] <= args.inspect_y <= c2[1]:
        parser.error("--inspect-y must be between P2 and C2")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    base = f"http://127.0.0.1:{port}/api/v1/line-follow"
    config = yaml.safe_load(CONFIG.read_bytes())
    config["network"]["api_port"] = port
    overlay = out / "core.yaml"
    overlay.write_text(yaml.safe_dump(config), encoding="utf-8")
    inspect = args.inspect_y is not None
    spawn = (c2[0], args.inspect_y) if inspect else c2
    scope = "stationary camera diagnostic" if inspect else "camera-line diagnostic"
    if args.expect_p2_hold:
        scope = "P2 approach wait without a grant"
    result = {"run_id": run_id, "scope": scope, "map_version": version, "c2": c2, "p2": p2, "s1": s1, "pass": False}
    with ((out / "launch.log").open("w") as launch_log,
          (out / "api-log.jsonl").open("w") as api_log,
          (out / "keep-debug.yaml").open("w") as debug_log):
        launch = subprocess.Popen([
            "ros2", "launch", "gz_sim", "map_261026_bay_lane.launch.py",
            "gazebo_gui:=false", f"spawn_x:={spawn[0]}", f"spawn_y:={spawn[1]}", "spawn_yaw:=-1.5708",
            f"core_overlay:={overlay}",
            f"pink_tape_centerline:={'true' if args.pink_centerline else 'false'}",
            *launch_args,
        ], stdout=launch_log, stderr=subprocess.STDOUT, start_new_session=True)
        debug = subprocess.Popen([
            "ros2", "topic", "echo", "/line/keep_debug", "std_msgs/msg/String", "--field", "data", "--full-length",
        ], stdout=debug_log, stderr=subprocess.STDOUT)
        try:
            if not until(75, lambda: call(base, OPERATOR)[0] == 200, 1):
                raise RuntimeError("CORE camera-line endpoint did not become ready")
            start = odom()
            result["start"] = start
            if math.dist(start["xy"], spawn) > 0.04:
                raise RuntimeError("Gazebo model pose did not match the diagnostic spawn")
            if inspect:
                inspect_camera(out, result)
                end = odom()
                result["end"] = end
                result["pass"] = (
                    math.dist(end["xy"], start["xy"]) < .002
                    and all(abs(x["linear"]) < .01 and abs(x["angular"]) < .02 for x in (start, end))
                )
                return 0 if result["pass"] else 1
            code, status = call(base + "/mode", OPERATOR, "PUT", {"mode": "CAMERA_LINE"}, api_log)
            result["mode_reply"] = code
            if code != 200:
                raise RuntimeError(f"CORE refused CAMERA_LINE: {status}")
            observations = []
            end = time.monotonic() + (55 if args.request_p2_turn or args.expect_p2_hold else 25)
            while time.monotonic() < end:
                current = odom()
                _, status = call(base, OPERATOR)
                observations.append({"odom": current, "line": status.get("state"), "reason": status.get("reason")})
                if args.expect_p2_hold:
                    samples = observations[-3:]
                    if (len(samples) == 3 and all(
                            item["reason"] == "junction_waiting" and abs(item["odom"]["linear"]) < .01
                            and abs(item["odom"]["angular"]) < .02 for item in samples)
                            and len({(item["odom"]["stamp"]["sec"], item["odom"]["stamp"]["nanosec"])
                                     for item in samples}) == 3
                            and 0 < current["xy"][1] - p2[1] < .35 and abs(current["xy"][0] - p2[0]) < .07
                            and math.dist(samples[0]["odom"]["xy"], current["xy"]) < .004):
                        result["p2_hold"] = current
                        break
                if (args.request_p2_turn and "p2_turn_reply" not in result and status.get("reason") == "junction_waiting"
                        and math.dist(current["xy"], p2) <= 0.12):
                    # Facing south at C2/P2: the westbound branch is a right turn.
                    action = {"action": "right", "place_id": "P2", "turn_deg": -90,
                              "advance_m": 0, "expires_s": 12}
                    code, response = call(base + "/junction", OPERATOR, "POST", action, api_log)
                    result["p2_turn_reply"] = {"status": code, "response": response, "at": current}
                if math.dist(current["xy"], s1) <= 0.10:
                    break
            result["samples"] = observations
            result["track_states"] = sorted({str(item["line"]) for item in observations})
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            result["error"] = str(error)
        finally:
            if debug.poll() is None:
                debug.send_signal(signal.SIGINT)
            if launch.poll() is None and not inspect:
                call(base + "/mode", OPERATOR, "PUT", {"mode": "OFF"}, api_log)
                try:
                    stops = [odom(), odom()]
                    result["end"] = stops[-1]
                    result["stopped"] = all(abs(x["linear"]) < 0.01 and abs(x["angular"]) < 0.02 for x in stops)
                    result["position_error_m"] = math.dist(stops[-1]["xy"], s1)
                    reached = "p2_hold" in result if args.expect_p2_hold else result["position_error_m"] <= .10
                    result["pass"] = not result.get("error") and result["stopped"] and reached
                except (OSError, ValueError, subprocess.SubprocessError):
                    result["stopped"] = False
            if launch.poll() is None:
                os.killpg(launch.pid, signal.SIGINT)
            (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
