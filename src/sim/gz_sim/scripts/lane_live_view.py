#!/usr/bin/env python3
"""Live web viewer for a Gazebo lane-following run: camera, perception
overlay and progress, served over HTTP so a Windows browser can watch a WSL
Gazebo run at http://localhost:<port>.

Usage (WSL, sourced overlay):
  ROS_DOMAIN_ID=57 python3 install/gz_sim/lib/gz_sim/lane_live_view.py \
      --graph install/control/share/control/map/map_v2_fleet/lane_graph.yaml \
      --port 28183

Observation only: this node creates no publishers and never touches motion
authority. It survives Gazebo relaunches between scenarios (DDS simply
rediscovers when a fresh `map_v2_fleet_lane.launch.py` starts); the trail
resets itself on a pose jump or an odom silence gap rather than assuming
any particular scenario boundary.

ROS imports (rclpy, nav_msgs, sensor_msgs, std_msgs) are deferred into
build_node()/spin() so this module's HTTP/HTML/MJPEG/state logic stays
importable and testable on a host without ROS 2 (e.g. the Windows dev
host), same pattern as junction_harness.py.
"""

import argparse
import json
import math
import signal
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import yaml

DEFAULT_PORT = 28183
DEFAULT_CORE_URL = "http://127.0.0.1:8080"
DEFAULT_TRAIL = 2000
STATUS_PATH = "/api/v1/line-follow"
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
CORE_POLL_S = 0.5
CORE_TIMEOUT_S = 2.0
#: Raw `camera/front` is re-encoded to JPEG at at most this rate.
CAMERA_MAX_HZ = 5.0
#: A stream with no frame in this long is reported stale / "NO DATA".
STREAM_STALE_S = 2.0
#: Window used to estimate frames-received-per-second for each stream.
FPS_WINDOW_S = 2.0
#: A pose jump bigger than this (metres) between consecutive odom samples
#: means a new scenario started (a Gazebo relaunch teleports the robot);
#: the trail is reset so it does not draw a straight line across the map.
POSE_JUMP_RESET_M = 0.3
#: An odom gap this long also means a new scenario started.
ODOM_SILENCE_RESET_S = 3.0
BOUNDARY = "rosyframe"
MJPEG_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
#: How often the MJPEG stream loop checks for a new frame to push.
MJPEG_POLL_S = 0.05


# --------------------------------------------------------------------------
# ROS-free state and framing logic (importable without rclpy)
# --------------------------------------------------------------------------


class FrameStream:
    """Latest-frame-wins store for one MJPEG source, with an fps/staleness
    health check. Thread-safe: `publish` runs on the ROS callback thread,
    `latest`/`health` run on HTTP handler threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = None
        self._ts = None
        self._recent = deque()

    def publish(self, jpeg_bytes, now):
        with self._lock:
            self._data = jpeg_bytes
            self._ts = now
            self._recent.append(now)
            cutoff = now - FPS_WINDOW_S
            while self._recent and self._recent[0] < cutoff:
                self._recent.popleft()

    def latest(self):
        with self._lock:
            return self._data, self._ts

    def health(self, now, timeout_s=STREAM_STALE_S):
        with self._lock:
            ts = self._ts
            cutoff = now - FPS_WINDOW_S
            count = sum(1 for t in self._recent if t >= cutoff)
        if ts is None:
            return {"ok": False, "age_s": None, "fps": 0.0}
        age = now - ts
        return {"ok": age <= timeout_s, "age_s": round(age, 2), "fps": round(count / FPS_WINDOW_S, 2)}


class Trail:
    """Odometry trail (last `maxlen` points), reset when a new scenario is
    detected: a pose jump bigger than POSE_JUMP_RESET_M, or an odom gap
    longer than ODOM_SILENCE_RESET_S since the previous point."""

    def __init__(self, maxlen=DEFAULT_TRAIL):
        self.points = deque(maxlen=maxlen)
        self._last_xy = None
        self._last_t = None

    def add(self, x, y, now):
        reset = False
        if self._last_xy is not None:
            jump = math.dist((x, y), self._last_xy)
            silence = now - self._last_t
            if jump > POSE_JUMP_RESET_M or silence > ODOM_SILENCE_RESET_S:
                self.points.clear()
                reset = True
        self.points.append((x, y))
        self._last_xy = (x, y)
        self._last_t = now
        return reset

    def as_list(self):
        return list(self.points)


def mjpeg_part(jpeg_bytes):
    """One multipart/x-mixed-replace part: boundary, Content-Type and a
    Content-Length matching the payload, terminated by the frame bytes."""
    header = (
        f"--{BOUNDARY}\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg_bytes)}\r\n\r\n"
    ).encode("ascii")
    return header + jpeg_bytes + b"\r\n"


def yaw_from_quaternion(x, y, z, w):
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def load_graph(path):
    """Lane-graph polylines for the map canvas: segment name -> [[x, y]...]
    and node name -> [x, y], read from lane_graph.yaml (§ segments/nodes)."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    segments = {
        name: [list(point) for point in (seg.get("points") or [])]
        for name, seg in (raw.get("segments") or {}).items()
    }
    nodes = {name: list(point) for name, point in (raw.get("nodes") or {}).items()}
    return {"segments": segments, "nodes": nodes}


