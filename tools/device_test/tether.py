"""D-512 tether guard (user decision 2026-10-08): the robot drives on its charging cable.

The agent declares the cable per run from the overhead frame (verdict `tether`):
cable_m (2.0 or 5.0), anchor_robot_frame [forward_m, left_m] at capture, how it judged it.
Each drive tick: trail.jsonl (pose samples >= 1 cm apart), distance to the anchor and the
unwrapped cumulative yaw. Over cable_m - margin_m or |turn| > max_turn_deg = trip: line-follow
OFF (confirmed), then reverse along the recorded trail (D-407 drove-through basis) under the
RobotBody rear gap until the cable is slack again or the trail ends; any doubt stops (IDLE).
The trip is still an abort (exit 2). Poses are /robot/state `pose`, the source the distance
cap uses. CORE (D-422, teleop watchdog) stays the motion authority.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import edge_drive
from core_common.robot_body import PINKY_PRO

CABLES_M = (2.0, 5.0)             # the two cables on site (user 2026-10-08)
STEP_M = 0.01                     # trail sample spacing
RETRACE_SPEED = 0.03              # m/s, reverse
RETRACE_MAX_ANG = 0.3             # rad/s, below the nudge limit edge_drive.LIMITS[1]
RETRACE_LOOKAHEAD_M = 0.08        # pure pursuit on the reversed trail
RETRACE_TOL_M = 0.10              # pose farther than this from the trail = off the driven space
RETRACE_MAX_S = 180.0             # time cap for one retrace
RETRACE_WINDOW = 50               # trail points searched ahead (0.5 m): a lap crossing is not progress
UNWIND_TURN_DEG = 90.0            # retrace ends at |turn| <= max_turn - this ...
UNWIND_SLACK_M = 0.1              # ... and anchor distance <= cable_m - margin - this
END_M = 0.02                      # within this of the first trail point = trail exhausted
TICK_S = 0.1


class TetherTrip(RuntimeError):
    pass


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check(verdict, policy):
    """The declared tether, or None. ValueError (fail closed) for anything not shown."""
    t = verdict.get("tether")
    if t is None:
        if verdict["cable_attached"]:
            raise ValueError("camera verdict: cable attached but no tether {cable_m, anchor_robot_frame, how}")
        return None
    if not verdict["cable_attached"]:
        raise ValueError("camera verdict: tether declared but cable_attached is false")
    anchor = t.get("anchor_robot_frame") if isinstance(t, dict) else None
    if not isinstance(t, dict) or not _finite(t.get("cable_m")) or t["cable_m"] not in CABLES_M:
        raise ValueError(f"camera verdict: tether.cable_m must be one of {CABLES_M}")
    if not (isinstance(anchor, list) and len(anchor) == 2 and all(_finite(a) for a in anchor)):
        raise ValueError("camera verdict: tether.anchor_robot_frame must be [forward_m, left_m]")
    if not str(t.get("how") or "").strip():
        raise ValueError("camera verdict: tether.how is empty")
    limit = t["cable_m"] - policy["margin_m"]
    if math.hypot(*anchor) > limit:
        raise ValueError(f"tether: anchor {math.hypot(*anchor):.2f} m away, over the {limit:.2f} m limit at start")
    return t


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class Guard:
    def __init__(self, verdict, policy, ev):
        self.t, self.policy, self.path = check(verdict, policy), policy, Path(ev) / "trail.jsonl"
        self.trail, self.anchor, self.yaw, self.turn = [], None, None, 0.0
        self.stats = {"declared": self.t, "policy": policy, "max_anchor_m": None, "max_turn_deg": 0.0,
                      "trail_points": 0}

    def limit_m(self):
        return self.t["cable_m"] - self.policy["margin_m"]

    def _pose(self, st):
        p = st.get("pose") if isinstance(st, dict) else None
        return (p["x"], p["y"], p["yaw"]) if isinstance(p, dict) and all(_finite(p.get(k)) for k in ("x", "y", "yaw")) \
            else None

    def _update(self, x, y, yaw):
        """Unwrap the yaw and keep the trail; returns the anchor distance (None without a tether)."""
        if self.yaw is None:
            f, l = self.t["anchor_robot_frame"] if self.t else (0.0, 0.0)
            self.anchor = (x + f * math.cos(yaw) - l * math.sin(yaw), y + f * math.sin(yaw) + l * math.cos(yaw))
        else:
            self.turn += wrap(yaw - self.yaw)
        self.yaw = yaw
        if not self.trail or math.hypot(x - self.trail[-1][0], y - self.trail[-1][1]) >= STEP_M:
            self.trail.append((x, y, yaw))
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"x": round(x, 4), "y": round(y, 4), "yaw": round(yaw, 4),
                                    "turn_deg": round(math.degrees(self.turn), 1)}) + "\n")
        self.stats["trail_points"] = len(self.trail)
        self.stats["max_turn_deg"] = round(max(self.stats["max_turn_deg"], abs(math.degrees(self.turn))), 1)
        if not self.t:
            return None
        d = math.hypot(x - self.anchor[0], y - self.anchor[1])
        self.stats["max_anchor_m"] = round(max(self.stats["max_anchor_m"] or 0.0, d), 3)
        return d

    def tick(self, st, run):
        """One drive tick with a /robot/state body (None = that read failed; run.py counts those)."""
        run.summary["tether"] = self.stats
        if st is None:
            return
        pose = self._pose(st)
        if pose is None:
            if self.t:
                raise TetherTrip("pose unknown: the tether limits cannot be enforced")
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
        self.stats.update(trip=trip, retrace_m=0.0, retrace_completed=False)
        run.phase("tether", trip=trip, anchor_m=self.stats["max_anchor_m"], turn_deg=round(math.degrees(self.turn), 1))
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
            "retrace_end", "retrace_m", "retrace_completed", "final_turn_deg", "final_anchor_m")})
        raise TetherTrip(f"tether trip {trip}, {'retraced' if self.stats['retrace_completed'] else 'retrace stopped'} "
                         f"{self.stats['retrace_m']:.2f} m ({end})")

    def _retrace(self, run):
        """Reverse along the trail; returns why it ended. Completed only when unwound or at the trail start."""
        path, i, t0, last = self.trail[::-1], 0, run.r.now(), None
        deg, _src = edge_drive.lidar_forward_deg(run.args.robot)
        while True:
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
            if run.r.now() - t0 > RETRACE_MAX_S:
                return f"time cap {RETRACE_MAX_S:.0f} s"
            x, y, yaw = pose
            d = self._update(x, y, yaw)
            self.stats["final_anchor_m"] = round(d, 3)
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
            _report, warn = edge_drive.advisory(PINKY_PRO.scan_view(scan, forward_deg=deg), -RETRACE_SPEED, 1.0)
            if warn:
                return f"rear {warn}"
            tx, ty = next(((p[0], p[1]) for p in path[i:] if math.hypot(p[0] - x, p[1] - y) >= RETRACE_LOOKAHEAD_M),
                          path[-1][:2])
            dx, dy = tx - x, ty - y          # pure pursuit in the reversed body frame (heading yaw + pi)
            left = dx * math.sin(yaw) - dy * math.cos(yaw)
            ang = RETRACE_SPEED * 2.0 * left / max(dx * dx + dy * dy, 1e-6)
            ang = max(-RETRACE_MAX_ANG, min(RETRACE_MAX_ANG, ang))
            s, _ = run.call("POST", "/teleop", {"linear": -RETRACE_SPEED, "angular": ang})
            if s != 200:
                return f"teleop refused {s}"
            run.r.sleep(TICK_S)
