#!/usr/bin/env python3
"""Live web viewer for a Gazebo lane-network mission: mission phase and
timeline, a live track map with route progress, camera and perception
overlay, the perception tier, CORE's state, parking and past runs, served
over HTTP so a Windows browser can watch a WSL Gazebo run at
http://localhost:<port>.

Usage (WSL, `~/rosy_mapv2_ws` install sourced; runs straight from source):
  ROS_DOMAIN_ID=57 python3 lane_live_view.py \
      --graph ~/rosy_mapv2_ws/install/control/share/control/map/map_v2_fleet/lane_graph.yaml \
      --evidence /rosy_mapv2_ws/evidence --port 28183
  python3 lane_live_view.py --graph <lane_graph.yaml> --demo   # no ROS, canned run

Endpoints (GET only): / (page), /overlay.mjpg, /camera.mjpg, /status.json,
/graph.json, /runs.json, /run/<id>.json, /common/<name> (shared-assets.json).

Observation only: this node creates no publishers and no service clients,
and only ever GETs CORE's API; it never touches motion authority. It
survives Gazebo relaunches between scenarios (DDS simply rediscovers when a
fresh launch starts); a pose jump, an odom silence gap or a sim clock that
goes backwards starts a new run (trail, route progress, tier counts).

ROS imports (rclpy, nav_msgs, sensor_msgs, std_msgs, rosgraph_msgs) are
deferred into build_node() so this module's HTTP/MJPEG/state logic stays
importable and testable on a host without ROS 2 (e.g. the Windows dev
host), same pattern as junction_harness.py.
"""

import argparse
import json
import math
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_view_model as model  # noqa: E402
from lane_live_view_helpers import (  # noqa: E402, F401
    BOUNDARY,
    CORE_STALE_S,
    DEFAULT_TRAIL,
    DOCK_MARKER_XY,
    FPS_WINDOW_S,
    MJPEG_CONTENT_TYPE,
    MJPEG_POLL_S,
    OBS_STALE_S,
    ODOM_SILENCE_RESET_S,
    POSE_JUMP_RESET_M,
    STREAM_STALE_S,
    TRAIL_SEND_MAX,
    FrameStream,
    Trail,
    ViewerState,
    _age,
    _alert,
    _fresh,
    _polylines,
    _wall_offset,
    build_status,
    graph_payload,
    load_graph,
    mjpeg_part,
    yaw_from_quaternion,
)

DEFAULT_PORT = 28183
DEFAULT_CORE_URL = "http://127.0.0.1:8080"
DEFAULT_EVIDENCE = Path("/rosy_mapv2_ws/evidence")
STATUS_PATH = "/api/v1/line-follow"
ROBOT_STATE_PATH = "/api/v1/robot/state"
DOCKING_STATUS_PATH = "/api/v1/docking/status"
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
CORE_POLL_S = 0.5
CORE_TIMEOUT_S = 2.0
#: A live mission harness's core_status.jsonl is re-read at most this often.
LOG_POLL_S = 1.0
#: Raw `camera/front` is re-encoded to JPEG at at most this rate.
CAMERA_MAX_HZ = 5.0
PAGE_PATH = Path(__file__).resolve().with_name("lane_live_view.html")


def web_common_dir():
    """Installed web_common share when it ships shared-assets.json, else the source tree."""
    try:
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory("web_common"))
    except (ImportError, LookupError):
        share = None
    if share and (share / "shared-assets.json").is_file():
        return share
    return Path(__file__).resolve().parents[4] / "shared" / "web"


COMMON = web_common_dir()
_MANIFEST = COMMON / "shared-assets.json"
#: name -> media type: the only /common allowlist (never scan the folder). No web_common -> all 404.
COMMON_ASSETS = json.loads(_MANIFEST.read_text(encoding="utf-8"))["shared_assets"] if _MANIFEST.is_file() else {}
_RUN_PATH = re.compile(r"^/run/([^/]+)\.json$")


