"""Expose isolated Gazebo Pinky pose and optional front camera snapshots."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.request

CANONICAL_FLEET_ROBOTS = {"pinkys": ["rosy_42", "rosy_45", "rosy_46"], "arms": ["arm_s", "arm_a", "arm_b"]}
_PARKED_PINKYS = {
    "rosy_42": [-0.414, 0.47, 0.0],
    "rosy_45": [-0.1914, 0.47, 0.0],
    "rosy_46": [0.032, 0.47, 0.0],
}
_REST_ARMS = {arm: [0.0, -1.0, 0.7, 0.3, 0.0, 0.0] for arm in CANONICAL_FLEET_ROBOTS["arms"]}


def build_world_state(
    *,
    binding: dict,
    world_id: str,
    sim_time_s: float,
    position: list[float],
    yaw: float,
    site_map_sha256: str,
    observed_at_ms: int | None = None,
) -> dict:
    """Translate isolated Gazebo odom observation into rosy.world.factory-state.v1."""
    robot_id = str(binding.get("robot_id") or "rosy_45")
    active_id = robot_id if robot_id in _PARKED_PINKYS else "rosy_45"
    pose_xyz = [round(float(v), 5) for v in position[:3]]
    yaw_r = round(float(yaw), 5)
    s3_ok = abs(pose_xyz[0] - 0.745) <= 0.04 and abs(pose_xyz[1] + 0.207) <= 0.025
    pinkys = []
    for rid in CANONICAL_FLEET_ROBOTS["pinkys"]:
        if rid == active_id:
            pinkys.append({"id": rid, "pose_m": pose_xyz, "yaw_rad": yaw_r, "observed": True})
        else:
            pinkys.append({"id": rid, "pose_m": list(_PARKED_PINKYS[rid]), "yaw_rad": -1.5708, "observed": False})
    now = time.time_ns() // 1_000_000 if observed_at_ms is None else observed_at_ms
    parity = {
        "schema": "rosy.world.parity.v1",
        "site_map_sha256": str(site_map_sha256 or "").lower(),
        "registration_sha256": None,
        "fleet_robots": CANONICAL_FLEET_ROBOTS,
        "has_cargo_tray": True,
    }
    return {
        "schema": "rosy.world.factory-state.v1",
        "stream_mode": "live",
        "world_id": world_id,
        "adapter": "gazebo",
        "simulator": "gazebo",
        "run_id": binding["run_id"],
        "sim_time_s": round(float(sim_time_s), 3),
        "observed_at_ms": now,
        "has_cargo_tray": True,
        "site_map_sha256": parity["site_map_sha256"],
        "fleet_robots": CANONICAL_FLEET_ROBOTS,
        "parity": parity,
        "stage": "s3_stop" if s3_ok else "c2_departure",
        "phase": "gazebo_live",
        "pinky": {"id": active_id, "pose_m": pose_xyz, "yaw_rad": yaw_r, "has_cargo": True, "s3_in_bounds": s3_ok},
        "pinkys": pinkys,
        "arms": {k: list(v) for k, v in _REST_ARMS.items()},
        "cargo": {"zone": "pinky_tray", "pose_m": [pose_xyz[0], pose_xyz[1], 0.115], "yaw_rad": yaw_r, "observed": False},
        "cell_ab": {"active_arm": None, "active_step": None, "stacked": []},
    }


def _publish_world(worlds_dir: Path | None, world_url: str | None, world_id: str, payload: dict, token: str | None) -> None:
    raw = (json.dumps(payload, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
    if worlds_dir is not None:
        worlds_dir.mkdir(parents=True, exist_ok=True)
        write_snapshot(worlds_dir / f"{world_id}.json", raw)
    if world_url:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"{world_url.rstrip('/')}/api/worlds/{world_id}", data=raw, headers=headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=1.0).close()
        except (OSError, urllib.error.URLError):
            pass


def stamp_ns(stamp):
    return stamp.sec * 1_000_000_000 + stamp.nanosec


def finite(value, length):
    return isinstance(value, (list, tuple)) and len(value) == length and all(
        type(item) in (int, float) and math.isfinite(item) for item in value
    )


def load_binding(path):
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("expected a binding object")
    robot = value.get("robot_id")
    odom = (value.get("odom_topic"), value.get("odom_frame_id"))
    if (not isinstance(robot, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", robot)
            or odom not in ((f"/{robot}/odom", f"{robot}/odom"), ("/odom", "odom"))
            or not re.fullmatch(r"sim-[a-z0-9-]{1,80}", str(value.get("run_id", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("site_cad_sha256", "")))
            or not finite(value.get("site_from_odom"), 3)):
        raise ValueError("invalid isolated simulation binding")
    return value


def site_pose(position, quaternion, transform):
    if not finite(position, 3) or not finite(quaternion, 4) or not math.isclose(
        math.hypot(*quaternion), 1, abs_tol=0.01
    ):
        raise ValueError("invalid odometry pose")
    x, y, z = position
    qx, qy, qz, qw = quaternion
    tx, ty, theta = transform
    yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz)) + theta
    return [tx + x * math.cos(theta) - y * math.sin(theta),
            ty + x * math.sin(theta) + y * math.cos(theta), z], math.remainder(yaw, math.tau)


def write_snapshot(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--camera", action="store_true", help="also expose the bound Gazebo JPEG preview")
    parser.add_argument("--world-id", help="optional parallel world_id for data/worlds/<world_id>.json or HTTP ingest")
    parser.add_argument("--world-url", help="optional Rosy World HTTP server base URL")
    parser.add_argument("--world-mdns-host", help="optional Rosy World .local mDNS hostname")
    parser.add_argument("--world-port", type=int, default=8140)
    parser.add_argument("--worlds-dir", type=Path, help="optional directory for worlds/<world_id>.json")
    parser.add_argument("--site-map-sha256", help="canonical 64-hex site map SHA-256")
    parser.add_argument("--ingest-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    args = parser.parse_args()
    if args.world_id and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", args.world_id):
        parser.error("invalid --world-id")
    target_world_url = args.world_url
    if not target_world_url and args.world_mdns_host:
        import sys

        if str(Path(__file__).resolve().parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
        import world_mdns

        target_world_url = world_mdns.discover_world_endpoint(args.world_mdns_host, default_port=args.world_port)
    worlds_dir = args.worlds_dir if args.worlds_dir is not None else (None if target_world_url else args.out.parent / "worlds")
    ingest_token = os.environ.get(args.ingest_token_env, "").strip() or None
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    if (not domain.isdecimal() or not 0 < int(domain) <= 232
            or os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST"):
        parser.error("a non-default ROS domain and LOCALHOST discovery are required")
    try:
        binding = load_binding(args.binding)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    camera_topic = binding.get("camera_topic")
    if args.camera and camera_topic not in (
        "/camera/preview/compressed", f"/{binding['robot_id']}/camera/preview/compressed"
    ):
        parser.error("camera requires an explicit Gazebo preview topic in the binding")

    import rclpy
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import CompressedImage
    from rclpy.executors import ExternalShutdownException
    from rclpy.qos import qos_profile_sensor_data

    rclpy.init()
    node = rclpy.create_node("world_pinky_observer")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    topic = binding["odom_topic"]
    clock_ns = last_pose_ns = last_write_ns = 0
    last_camera_ns = last_camera_write_ns = 0
    clock_is_advancing = False

    def clock(msg):
        nonlocal clock_ns, clock_is_advancing, last_pose_ns, last_camera_ns
        tick = stamp_ns(msg.clock)
        if tick < clock_ns:
            clock_is_advancing = False
            last_pose_ns = 0
            last_camera_ns = 0
        elif tick > clock_ns:
            clock_is_advancing = clock_ns > 0
        clock_ns = tick

    def odom(msg):
        nonlocal last_pose_ns, last_write_ns
        stamp = stamp_ns(msg.header.stamp)
        now = time.monotonic_ns()
        if (not clock_is_advancing or stamp <= last_pose_ns or abs(stamp - clock_ns) > 250_000_000
                or now - last_write_ns < 100_000_000 or msg.header.frame_id != binding["odom_frame_id"]
                or node.count_publishers(topic) != 1 or node.count_publishers("/clock") != 1):
            return
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        try:
            position, yaw = site_pose((p.x, p.y, p.z), (q.x, q.y, q.z, q.w), binding["site_from_odom"])
            snapshot = {
                "schema": "rosy.world.pinky-sim.v1", "run_id": binding["run_id"], "robot_id": binding["robot_id"],
                "site_cad_sha256": binding["site_cad_sha256"], "frame_id": "world_261026_cad",
                "observed_at_ms": time.time_ns() // 1_000_000, "sim_time_s": stamp / 1_000_000_000,
                "pose_m": position, "yaw_rad": yaw,
                "linear_m_s": msg.twist.twist.linear.x, "angular_rad_s": msg.twist.twist.angular.z,
            }
            write_snapshot(args.out, json.dumps(snapshot, allow_nan=False).encode("utf-8"))
            if args.world_id:
                site_map_sha = (args.site_map_sha256 or binding.get("site_map_sha256") or "").lower()
                world_payload = build_world_state(
                    binding=binding,
                    world_id=args.world_id,
                    sim_time_s=stamp / 1_000_000_000,
                    position=position,
                    yaw=yaw,
                    site_map_sha256=site_map_sha,
                    observed_at_ms=snapshot["observed_at_ms"],
                )
                _publish_world(worlds_dir, target_world_url, args.world_id, world_payload, ingest_token)
        except ValueError:
            return
        last_pose_ns, last_write_ns = stamp, now

    def camera(msg):
        nonlocal last_camera_ns, last_camera_write_ns
        stamp = stamp_ns(msg.header.stamp)
        now = time.monotonic_ns()
        if (not clock_is_advancing or stamp <= last_camera_ns or abs(stamp - clock_ns) > 250_000_000
                or now - last_camera_write_ns < 200_000_000 or node.count_publishers(camera_topic) != 1
                or node.count_publishers("/clock") != 1 or not msg.format.startswith("jpeg;")
                or not msg.format.endswith("; source=gz") or not 4 <= len(msg.data) <= 512_000):
            return
        content = bytes(msg.data)
        if not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
            return
        write_snapshot(args.out.with_name("pinky-camera.jpg"), content)
        last_camera_ns, last_camera_write_ns = stamp, now

    node.create_subscription(Clock, "/clock", clock, qos_profile_sensor_data)
    node.create_subscription(Odometry, topic, odom, qos_profile_sensor_data)
    if args.camera:
        node.create_subscription(CompressedImage, camera_topic, camera, qos_profile_sensor_data)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
