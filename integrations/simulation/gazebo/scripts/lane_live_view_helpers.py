#!/usr/bin/env python3
"""ROS-free state, graph loading, trail, and MJPEG framing helpers for lane_live_view.py."""

import math
import sys
import threading
import time
from collections import deque
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_view_model as model  # noqa: E402

DEFAULT_TRAIL = 2000
#: CORE answers older than this count as unreachable.
CORE_STALE_S = 3.0
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
#: Observations (line/dock/road) and odom older than this are stale.
OBS_STALE_S = 2.0
#: The dock tag's bottom edge on map_v2_fleet (build_world.DOCK_TAG_BOTTOM_X).
DOCK_MARKER_XY = (-0.78, 0.0)
#: Trail points sent per /status.json.
TRAIL_SEND_MAX = 400
BOUNDARY = "rosyframe"
MJPEG_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
#: How often the MJPEG stream loop checks for a new frame to push.
MJPEG_POLL_S = 0.05


class FrameStream:
    """Latest-frame-wins store for one MJPEG source, with an fps/staleness health check.
    Thread-safe: `publish` runs on the ROS callback thread, `latest`/`health` on HTTP threads."""

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
    """Odometry trail (last `maxlen` points), reset when a new scenario is detected: a pose
    jump bigger than POSE_JUMP_RESET_M, or an odom gap longer than ODOM_SILENCE_RESET_S."""

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

    def clear(self):
        self.points.clear()

    def as_list(self):
        return list(self.points)


def mjpeg_part(jpeg_bytes):
    """One multipart/x-mixed-replace part: boundary, Content-Type, Content-Length, frame bytes."""
    header = (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
              f"Content-Length: {len(jpeg_bytes)}\r\n\r\n").encode("ascii")
    return header + jpeg_bytes + b"\r\n"


def yaw_from_quaternion(x, y, z, w):
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _polylines(raw):
    segments = {
        name: [list(point) for point in (seg.get("points") or [])]
        for name, seg in (raw.get("segments") or {}).items()
    }
    nodes = {name: list(point) for name, point in (raw.get("nodes") or {}).items()}
    return {"segments": segments, "nodes": nodes}


