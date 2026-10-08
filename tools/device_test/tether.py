"""D-512 amendment 1 tether guard (user decision 2026-10-08): the robot drives on its charging cable.

The agent declares the cable per run from the overhead frame (verdict `tether`): cable_m
(2.0 or 5.0) and how it judged it, plus either charger_robot_frame [forward_m, left_m] (the
charger the cable plugs into, in the robot pose at capture; needs a D-395 localized map pose)
or `pixels` {robot_center, robot_front, charger} picked on the judged overhead frame (any
robot; the tool computes charger_robot_frame through the inverted calibration). `run.py
--tether-check VERDICT` draws the charger, the radius circle (cable_m - margin_m) and the robot
on that frame through the site's approved camera-to-map calibration (D-375/D-457; none, another
map or a bad fit = tethered run refused) into tether_check.jpg; the agent looks and sets
tether.visual_check_ok. The charger is placed from pose_at_capture (the pose the check used);
the first driving pose must match it. Each drive tick: trail.jsonl, distance to the charger,
unwrapped cumulative yaw. Over the radius or |turn| > max_turn_deg = trip (both retrace; backing
over the robot's own cable is a risk the user accepted 2026-10-08): line-follow OFF (confirmed),
then reverse along the recorded trail (D-407 drove-through basis) at a real 10 Hz under the
RobotBody rear gap on fresh scans until the cable is slack or the trail ends; any doubt stops
(IDLE). The trip is still an abort (exit 2). While reversing in MANUAL, CORE applies E-Stop,
limits and the teleop watchdog only (no D-422 body stop): the rear-gap check here is the only
obstacle stop. Poses are /robot/state `pose`, the source the distance cap uses.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import edge_drive
import identify
from core_common.robot_body import PINKY_PRO

CABLES_M = (2.0, 5.0)             # the two cables on site (user 2026-10-08)
CHECK_IMAGE = "tether_check.jpg"
STEP_M = 0.01                     # trail sample spacing
START_MAX_MOVE_M = 0.05           # first driving pose vs pose_at_capture (as the verdict's own check) ...
START_MAX_TURN_DEG = 3.0          # ... and heading
FRONT_MIN_SCALE = 0.5             # pixel mode: |robot_center - robot_front| in metres must lie in
FRONT_MAX_SCALE = 2.0             # [0.5, 2.0] x RobotBody.front_x_m (the front edge middle)
RETRACE_SPEED = 0.03              # m/s, reverse
RETRACE_MAX_ANG = 0.3             # rad/s, below the nudge limit edge_drive.LIMITS[1]
RETRACE_LOOKAHEAD_M = 0.08        # pure pursuit on the reversed trail
RETRACE_TOL_M = 0.10              # pose farther than this from the trail = off the driven space
RETRACE_MAX_S = 180.0             # time cap for one retrace
RETRACE_WINDOW = 50               # trail points searched ahead (0.5 m): a lap crossing is not progress
RETRACE_MAX_PERIOD_S = 0.3        # teleop send period above this = stop (watchdog margin)
SCAN_STALE_S = 0.5                # LiDAR received_at/source_stamp_ns not advanced for this = stop
UNWIND_TURN_DEG = 90.0            # retrace ends at |turn| <= max_turn - this ...
UNWIND_SLACK_M = 0.1              # ... and charger distance <= cable_m - margin - this (also the start slack)
END_M = 0.02                      # within this of the first trail point = trail exhausted
TICK_S = 0.1


class Abort(RuntimeError):
    """run.py's abort: every reason (tether trip included) ends in the normal cleanup."""


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def pose_of(p):
    """(x, y, yaw) from a pose dict, None when any value is missing or not finite."""
    return (p["x"], p["y"], p["yaw"]) if isinstance(p, dict) and all(_finite(p.get(k)) for k in ("x", "y", "yaw")) \
        else None