def build_status(core, observation, odom, overlay_health, camera_health, now):
    return {
        "core": core or {},
        "observation": observation or {},
        "odom": odom or {},
        "streams": {"overlay": overlay_health, "camera": camera_health},
        "timestamp": now,
    }


def poll_core(core_url, timeout=CORE_TIMEOUT_S):
    """GET CORE's line-follow status; returns None on any failure (a stale
    launch, a not-yet-booted CORE, a network blip) so the poll loop can keep
    retrying instead of raising."""
    url = core_url.rstrip("/") + STATUS_PATH
    req = urllib.request.Request(url, headers=VIEWER)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


class ViewerState:
    """All mutable state the HTTP handlers read and the ROS callbacks (plus
    the CORE poll loop) write. `lock` guards `core`/`observation`/`odom`;
    the frame streams and trail have their own internal locking."""

    def __init__(self, graph, trail_maxlen=DEFAULT_TRAIL):
        self.graph = graph
        self.lock = threading.Lock()
        self.overlay = FrameStream()
        self.camera = FrameStream()
        self.trail = Trail(maxlen=trail_maxlen)
        self.core = {}
        self.observation = {}
        self.odom = {}

    def set_core(self, core):
        with self.lock:
            self.core = core

    def set_observation(self, observation):
        with self.lock:
            self.observation = observation

    def set_odom(self, odom):
        with self.lock:
            self.odom = odom

    def status(self, now):
        with self.lock:
            core, observation, odom = dict(self.core), dict(self.observation), dict(self.odom)
        return build_status(
            core, observation, odom,
            self.overlay.health(now), self.camera.health(now), now)


