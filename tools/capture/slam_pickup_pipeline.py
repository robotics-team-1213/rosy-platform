"""slam_pickup_pipeline.py — End-to-end 360-deg SLAM mapping, peer pose relay, Nav2 cargo pickup, and deterministic stop pipeline.

    slam_pickup_pipeline.py --base-url https://rosy-pinky-y8xs.local:8080 --ca-file /etc/rosy/tls/ca.pem
                            [--map-name mapping_45_loop] [--slam-forward-m 0.22] [--slam-turn-rad 6.283]
                            [--pickup-x 0.45] [--pickup-y 0.0] [--pickup-yaw 0.0] [--pickup-dwell-s 2.0]
                            [--return-home] [--skip-slam]

Stages:
1. Preflight & Safety Guard (`preflight_judge`, `verify_preflight_sensors`):
   - Verify battery >= 7.0 V, fresh LiDAR scan & odometry, E-Stop inactive, and `PINKY_PRO` LiDAR clearance.
   - Suspend `rosy-os-update.timer` during active SLAM/Nav2 run.
2. Stage 1 — 360-deg SLAM Mapping (`start_standalone_slam`, `drive_slam_loop_steps`, `install_site_map_files`):
   - Drive forward excursion (`+slam_forward_m`), 360-deg (`2 * pi` rad) scan rotation, and reverse to origin.
   - Save `/var/lib/rosy/maps/<map_name>.{yaml,pgm}` and install `/var/lib/rosy/maps/site.{yaml,pgm}` (`0640`).
3. Stage 2 — Nav2 Autonomous Pickup Dispatch (`dispatch_pickup_and_return`, `normalize_swarm_pose_frame`):
   - Start `rosy-navigation` via `POST /api/v1/navigation/approval/navigation-start`, navigate to pickup zone, dwell, and optionally return home.
4. Stage 3 — Deterministic Stop (`deterministic_stop` in `finally`):
   - Cancel active goals, send 3x zero velocity in `MANUAL`, enter `IDLE`, verify `robot_still`, and restore `rosy-io.service` + `rosy-os-update.timer`.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

HERE = Path(__file__).resolve().parent
if len(HERE.parents) > 1 and (HERE.parents[1] / "contracts" / "foundation").is_dir():
    REPO = HERE.parents[1]
    if str(REPO / "contracts" / "foundation") not in sys.path:
        sys.path.insert(0, str(REPO / "contracts" / "foundation"))

from core_common.robot_body import PINKY_PRO  # noqa: E402

LINEAR_MPS = 0.04
ANGULAR_RPS = 0.35
TICK_S = 0.1
STALE_S = 0.5
LOW_BATTERY_V = 7.0
FORWARD_DEG = 180.0
PATH_MARGIN_M = 0.05
STILL_LINEAR_MAX_MPS = 0.005
STILL_ANGULAR_MAX_RPS = 0.01


@dataclass(frozen=True)
class SlamLoopConfig:
    forward_m: float = 0.22
    turn_rad: float = 2.0 * math.pi
    linear_mps: float = LINEAR_MPS
    angular_rps: float = ANGULAR_RPS
    tick_s: float = TICK_S
    forward_deg: float = FORWARD_DEG
    path_margin_m: float = PATH_MARGIN_M
    forward_timeout_s: float = 20.0
    turn_timeout_s: float = 35.0
    reverse_timeout_s: float = 20.0


@dataclass(frozen=True)
class PickupNav2Config:
    pickup_x: float = 0.45
    pickup_y: float = 0.0
    pickup_yaw: float = 0.0
    pickup_dwell_s: float = 2.0
    return_home: bool = True
    home_x: float = 0.0
    home_y: float = 0.0
    home_yaw: float = 0.0
    goal_timeout_s: float = 35.0
    ready_timeout_s: float = 45.0


def stop_threshold_m(linear_mps: float = LINEAR_MPS, margin_m: float = PATH_MARGIN_M, body=PINKY_PRO) -> float:
    return body.stop_gap_m(abs(linear_mps)) + margin_m


def preflight_judge(scan_dict: dict, forward_deg: float = FORWARD_DEG, body=PINKY_PRO) -> dict:
    pts = body.scan_view(scan_dict, forward_deg=forward_deg).points
    return {
        "forward_gap": body.translation_gap(pts),
        "reverse_gap": body.translation_gap(pts, reverse=True),
        "can_rotate": body.can_rotate(pts),
        "rotation_gap": body.rotation_gap(pts),
    }


def verify_preflight_sensors(
    latest: dict, now_monotonic: float, stale_s: float = STALE_S, low_battery_v: float = LOW_BATTERY_V
) -> tuple[bool, str | None]:
    if "scan" not in latest or "scan_t" not in latest:
        return False, "missing_scan"
    if "odom" not in latest or "odom_t" not in latest:
        return False, "missing_odom"
    if now_monotonic - float(latest["scan_t"]) >= stale_s:
        return False, "stale_scan"
    if now_monotonic - float(latest["odom_t"]) >= stale_s:
        return False, "stale_odom"
    if "volt" not in latest:
        return False, "missing_battery"
    if float(latest["volt"]) < low_battery_v:
        return False, "low_battery"
    return True, None


def angle_delta_abs(curr_yaw: float, prev_yaw: float) -> float:
    return abs(math.atan2(math.sin(curr_yaw - prev_yaw), math.cos(curr_yaw - prev_yaw)))


def is_robot_still(
    velocity: dict | None, max_linear_mps: float = STILL_LINEAR_MAX_MPS, max_angular_rps: float = STILL_ANGULAR_MAX_RPS
) -> tuple[bool, float, float]:
    vel = velocity or {}
    lin = float(vel.get("linear", 0.0) or 0.0)
    ang = float(vel.get("angular", 0.0) or 0.0)
    return abs(lin) <= max_linear_mps and abs(ang) <= max_angular_rps, lin, ang


def normalize_swarm_pose_frame(frame: dict, fallback_map_id: str) -> dict:
    cloned = json.loads(json.dumps(frame))
    payload = cloned.setdefault("payload", {})
    if not payload.get("map_id"):
        payload["map_id"] = fallback_map_id
    return cloned


def install_site_map_files(
    map_base: str | Path, site_dir: str | Path = "/var/lib/rosy/maps", run_cmd: Callable[..., object] = subprocess.run
) -> dict:
    base_path, target_dir = Path(map_base), Path(site_dir)
    yaml_src, pgm_src = base_path.with_suffix(".yaml"), base_path.with_suffix(".pgm")
    if not yaml_src.exists() or not pgm_src.exists():
        raise FileNotFoundError(f"Missing saved SLAM map files: {yaml_src} or {pgm_src}")
    site_yaml, site_pgm = target_dir / "site.yaml", target_dir / "site.pgm"
    shutil.copyfile(pgm_src, site_pgm)
    meta = yaml.safe_load(yaml_src.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError(f"Invalid map YAML in {yaml_src}")
    meta["image"] = "site.pgm"
    site_yaml.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    paths = [str(yaml_src), str(pgm_src), str(site_yaml), str(site_pgm)]
    run_cmd(["chown", "rosy-io:rosy-core", *paths], check=True)
    run_cmd(["chmod", "0640", *paths], check=True)
    return meta


def drive_slam_loop_steps(
    api: Callable[[str, dict | None, str | None], dict | None],
    token: str,
    pose_fn: Callable[[], tuple[float, float, float]],
    judge_fn: Callable[[], dict],
    spin_fn: Callable[[float], None],
    cfg: SlamLoopConfig = SlamLoopConfig(),
    clock_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    need = stop_threshold_m(cfg.linear_mps, cfg.path_margin_m)
    start_p = pose_fn()
    travelled_fwd, turned_total, travelled_back = 0.0, 0.0, 0.0
    stop_reason = "completed"
    try:
        state = api("/api/v1/robot/state", None, token) or {}
        if state.get("estop") or (state.get("safety") or {}).get("estop"):
            raise RuntimeError("Refused: E-Stop active")
        api("/api/v1/mode", {"mode": "MANUAL"}, token)

        last, t0 = pose_fn(), clock_fn()
        while travelled_fwd < cfg.forward_m and clock_fn() - t0 < cfg.forward_timeout_s:
            spin_fn(cfg.tick_s)
            cur = pose_fn()
            travelled_fwd += math.dist(last[:2], cur[:2])
            last = cur
            j = judge_fn()
            if j.get("forward_gap") is not None and j["forward_gap"] <= need:
                stop_reason = "forward_gap_limit"
                break
            api("/api/v1/teleop", {"linear": cfg.linear_mps, "angular": 0.0}, token)
        api("/api/v1/teleop", {"linear": 0.0, "angular": 0.0}, token)
        spin_fn(0.4)

        last, t0 = pose_fn(), clock_fn()
        while turned_total < cfg.turn_rad and clock_fn() - t0 < cfg.turn_timeout_s:
            spin_fn(cfg.tick_s)
            cur = pose_fn()
            turned_total += angle_delta_abs(cur[2], last[2])
            last = cur
            if not judge_fn().get("can_rotate", False):
                stop_reason = "rotation_gap_limit"
                break
            api("/api/v1/teleop", {"linear": 0.0, "angular": cfg.angular_rps}, token)
        api("/api/v1/teleop", {"linear": 0.0, "angular": 0.0}, token)
        spin_fn(0.4)

        last, t0 = pose_fn(), clock_fn()
        while travelled_back < travelled_fwd and clock_fn() - t0 < cfg.reverse_timeout_s:
            spin_fn(cfg.tick_s)
            cur = pose_fn()
            travelled_back += math.dist(last[:2], cur[:2])
            last = cur
            j = judge_fn()
            if j.get("reverse_gap") is not None and j["reverse_gap"] <= need:
                stop_reason = "reverse_gap_limit"
                break
            api("/api/v1/teleop", {"linear": -cfg.linear_mps, "angular": 0.0}, token)
        api("/api/v1/teleop", {"linear": 0.0, "angular": 0.0}, token)
        spin_fn(0.6)
    finally:
        for _ in range(3):
            try:
                api("/api/v1/teleop", {"linear": 0.0, "angular": 0.0}, token)
            except Exception:
                pass
            sleep_fn(0.1)
        try:
            api("/api/v1/mode", {"mode": "IDLE"}, token)
        except Exception:
            pass
        end_p = pose_fn()

    return {
        "stop_reason": stop_reason,
        "start_pose": [round(x, 3) for x in start_p],
        "end_pose": [round(x, 3) for x in end_p],
        "travelled_fwd_m": round(travelled_fwd, 3),
        "turned_rad": round(turned_total, 3),
        "turned_deg": round(math.degrees(turned_total), 1),
        "travelled_back_m": round(travelled_back, 3),
    }


def wait_for_nav2_ready(
    api: Callable[[str, dict | None, str | None], dict | None],
    token: str,
    timeout_s: float = 45.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    for i in range(max(1, int(timeout_s))):
        sleep_fn(1.0)
        caps = api("/api/v1/system/capabilities", None, token) or {}
        st = api("/api/v1/robot/state", None, token) or {}
        if (caps.get("navigation") or {}).get("goal_navigation") and st.get("pose") is not None:
            m = api("/api/v1/map", None, token) or {}
            return {
                "ready_after_s": i + 1,
                "pose": st.get("pose"),
                "map": {k: m.get(k) for k in ("width", "height", "resolution", "origin")},
            }
    raise RuntimeError(f"Nav2 failed to become ready within {timeout_s}s")


def wait_for_nav2_goal(
    api: Callable[[str, dict | None, str | None], dict | None],
    token: str,
    timeout_s: float = 35.0,
    clock_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    t0 = clock_fn()
    while clock_fn() - t0 < timeout_s:
        sleep_fn(0.5)
        nst = api("/api/v1/navigation/state", None, token) or {}
        rst = api("/api/v1/robot/state", None, token) or {}
        status = nst.get("navigation") or rst.get("navigation")
        if status in ("ARRIVED", "FAILED", "CANCELED", "ABORTED"):
            return {
                "navigation": status,
                "result": (nst.get("operation") or {}).get("result"),
                "map_id": nst.get("map_id"),
                "pose": rst.get("pose"),
                "odom_pose": rst.get("odom_pose"),
                "velocity": rst.get("velocity"),
                "elapsed_s": round(clock_fn() - t0, 2),
            }
    raise TimeoutError("Nav2 goal did not reach terminal state within timeout")


def dispatch_pickup_and_return(
    api: Callable[[str, dict | None, str | None], dict | None],
    token: str,
    cfg: PickupNav2Config = PickupNav2Config(),
    clock_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    nav_start = api("/api/v1/navigation/approval/navigation-start", {}, token) or {}
    ready_info = wait_for_nav2_ready(api, token, timeout_s=cfg.ready_timeout_s, sleep_fn=sleep_fn)
    pickup_goal = {"x": round(cfg.pickup_x, 3), "y": round(cfg.pickup_y, 3), "theta": round(cfg.pickup_yaw, 3)}
    pickup_dispatch = api("/api/v1/navigation/goal", pickup_goal, token)
    pickup_outcome = wait_for_nav2_goal(api, token, timeout_s=cfg.goal_timeout_s, clock_fn=clock_fn, sleep_fn=sleep_fn)
    if pickup_outcome["navigation"] != "ARRIVED":
        raise RuntimeError(f"Pickup navigation did not arrive: {pickup_outcome}")
    sleep_fn(cfg.pickup_dwell_s)

    home_outcome = None
    if cfg.return_home:
        home_goal = {"x": round(cfg.home_x, 3), "y": round(cfg.home_y, 3), "theta": round(cfg.home_yaw, 3)}
        api("/api/v1/navigation/goal", home_goal, token)
        home_outcome = wait_for_nav2_goal(api, token, timeout_s=cfg.goal_timeout_s, clock_fn=clock_fn, sleep_fn=sleep_fn)
        if home_outcome["navigation"] != "ARRIVED":
            raise RuntimeError(f"Return-home navigation did not arrive: {home_outcome}")
    return {
        "approval_valid": (nav_start.get("approval") or {}).get("valid"),
        "nav2_ready": ready_info,
        "pickup_goal": pickup_goal,
        "pickup_dispatch": pickup_dispatch,
        "pickup_outcome": pickup_outcome,
        "home_outcome": home_outcome,
    }


def deterministic_stop(
    api: Callable[[str, dict | None, str | None], dict | None],
    token: str,
    restore_io_and_timer: bool = True,
    run_cmd: Callable[..., object] = subprocess.run,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    for cancel_path in ("/api/v1/navigation/cancel", "/api/v1/swarm/cancel"):
        try:
            api(cancel_path, {}, token)
        except Exception:
            pass
    try:
        api("/api/v1/mode", {"mode": "MANUAL"}, token)
        for _ in range(3):
            api("/api/v1/teleop", {"linear": 0.0, "angular": 0.0}, token)
            sleep_fn(0.08)
    except Exception:
        pass
    try:
        api("/api/v1/mode", {"mode": "IDLE"}, token)
    except Exception:
        pass

    sleep_fn(0.4)
    st = api("/api/v1/robot/state", None, token) or {}
    still, lin, ang = is_robot_still(st.get("velocity"))
    if restore_io_and_timer:
        for unit in ("rosy-standalone-slam", "rosy-navigation.service"):
            run_cmd(["systemctl", "stop", unit], capture_output=True)
            run_cmd(["systemctl", "reset-failed", unit], capture_output=True)
        run_cmd(["systemctl", "start", "rosy-io.service"], check=True)
        run_cmd(["systemctl", "start", "rosy-os-update.timer"], check=True)

    def _unit_state(unit: str) -> str:
        res = run_cmd(["systemctl", "is-active", unit], capture_output=True, text=True)
        return getattr(res, "stdout", "").strip()

    return {
        "mode": st.get("mode"),
        "navigation": st.get("navigation"),
        "velocity": {"linear": lin, "angular": ang},
        "robot_still_verified": still,
        "pose": st.get("pose"),
        "odom_pose": st.get("odom_pose"),
        "services": {
            "rosy-io.service": _unit_state("rosy-io.service"),
            "rosy-navigation.service": _unit_state("rosy-navigation.service"),
            "rosy-os-update.timer": _unit_state("rosy-os-update.timer"),
        },
    }


def make_api_client(base_url: str, ca_file: str):
    ctx = ssl.create_default_context(cafile=ca_file)

    def api(path: str, body: dict | None = None, token: str | None = None) -> dict | None:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(base_url + path, headers=headers, data=data)
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None

    return api


def pair_operator_token(api: Callable[[str, dict | None, str | None], dict | None], label: str = "slam-pickup-pipeline") -> str:
    out = subprocess.run(
        ["rosy-login-code", "--role", "operator", "--minutes", "10"], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", out)
    if not match:
        raise RuntimeError("Failed to generate operator pairing code")
    res = api("/api/v1/auth/pair", {"code": match[0], "label": label}, None)
    if not res or "token" not in res:
        raise RuntimeError("Failed to pair operator token")
    return res["token"]


def start_standalone_slam(
    ns: str, run_cmd: Callable[..., object] = subprocess.run, sleep_fn: Callable[[float], None] = time.sleep
) -> None:
    mapper_path = pathlib.Path("/opt/rosy/current/install/share/navigation/params/mapper_params.yaml")
    params = yaml.safe_load(mapper_path.read_text(encoding="utf-8"))["slam_toolbox"]["ros__parameters"]
    params.update(
        odom_frame=f"{ns}/odom", map_frame=f"{ns}/map", base_frame=f"{ns}/base_footprint",
        scan_topic=f"/{ns}/scan", mode="mapping", minimum_travel_distance=0.08,
        minimum_travel_heading=0.12, use_lifecycle_manager=False, map_name=f"/{ns}/map",
    )
    bench = pathlib.Path("/run/rosy-standalone-slam")
    bench.mkdir(mode=0o755, exist_ok=True)
    path = bench / "params.yaml"
    path.write_text(yaml.safe_dump({f"/{ns}/slam_toolbox": {"ros__parameters": params}}), encoding="utf-8")
    path.chmod(0o644)

    run_cmd(["systemctl", "stop", "rosy-standalone-slam"], capture_output=True)
    run_cmd(["systemctl", "reset-failed", "rosy-standalone-slam"], capture_output=True)
    run_cmd(
        [
            "systemd-run", "--unit=rosy-standalone-slam", "--collect",
            "-p", "User=rosy-io", "-p", "Group=rosy-io",
            "-p", "EnvironmentFile=/etc/rosy/runtime.env",
            "-p", "Environment=ROS_HOME=/var/log/rosy-io",
            "-p", "Environment=ROS_LOG_DIR=/var/log/rosy-io",
            "-p", "Environment=HOME=/run/rosy-standalone-slam",
            "/usr/bin/bash", "--noprofile", "--norc", "-c",
            "source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && "
            f"exec /opt/ros/jazzy/lib/slam_toolbox/sync_slam_toolbox_node --ros-args -r __node:=slam_toolbox -r __ns:=/{ns} --params-file {path}",
        ],
        check=True,
    )
    sleep_fn(7.0)
    for step in ("configure", "activate"):
        run_cmd(
            [
                "bash", "--noprofile", "--norc", "-c",
                f"set -a; source /etc/rosy/runtime.env; set +a; source /opt/ros/jazzy/setup.bash; timeout 15 ros2 lifecycle set /{ns}/slam_toolbox {step}",
            ],
            capture_output=True, text=True, check=True,
        )
    sleep_fn(3.0)


def run_slam_loop_and_save(
    api: Callable[[str, dict | None, str | None], dict | None],
    token: str,
    ns: str,
    map_name: str,
    cfg: SlamLoopConfig = SlamLoopConfig(),
) -> dict:
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import Float32

    rclpy.init()
    node = rclpy.create_node("rosy_slam_loop_pipeline")
    latest: dict = {}
    node.create_subscription(LaserScan, f"/{ns}/scan", lambda m: latest.update(scan=m, scan_t=time.monotonic()), qos_profile_sensor_data)
    node.create_subscription(Odometry, f"/{ns}/odom", lambda m: latest.update(odom=m, odom_t=time.monotonic()), qos_profile_sensor_data)
    node.create_subscription(Float32, f"/{ns}/battery/voltage", lambda m: latest.update(volt=m.data, volt_t=time.monotonic()), 10)

    def spin(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.02)

    def judge() -> dict:
        s = latest["scan"]
        return preflight_judge(
            {"ranges": list(s.ranges), "angle_min": s.angle_min, "angle_increment": s.angle_increment, "range_min": s.range_min, "range_max": s.range_max},
            forward_deg=cfg.forward_deg,
        )

    def pose() -> tuple[float, float, float]:
        o = latest["odom"].pose.pose
        q = o.orientation
        return o.position.x, o.position.y, math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))

    try:
        spin(2.5)
        deadline = time.monotonic() + 5.0
        while "volt" not in latest and time.monotonic() < deadline:
            spin(0.2)
        ok, err = verify_preflight_sensors(latest, time.monotonic())
        if not ok:
            raise RuntimeError(f"Preflight sensor/battery check failed: {err}")
        need = stop_threshold_m(cfg.linear_mps, cfg.path_margin_m)
        preflight_info = {"ns": ns, "volt": round(float(latest["volt"]), 3), "need_m": round(need, 3), **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in judge().items()}}
        print(json.dumps({"stage": "preflight", "data": preflight_info}), flush=True)
        loop_result = drive_slam_loop_steps(api, token, pose, judge, spin, cfg=cfg)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    map_base = f"/var/lib/rosy/maps/{map_name}"
    for ext in (".yaml", ".pgm"):
        if os.path.exists(map_base + ext):
            os.remove(map_base + ext)
    saved = subprocess.run(
        ["ros2", "service", "call", f"/{ns}/slam_toolbox/save_map", "slam_toolbox/srv/SaveMap", "{name: {data: '" + map_base + "'}}"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    if not (os.path.exists(map_base + ".yaml") and os.path.exists(map_base + ".pgm")):
        raise RuntimeError(f"SLAM map save failed: {saved.stdout}")

    site_meta = install_site_map_files(map_base)
    subprocess.run(["systemctl", "stop", "rosy-standalone-slam"], capture_output=True)
    subprocess.run(["systemctl", "reset-failed", "rosy-standalone-slam"], capture_output=True)
    result = {**loop_result, "saved_map": map_name, "site_yaml": site_meta}
    print(json.dumps({"stage": "slam_mapping_complete", "data": result}), flush=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://rosy-pinky-y8xs.local:8080")
    parser.add_argument("--ca-file", default="/etc/rosy/tls/ca.pem")
    parser.add_argument("--map-name", default="mapping_45_20261111_loop")
    parser.add_argument("--slam-forward-m", type=float, default=0.22)
    parser.add_argument("--slam-turn-rad", type=float, default=6.283)
    parser.add_argument("--skip-slam", action="store_true")
    parser.add_argument("--pickup-x", type=float, default=0.45)
    parser.add_argument("--pickup-y", type=float, default=0.0)
    parser.add_argument("--pickup-yaw", type=float, default=0.0)
    parser.add_argument("--pickup-dwell-s", type=float, default=2.0)
    parser.add_argument("--return-home", action="store_true")
    args = parser.parse_args(argv)

    env = dict(line.split("=", 1) for line in pathlib.Path("/etc/rosy/runtime.env").read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#"))
    ns = env["ROSY_NAMESPACE"]
    api = make_api_client(args.base_url, args.ca_file)
    token = pair_operator_token(api)

    try:
        subprocess.run(["systemctl", "stop", "rosy-os-update.timer"], check=True)
        if not args.skip_slam:
            subprocess.run(["systemctl", "stop", "rosy-navigation.service"], capture_output=True)
            subprocess.run(["systemctl", "reset-failed", "rosy-navigation.service"], capture_output=True)
            subprocess.run(["systemctl", "start", "rosy-io.service"], check=True)
            time.sleep(2.0)
            start_standalone_slam(ns)
            run_slam_loop_and_save(api, token, ns, map_name=args.map_name, cfg=SlamLoopConfig(forward_m=args.slam_forward_m, turn_rad=args.slam_turn_rad))

        nav_cfg = PickupNav2Config(pickup_x=args.pickup_x, pickup_y=args.pickup_y, pickup_yaw=args.pickup_yaw, pickup_dwell_s=args.pickup_dwell_s, return_home=args.return_home)
        nav_result = dispatch_pickup_and_return(api, token, cfg=nav_cfg)
        print(json.dumps({"stage": "nav2_pickup_pipeline_complete", "data": nav_result}), flush=True)
        return 0
    finally:
        try:
            stop_report = deterministic_stop(api, token, restore_io_and_timer=True)
            print(json.dumps({"stage": "deterministic_stop_complete", "data": stop_report}), flush=True)
        finally:
            try:
                api("/api/v1/auth/logout", {}, token)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