def place(pose, offset):
    """A robot-frame [forward, left] offset placed in the pose's frame."""
    (x, y, yaw), (f, l) = pose, offset
    return x + f * math.cos(yaw) - l * math.sin(yaw), y + f * math.sin(yaw) + l * math.cos(yaw)


def binding(verdict, policy):
    """What tether_check.jpg showed: cable, charger, picked pixels, margin, the capture pose and the
    lamp identify that proved the robot (D-512 amendment 2)."""
    t = verdict["tether"]
    key = [t["cable_m"], t.get("charger_robot_frame"), t.get("pixels"), policy["margin_m"],
           pose_of(verdict.get("pose_at_capture")), t.get("identity")]
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def declared(verdict, policy):
    """The declared tether, or None. ValueError (fail closed) for anything not shown."""
    t = verdict.get("tether")
    if t is None:
        if verdict["cable_attached"]:
            raise ValueError("camera verdict: cable attached but no tether {cable_m, charger_robot_frame, how}")
        return None
    if not verdict["cable_attached"]:
        raise ValueError("camera verdict: tether declared but cable_attached is false")
    charger = t.get("charger_robot_frame") if isinstance(t, dict) else None
    if not isinstance(t, dict) or not _finite(t.get("cable_m")) or t["cable_m"] not in CABLES_M:
        raise ValueError(f"camera verdict: tether.cable_m must be one of {CABLES_M}")
    if not (isinstance(charger, list) and len(charger) == 2 and all(_finite(a) for a in charger)):
        raise ValueError("camera verdict: tether.charger_robot_frame must be [forward_m, left_m]")
    if not str(t.get("how") or "").strip():
        raise ValueError("camera verdict: tether.how is empty")
    if pose_of(verdict.get("pose_at_capture")) is None:
        raise ValueError("camera verdict: a tether needs pose_at_capture with x, y and yaw")
    limit = t["cable_m"] - policy["margin_m"]
    if math.hypot(*charger) > limit - UNWIND_SLACK_M:
        raise ValueError(f"tether: charger {math.hypot(*charger):.2f} m away, over the {limit:.2f} m limit "
                         f"less the {UNWIND_SLACK_M} m retrace slack at start")
    return t