def render_index_html():
    """One self-contained page: overlay stream (large), raw camera (small),
    a status panel (CORE/observation/odom + per-stream fps/age/NO DATA),
    and a canvas map with the lane graph, the robot pose and its trail."""
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8"/>
<title>Rosy Lane Live View</title>
<style>
  :root { color-scheme: dark; }
  body { background: #111318; color: #e8e8ea; font-family: system-ui, sans-serif; margin: 0; padding: 12px; }
  h1 { font-size: 1.1rem; font-weight: 600; margin: 0 0 10px; }
  .layout { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; }
  .streams { display: flex; flex-direction: column; gap: 10px; }
  #overlay { width: 100%; border: 1px solid #333; border-radius: 4px; background: #000; }
  #camera { width: 240px; border: 1px solid #333; border-radius: 4px; background: #000; }
  #map { width: 100%; max-width: 480px; background: #0a0c10; border: 1px solid #333; border-radius: 4px; }
  #status { background: #1a1d24; border: 1px solid #333; border-radius: 4px; padding: 10px;
            font-size: 0.85rem; white-space: pre-wrap; }
  .stale { color: #ff6b6b; font-weight: 700; }
  .fresh { color: #6bffa0; }
  .panel-title { font-size: 0.8rem; color: #9aa0ac; margin: 0 0 4px; }
</style>
</head>
<body>
<h1>Rosy 차선 추종 라이브 뷰</h1>
<div class="layout">
  <div class="streams">
    <div>
      <p class="panel-title">인식 오버레이 (line/debug/compressed)</p>
      <img id="overlay" src="/overlay.mjpg" alt="perception overlay"/>
    </div>
    <div>
      <p class="panel-title">원본 카메라 (camera/front)</p>
      <img id="camera" src="/camera.mjpg" alt="raw camera"/>
    </div>
  </div>
  <div>
    <p class="panel-title">지도 / 궤적</p>
    <canvas id="map" width="480" height="480"></canvas>
    <p class="panel-title">상태</p>
    <pre id="status">loading...</pre>
  </div>
</div>
<script>
const graphReady = fetch('/graph.json').then(r => r.json()).catch(() => ({segments: {}, nodes: {}}));
let graph = {segments: {}, nodes: {}};
graphReady.then(g => { graph = g; drawMap(null); });

function fmt(v, digits) {
  if (v === null || v === undefined) return 'NO DATA';
  return Number(v).toFixed(digits === undefined ? 2 : digits);
}

function streamLine(name, health) {
  if (!health || !health.ok) {
    return name + ': NO DATA (stale)';
  }
  return name + ': ok fps=' + fmt(health.fps, 1) + ' age=' + fmt(health.age_s, 2) + 's';
}

function renderStatus(s) {
  const core = s.core || {};
  const obs = s.observation || {};
  const odom = s.odom || {};
  const streams = s.streams || {};
  const lines = [
    'CORE mode=' + (core.mode || 'NO DATA') + ' state=' + (core.state || 'NO DATA') +
      ' reason=' + (core.reason || '') + ' error=' + fmt(core.error) + ' confidence=' + fmt(core.confidence),
    'observation visible=' + (obs.visible === undefined ? 'NO DATA' : obs.visible) +
      ' error=' + fmt(obs.error) + ' confidence=' + fmt(obs.confidence),
    'odom x=' + fmt(odom.x, 3) + ' y=' + fmt(odom.y, 3) + ' yaw=' + fmt(odom.yaw, 3) + ' speed=' + fmt(odom.speed, 3),
    streamLine('overlay', streams.overlay),
    streamLine('camera', streams.camera),
  ];
  document.getElementById('status').textContent = lines.join('\\n');
  drawMap(odom);
}

function drawMap(odom) {
  const canvas = document.getElementById('map');
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#0a0c10';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const segs = Object.values(graph.segments || {});
  if (!segs.length) return;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const pts of segs) {
    for (const [x, y] of pts) {
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
    }
  }
  const pad = 20;
  const sx = (canvas.width - 2 * pad) / Math.max(maxX - minX, 1e-6);
  const sy = (canvas.height - 2 * pad) / Math.max(maxY - minY, 1e-6);
  const scale = Math.min(sx, sy);
  const project = (x, y) => [
    pad + (x - minX) * scale,
    canvas.height - (pad + (y - minY) * scale),
  ];
  ctx.strokeStyle = '#4a5568';
  ctx.lineWidth = 1.5;
  for (const pts of segs) {
    ctx.beginPath();
    pts.forEach(([x, y], i) => {
      const [px, py] = project(x, y);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.stroke();
  }
  if (odom && odom.x !== undefined) {
    const [px, py] = project(odom.x, odom.y);
    ctx.fillStyle = '#ffd166';
    ctx.beginPath();
    ctx.arc(px, py, 4, 0, Math.PI * 2);
    ctx.fill();
    const yaw = odom.yaw || 0;
    ctx.strokeStyle = '#ffd166';
    ctx.beginPath();
    ctx.moveTo(px, py);
    ctx.lineTo(px + 12 * Math.cos(-yaw), py + 12 * Math.sin(-yaw));
    ctx.stroke();
  }
}

async function pollStatus() {
  try {
    const r = await fetch('/status.json');
    const s = await r.json();
    renderStatus(s);
  } catch (e) {
    document.getElementById('status').textContent = 'NO DATA (status.json unreachable)';
  }
  setTimeout(pollStatus, 500);
}
pollStatus();
</script>
</body>
</html>"""


def make_handler(state):
    """Build a BaseHTTPRequestHandler bound to `state` via closure (the
    stdlib server passes only (request, client_address, server) to the
    handler class, so state cannot be an __init__ argument)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "RosyLaneLiveView/1.0"

        def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send_html(render_index_html())
            elif self.path == "/overlay.mjpg":
                self._stream_mjpeg(state.overlay)
            elif self.path == "/camera.mjpg":
                self._stream_mjpeg(state.camera)
            elif self.path == "/status.json":
                self._send_json(state.status(time.monotonic()))
            elif self.path == "/graph.json":
                self._send_json(state.graph)
            else:
                self.send_error(404)

        def _send_html(self, html):
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
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
                    data, ts = stream.latest()
                    if data is not None and ts != last_ts:
                        self.wfile.write(mjpeg_part(data))
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

    def on_observation(msg):
        try:
            state.set_observation(json.loads(msg.data))
        except (json.JSONDecodeError, ValueError):
            pass

    def on_odom(msg):
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        yaw = yaw_from_quaternion(q.x, q.y, q.z, q.w)
        v = msg.twist.twist.linear
        speed = math.hypot(v.x, v.y)
        state.set_odom({"x": x, "y": y, "yaw": yaw, "speed": speed})
        state.trail.add(x, y, time.monotonic())

    node.create_subscription(CompressedImage, "line/debug/compressed", on_overlay, qos_profile_sensor_data)
    node.create_subscription(Image, "camera/front", on_camera, qos_profile_sensor_data)
    node.create_subscription(String, "line/observation", on_observation, 10)
    node.create_subscription(Odometry, "odom", on_odom, qos_profile_sensor_data)
    return node, rclpy


def spin(rclpy_module, node, stop_event):
    """Runs on a background thread so the HTTP server's main-thread loop is
    never blocked by ROS callbacks. Keeps spinning across Gazebo relaunches
    between scenarios; DDS rediscovers publishers on its own."""
    while not stop_event.is_set():
        rclpy_module.spin_once(node, timeout_sec=0.1)


def core_poll_loop(state, core_url, stop_event):
    """Runs on its own thread: CORE's HTTP API is polled with blocking
    urllib calls, which must never happen on the ROS callback thread."""
    while not stop_event.is_set():
        result = poll_core(core_url)
        if result is not None:
            state.set_core(result)
        stop_event.wait(CORE_POLL_S)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL)
    parser.add_argument("--trail", type=int, default=DEFAULT_TRAIL)
    args = parser.parse_args(argv)

    graph = load_graph(args.graph)
    state = ViewerState(graph, trail_maxlen=args.trail)

    node, rclpy_module = build_node(args, state)
    stop_event = threading.Event()

    poll_thread = threading.Thread(
        target=core_poll_loop, args=(state, args.core_url, stop_event), daemon=True)
    poll_thread.start()
    ros_thread = threading.Thread(
        target=spin, args=(rclpy_module, node, stop_event), daemon=True)
    ros_thread.start()

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(state))

    def handle_sigint(signum, frame):
        stop_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, handle_sigint)
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
