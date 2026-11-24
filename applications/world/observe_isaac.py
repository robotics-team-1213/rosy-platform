#!/usr/bin/env python3
"""Export read-only Isaac simulation observations to an existing World bundle."""

import argparse
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path
import urllib.error
import urllib.request

CLOCK, JOINTS, OBJECTS = "/clock", "/sim/joint_states", "/sim/object_tf"
NANOSECOND = 1_000_000_000
SIM_WINDOW = NANOSECOND // 2
WALL_WINDOW = 1.0
CANONICAL_FLEET_ROBOTS = {"pinkys": ["rosy_42", "rosy_45", "rosy_46"], "arms": ["arm_s", "arm_a", "arm_b"]}
_REST_ARM = [0.0, -1.0, 0.7, 0.3, 0.0, 0.0]
_PARKED_PINKYS = {
    "rosy_42": [-0.414, 0.47, 0.0],
    "rosy_45": [-0.1914, 0.47, 0.0],
    "rosy_46": [0.032, 0.47, 0.0],
}


def _yaw_from_xyzw(q: list[float]) -> float:
    qx, qy, qz, qw = q
    return round(math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz)), 5)


def _bundle_site_map_sha256(bundle: Path) -> str:
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key, entry in (manifest.get("inputs") or {}).items():
                if key.endswith("_active.json") and isinstance(entry, dict) and entry.get("sha256"):
                    return str(entry["sha256"]).lower()
        except (OSError, ValueError):
            pass
    return ""


def build_world_state(
    *,
    run_id: str,
    world_id: str,
    state: str,
    sim_time_s: float,
    joints: list[dict],
    objects: list[dict],
    site_map_sha256: str,
    scene: str = "conformance",
    observed_at_ms: int | None = None,
) -> dict:
    """Translate Isaac ROS 2 /sim observations into a canonical rosy.world.factory-state.v1 payload."""
    arms = {name: list(_REST_ARM) for name in CANONICAL_FLEET_ROBOTS["arms"]}
    generic_arm = list(_REST_ARM)
    for item in joints:
        name = str(item.get("name") or "")
        pos = float(item.get("position_rad") or 0.0)
        matched = re.match(r"^(arm_[sab])_(?:joint(\d+)|(gripper))$", name)
        if matched:
            arm_id, j_idx, grip = matched.groups()
            slot = 5 if grip else int(j_idx) - 1
            if 0 <= slot < 6:
                arms[arm_id][slot] = round(pos, 5)
            continue
        g_match = re.match(r"^(?:joint(\d+)|(gripper))$", name)
        if g_match:
            j_idx, grip = g_match.groups()
            slot = 5 if grip else int(j_idx) - 1
            if 0 <= slot < 6:
                generic_arm[slot] = round(pos, 5)
    if scene == "ab" and arms["arm_s"] == _REST_ARM and generic_arm != _REST_ARM:
        arms["arm_a"] = generic_arm
    elif arms["arm_s"] == _REST_ARM and generic_arm != _REST_ARM:
        arms["arm_s"] = generic_arm

    pinky_poses = {rid: {"id": rid, "pose_m": list(pos), "yaw_rad": -1.5708, "observed": False}
                   for rid, pos in _PARKED_PINKYS.items()}
    cargo = {"zone": "s3", "pose_m": [0.745, -0.207, 0.055], "yaw_rad": 0.0, "observed": False}
    for obj in objects:
        oid = str(obj.get("id") or "")
        pos = [round(float(v), 5) for v in (obj.get("position_m") or [0.0, 0.0, 0.0])[:3]]
        yaw = _yaw_from_xyzw(list(obj.get("orientation_xyzw") or [0.0, 0.0, 0.0, 1.0])[:4])
        if oid in pinky_poses or oid == "pinky":
            target = "rosy_45" if oid == "pinky" else oid
            pinky_poses[target] = {"id": target, "pose_m": pos, "yaw_rad": yaw, "observed": True}
        elif "cargo" in oid or "container" in oid:
            cargo = {"zone": oid, "pose_m": pos, "yaw_rad": yaw, "observed": True}

    primary = next((p for p in pinky_poses.values() if p["observed"]), pinky_poses["rosy_45"])
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
        "adapter": "isaac",
        "simulator": "isaac",
        "run_id": run_id,
        "sim_time_s": round(float(sim_time_s), 3),
        "observed_at_ms": now,
        "has_cargo_tray": True,
        "site_map_sha256": parity["site_map_sha256"],
        "fleet_robots": CANONICAL_FLEET_ROBOTS,
        "parity": parity,
        "stage": "ab_stack" if scene == "ab" else "arm_s_to_belt",
        "phase": f"isaac_{state}",
        "pinky": {
            "id": primary["id"],
            "pose_m": primary["pose_m"],
            "yaw_rad": primary["yaw_rad"],
            "has_cargo": True,
            "s3_in_bounds": True,
        },
        "pinkys": [pinky_poses[rid] for rid in CANONICAL_FLEET_ROBOTS["pinkys"]],
        "arms": arms,
        "cargo": cargo,
        "cell_ab": {"active_arm": "arm_a" if scene == "ab" else None, "active_step": scene, "stacked": []},
    }