def load_graph(path):
    """Map polylines from lane_graph.yaml: segment name -> [[x, y]...], node name -> [x, y]."""
    return _polylines(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def graph_payload(raw, route=None):
    """/graph.json: polylines, parking spur and spot, dock marker, directions, route keys/length."""
    graph = _polylines(raw)
    parking = raw.get("parking") or {}
    if parking.get("points"):
        graph["parking"] = {"points": [list(p) for p in parking["points"]],
                            "spot": [float(v) for v in parking.get("spot") or
                                     list(parking["points"][-1]) + [0.0]]}
    graph["marker"] = list(DOCK_MARKER_XY)
    graph["directions"] = {
        name: {"from": seg.get("from"), "to": seg.get("to"),
               "two_way": "reverse" in (seg.get("directions") or [])}
        for name, seg in (raw.get("segments") or {}).items()}
    if route is not None:
        graph["route"] = {"keys": route.keys, "length_m": round(route.length_m, 3)}
    return graph


def build_status(core, observation, odom, overlay_health, camera_health, now):
    return {
        "core": core or {},
        "observation": observation or {},
        "odom": odom or {},
        "streams": {"overlay": overlay_health, "camera": camera_health},
        "timestamp": now,
    }


def _wall_offset():
    """Realtime minus monotonic: constant unless the wall clock steps (junction_harness)."""
    return time.time() - time.monotonic()


def _fresh(t, now, limit=OBS_STALE_S):
    return t is not None and now - t <= limit


def _age(t, now):
    return None if t is None else round(now - t, 2)


class ViewerState:
    """All mutable state the HTTP handlers read and the ROS callbacks (plus
    the CORE poll loop, or --demo) write. `lock` guards everything but the
    frame streams, which lock themselves."""

    def __init__(self, graph, trail_maxlen=DEFAULT_TRAIL, route=None, spot=None,
                 evidence_dir=None):
        self.graph = graph
        self.lock = threading.Lock()
        self.overlay = FrameStream()
        self.camera = FrameStream()
        self.trail = Trail(maxlen=trail_maxlen)
        self.route = route
        self.spot = tuple(spot) if spot else None
        self.evidence_dir = evidence_dir
        self.core = {}
        self.observation = {}
        self.odom = {}
        self.robot = {}
        self.docking = {}
        self.core_ok = False
        self.core_t = None
        self.observation_t = None
        self.odom_t = None
        self.dock_observation, self.dock_observation_t = {}, None
        self.road_observation, self.road_observation_t = {}, None
        self.clock = model.ClockMonitor(offset=_wall_offset())
        self.tiers = model.TierStats()
        self.history = model.History()
        self.phase = "boot"
        self.phase_marks = {"boot": None}
        self.log_live = None

    @classmethod
    def from_raw_graph(cls, raw, trail_maxlen=DEFAULT_TRAIL, route_keys=None,
                       evidence_dir=None):
        keys = list(route_keys) if route_keys else model.tour_keys(raw)
        route = model.RouteProgress(raw, keys)
        parking = raw.get("parking") or {}
        spot = parking.get("spot")
        return cls(graph_payload(raw, route), trail_maxlen=trail_maxlen, route=route,
                   spot=spot, evidence_dir=evidence_dir)

    # -- writers ---------------------------------------------------------

    def set_core(self, core):
        with self.lock:
            self.core = core

    def set_core_status(self, polled, now):
        with self.lock:
            if polled.get("ok"):
                self.core_ok, self.core_t = True, now
                if polled.get("line_follow") is not None:
                    self.core = polled["line_follow"]
                self.robot = polled.get("robot") or {}
                self.docking = polled.get("docking") or (self.robot.get("docking") or {})
            else:
                self.core_ok = False

    def set_observation(self, observation, now=None):
        now = time.monotonic() if now is None else now
        tier = model.classify_tier(observation)
        with self.lock:
            self.observation, self.observation_t = observation, now
            self.history.add(now, observation.get("error"), observation.get("confidence"), tier)
            if self.phase == "tour":
                self.tiers.add(tier)

    def set_dock_observation(self, observation, now=None):
        with self.lock:
            self.dock_observation = observation
            self.dock_observation_t = time.monotonic() if now is None else now

    def set_road_observation(self, observation, now=None):
        with self.lock:
            self.road_observation = observation
            self.road_observation_t = time.monotonic() if now is None else now

    def set_odom(self, odom, now=None):
        with self.lock:
            self.odom = odom
            self.odom_t = time.monotonic() if now is None else now

    def add_pose(self, x, y, yaw, now, speed=0.0):
        """One odom pose: odom, trail and route progress; a trail reset
        (pose jump / odom silence) starts a new run."""
        self.set_odom({"x": x, "y": y, "yaw": yaw, "speed": speed}, now)
        if self.trail.add(x, y, now):
            self.new_run()
        if self.route is not None:
            with self.lock:
                self.route.update((x, y))

    def on_clock(self, sim_s, now):
        with self.lock:
            went_back = self.clock.on_clock(sim_s, now)
        if went_back:
            self.new_run()

    def set_log_phase(self, live):
        with self.lock:
            self.log_live = live

    def set_phase(self, phase, sim_s=None):
        with self.lock:
            if phase != self.phase:
                self.phase_marks[phase] = sim_s
            self.phase = phase

    def new_run(self):
        """Forget the previous run's progress, tier counts and phase."""
        with self.lock:
            if self.route is not None:
                self.route.reset()
            self.tiers.reset()
            self.history.reset()
            self.phase, self.phase_marks = "boot", {"boot": None}
        self.trail.clear()

    def tick(self, now):
        """Re-derive the mission phase from the latest inputs."""
        with self.lock:
            core_ok = self.core_ok and _fresh(self.core_t, now, CORE_STALE_S)
            log = self.log_live or {}
            route_done = bool(self.route and self.route.snapshot()["finished"])
            phase = model.derive_phase(
                self.phase, core_ok=core_ok, docking=self.docking.get("state"),
                line_mode=self.core.get("mode") if core_ok else None,
                log_phase=log.get("phase"), route_done=route_done)
            sim_s = self.clock.snapshot(now, _wall_offset())["sim_s"]
        self.set_phase(phase, sim_s)

    # -- reader ----------------------------------------------------------

    def status(self, now):
        with self.lock:
            core, observation, odom = dict(self.core), dict(self.observation), dict(self.odom)
            robot, docking = dict(self.robot), dict(self.docking)
            core_ok = self.core_ok and _fresh(self.core_t, now, CORE_STALE_S)
            core_age = _age(self.core_t, now)
            obs_t, odom_t = self.observation_t, self.odom_t
            dock_obs, dock_t = dict(self.dock_observation), self.dock_observation_t
            road_obs, road_t = dict(self.road_observation), self.road_observation_t
            clock = self.clock.snapshot(now, _wall_offset())
            tiers = self.tiers.snapshot()
            history = self.history.series(now)
            phase, marks, log = self.phase, dict(self.phase_marks), self.log_live
            route = self.route.snapshot() if self.route is not None else None
        overlay_h, camera_h = self.overlay.health(now), self.camera.health(now)
        status = build_status(core, observation, odom, overlay_h, camera_h, now)

        tier = model.classify_tier(observation) if _fresh(obs_t, now) else None
        odom_fresh = _fresh(odom_t, now)
        clock_fresh = clock["age_s"] is not None and clock["age_s"] <= OBS_STALE_S
        status["live"] = bool(overlay_h["ok"] or camera_h["ok"] or odom_fresh or clock_fresh)
        status["wall_time"] = time.time()
        status["clock"] = clock
        status["odom_age_s"] = _age(odom_t, now)
        status["core_api"] = {
            "reachable": core_ok, "age_s": core_age,
            "mode": robot.get("mode"), "navigation": robot.get("navigation"),
            "estop": (robot.get("safety") or {}).get("estop"),
            "velocity": robot.get("velocity") or {},
            "line_follow": core, "docking": docking}
        index = model.PHASES.index(phase)
        status["mission"] = {
            "phase": phase, "phase_label": model.PHASE_LABELS[phase], "phase_index": index,
            "phases": [{"key": p, "label": model.PHASE_LABELS[p],
                        "state": "done" if i < index or phase == "done" else
                        "current" if i == index else "todo",
                        "sim_start": marks.get(p)} for i, p in enumerate(model.PHASES)],
            "source": "log" if log and log.get("phase") else "core",
            "log_run": (log or {}).get("run"),
            "alert": _alert(docking, robot, core)}
        status["route"] = route
        status["perception"] = {
            "tier": tier, "tier_label": model.TIER_LABELS.get(tier),
            "visible": observation.get("visible"), "error": observation.get("error"),
            "confidence": observation.get("confidence"), "source": observation.get("source"),
            "age_s": _age(obs_t, now), "history": history, "distribution": tiers,
            "thresholds": model.TIER_MIN_CONFIDENCE}
        tag_visible = bool(_fresh(dock_t, now) and dock_obs.get("visible"))
        spot_err = (model.spot_error((odom["x"], odom["y"], odom.get("yaw", 0.0)), self.spot)
                    if self.spot and "x" in odom else None)
        status["parking"] = {
            "active": bool(docking.get("state") in ("DOCKING", "UNDOCKING")
                           or phase in ("confirm", "park") or tag_visible),
            "tag_visible": tag_visible, "tag_age_s": _age(dock_t, now),
            "tag": {k: dock_obs.get(k) for k in ("tag_id", "x", "y", "yaw", "range_m",
                                                 "confidence")},
            "spot": list(self.spot) if self.spot else None, "spot_error": spot_err}
        status["dock_observation"] = dock_obs if _fresh(dock_t, now) else {}
        status["road_observation"] = road_obs if _fresh(road_t, now) else {}
        status["trail"] = [[round(x, 3), round(y, 3)]
                           for x, y in model.downsample(self.trail.as_list(), TRAIL_SEND_MAX)]
        return status


def _alert(docking, robot, line):
    """The one thing the operator must see now, or None."""
    if (robot.get("safety") or {}).get("estop") or robot.get("mode") == "EMERGENCY":
        return "비상 정지"
    if docking.get("state") == "DOCK_FAILED":
        return f"주차 실패 ({docking.get('error') or 'retries exhausted'})"
    if line.get("mode") not in (None, "OFF") and line.get("state") in ("STOPPED", "LOST"):
        return f"차선 추종 정지: {line.get('reason')}"
    return None
