"""Run the World controller beside one owned Gazebo and simulation CORE."""

import argparse
from functools import partial
from hashlib import sha256
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

from fleet_trips import until
from world_pinky_camera_drive import CONFIG, OPERATOR, REPO

sys.path.insert(0, str(REPO / "applications/world"))
from serve import WorldHandler


class Simulation:
    def __init__(self, args, run_id, world, c2, map_version):
        self.args, self.run_id, self.world, self.c2, self.map_version = args, run_id, world, c2, map_version
        self.lock = threading.Lock()
        self.generation = 0
        self.launch = self.observer = self.token = None
        self.sequence = -1
        self.core = None
        self.booting = True
        self.failed = False
        self.data = args.out / "bundle" / "data"

    def api(self, path, body=None):
        if self.core is None or self.launch is None or self.launch.poll() is not None:
            return 503, {}
        req = Request(self.core + "/api/v1/" + path, data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPERATOR}"})
        try:
            with urlopen(req, timeout=.5) as reply:
                return reply.status, json.load(reply)
        except HTTPError as error:
            error.close()
            return error.code, {}
        except (OSError, ValueError):
            return 503, {}

    def spawn(self):
        self.generation += 1
        self.token = None
        config = yaml.safe_load(CONFIG.read_bytes())
        with socket.socket() as port:
            port.bind(("127.0.0.1", 0))
            address = port.getsockname()[1]
        config["network"].update(api_host="127.0.0.1", api_port=address)
        config["runtime"]["mode"] = "simulation"
        overlay = self.args.out / "core.yaml"
        overlay.write_text(yaml.safe_dump(config), encoding="utf-8")
        self.core = f"http://127.0.0.1:{address}"
        with (self.args.out / "simulation.log").open("a") as log:
            self.launch = subprocess.Popen([
                "ros2", "launch", "gz_sim", "map_261026_bay_lane.launch.py", f"world:={self.world}",
                "gazebo_gui:=false", f"spawn_x:={self.c2['x']}", f"spawn_y:={self.c2['y']}",
                f"spawn_yaw:={self.c2['yaw']}", f"core_overlay:={overlay}",
            ], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        if not until(65, lambda: self.api("host/commissioning")[1].get("runtime_mode") == "simulation", .5):
            raise RuntimeError("isolated simulation CORE did not become ready")
        self.bound = {
            "robot_id": "pinky", "odom_topic": "/odom", "odom_frame_id": "odom",
            "run_id": self.run_id, "site_from_odom": [0, 0, 0], "camera_topic": "/camera/preview/compressed",
            "site_cad_sha256": "dd91457a4a8d17d7fbb4fbfdb12dff9c2ae98e92e74760231c9ec08aa377f3cc",
        }
        binding = self.args.out / "binding.json"
        binding.write_text(json.dumps(self.bound), encoding="utf-8")
        with (self.args.out / "observer.log").open("a") as log:
            self.observer = subprocess.Popen([
                sys.executable, str(REPO / "applications/world/observe_pinky.py"),
                "--binding", str(binding), "--out", str(self.data / "pinky-sim.json"), "--camera",
            ], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        if not until(15, lambda: self.pose() is not None and (self.data / "pinky-camera.jpg").is_file(), .2):
            raise RuntimeError("Gazebo pose or camera did not become ready")
        self.booting = self.failed = False

    def pose(self):
        try:
            pose = json.loads((self.data / "pinky-sim.json").read_bytes())
            if (pose["run_id"] == self.run_id
                    and 0 <= time.time_ns() // 1_000_000 - pose["observed_at_ms"] < 2000):
                return pose
        except (OSError, ValueError, KeyError):
            pass
        return None

    def status(self):
        return {"run_id": self.run_id, "generation": self.generation, "map_version": self.map_version,
                "armed": self.token is not None, "booting": self.booting, "failed": self.failed, "pose": self.pose()}

    def halt(self):
        self.token = None
        for proc in (self.observer, self.launch):
            if proc is None:
                continue
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGINT)
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=5)
        self.observer = self.launch = None
        for name in ("pinky-camera.jpg", "pinky-sim.json"):
            (self.data / name).unlink(missing_ok=True)

    def reset(self):
        with self.lock:
            try:
                self.halt()
                self.spawn()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                self.failed, self.booting = True, False
                print(f"World reset failed: {error}", flush=True)

    def command(self, body):
        # Never queue a delayed drive pulse behind a reset or a blocked upstream.
        if not self.lock.acquire(blocking=False):
            return 409, {"error": "simulation_busy"}
        try:
            if body.get("generation") != self.generation or self.booting or self.failed:
                return 409, {"error": "simulation_changed"}
            action = body.get("action")
            if action == "reset":
                if self.token is not None:
                    self.api("teleop", {"linear": 0, "angular": 0})
                self.token, self.booting = None, True
                threading.Thread(target=self.reset, daemon=True).start()
                return 202, self.status()
            if action == "start":
                if self.pose() is None or self.api("host/commissioning")[1].get("runtime_mode") != "simulation":
                    return 409, {"error": "simulation_not_ready"}
                if self.token is not None:
                    self.api("teleop", {"linear": 0, "angular": 0})
                if self.api("mode", {"mode": "MANUAL"})[0] != 200:
                    return 409, {"error": "core_manual_refused"}
                self.token = secrets.token_hex(16)
                self.sequence = -1
                return 200, {"token": self.token}
            if self.token is None or self.token != body.get("token"):
                return 409, {"error": "not_driver"}
            seq = body.get("seq")
            if type(seq) is not int or not self.sequence < seq <= 2**53 - 1:
                return 409, {"error": "stale_input"}
            values = {"forward": (.08, 0), "reverse": (-.06, 0), "left": (0, .55),
                      "right": (0, -.55), "stop": (0, 0)}
            if not isinstance(action, str) or action not in values:
                return 400, {"error": "invalid_action"}
            self.sequence = seq
            linear, angular = values[action]
            if action != "stop" and self.pose() is None:
                return 409, {"error": "observation_lost"}
            accepted = self.api("teleop", {"linear": linear, "angular": angular})[0] == 200
            return (200 if accepted else 409), {"accepted": accepted}
        finally:
            self.lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", required=True, type=Path, help="generated Gazebo bundle")
    parser.add_argument("--web", required=True, type=Path, help="built Rosy World bundle")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--port", default=18141, type=int)
    parser.add_argument("--seconds", default=360, type=int)
    args = parser.parse_args()
    run = os.environ.get("GZ_PARTITION", "")
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    if (not re.fullmatch(r"sim-[a-z0-9-]{1,80}", run) or not domain.isdecimal()
            or not 0 < int(domain) <= 232 or os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST"
            or os.environ.get("GZ_IP") != "127.0.0.1" or not 20 <= args.seconds <= 600):
        parser.error("requires an isolated remote_sim run with a bounded lifetime")
    scene = json.loads((args.world / "manifest.json").read_bytes())
    world = args.world.resolve() / "worlds/map_world_261026.world"
    site = args.world / "site-map.json"
    if scene.get("schema") != "rosy.world.gazebo-scene.v1" or any(
            sha256(file.read_bytes()).hexdigest() != scene["sha256"][name]
            for file, name in ((world, "worlds/map_world_261026.world"), (site, "site-map.json"))):
        parser.error("world bundle differs from its manifest")
    envelope = json.loads(site.read_bytes())
    if envelope["version"] != scene["map_version"]:
        parser.error("world/map version mismatch")
    c2 = next(place for place in envelope["map"]["places"] if place["id"] == "C2")
    args.out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.web, args.out / "bundle")
    controller = Simulation(args, run, world, c2, envelope["version"])
    handler = partial(WorldHandler, directory=str(args.out / "bundle"))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        server.sim_control = controller
        server.health = b'{"application":"rosy-world","status":"ready"}\n'
        server.timeout = .2
        try:
            controller.reset()
            if controller.failed:
                return 1
            print(f"WORLD_PLAY_READY {args.port} {run}", flush=True)
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                server.handle_request()
        finally:
            with controller.lock:
                controller.api("teleop", {"linear": 0, "angular": 0})
                controller.halt()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