def _publish_world(worlds_dir: Path | None, world_url: str | None, world_id: str, payload: dict, token: str | None) -> None:
    raw = (json.dumps(payload, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
    if worlds_dir is not None:
        worlds_dir.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=worlds_dir, prefix=f".{world_id}.", suffix=".tmp", delete=False) as h:
                temp_path = Path(h.name)
                h.write(raw)
                h.flush()
            try:
                temp_path.replace(worlds_dir / f"{world_id}.json")
                temp_path = None
            except PermissionError:
                pass
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
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
    if stamp.sec >= 0 and 0 <= stamp.nanosec < NANOSECOND:
        return stamp.sec * NANOSECOND + stamp.nanosec
    return -1


def valid_ids(ids):
    return ids and all(value and value == value.strip() for value in ids)


class Observation:
    def __init__(self):
        self.topology = None
        self.clock_ns = self.last_clock_ns = -1
        self.advanced_at = None
        self.reset_count = 0
        self.streams = {}
        self.paused_at_clock = None

    def clear(self):
        self.streams.clear()
        self.paused_at_clock = None

    def on_clock(self, message):
        stamp = stamp_ns(message.clock)
        if stamp < 0:
            self.clear()
            self.clock_ns, self.advanced_at = -1, None
            return
        if 0 <= self.last_clock_ns and stamp < self.last_clock_ns:
            self.reset_count += 1
            self.clear()
            self.advanced_at = None
        elif 0 <= self.clock_ns < stamp:
            self.advanced_at = time.monotonic()
            self.paused_at_clock = None
        self.clock_ns = self.last_clock_ns = stamp

    def on_joints(self, message):
        names, values = message.name, message.position
        stamp = stamp_ns(message.header.stamp)
        if (stamp < 0 or not valid_ids(names) or len(set(names)) != len(names)
                or len(names) != len(values) or not all(map(math.isfinite, values))):
            self.clear()
            return
        self.streams[JOINTS] = (time.monotonic(), [stamp], [
            {"name": name, "position_rad": position} for name, position in zip(names, values)])

    def on_objects(self, message):
        stamps, values, ids = [], [], set()
        for item in message.transforms:
            name, frame = item.child_frame_id, item.header.frame_id
            stamp = stamp_ns(item.header.stamp)
            p, q = item.transform.translation, item.transform.rotation
            position, rotation = [p.x, p.y, p.z], [q.x, q.y, q.z, q.w]
            if stamp < 0 or not valid_ids([name, frame]) or name in ids or not all(map(math.isfinite, position + rotation)):
                self.clear()
                return
            ids.add(name)
            stamps.append(stamp)
            values.append({"id": name, "frame_id": frame, "position_m": position, "orientation_xyzw": rotation})
        if not values:
            self.clear()
            return
        self.streams[OBJECTS] = (time.monotonic(), stamps, values)

    def snapshot(self, node):
        endpoints = [node.get_publishers_info_by_topic(topic) for topic in (CLOCK, JOINTS, OBJECTS)]
        topology = tuple(bytes(group[0].endpoint_gid) for group in endpoints) if all(len(group) == 1 for group in endpoints) else None
        if topology != self.topology or topology is None:
            self.clear()
            self.topology = topology
            self.clock_ns, self.advanced_at = -1, None
            return ("stopped" if self.last_clock_ns >= 0 else "waiting"), [], []
        if self.advanced_at is None or len(self.streams) != 2:
            return "waiting", [], []
        if any(not 0 <= self.clock_ns - stamp <= SIM_WINDOW for _, stamps, _ in self.streams.values() for stamp in stamps):
            self.paused_at_clock = None
            return "waiting", [], []
        now = time.monotonic()
        if now - self.advanced_at < WALL_WINDOW:
            if any(now - received >= WALL_WINDOW for received, _, _ in self.streams.values()):
                self.clear()
                return "waiting", [], []
            self.paused_at_clock = self.clock_ns
            state = "running"
        elif self.paused_at_clock == self.clock_ns:
            state = "paused"
        else:
            return "waiting", [], []
        return state, self.streams[JOINTS][2], self.streams[OBJECTS][2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sim-domain-id", required=True, type=int)
    parser.add_argument("--scene", choices=("conformance", "ab"), default="conformance")
    parser.add_argument("--layout-sha256")
    parser.add_argument("--world-id", help="optional parallel world_id for data/worlds/<world_id>.json or HTTP ingest")
    parser.add_argument("--world-url", help="optional Rosy World HTTP server base URL")
    parser.add_argument("--world-mdns-host", help="optional Rosy World .local mDNS hostname")
    parser.add_argument("--world-port", type=int, default=8140)
    parser.add_argument("--worlds-dir", type=Path, help="optional directory for worlds/<world_id>.json")
    parser.add_argument("--site-map-sha256", help="canonical 64-hex site map SHA-256")
    parser.add_argument("--ingest-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    data = (bundle / "data").resolve()
    if data.parent != bundle or not data.is_dir() or not all(
            (bundle / name).is_file() for name in ("index.html", "manifest.json", "SHA256SUMS.txt")):
        parser.error("--bundle must name an existing World bundle with a local data directory")
    if args.world_id and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", args.world_id):
        parser.error("invalid --world-id")
    if not 1 <= args.sim_domain_id <= 232 or not valid_ids([args.run_id]):
        parser.error("give a dedicated --sim-domain-id (1–232) and a nonempty --run-id")
    if ((args.scene == "ab" and not re.fullmatch(r"[0-9a-f]{64}", args.layout_sha256 or ""))
            or (args.scene == "conformance" and args.layout_sha256 is not None)):
        parser.error("a lowercase SHA-256 is required for --scene ab and exclusive to it")
    site_map_sha = (args.site_map_sha256 or _bundle_site_map_sha256(bundle)).lower()
    target_world_url = args.world_url
    if not target_world_url and args.world_mdns_host:
        import sys

        if str(Path(__file__).resolve().parent) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
        import world_mdns

        target_world_url = world_mdns.discover_world_endpoint(args.world_mdns_host, default_port=args.world_port)
    worlds_dir = args.worlds_dir if args.worlds_dir is not None else (None if target_world_url else data / "worlds")
    ingest_token = os.environ.get(args.ingest_token_env, "").strip() or None
    os.environ.update(ROS_DOMAIN_ID=str(args.sim_domain_id), ROS_AUTOMATIC_DISCOVERY_RANGE="LOCALHOST",
                      ROS_STATIC_PEERS="", RMW_IMPLEMENTATION="rmw_fastrtps_cpp", SKIP_DEFAULT_XML="1")
    for name in ("ROS_DISCOVERY_SERVER", "ROS_LOCALHOST_ONLY", "FASTDDS_DEFAULT_PROFILES_FILE", "FASTRTPS_DEFAULT_PROFILES_FILE"):
        os.environ.pop(name, None)
    observation = Observation()

    def write(state, joints, objects):
        sim_time_s = max(0, observation.clock_ns) / NANOSECOND
        payload = json.dumps({
            "schema": "rosy.world.isaac-state.v1", "run_id": args.run_id, "scene": args.scene,
            "layout_sha256": args.layout_sha256, "observed_at_ms": time.time_ns() // 1_000_000,
            "sim_time_s": sim_time_s, "reset_count": observation.reset_count,
            "state": state, "joints": joints, "objects": objects,
        }, allow_nan=False)
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=data, delete=False)
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(payload)
            try:
                temporary.replace(data / "isaac-live.json")
            except PermissionError:
                # An HTTP reader can hold the prior file open on Windows; try again next tick.
                pass
        finally:
            temporary.unlink(missing_ok=True)
        if args.world_id and state == "running":
            world_payload = build_world_state(
                run_id=args.run_id,
                world_id=args.world_id,
                state=state,
                sim_time_s=sim_time_s,
                joints=joints,
                objects=objects,
                site_map_sha256=site_map_sha,
                scene=args.scene,
            )
            _publish_world(worlds_dir, target_world_url, args.world_id, world_payload, ingest_token)

    try:
        import rclpy
        from rclpy.executors import ExternalShutdownException
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from rosgraph_msgs.msg import Clock
        from sensor_msgs.msg import JointState
        from tf2_msgs.msg import TFMessage
    except ImportError as error:
        parser.error(f"source the local ROS 2 Jazzy environment: {error}")

    class SubscriberNode(Node):
        def create_publisher(self, msg_type, topic, *args, **kwargs):
            if topic == "/parameter_events":
                # Jazzy Node constructs this publisher internally, before returning.
                return type("DiscardParameterEvents", (), {"publish": lambda self, message: None})()
            raise RuntimeError("the World observer cannot publish ROS messages")

    rclpy.init(args=[], domain_id=args.sim_domain_id)
    node = SubscriberNode("rosy_world_isaac_observer", enable_rosout=False, start_parameter_services=False,
                          parameter_overrides=[Parameter("start_type_description_service", value=False)])
    try:
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        node.create_subscription(Clock, CLOCK, observation.on_clock, qos)
        node.create_subscription(JointState, JOINTS, observation.on_joints, qos)
        node.create_subscription(TFMessage, OBJECTS, observation.on_objects, qos)
        write("waiting", [], [])
        next_write = time.monotonic()
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
            if time.monotonic() >= next_write:
                write(*observation.snapshot(node))
                next_write = time.monotonic() + 0.2
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        try:
            write("stopped", [], [])
        finally:
            node.destroy_node()
            rclpy.try_shutdown()


if __name__ == "__main__":
    main()
