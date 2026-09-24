"""Pure logic behind lane_live_view.py (ROS-free, read-only).

- classify_tier / TierStats / History: the lane follower's confidence tier
  inferred from `line/observation` confidence (the tier itself is not on
  the wire; lane_boundaries: BOTH, ONE capped at 0.8, MEMORY at 0.6, STOP).
- derive_phase: the mission phase (부팅 → 칸 확인 → 출차 → 순회 → 주차 →
  완료) from CORE's docking and line-follow state, or from a mission
  harness's live core_status.jsonl when one is being written.
- RouteProgress: forward-only progress of an odom pose along the all-lane
  tour (lane_coverage.coverage_route from the parking junction).
- ClockMonitor: sim real-time factor and the wall-clock step that
  junction_harness also checks (CLOCK_STEP_TOLERANCE_S).
- spot_error: pose against the parking spot (mission_harness tolerances).
- list_runs / load_run / live_log_phase: the evidence directory.

Nothing here publishes, commands or writes: it only reads.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import deque
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# `control` import: the sourced install first, the worktree's source second
# --------------------------------------------------------------------------

_WORKTREE_CONTROL = Path(__file__).resolve().parents[3] / "core" / "control"


def _control_sensing():
    """(lane_coverage, lane_route) from `control.sensing`. The sourced
    install is preferred; when it lacks these modules (an install older
    than lane_coverage) or is not sourced, the worktree's own
    src/core/control is used so the viewer runs straight from source."""
    try:
        from control.sensing import lane_coverage, lane_route
        return lane_coverage, lane_route
    except ImportError:
        pass
    for name in [n for n in sys.modules if n == "control" or n.startswith("control.")]:
        del sys.modules[name]
    sys.path.insert(0, str(_WORKTREE_CONTROL))
    from control.sensing import lane_coverage, lane_route
    return lane_coverage, lane_route


# --------------------------------------------------------------------------
# Confidence tier
# --------------------------------------------------------------------------

TIERS = ("BOTH", "ONE", "MEMORY", "STOP")
TIER_LABELS = {"BOTH": "양쪽 인식", "ONE": "한쪽 인식", "MEMORY": "기억", "STOP": "정지"}
#: Lower bounds of each tier's confidence. BOTH reports >= 0.85, ONE is
#: capped at lane_boundaries.ONE_MAX_CONFIDENCE (0.8), MEMORY sits at
#: lane_bev.MEMORY_CONFIDENCE (0.6), and below CORE_MIN_CONFIDENCE (0.35)
#: CORE stops.
TIER_MIN_CONFIDENCE = {"BOTH": 0.85, "ONE": 0.65, "MEMORY": 0.35}


def classify_tier(observation):
    """Tier of one `line/observation` sample, or None when there is none."""
    if not observation:
        return None
    confidence = observation.get("confidence")
    if not observation.get("visible") or confidence is None:
        return "STOP"
    for tier in ("BOTH", "ONE", "MEMORY"):
        if confidence >= TIER_MIN_CONFIDENCE[tier]:
            return tier
    return "STOP"


class TierStats:
    """Cumulative tier distribution over one run."""

    def __init__(self):
        self.counts = dict.fromkeys(TIERS, 0)

    def add(self, tier):
        if tier in self.counts:
            self.counts[tier] += 1

    def reset(self):
        self.counts = dict.fromkeys(TIERS, 0)

    def snapshot(self):
        total = sum(self.counts.values())
        pct = {t: round(100.0 * c / total, 1) if total else 0.0 for t, c in self.counts.items()}
        return {"samples": total, "pct": pct}


class History:
    """Rolling (t, error, confidence, tier) samples for the sparkline."""

    def __init__(self, window_s=60.0):
        self.window_s = window_s
        self._items = deque()

    def add(self, t, error, confidence, tier):
        self._items.append((t, error, confidence, tier))
        while self._items and self._items[0][0] < t - self.window_s:
            self._items.popleft()

    def reset(self):
        self._items.clear()

    def series(self, now):
        cutoff = now - self.window_s
        return [[round(t - now, 2), _r(e, 4), _r(c, 3), tier]
                for t, e, c, tier in list(self._items) if t >= cutoff]


def _r(value, digits):
    return None if value is None else round(float(value), digits)


# --------------------------------------------------------------------------
# Parking spot error
# --------------------------------------------------------------------------

#: mission_harness PARK_POSITION_TOLERANCE_M / PARK_HEADING_TOLERANCE_RAD.
SPOT_POSITION_TOLERANCE_M = 0.020
SPOT_HEADING_TOLERANCE_DEG = 5.0


def spot_error(pose, spot):
    """Distance and heading error of (x, y, yaw) against the spot pose."""
    dist = math.hypot(pose[0] - spot[0], pose[1] - spot[1])
    dyaw = math.atan2(math.sin(pose[2] - spot[2]), math.cos(pose[2] - spot[2]))
    heading = math.degrees(dyaw)
    ok_position = dist <= SPOT_POSITION_TOLERANCE_M
    ok_heading = abs(heading) <= SPOT_HEADING_TOLERANCE_DEG
    return {"dist_m": round(dist, 4), "heading_err_deg": round(heading, 3),
            "ok_position": ok_position, "ok_heading": ok_heading,
            "ok": ok_position and ok_heading,
            "target_m": SPOT_POSITION_TOLERANCE_M, "target_deg": SPOT_HEADING_TOLERANCE_DEG}


# --------------------------------------------------------------------------
# Mission phase
# --------------------------------------------------------------------------

PHASES = ("boot", "confirm", "undock", "tour", "park", "done")
PHASE_LABELS = {"boot": "부팅", "confirm": "칸 확인", "undock": "출차",
                "tour": "순회", "park": "주차", "done": "완료"}
_LOG_PHASES = ("confirm", "undock", "tour", "park")


def derive_phase(prev, *, core_ok, docking, line_mode, log_phase=None, route_done=False):
    """Current mission phase. A fresh mission-harness log names it directly
    (its `park` becomes `done` once docked); otherwise it follows CORE:
    UNDOCKING is 출차, an active line-follow mode is 순회, DOCKING is 칸
    확인 before the tour and 주차 after it, DOCKED after parking is 완료.
    A CORE blip or an idle gap between phases keeps the phase it was in."""
    if log_phase in _LOG_PHASES:
        if log_phase == "park" and docking == "DOCKED":
            return "done"
        return log_phase
    if not core_ok:
        return prev if prev not in (None,) else "boot"
    after_tour = route_done or prev in ("tour", "park", "done")
    if docking == "UNDOCKING":
        return "undock"
    if line_mode not in (None, "OFF"):
        return "tour"
    if docking == "DOCKING":
        return "park" if after_tour else "confirm"
    if docking == "DOCKED":
        return "done" if (route_done or prev in ("park", "done")) else "confirm"
    if prev in ("undock", "tour", "park"):
        return prev
    return "boot"


# --------------------------------------------------------------------------
# Sim clock health
# --------------------------------------------------------------------------

#: junction_harness.CLOCK_STEP_TOLERANCE_S: a wall-clock step bigger than
#: this invalidates timing (WSL clock resync).
CLOCK_STEP_TOLERANCE_S = 1.0


class ClockMonitor:
    """Real-time factor over a sliding wall window, the sim clock's age,
    and how far the wall clock has been stepped since the viewer started
    (`offset` = time.time() - time.monotonic(), constant unless stepped)."""

    def __init__(self, window_s=5.0, offset=None):
        self.window_s = window_s
        self._base_offset = offset
        self._samples = deque()

    def on_clock(self, sim_s, wall_mono):
        """Record one /clock sample; True when the sim clock went backwards
        (Gazebo relaunched)."""
        reset = bool(self._samples) and sim_s < self._samples[-1][1]
        if reset:
            self._samples.clear()
        self._samples.append((wall_mono, sim_s))
        while self._samples and self._samples[0][0] < wall_mono - self.window_s:
            self._samples.popleft()
        return reset

    def snapshot(self, wall_mono, offset):
        if self._base_offset is None:
            self._base_offset = offset
        step = round(offset - self._base_offset, 1)
        out = {"sim_s": None, "rtf": None, "age_s": None, "step_s": step,
               "step_warn": abs(step) > CLOCK_STEP_TOLERANCE_S}
        if not self._samples:
            return out
        (w0, s0), (w1, s1) = self._samples[0], self._samples[-1]
        out["sim_s"] = round(s1, 2)
        out["age_s"] = round(wall_mono - w1, 2)
        if w1 - w0 > 0.2:
            out["rtf"] = round((s1 - s0) / (w1 - w0), 3)
        return out


# --------------------------------------------------------------------------
# Route progress
# --------------------------------------------------------------------------


def tour_start(graph):
    """The tour's start: the parking spur's junction point on `west`."""
    return tuple(float(v) for v in graph["parking"]["points"][0])


def tour_keys(graph, start_xy=None):
    """lane_coverage's all-lane tour from the parking junction (13 keys on
    map_v2_fleet), the route the mission harness hands the follower."""
    lane_coverage, _ = _control_sensing()
    return lane_coverage.coverage_route(graph, start_xy or tour_start(graph))


class RouteProgress:
    """Forward-only arc-length progress of a pose along `keys`, from
    `start_xy` on the first key to `start_xy` on the last (the tour starts
    and ends mid-segment at the parking junction). Each fix searches only
    a window around the last one, so a pass cannot jump to another pass
    of the same place, and a fix behind the last never moves it back."""

    BACK_WINDOW_M = 0.1
    AHEAD_WINDOW_M = 0.5
    MAX_LATERAL_M = 0.12
    FINISH_M = 0.03

    def __init__(self, graph, keys, start_xy=None):
        _, lane_route = _control_sensing()
        self.keys = list(keys)
        segs = [lane_route.DirectedSegment.from_graph(graph, k) for k in self.keys]
        chunks, starts = [segs[0].points], [0.0]
        for prev, seg in zip(segs, segs[1:]):
            starts.append(starts[-1] + prev.length_m)
            chunks.append(seg.points[1:])
        self._points = np.vstack(chunks)
        self._arc = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(self._points, axis=0), axis=1))])
        self._starts = np.asarray(starts)
        start = np.asarray(start_xy or tour_start(graph), float)
        first_end = segs[0].length_m
        self._s0 = self._project(start, 0.0, first_end)[0]
        self._s_end = self._project(start, starts[-1], float(self._arc[-1]))[0]
        self.length_m = self._s_end - self._s0
        self._s = self._s0

    def _project(self, p, lo, hi):
        a, b = self._points[:-1], self._points[1:]
        mask = (self._arc[1:] >= lo) & (self._arc[:-1] <= hi)
        idx = np.nonzero(mask)[0]
        a, b = a[idx], b[idx]
        ab = b - a
        ab_len2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12)
        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / ab_len2, 0.0, 1.0)
        proj = a + ab * t[:, None]
        d = np.linalg.norm(p - proj, axis=1)
        k = int(np.argmin(d))
        i = int(idx[k])
        s = float(self._arc[i] + t[k] * math.sqrt(ab_len2[k]))
        return min(max(s, lo), hi), float(d[k])

    def reset(self):
        self._s = self._s0

    def point_at(self, progress_m):
        """(x, y, heading) `progress_m` along the route from its start."""
        s = min(max(self._s0 + progress_m, self._s0), self._s_end)
        i = int(np.searchsorted(self._arc, s, side="right")) - 1
        i = min(max(i, 0), len(self._points) - 2)
        a, b = self._points[i], self._points[i + 1]
        span = self._arc[i + 1] - self._arc[i]
        t = 0.0 if span <= 0 else (s - self._arc[i]) / span
        p = a + t * (b - a)
        return float(p[0]), float(p[1]), math.atan2(b[1] - a[1], b[0] - a[0])

    def update(self, xy):
        """Advance on one pose; False when it is off the route window."""
        lo = max(self._s - self.BACK_WINDOW_M, self._s0)
        hi = min(self._s + self.AHEAD_WINDOW_M, self._s_end)
        s, lateral = self._project(np.asarray(xy, float), lo, hi)
        if lateral > self.MAX_LATERAL_M:
            return False
        self._s = max(self._s, s)
        return True

    def snapshot(self):
        finished = self._s_end - self._s <= self.FINISH_M
        idx = int(np.searchsorted(self._starts, self._s, side="right")) - 1
        idx = min(max(idx, 0), len(self.keys) - 1)
        if finished:
            states = ["done"] * len(self.keys)
            done = set(self.keys)
        else:
            states = ["done"] * idx + ["current"] + ["todo"] * (len(self.keys) - idx - 1)
            done = set(self.keys[1:idx])
        progress = self._s - self._s0
        return {"keys": self.keys, "length_m": round(self.length_m, 3),
                "progress_m": round(progress, 3),
                "fraction": round(progress / self.length_m, 4) if self.length_m else 0.0,
                "segment_index": idx, "current_key": self.keys[idx],
                "key_states": states, "done_unique": len(done),
                "total_unique": len(set(self.keys)), "finished": finished}


# --------------------------------------------------------------------------
# Evidence runs
# --------------------------------------------------------------------------

RUN_KINDS = {"junctions_": ("junctions", "교차로"), "tour_": ("tour", "순회"),
             "mission_": ("mission", "미션")}
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TRACK_MAX_POINTS = 600


def _kind(name):
    for prefix, (kind, label) in RUN_KINDS.items():
        if name.startswith(prefix):
            return kind, label, name[len(prefix):]
    return None


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _summarise(run_dir):
    kind, label, tag = _kind(run_dir.name)
    results_path = run_dir / "results.json"
    results = _read_json(results_path) if results_path.is_file() else None
    mtime = (results_path if results_path.is_file() else run_dir).stat().st_mtime
    summary = {"id": run_dir.name, "kind": kind, "label": label, "tag": tag,
               "mtime": mtime, "pass": None, "reason": None, "metrics": {}}
    if kind == "junctions" and isinstance(results, list):
        devs = [s.get("max_centre_dev_m") for s in results if s.get("max_centre_dev_m") is not None]
        summary["pass"] = bool(results) and all(s.get("pass") for s in results)
        summary["metrics"] = {
            "scenarios": len(results), "passed": sum(1 for s in results if s.get("pass")),
            "max_dev_m": max(devs) if devs else None,
            "sim_s": round(sum(s.get("sim_s") or 0.0 for s in results), 2)}
    elif isinstance(results, dict):
        summary["pass"] = bool(results.get("pass"))
        summary["reason"] = results.get("reason")
        metrics = {"sim_s": results.get("sim_s"), "rtf": results.get("real_time_factor")}
        if kind == "mission":
            tour = results.get("tour") or {}
            metrics.update(max_dev_m=tour.get("max_centre_dev_m"),
                           end_error_m=tour.get("end_distance_m"),
                           park_error_m=results.get("park_error_m"),
                           park_dyaw_deg=results.get("park_dyaw_deg"))
        else:
            metrics.update(max_dev_m=results.get("max_centre_dev_m"),
                           end_error_m=results.get("end_distance_m"),
                           progress_m=results.get("progress_m"),
                           route_length_m=results.get("route_length_m"))
        summary["metrics"] = metrics
    return summary, results


def _run_dirs(evidence_dir):
    base = Path(evidence_dir)
    if not base.is_dir():
        return []
    return [d for d in base.iterdir() if d.is_dir() and _kind(d.name)]


def list_runs(evidence_dir):
    """Every junctions_/tour_/mission_ run, newest first."""
    runs = [_summarise(d)[0] for d in _run_dirs(evidence_dir)]
    return sorted(runs, key=lambda r: (-r["mtime"], r["id"]))


def downsample(points, max_points):
    """At most ~max_points evenly spaced points, first and last kept."""
    if len(points) <= max_points:
        return list(points)
    step = len(points) / max_points
    out = [points[int(i * step)] for i in range(max_points)]
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _xy(track):
    return [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in track]


def _tracks(run_dir, kind):
    if kind == "junctions":
        tracks = []
        for sub in sorted(d for d in run_dir.iterdir() if d.is_dir()):
            track = _read_json(sub / "track.json")
            if track:
                tracks.append({"label": sub.name,
                               "points": downsample(_xy(track), TRACK_MAX_POINTS)})
        return tracks
    track = _read_json(run_dir / "track.json") or []
    if kind != "mission":
        return [{"label": "tour", "points": downsample(_xy(track), TRACK_MAX_POINTS)}] \
            if track else []
    groups = []
    for p in track:
        phase = p[4] if len(p) > 4 else None
        if phase is None:
            continue
        if not groups or groups[-1]["label"] != phase:
            groups.append({"label": phase, "points": []})
        groups[-1]["points"].append(p)
    return [{"label": g["label"], "points": downsample(_xy(g["points"]), TRACK_MAX_POINTS)}
            for g in groups]


def load_run(evidence_dir, run_id):
    """Summary, raw results and tracks of one run, or None for an unknown
    id (only a direct child named like a run is ever read)."""
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
        return None
    run_dir = next((d for d in _run_dirs(evidence_dir) if d.name == run_id), None)
    if run_dir is None:
        return None
    summary, results = _summarise(run_dir)
    if isinstance(results, dict):
        results = {k: v for k, v in results.items() if k != "launch"}
    return {"summary": summary, "results": results, "tracks": _tracks(run_dir, summary["kind"])}


def _last_json_line(path, tail_bytes=8192):
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - tail_bytes))
        lines = fh.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def live_log_phase(evidence_dir, now_wall, fresh_s=5.0):
    """Phase of the newest mission_* run whose core_status.jsonl was written
    within `fresh_s`, or None when no mission harness is writing now."""
    logs = [d / "core_status.jsonl" for d in _run_dirs(evidence_dir)
            if d.name.startswith("mission_") and (d / "core_status.jsonl").is_file()]
    if not logs:
        return None
    newest = max(logs, key=lambda p: p.stat().st_mtime)
    if now_wall - newest.stat().st_mtime > fresh_s:
        return None
    try:
        last = _last_json_line(newest)
    except OSError:
        return None
    if not isinstance(last, dict):
        return None
    return {"run": newest.parent.name, "phase": last.get("phase"), "sim": last.get("sim")}