def check(verdict, policy):
    """declared() plus the agent's look at tether_check.jpg for exactly these values."""
    t = declared(verdict, policy)
    ident = (t or {}).get("identity") or {}
    if t is not None and not (ident.get("request_id") and "refused" not in ident):
        raise ValueError("tether: no lamp identify proved the robot (tether.identity); run --tether-check again")
    if t is not None and not (t.get("visual_check_ok") is True and CHECK_IMAGE in (verdict.get("frames") or {})
                              and (t.get("check") or {}).get("for") == binding(verdict, policy)):
        raise ValueError(f"tether: run --tether-check, look at {CHECK_IMAGE}, then set tether.visual_check_ok "
                         "true (the check must be for these cable, charger, margin and pose values)")
    return t


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def _project(h, x, y):
    w = h[6] * x + h[7] * y + h[8]
    if not w > 1e-9:
        return math.nan, math.nan            # horizon or behind the camera
    return (h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w


def overlay_points(map_to_image, pose, charger, radius_m, n=72):
    """Overhead pixels of the charger, the radius circle, the robot and a 0.1 m heading tip."""
    cx, cy = place(pose, charger)
    tip = place(pose, (0.1, 0.0))
    return {"charger": _project(map_to_image, cx, cy), "robot": _project(map_to_image, *pose[:2]),
            "heading": _project(map_to_image, *tip),
            "circle": [_project(map_to_image, cx + radius_m * math.cos(2 * math.pi * k / n),
                                cy + radius_m * math.sin(2 * math.pi * k / n)) for k in range(n)]}


def from_pixels(map_to_image, pixels, size, body=PINKY_PRO):
    """Pixel mode: ((x, y, heading) of the robot in the calibration's map, charger_robot_frame,
    center-to-front metres) from points picked on the overhead frame. ValueError if not shown."""
    import numpy as np
    h = np.array(map_to_image, float).reshape(3, 3)
    if not np.all(np.isfinite(h)) or abs(np.linalg.det(h)) < 1e-12:
        raise ValueError("the calibration homography is singular")
    inv, (w, hgt), m = np.linalg.inv(h), size, {}
    for key in ("robot_center", "robot_front", "charger"):
        p = pixels.get(key) if isinstance(pixels, dict) else None
        if not (isinstance(p, list) and len(p) == 2 and all(_finite(a) for a in p)
                and 0 <= p[0] < w and 0 <= p[1] < hgt):
            raise ValueError(f"tether.pixels.{key} must be [u, v] inside the {w}x{hgt} frame")
        q = inv @ np.array([p[0], p[1], 1.0])
        if not (np.all(np.isfinite(q)) and abs(q[2]) > 1e-12):
            raise ValueError(f"tether.pixels.{key} does not map to the floor")
        m[key] = (float(q[0] / q[2]), float(q[1] / q[2]))
    (cx, cy), (fx, fy), (gx, gy) = m["robot_center"], m["robot_front"], m["charger"]
    length, lo, hi = math.hypot(fx - cx, fy - cy), FRONT_MIN_SCALE * body.front_x_m, FRONT_MAX_SCALE * body.front_x_m
    if not lo <= length <= hi:
        raise ValueError(f"robot_center to robot_front is {length:.3f} m, not within [{lo:.3f}, {hi:.3f}] m "
                         "(RobotBody front); pick the body centre and the middle of its front edge")
    yaw = math.atan2(fy - cy, fx - cx)
    dx, dy = gx - cx, gy - cy
    charger = [round(dx * math.cos(yaw) + dy * math.sin(yaw), 4), round(-dx * math.sin(yaw) + dy * math.cos(yaw), 4)]
    return (cx, cy, yaw), charger, length


def tether_check(robot, args):
    """--tether-check VERDICT --plan PLAN: draw the declared tether on the judged overhead frame.
    Reads the site calibration; to the robot it sends only the lamp identify (identify.py, D-512
    amendment 2), which must blink at the drawn robot. Refuses rather than guessing a scale or a robot."""
    import cv2
    import numpy as np
    from plan_rules import load_plan
    if not args.plan:
        raise SystemExit("--tether-check needs --plan (tether_policy.margin_m)")
    policy, path = load_plan(args.plan)["tether_policy"], Path(args.tether_check)
    v = json.loads(path.read_text(encoding="utf-8"))
    t = v.get("tether")
    if not isinstance(t, dict):
        raise SystemExit("tether check: the verdict declares no tether")
    over = [n for n in v.get("frames") or {} if n.endswith("_overhead.jpg")]
    img = cv2.imdecode(np.frombuffer((path.parent / over[0]).read_bytes(), np.uint8), cv2.IMREAD_COLOR) \
        if len(over) == 1 else None
    source = robot.overhead_source()
    rec = next((r for r in robot.calibrations() or [] if r.get("source_id") == source), None)
    if img is None or rec is None or [rec["image"]["width"], rec["image"]["height"]] != [img.shape[1], img.shape[0]]:
        raise SystemExit(f"tether check: no approved camera-to-map calibration (GET /api/fleet/calibrations) for "
                         f"overhead source {source!r} matching the judged frame; a tethered run is refused "
                         "(no guessed pixel scale)")
    pixel = "pixels" in t
    want, whose = (robot.active_site_map_id(), "the Fleet active SiteMap") if pixel else \
        (v.get("map_id_at_capture"), "the robot's map at capture")
    if not rec.get("map_id") or rec.get("map_id") != want:
        raise SystemExit(f"tether check: calibration map {rec.get('map_id')!r} is not {whose} {want!r}; refused")
    try:
        if pixel:
            draw_pose, t["charger_robot_frame"], length = from_pixels(rec["map_to_image"], t["pixels"],
                                                                      (img.shape[1], img.shape[0]))
            t["from_pixels"] = {"robot_center_m": [round(c, 4) for c in draw_pose[:2]],
                                "heading_deg": round(math.degrees(draw_pose[2]), 1),
                                "center_to_front_m": round(length, 4)}
        else:
            loc, draw_pose = v.get("localization_at_capture") or {}, pose_of(v.get("pose_at_capture"))
            if loc.get("state") != "LOCALIZED" or loc.get("pose_frame") != "map" or draw_pose is None:
                raise ValueError("the capture pose is not a localized map pose (D-395); give tether.pixels "
                                 "{robot_center, robot_front, charger} picked on the overhead frame instead")
        declared({"cable_attached": True, **v}, policy)
    except ValueError as exc:
        raise SystemExit(f"tether check: {exc}; a tethered run is refused") from exc
    radius = t["cable_m"] - policy["margin_m"]
    pts = overlay_points(rec["map_to_image"], draw_pose, t["charger_robot_frame"], radius)
    h, w = img.shape[:2]
    if not all(0 <= u < w and 0 <= q < h for u, q in (pts["charger"], pts["robot"])):
        raise SystemExit(f"tether check: charger or robot falls outside the overhead picture: {pts['charger']}, "
                         f"{pts['robot']}")
    try:      # the drawn robot must be the target: its lamp blinks there (D-512 amendment 2)
        t["identity"] = identify.identify(robot, pts["robot"], identify.radius_px(
            rec["map_to_image"], draw_pose[:2], _project), path.parent)
    except identify.Refused as exc:     # the refusal and its frames go into the verdict as evidence
        t.update(identity=exc.evidence, visual_check_ok=False)
        path.write_text(json.dumps(v, indent=2), encoding="utf-8")
        raise SystemExit(f"tether check: {exc}") from exc
    ring = np.array([p for p in pts["circle"] if all(map(math.isfinite, p))], np.int32)
    cv2.polylines(img, [ring], True, (0, 220, 255), 2)
    cv2.circle(img, tuple(map(round, pts["charger"])), 7, (0, 0, 255), -1)
    cv2.circle(img, tuple(map(round, pts["robot"])), 6, (0, 200, 0), 2)
    cv2.arrowedLine(img, tuple(map(round, pts["robot"])), tuple(map(round, pts["heading"])), (0, 200, 0), 2)
    cv2.circle(img, tuple(map(round, t["identity"]["blob_center"])), 4, (255, 0, 255), -1)   # lamp blob
    cv2.putText(img, f"charger, {t['cable_m']} m cable - {policy['margin_m']} m = {radius:.2f} m", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2)
    out = path.parent / CHECK_IMAGE
    out.write_bytes(cv2.imencode(".jpg", img)[1].tobytes())
    v.setdefault("frames", {})[CHECK_IMAGE] = "sha256:" + hashlib.sha256(out.read_bytes()).hexdigest()
    t.update(visual_check_ok=False, check={
        "for": binding(v, policy), "mode": "pixels" if pixel else "map", "source_id": source, "map_id": rec["map_id"],
        "calibration_revision": rec.get("calibration_revision"), "use": rec.get("use")})   # D-457: display-only
    path.write_text(json.dumps(v, indent=2), encoding="utf-8")
    print(f"look at {out}: red = charger, yellow = {radius:.2f} m stop radius, green = robot and heading, "
          f"magenta = the target's lamp blink. "
          f"If they match the picture, set tether.visual_check_ok true in {path}; otherwise fix the tether and rerun.")
    return 0


class Guard:
    def __init__(self, verdict, policy, ev):
        self.t, self.policy, self.path = check(verdict, policy), policy, Path(ev) / "trail.jsonl"
        self.capture = pose_of(verdict.get("pose_at_capture"))
        self.trail, self.anchor, self.yaw, self.turn = [], None, None, 0.0
        self.stats = {"declared": self.t, "policy": policy, "max_charger_m": None, "max_turn_deg": 0.0,
                      "trail_points": 0}

    def limit_m(self):
        return self.t["cable_m"] - self.policy["margin_m"]

    def _pose(self, st):
        return pose_of(st.get("pose") if isinstance(st, dict) else None)

    def _start(self, x, y, yaw):
        """The charger from the pose the image check used; the first driving pose must still be it."""
        cx, cy, cyaw = self.capture
        moved, turned = math.hypot(x - cx, y - cy), abs(math.degrees(wrap(yaw - cyaw)))
        if moved > START_MAX_MOVE_M or turned > START_MAX_TURN_DEG:
            raise Abort(f"tether: first driving pose is {moved:.3f} m / {turned:.1f} deg from the checked capture "
                        f"pose (max {START_MAX_MOVE_M} m / {START_MAX_TURN_DEG} deg); preflight again")
        self.anchor = place(self.capture, self.t["charger_robot_frame"])

    def _update(self, x, y, yaw, phase="drive"):
        """Unwrap the yaw and keep the trail; returns the charger distance (None without a tether)."""
        if self.yaw is None:
            if self.t:
                self._start(x, y, yaw)
        else:
            self.turn += wrap(yaw - self.yaw)
        self.yaw = yaw
        if not self.trail or math.hypot(x - self.trail[-1][0], y - self.trail[-1][1]) >= STEP_M:
            if phase == "drive":
                self.trail.append((x, y, yaw))
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"x": round(x, 4), "y": round(y, 4), "yaw": round(yaw, 4),
                                    "turn_deg": round(math.degrees(self.turn), 1), "phase": phase}) + "\n")
        self.stats["trail_points"] = len(self.trail)
        self.stats["max_turn_deg"] = round(max(self.stats["max_turn_deg"], abs(math.degrees(self.turn))), 1)
        if not self.t:
            return None
        d = math.hypot(x - self.anchor[0], y - self.anchor[1])
        self.stats["max_charger_m"] = round(max(self.stats["max_charger_m"] or 0.0, d), 3)
        return d

    def tick(self, st, run):
        """One drive tick with a /robot/state body (None = that read failed; run.py counts those)."""
        run.summary["tether"] = self.stats
        if st is None:
            return
        pose = self._pose(st)
        if pose is None:
            if self.t:
                raise Abort("pose unknown: the tether limits cannot be enforced")
            return
        d = self._update(*pose)
        if d is None:
            return
        if d > self.limit_m():
            self.retrace("tether_radius", run)
        if abs(math.degrees(self.turn)) > self.policy["max_turn_deg"]:
            self.retrace("tether_turn", run)

    def retrace(self, trip, run):
        core = run.r.core
        self.stats.update(trip=trip, retrace_m=0.0, retrace_completed=False, retrace_max_period_s=None)
        run.phase("tether", trip=trip, charger_m=self.stats["max_charger_m"],
                  turn_deg=round(math.degrees(self.turn), 1))
        s, _ = core.call("PUT", "/line-follow/mode", {"mode": "OFF"})
        s2, lf = core.call("GET", "/line-follow")
        if s != 200 or s2 != 200 or not isinstance(lf, dict) or lf.get("mode") != "OFF":
            end = f"line-follow OFF not confirmed ({s}, {s2}); no retrace"
        elif core.call("POST", "/mode", {"mode": "MANUAL"})[0] != 200:
            end = "MANUAL refused; no retrace"
        else:
            try:
                end = self._retrace(run)
            finally:
                run.call("POST", "/teleop", {"linear": 0.0, "angular": 0.0})
                core.call("POST", "/mode", {"mode": "IDLE"})
        self.stats.update(retrace_end=end, final_turn_deg=round(math.degrees(self.turn), 1))
        run.phase("tether:retrace", **{k: self.stats.get(k) for k in (
            "retrace_end", "retrace_m", "retrace_completed", "final_turn_deg", "final_charger_m",
            "retrace_max_period_s")})
        raise Abort(f"tether trip {trip}, {'retraced' if self.stats['retrace_completed'] else 'retrace stopped'} "
                    f"{self.stats['retrace_m']:.2f} m ({end})")

    def _retrace(self, run):
        """Reverse along the trail; returns why it ended. Completed only when unwound or at the trail start."""
        path, i, t0, last = self.trail[::-1], 0, run.r.now(), None
        scan_key, scan_at, sent_at = None, t0, None
        deg, _src = edge_drive.lidar_forward_deg(run.args.robot)
        while True:
            tick_at = run.r.now()
            ss, st = run.call("GET", "/robot/state")
            pose = self._pose(st) if ss == 200 else None
            if pose is None:
                return "pose unknown"
            if (st.get("safety") or {}).get("estop"):
                return "estop"
            if st.get("mode") != "MANUAL":
                return f"mode {st.get('mode')} (CORE or someone else changed it)"
            if (run.ev / "STOP").exists():
                return "operator STOP file"
            if tick_at - t0 > RETRACE_MAX_S:
                return f"time cap {RETRACE_MAX_S:.0f} s"
            x, y, yaw = pose
            d = self._update(x, y, yaw, phase="retrace")
            self.stats["final_charger_m"] = round(d, 3)
            if last:
                self.stats["retrace_m"] = round(self.stats["retrace_m"] + math.hypot(x - last[0], y - last[1]), 3)
            last = pose
            if abs(math.degrees(self.turn)) <= self.policy["max_turn_deg"] - UNWIND_TURN_DEG \
                    and d <= self.limit_m() - UNWIND_SLACK_M:
                self.stats["retrace_completed"] = True
                return "unwound"
            window = path[i:i + RETRACE_WINDOW]
            near = min(range(len(window)), key=lambda k: math.hypot(window[k][0] - x, window[k][1] - y))
            i += near
            if math.hypot(path[i][0] - x, path[i][1] - y) > RETRACE_TOL_M:
                return f"off the driven trail by more than {RETRACE_TOL_M} m"
            if i == len(path) - 1 and math.hypot(path[-1][0] - x, path[-1][1] - y) <= END_M:   # a lap passes the start
                self.stats["retrace_completed"] = True
                return "trail end (start pose)"
            s, scan = run.call("GET", "/sensors/lidar")
            if s != 200 or not isinstance(scan, dict):
                return f"no LiDAR scan ({s})"
            key = (scan.get("received_at"), scan.get("source_stamp_ns"))
            if key != scan_key and key != (None, None):
                scan_key, scan_at = key, run.r.now()
            if run.r.now() - scan_at > SCAN_STALE_S:
                return f"LiDAR scan not updated for more than {SCAN_STALE_S} s"
            _report, warn = edge_drive.advisory(PINKY_PRO.scan_view(scan, forward_deg=deg), -RETRACE_SPEED, 1.0)
            if warn:
                return f"rear {warn}"
            tx, ty = next(((p[0], p[1]) for p in path[i:] if math.hypot(p[0] - x, p[1] - y) >= RETRACE_LOOKAHEAD_M),
                          path[-1][:2])
            dx, dy = tx - x, ty - y          # pure pursuit in the reversed body frame (heading yaw + pi)
            left = dx * math.sin(yaw) - dy * math.cos(yaw)
            ang = RETRACE_SPEED * 2.0 * left / max(dx * dx + dy * dy, 1e-6)
            ang = max(-RETRACE_MAX_ANG, min(RETRACE_MAX_ANG, ang))
            now = run.r.now()
            if sent_at is not None:
                period = now - sent_at
                self.stats["retrace_max_period_s"] = round(max(self.stats["retrace_max_period_s"] or 0.0, period), 3)
                if period > RETRACE_MAX_PERIOD_S:
                    return f"send period {period:.2f} s over {RETRACE_MAX_PERIOD_S} s"
            s, _ = run.call("POST", "/teleop", {"linear": -RETRACE_SPEED, "angular": ang})
            sent_at = now
            if s != 200:
                return f"teleop refused {s}"
            run.r.sleep(max(0.0, TICK_S - (run.r.now() - tick_at)))
