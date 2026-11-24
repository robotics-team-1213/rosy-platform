#!/usr/bin/env python3
"""Virtual 6-robot CORE HTTP/HTTPS fleet (3 Pinky Pros + 3 OMX-AI arms) for closed-loop Fleet simulation."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import math
import os
from pathlib import Path
import ssl
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

SIM_DIR = Path(__file__).resolve().parent
REPO = SIM_DIR.parents[1] if len(SIM_DIR.parents) > 1 and (SIM_DIR.parents[1] / "middleware").is_dir() else SIM_DIR

DEFAULT_PINKY_POSES: dict[str, tuple[float, float, float]] = {
    "rosy_42": (-0.414, 0.47, -math.pi / 2),
    "rosy_45": (-0.1914, 0.47, -math.pi / 2),
    "rosy_46": (0.032, 0.47, -math.pi / 2),
}
DEFAULT_ARM_BASES: dict[str, tuple[float, float, float]] = {
    "arm_s": (0.975, -0.004, math.pi),
    "arm_a": (0.62625, 0.278, 0.0),
    "arm_b": (0.96275, 0.278, math.pi),
}
DEFAULT_ARM_JOINTS: dict[str, list[float]] = {
    "arm_s": [0.18, -0.78, 0.74, 0.72, 1.5708, 0.72],
    "arm_a": [-0.62, -0.78, 0.72, 0.72, 1.5708, 0.72],
    "arm_b": [0.62, -0.78, 0.72, 0.72, 1.5708, 0.72],
}
ARM_PRESETS: dict[str, list[float]] = {
    "home": [0.0, -0.82, 0.78, 0.65, 1.5708, 0.72],
    "pick": [0.35, -0.25, 0.42, 0.85, 1.5708, 0.14],
    "place": [-0.35, -0.22, 0.45, 0.82, 1.5708, 0.72],
}
DEFAULT_ROBOT_ORDER = ("rosy_42", "rosy_45", "rosy_46", "arm_s", "arm_a", "arm_b")
SITE_MAP_GRID = {
    "map_id": "site_map_v2",
    "width": 60,
    "height": 40,
    "resolution": 0.05,
    "origin": {"x": -1.5, "y": -1.0, "yaw": 0.0},
    "data": [0] * (60 * 40),
}


def _wrap_angle(angle: float) -> float:
    return math.remainder(angle, math.tau)


class VirtualRobotState:
    """Thread-safe CORE runtime state + kinematic stepper for one Pinky or OMX arm."""

    def __init__(self, robot_id: str) -> None:
        self.robot_id = robot_id
        self.is_arm = robot_id.startswith("arm_")
        self.boot_id = str(uuid.uuid4())
        self.owner_generation = 1
        self.lock = threading.Lock()
        if self.is_arm:
            bx, by, byaw = DEFAULT_ARM_BASES[robot_id]
            self.pose: list[float] = [bx, by, byaw]
            self.joints: list[float] = list(DEFAULT_ARM_JOINTS[robot_id])
            self.arm_target: list[float] | None = None
        else:
            px, py, pyaw = DEFAULT_PINKY_POSES[robot_id]
            self.pose = [px, py, pyaw]
            self.joints = []
            self.arm_target = None
        self.velocity = {"linear": 0.0, "angular": 0.0}
        self.waypoints: list[dict[str, float]] = []
        self.active_run_id: str | None = None
        self.estop = False
        self.mode = "IDLE"
        self.nav_state = "IDLE"

    def step(self, dt: float) -> None:
        with self.lock:
            if self.estop:
                self.velocity = {"linear": 0.0, "angular": 0.0}
                self.waypoints.clear()
                self.arm_target = None
                self.mode = "EMERGENCY"
                self.nav_state = "IDLE"
                return
            if self.is_arm:
                if self.arm_target is not None:
                    max_delta = 1.6 * dt
                    moved = False
                    for idx in range(6):
                        diff = self.arm_target[idx] - self.joints[idx]
                        if abs(diff) > 1e-3:
                            step_val = max(-max_delta, min(max_delta, diff))
                            self.joints[idx] = round(self.joints[idx] + step_val, 5)
                            moved = True
                        else:
                            self.joints[idx] = round(self.arm_target[idx], 5)
                    if not moved:
                        self.arm_target = None
                        self.mode = "IDLE"
                    else:
                        self.mode = "MOVING"
                return

            if not self.waypoints:
                self.velocity = {"linear": 0.0, "angular": 0.0}
                if self.mode == "NAVIGATING":
                    self.mode = "IDLE"
                    self.nav_state = "ARRIVED"
                return

            target = self.waypoints[0]
            dx = target["x"] - self.pose[0]
            dy = target["y"] - self.pose[1]
            dist = math.hypot(dx, dy)
            v_cmd = 0.0
            w_cmd = 0.0
            if dist > 0.015:
                step_dist = min(dist, 0.45 * dt)
                move_yaw = math.atan2(dy, dx)
                self.pose[0] = round(self.pose[0] + (dx / dist) * step_dist, 5)
                self.pose[1] = round(self.pose[1] + (dy / dist) * step_dist, 5)
                dyaw = _wrap_angle(move_yaw - self.pose[2])
                w_cmd = max(-2.5, min(2.5, dyaw / max(dt, 1e-3)))
                self.pose[2] = round(_wrap_angle(self.pose[2] + max(-2.5 * dt, min(2.5 * dt, dyaw))), 5)
                v_cmd = step_dist / max(dt, 1e-3)
            else:
                self.pose[0] = round(target["x"], 5)
                self.pose[1] = round(target["y"], 5)
                dyaw = _wrap_angle(target["yaw"] - self.pose[2])
                if abs(dyaw) > 0.04:
                    step_w = max(-2.5 * dt, min(2.5 * dt, dyaw))
                    self.pose[2] = round(_wrap_angle(self.pose[2] + step_w), 5)
                    w_cmd = step_w / max(dt, 1e-3)
                else:
                    self.pose[2] = round(target["yaw"], 5)
                    self.waypoints.pop(0)
                    if not self.waypoints:
                        self.mode = "IDLE"
                        self.nav_state = "ARRIVED"
            self.velocity = {"linear": round(v_cmd, 4), "angular": round(w_cmd, 4)}

    def nav_state_detail(self) -> dict[str, Any]:
        with self.lock:
            goal = dict(self.waypoints[-1]) if self.waypoints else None
            return {"state": self.nav_state, "goal": goal, "run_id": self.active_run_id}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            payload: dict[str, Any] = {
                "robot_id": self.robot_id,
                "boot_id": self.boot_id,
                "owner_generation": self.owner_generation,
                "mode": self.mode,
                "map_id": "site_map_v2",
                "localization": {"state": "LOCALIZED", "pose_frame": "map", "confidence": 0.99},
                "pose": {"x": self.pose[0], "y": self.pose[1], "yaw": self.pose[2]},
                "odom_pose": {"x": self.pose[0], "y": self.pose[1], "yaw": self.pose[2]},
                "velocity": dict(self.velocity),
                "battery": {"percent": 92.0, "charging": False},
                "safety": {"estop": self.estop, "source": "fleet" if self.estop else ""},
                "navigation": self.nav_state,
            }
            if self.is_arm:
                payload["joints"] = list(self.joints)
                payload["joint_positions"] = list(self.joints)
                payload["arm"] = {"moving": self.arm_target is not None, "target": list(self.arm_target) if self.arm_target else None}
            return payload

    def capabilities(self) -> dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "navigation": {"goal_navigation": not self.is_arm, "route": not self.is_arm},
            "estop": True,
            "arm": self.is_arm,
        }

    def nav_path(self) -> dict[str, Any]:
        with self.lock:
            poses = [{"x": self.pose[0], "y": self.pose[1], "yaw": self.pose[2]}]
            poses.extend(dict(wp) for wp in self.waypoints)
            return {"map_id": "site_map_v2", "frame_id": "map", "poses": poses}

    def set_goal(self, points: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        with self.lock:
            if self.estop:
                return 409, {"error": "ESTOP_ACTIVE", "mode": self.mode}
            if self.is_arm:
                return 409, {"error": "ARM_ROBOT_NO_BASE_NAV"}
            self.waypoints = [{"x": float(p["x"]), "y": float(p["y"]), "yaw": float(p.get("yaw", 0.0))} for p in points]
            self.active_run_id = str(uuid.uuid4())
            self.mode = "NAVIGATING"
            self.nav_state = "NAVIGATING"
            return 200, {
                "accepted": True,
                "robot_id": self.robot_id,
                "run_id": self.active_run_id,
                "goal": dict(self.waypoints[-1]),
            }

    def set_arm_goal(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        with self.lock:
            if self.estop:
                return 409, {"error": "ESTOP_ACTIVE", "mode": self.mode}
            if not self.is_arm:
                return 409, {"error": "NOT_AN_ARM_ROBOT"}
            target = body.get("joints")
            if target is None and body.get("preset") in ARM_PRESETS:
                target = ARM_PRESETS[body["preset"]]
            if not isinstance(target, list) or len(target) < 5 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in target[:6]):
                return 400, {"error": "INVALID_ARM_JOINTS"}
            padded = [round(float(v), 5) for v in target[:6]]
            if len(padded) < 6:
                padded.extend([0.0] * (6 - len(padded)))
            self.arm_target = padded
            self.mode = "MOVING"
            return 200, {"accepted": True, "robot_id": self.robot_id, "joints": padded}

    def cancel_nav(self) -> dict[str, Any]:
        with self.lock:
            self.waypoints.clear()
            if not self.estop:
                self.mode = "IDLE"
                self.nav_state = "CANCELED"
            return {"canceled": True, "navigation": "CANCELED"}

    def trigger_estop(self) -> dict[str, Any]:
        with self.lock:
            self.estop = True
            self.waypoints.clear()
            self.arm_target = None
            self.velocity = {"linear": 0.0, "angular": 0.0}
            self.mode = "EMERGENCY"
            self.nav_state = "CANCELED"
            return {"estop": True, "mode": "EMERGENCY"}

    def release_estop(self) -> dict[str, Any]:
        with self.lock:
            self.estop = False
            self.mode = "IDLE"
            self.nav_state = "IDLE"
            return {"estop": False, "mode": "IDLE"}


class _RobotHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


def _make_handler(robot: VirtualRobotState, token: str):
    class _Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization") or ""
            scheme, _, supplied = header.partition(" ")
            return scheme.lower() == "bearer" and bool(supplied) and hmac.compare_digest(supplied.strip(), token)

        def _read_json(self) -> dict[str, Any]:
            size = int(self.headers.get("Content-Length") or "0")
            if size <= 0:
                return {}
            return json.loads(self.rfile.read(size).decode("utf-8"))

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz":
                return self._send_json(200, {"ok": True, "robot_id": robot.robot_id})
            if not self._authorized():
                return self._send_json(401, {"error": "UNAUTHORIZED"})
            if path == "/api/v1/robot/state":
                return self._send_json(200, robot.snapshot())
            if path == "/api/v1/system/capabilities":
                return self._send_json(200, robot.capabilities())
            if path == "/api/v1/system/info":
                return self._send_json(200, {"robot_id": robot.robot_id, "boot_id": robot.boot_id, "runtime_mode": "simulation"})
            if path == "/api/v1/map":
                return self._send_json(200, SITE_MAP_GRID)
            if path == "/api/v1/navigation/state":
                return self._send_json(200, robot.nav_state_detail())
            if path == "/api/v1/navigation/path":
                return self._send_json(200, robot.nav_path())
            if path == "/api/v1/docking/status":
                return self._send_json(200, {"state": "IDLE", "docked": False})
            return self._send_json(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if not self._authorized():
                return self._send_json(401, {"error": "UNAUTHORIZED"})
            body = self._read_json()
            if path in ("/api/v1/navigation/goal", "/api/v1/navigation/bound-goal"):
                status, payload = robot.set_goal([body])
                return self._send_json(status, payload)
            if path == "/api/v1/navigation/route":
                pts = body.get("points") or []
                if not pts:
                    return self._send_json(400, {"error": "ROUTE_POINTS_REQUIRED"})
                status, payload = robot.set_goal(pts)
                return self._send_json(status, payload)
            if path == "/api/v1/navigation/cancel":
                return self._send_json(200, robot.cancel_nav())
            if path == "/api/v1/safety/stop":
                return self._send_json(200, robot.trigger_estop())
            if path == "/api/v1/safety/release":
                return self._send_json(200, robot.release_estop())
            if path == "/api/v1/arm/goal":
                status, payload = robot.set_arm_goal(body)
                return self._send_json(status, payload)
            if path == "/api/v1/docking/dock":
                return self._send_json(200, {"accepted": True, "state": "DOCKING"})
            return self._send_json(404, {"error": "NOT_FOUND"})

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return _Handler


class VirtualCoreFleet:
    """Manage all 6 virtual CORE HTTP/HTTPS servers + kinematic tick loop."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        advertise_host: str | None = None,
        base_port: int = 9101,
        token: str = "virtual-core-operator-token",
        tls_cert: Path | None = None,
        tls_key: Path | None = None,
        tls_ca_file: str | None = None,
        world_hook: Any | None = None,
    ) -> None:
        self.host = host
        self.advertise_host = advertise_host or host
        self.base_port = int(base_port)
        self.token = token
        self.tls_cert = tls_cert
        self.tls_key = tls_key
        self.tls_ca_file = tls_ca_file
        self.world_hook = world_hook
        self.robots: dict[str, VirtualRobotState] = {rid: VirtualRobotState(rid) for rid in DEFAULT_ROBOT_ORDER}
        self.servers: dict[str, _RobotHTTPServer] = {}
        self.ports: dict[str, int] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        ssl_ctx = None
        if self.tls_cert is not None and self.tls_key is not None:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(certfile=str(self.tls_cert), keyfile=str(self.tls_key))
        for idx, rid in enumerate(DEFAULT_ROBOT_ORDER):
            port = 0 if self.base_port == 0 else (self.base_port + idx)
            srv = _RobotHTTPServer((self.host, port), _make_handler(self.robots[rid], self.token))
            if ssl_ctx is not None:
                srv.socket = ssl_ctx.wrap_socket(srv.socket, server_side=True)
            self.servers[rid] = srv
            self.ports[rid] = int(srv.server_port)
            t = threading.Thread(target=srv.serve_forever, daemon=True, name=f"vcore-{rid}")
            t.start()
            self._threads.append(t)
        stepper = threading.Thread(target=self._run_loop, daemon=True, name="vcore-stepper")
        stepper.start()
        self._threads.append(stepper)

    def _run_loop(self) -> None:
        started = time.monotonic()
        step_idx = 0
        dt = 0.05
        while not self._stop.is_set():
            tick = time.monotonic()
            for robot in self.robots.values():
                robot.step(dt)
            if self.world_hook is not None and (step_idx % 4 == 0):
                snaps = {rid: r.snapshot() for rid, r in self.robots.items()}
                pinkys = [
                    {
                        "id": rid,
                        "pose_m": [snaps[rid]["pose"]["x"], snaps[rid]["pose"]["y"], 0.0],
                        "yaw_rad": snaps[rid]["pose"]["yaw"],
                        "observed": True,
                    }
                    for rid in ("rosy_42", "rosy_45", "rosy_46")
                ]
                arms = {rid: list(snaps[rid]["joints"]) for rid in ("arm_s", "arm_a", "arm_b")}
                p45 = pinkys[1]
                px, py, _ = p45["pose_m"]
                s3_ok = abs(px - 0.745) <= 0.04 and abs(py + 0.207) <= 0.025
                self.world_hook.publish_step(
                    sim_time_s=tick - started,
                    stage="s3_stop" if s3_ok else "c2_departure",
                    phase="virtual_fleet_closed_loop",
                    pinky={
                        "id": "rosy_45",
                        "pose_m": p45["pose_m"],
                        "yaw_rad": p45["yaw_rad"],
                        "has_cargo": True,
                        "s3_in_bounds": s3_ok,
                    },
                    pinkys=pinkys,
                    arms=arms,
                    episode=1,
                    step=step_idx,
                    sim_fps=20.0,
                )
            step_idx += 1
            elapsed = time.monotonic() - tick
            self._stop.wait(max(0.0, dt - elapsed))

    def robots_entries(self) -> list[dict[str, Any]]:
        scheme = "https" if (self.tls_cert is not None and self.tls_key is not None) else "http"
        entries = []
        for rid in DEFAULT_ROBOT_ORDER:
            row: dict[str, Any] = {
                "robot_id": rid,
                "base_url": f"{scheme}://{self.advertise_host}:{self.ports[rid]}",
                "token": self.token,
            }
            if self.tls_ca_file and scheme == "https":
                row["tls_ca_file"] = self.tls_ca_file
            entries.append(row)
        return entries

    def write_robots_yaml(self, path: Path) -> None:
        lines = ["robots:"]
        for row in self.robots_entries():
            lines.append(f"  - robot_id: {row['robot_id']}")
            lines.append(f"    base_url: {json.dumps(row['base_url'])}")
            lines.append(f"    token: {json.dumps(row['token'])}")
            if "tls_ca_file" in row:
                lines.append(f"    tls_ca_file: {json.dumps(row['tls_ca_file'])}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def close(self) -> None:
        self._stop.set()
        for srv in self.servers.values():
            try:
                srv.shutdown()
                srv.server_close()
            except OSError:
                pass
        if self.world_hook is not None:
            self.world_hook.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--advertise-host", default=None, help="host written to --write-robots-yaml")
    parser.add_argument("--base-port", type=int, default=9101, help="consecutive 6 ports starting here")
    parser.add_argument("--token-env", default="ROSY_VIRTUAL_CORE_TOKEN")
    parser.add_argument("--token", default=None)
    parser.add_argument("--tls-cert", type=Path, default=None)
    parser.add_argument("--tls-key", type=Path, default=None)
    parser.add_argument("--tls-ca-file", default=None)
    parser.add_argument("--write-robots-yaml", type=Path, default=None)
    parser.add_argument("--world-id", default=None)
    parser.add_argument("--world-backend", default="gazebo", choices=("isaac", "gazebo", "mujoco"))
    parser.add_argument("--world-url", default=None)
    parser.add_argument("--world-mdns-host", default=None)
    parser.add_argument("--world-port", type=int, default=8140)
    parser.add_argument("--site-map-sha256", default=None)
    parser.add_argument("--world-token-env", default="ROSY_WORLD_INGEST_TOKEN")
    args = parser.parse_args(argv)

    token = args.token or os.environ.get(args.token_env, "").strip() or "virtual-core-operator-token"
    world_hook = None
    if args.world_id and (args.world_url or args.world_mdns_host):
        if str(SIM_DIR) not in sys.path:
            sys.path.insert(0, str(SIM_DIR))
        from world_env_adapter import TrainingWorldHook
        from world_training_hooks import canonical_parity_inputs

        parity_in = canonical_parity_inputs(REPO, site_map_sha256=args.site_map_sha256)
        world_hook = TrainingWorldHook(
            world_id=args.world_id,
            backend=args.world_backend,
            run_id=f"{args.world_id}-virtual-core",
            site_map_sha256=parity_in["site_map_sha256"],
            world_url=args.world_url,
            world_mdns_host=args.world_mdns_host,
            world_mdns_port=args.world_port,
            token=os.environ.get(args.world_token_env, "").strip() or None,
            physics_profile="virtual-core-6bot",
            cargo_tray=parity_in["cargo_tray"],
        )

    fleet = VirtualCoreFleet(
        host=args.host,
        advertise_host=args.advertise_host or args.host,
        base_port=args.base_port,
        token=token,
        tls_cert=args.tls_cert,
        tls_key=args.tls_key,
        tls_ca_file=args.tls_ca_file,
        world_hook=world_hook,
    )
    fleet.start()
    if args.write_robots_yaml is not None:
        fleet.write_robots_yaml(args.write_robots_yaml)
    print(json.dumps({"robots": fleet.ports, "robots_yaml": str(args.write_robots_yaml) if args.write_robots_yaml else None}), flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        fleet.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