def _get_json(url, timeout=CORE_TIMEOUT_S):
    """GET one CORE document with the viewer token; None on any failure."""
    req = urllib.request.Request(url, headers=VIEWER)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def poll_core(core_url, timeout=CORE_TIMEOUT_S):
    """GET CORE's line-follow status; None on any failure so the poll loop keeps retrying."""
    return _get_json(core_url.rstrip("/") + STATUS_PATH, timeout)


def poll_core_status(core_url, get=_get_json, timeout=CORE_TIMEOUT_S):
    """GET line-follow, robot state and docking (viewer token); `ok` if CORE answered any."""
    base = core_url.rstrip("/")
    out = {"line_follow": get(base + STATUS_PATH, timeout),
           "robot": get(base + ROBOT_STATE_PATH, timeout),
           "docking": get(base + DOCKING_STATUS_PATH, timeout)}
    out["ok"] = any(v is not None for v in out.values())
    return out


def render_index_html():
    """lane_live_view.html next to this script; its only external resources are /common/ assets."""
    return PAGE_PATH.read_text(encoding="utf-8")


def make_handler(state):
    """Build a BaseHTTPRequestHandler bound to `state` via closure (the
    stdlib server passes only (request, client_address, server) to the
    handler class, so state cannot be an __init__ argument). GET only: any
    other method gets the stdlib's 501."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "RosyLaneLiveView/2.0"

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            run, asset = _RUN_PATH.match(path), path.removeprefix("/common/")
            if path in ("/", "/index.html"):
                self._send(render_index_html().encode("utf-8"), "text/html; charset=utf-8")
            elif path.startswith("/common/") and asset in COMMON_ASSETS and (COMMON / asset).is_file():
                self._send((COMMON / asset).read_bytes(), f"{COMMON_ASSETS[asset]}; charset=utf-8")
            elif path == "/overlay.mjpg":
                self._stream_mjpeg(state.overlay)
            elif path == "/camera.mjpg":
                self._stream_mjpeg(state.camera)
            elif path == "/status.json":
                self._send_json(state.status(time.monotonic()))
            elif path == "/graph.json":
                self._send_json(state.graph)
            elif path == "/runs.json":
                runs = model.list_runs(state.evidence_dir) if state.evidence_dir else []
                self._send_json({"evidence": str(state.evidence_dir or ""), "runs": runs})
            elif run and state.evidence_dir:
                found = model.load_run(state.evidence_dir, run.group(1))
                if found is None:
                    self.send_error(404)
                else:
                    self._send_json(found)
            else:
                self.send_error(404)

        def _send_json(self, obj):
            self._send(json.dumps(obj).encode("utf-8"), "application/json")

        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _stream_mjpeg(self, stream):
            self.send_response(200)
            self.send_header("Content-Type", MJPEG_CONTENT_TYPE)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last_ts = None
            try:
                while True:
                    frame, ts = stream.latest()
                    if frame is not None and ts != last_ts:
                        self.wfile.write(mjpeg_part(frame))
                        self.wfile.flush()
                        last_ts = ts
                    time.sleep(MJPEG_POLL_S)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    return Handler


# --------------------------------------------------------------------------
# ROS wiring (rclpy deferred here)
# --------------------------------------------------------------------------


def build_node(args, state):
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import CompressedImage, Image
    from std_msgs.msg import String

    rclpy.init()
    node = Node("lane_live_view")
    last_camera_encode = {"t": 0.0}

    def on_overlay(msg):
        state.overlay.publish(bytes(msg.data), time.monotonic())

    def on_camera(msg):
        now = time.monotonic()
        if now - last_camera_encode["t"] < 1.0 / CAMERA_MAX_HZ:
            return
        if msg.encoding not in ("bgr8", "rgb8"):
            return
        arr = np.frombuffer(msg.data, dtype=np.uint8)
        try:
            image = arr.reshape(msg.height, msg.width, 3)
        except ValueError:
            return
        if msg.encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", image)
        if not ok:
            return
        last_camera_encode["t"] = now
        state.camera.publish(buf.tobytes(), now)

    def json_callback(setter):
        def on_msg(msg):
            try:
                setter(json.loads(msg.data), time.monotonic())
            except (json.JSONDecodeError, ValueError, AttributeError):
                pass
        return on_msg

    def on_odom(msg):
        now = time.monotonic()
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)
        v = msg.twist.twist.linear
        speed = math.hypot(v.x, v.y)
        state.add_pose(x, y, yaw, now, speed)

    def on_clock(msg):
        state.on_clock(msg.clock.sec + msg.clock.nanosec * 1e-9, time.monotonic())

    node.create_subscription(CompressedImage, "line/debug/compressed", on_overlay, qos_profile_sensor_data)
    node.create_subscription(Image, "camera/front", on_camera, qos_profile_sensor_data)
    node.create_subscription(String, "line/observation", json_callback(state.set_observation), 10)
    node.create_subscription(String, "dock/observation", json_callback(state.set_dock_observation), 10)
    node.create_subscription(String, "road/observation", json_callback(state.set_road_observation), 10)
    node.create_subscription(Odometry, "odom", on_odom, qos_profile_sensor_data)
    node.create_subscription(Clock, "/clock", on_clock, qos_profile_sensor_data)
    return node, rclpy


def spin(rclpy_module, node, stop_event):
    """Runs on a background thread so the HTTP server's main-thread loop is
    never blocked by ROS callbacks. Keeps spinning across Gazebo relaunches
    between scenarios; DDS rediscovers publishers on its own."""
    while not stop_event.is_set():
        rclpy_module.spin_once(node, timeout_sec=0.1)


def core_poll_loop(state, core_url, stop_event):
    """Runs on its own thread: CORE's HTTP API is polled with blocking
    urllib GETs, which must never happen on the ROS callback thread. Also
    re-reads a live mission harness log and re-derives the phase."""
    next_log = 0.0
    while not stop_event.is_set():
        now = time.monotonic()
        state.set_core_status(poll_core_status(core_url), now)
        if state.evidence_dir and now >= next_log:
            state.set_log_phase(model.live_log_phase(state.evidence_dir, time.time()))
            next_log = now + LOG_POLL_S
        state.tick(time.monotonic())
        stop_event.wait(CORE_POLL_S)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL)
    parser.add_argument("--trail", type=int, default=DEFAULT_TRAIL)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE,
                        help="evidence dir with junctions_/tour_/mission_ runs")
    parser.add_argument("--route", nargs="+", metavar="KEY",
                        help="route keys (default: lane_coverage's all-lane tour)")
    parser.add_argument("--demo", action="store_true",
                        help="no ROS, no CORE: replay a canned mission")
    args = parser.parse_args(argv)

    raw = yaml.safe_load(args.graph.read_text(encoding="utf-8"))
    route = [k.strip("[],") for k in args.route] if args.route else None
    state = ViewerState.from_raw_graph(raw, trail_maxlen=args.trail, route_keys=route,
                                       evidence_dir=args.evidence)
    stop_event = threading.Event()
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(state))

    def handle_sigint(signum, frame):
        stop_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, handle_sigint)
    print(f"lane_live_view: http://localhost:{args.port}/", flush=True)

    if args.demo:
        import live_view_demo

        demo = live_view_demo.DemoSource(state)
        threading.Thread(target=demo.run, args=(stop_event,), daemon=True).start()
        try:
            httpd.serve_forever()
        finally:
            stop_event.set()
            httpd.server_close()
        return 0

    node, rclpy_module = build_node(args, state)
    poll_thread = threading.Thread(
        target=core_poll_loop, args=(state, args.core_url, stop_event), daemon=True)
    poll_thread.start()
    ros_thread = threading.Thread(
        target=spin, args=(rclpy_module, node, stop_event), daemon=True)
    ros_thread.start()
    try:
        httpd.serve_forever()
    finally:
        stop_event.set()
        httpd.server_close()
        node.destroy_node()
        if rclpy_module.ok():
            rclpy_module.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
