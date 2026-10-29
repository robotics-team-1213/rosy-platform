"""Jaw marking and pivot self-calibration of the pixel -> arm map, without a person (2026-10-28 field results).

The top camera sees the gripper linkage move when the jaws open, not both fingers. mark_jaws() finds it:
grip to the mark value (50.5; the jaws' own end 48.5 twists the wrist), wait until the view is still, open,
wait again, difference the frames, keep blobs of a plausible size, follow the one nearest the last mark, and
accept a point when two marks agree within 3 px.

pivot_calibrate() holds the TCP at one arm point over a plain surface and commands several yaws. The mark
traces a circle around the TCP (radius ~18.8 mm, mark angle - FK yaw ~53 deg on arm S). The circle's centre
against the TCP from the measured joints (FK, not the commanded yaw: the solver may return the 180 deg twin)
is the map's bias for that region: arm point read from the map = true point + bias. The bias record is saved
next to the map (`<map>.bias.json`, rosy.omx-cell-bias.v1) and used to correct located objects; objects under
the jaws corrupt the difference, so the point must be clear.
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts  # noqa: E402
import cell_calibration as cal  # noqa: E402
import cell_params as prm  # noqa: E402

SCHEMA = "rosy.omx-cell-bias.v1"
STILL_PX, DIFF_PX, MIN_BLOB, MAX_BLOB, FOLLOW_PX, AGREE_PX = (
    prm.default(f"pivot.{k}") for k in ("still_px", "diff_px", "min_blob", "max_blob", "follow_px", "agree_px"))
BIAS_REACH_MM = prm.default("pivot.bias_reach_mm")  # a region's bias is trusted this far from its pivot point


def _changed_mask(a, b, threshold: int = DIFF_PX):  # the 3x3 opening is fixed: noise removal, not a decision
    import cv2

    diff = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    return cv2.morphologyEx((diff > threshold).astype(np.uint8) * 255, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def settled_frame(cell, sleep=time.sleep, clock=time.monotonic, limit_s: float | None = None, params=None):
    """Two top frames 0.4 s apart that differ by < 40 px (sensor noise scatters ~200 px, hence the opening)."""
    limit_s = prm.get(params, "pivot.settle_limit_s") if limit_s is None else limit_s
    before, deadline = cell.frame("top"), clock() + limit_s
    while True:
        sleep(prm.get(params, "pivot.settle_step_s"))
        now = cell.frame("top")
        if int(np.count_nonzero(_changed_mask(before, now, prm.get(params, "pivot.diff_px", DIFF_PX)))) < prm.get(params, "pivot.still_px", STILL_PX) or clock() > deadline:
            return now
        before = now


def jaw_blobs(closed, opened, params=None) -> list:
    """(cx, cy, area) of the changed blobs of plausible size; [] when the frames barely differ."""
    import cv2

    diff_px, max_blob = prm.get(params, "pivot.diff_px", DIFF_PX), prm.get(params, "pivot.max_blob", MAX_BLOB)
    mask = _changed_mask(closed, opened, diff_px)
    if int(np.count_nonzero(mask)) <= diff_px:
        return []
    n, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
    return [(float(centroids[i][0]), float(centroids[i][1]), int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, n)
            if stats[i, cv2.CC_STAT_AREA] >= prm.get(params, "pivot.min_blob", MIN_BLOB)
            and stats[i, cv2.CC_STAT_WIDTH] <= max_blob and stats[i, cv2.CC_STAT_HEIGHT] <= max_blob]


def mark_jaws(cell, config: dict, sleep=time.sleep, clock=time.monotonic, max_marks: int = 6, near=None):
    """The jaw mark in the top view as (cx, cy), or None when no two marks agree. `near` = (pixel, radius_px): only
    blobs that close to where the jaws should be count, nearest first - with the arm stretched out, opening the jaws
    shook the whole link and the largest changed blob was not the jaws (2026-10-29, a look 30 mm off)."""
    import cell_pipeline as cp

    plan, mark_cfg = config["plan"], config.get("jaw_mark", {})
    p = config.get("params")
    closed_to, marks = mark_cfg.get("closed", prm.get(p, "pivot.grip_closed")), []
    follow, agree = prm.get(p, "pivot.follow_px", FOLLOW_PX), prm.get(p, "pivot.agree_px", AGREE_PX)
    for _ in range(max_marks):
        if not cp.grip_to(cell, closed_to):
            return None
        closed = settled_frame(cell, sleep, clock, params=p)
        if not cp.grip_to(cell, plan["grip_open"]):
            return None
        blobs = jaw_blobs(closed, settled_frame(cell, sleep, clock, params=p), p)
        if marks:
            blobs = [b for b in blobs if math.dist(b[:2], marks[-1]) <= follow]
            pick = min(blobs, key=lambda b: math.dist(b[:2], marks[-1]), default=None)
        elif near is not None:
            blobs = [b for b in blobs if math.dist(b[:2], near[0]) <= near[1]]
            pick = min(blobs, key=lambda b: math.dist(b[:2], near[0]), default=None)
        else:
            pick = max(blobs, key=lambda b: b[2], default=None)
        if pick is None:
            continue
        if any(math.dist(pick[:2], m) <= agree for m in marks):
            return pick[0], pick[1]
        marks.append(pick[:2])
    return None


def fit_circle(points) -> tuple[float, float, float, float]:
    """Algebraic (Kasa) least squares: centre x, y, radius, rms residual."""
    p = np.asarray(points, float)
    a = np.c_[2 * p, np.ones(len(p))]
    (cx, cy, c), *_ = np.linalg.lstsq(a, (p ** 2).sum(axis=1), rcond=None)
    r = math.sqrt(max(c + cx * cx + cy * cy, 0.0))
    return float(cx), float(cy), r, float(np.sqrt(np.mean((np.hypot(p[:, 0] - cx, p[:, 1] - cy) - r) ** 2)))


def map_record(calibration: dict, site: str) -> dict | None:
    from cell_observe import record_key

    sites = calibration.get("sites", {})
    return sites.get(record_key(site, "top")) or sites.get(f"{site}~coarse")


def mark_to_arm(record: dict, config: dict, site: str, pixel, jaw_z: float):
    """The mark pixel (seen at the jaws' height) to the height the map was fitted at, then through the map."""
    fit_z = record.get("z_view", config["sites"][site]["z"])
    return cal.to_arm(record["homography"], cal.parallax(pixel, jaw_z, fit_z, config["cameras"]["top"]))


def mark_pixel(record: dict, config: dict, site: str, raw, jaw_z: float):
    """mark_to_arm backwards: where a raw map point at the jaws' height shows in the top view."""
    fit_z = record.get("z_view", config["sites"][site]["z"])
    return cal.parallax(cal.to_pixel(record["homography"], raw), fit_z, jaw_z, config["cameras"]["top"])


def joints_tcp(state):
    """FK of the measured joints (planner units): x, y, z in metres and the FK yaw in degrees."""
    import grasp_planner as gp

    kin = gp.load_kinematics(None)[0]
    fk = kin.fk([gp.norm_to_rad(v) for v in state[:5]])
    return fk.x, fk.y, fk.z, math.degrees(fk.yaw)


def pivot_calibrate(cell, config: dict, point, yaws, calibration: dict, site: str, work: Path,
                    sleep=time.sleep, log=print) -> dict:
    """Hold the TCP at `point` (x, y metres) over a clear surface at each yaw, mark the jaws, fit the circle.
    Returns {"result": "calibrated", "bias": record} or {"result": "stopped"/..., ...}; the arm is parked."""
    import cell_pipeline as cp

    record = map_record(calibration, site)
    if record is None:
        return {"result": "no map for the site"}
    z_view = config.get("pivot", {}).get("z_view", config["coarse"]["z_view"])
    view = {"x": point[0], "y": point[1], "z": round(z_view - config["plan"]["approach_m"], 4)}
    marks, tcps = [], []
    try:
        for i, yaw in enumerate(yaws):
            try:
                library = cp.write_library(config, dict(view, yaw_deg=yaw), dict(view, yaw_deg=yaw),
                                           work / f"pivot-{site}-{i}.json")
            except SystemExit as exc:  # no IK at this yaw: the other yaws still fit
                log({"pivot": yaw, "skipped": str(exc)[:120]})
                continue
            for command in (f"load {library}", "goto above_pick"):
                status = cell.act(command)
                if not status.get("ok"):
                    return {"result": "stopped", "at": command, "error": status.get("error")}
            state = cell.act("state").get("state")
            pixel = mark_jaws(cell, config, sleep)
            log({"pivot": yaw, "mark_px": pixel})
            if state is None or pixel is None:
                continue
            x, y, z, fk_yaw = joints_tcp(state)
            marks.append(mark_to_arm(record, config, site, pixel, z))
            tcps.append((x, y, z, fk_yaw))
    finally:
        cell.act("park")
    if len(marks) < 4:
        return {"result": f"jaws marked at {len(marks)} yaws, need 4"}
    cx, cy, radius, rms = fit_circle(marks)
    tx, ty = (float(np.mean([t[i] for t in tcps])) for i in (0, 1))
    phases = [math.atan2(m[1] - cy, m[0] - cx) - math.radians(t[3]) for m, t in zip(marks, tcps)]
    phase = math.degrees(math.atan2(np.mean(np.sin(phases)), np.mean(np.cos(phases))))
    bias = {"site": site, "point_m": [round(tx, 4), round(ty, 4)], "bias_mm": [round(1000 * (cx - tx), 1), round(1000 * (cy - ty), 1)],
            "radius_mm": round(1000 * radius, 1), "phase_deg": round(phase, 1), "rms_mm": round(1000 * rms, 1),
            "yaws_fk_deg": [round(t[3], 1) for t in tcps], "n": len(marks),
            "map_sha": cell_attempts.digest(record),
            "measured": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    # a circle the marks do not follow is not a bias: next to the Pinky body the marks gave radius 70 mm, rms 13.6 mm
    # and a 6 cm "bias" (2026-10-28); the mark sits ~19-28 mm off the TCP, so a radius far outside that is refused
    params = config.get("params")
    if rms * 1000 > prm.get(params, "pivot.max_rms_mm") or not (
            prm.get(params, "pivot.radius_lo_mm") <= radius * 1000 <= prm.get(params, "pivot.radius_hi_mm")):
        return {"result": f"circle refused: radius {bias['radius_mm']} mm, rms {bias['rms_mm']} mm", "bias": bias}
    return {"result": "calibrated", "bias": bias}


def bias_path(calibration_path) -> Path:
    return Path(calibration_path).with_suffix(".bias.json")


def load_bias(path) -> dict:
    path = Path(path)
    data = json.loads(path.read_text()) if path.exists() else {"schema": SCHEMA, "regions": []}
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: not a {SCHEMA} file")
    return data


def save_bias(path, bias: dict) -> None:
    """Keep one region per site and place: a new one within 10 mm replaces the older."""
    data = load_bias(path)
    data["regions"] = [r for r in data["regions"] if r["site"] != bias["site"]
                       or math.dist(r["point_m"], bias["point_m"]) > 0.010] + [bias]
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def bias_at(data: dict, site: str, point_m, reach_mm: float | None = None, params=None):
    """The nearest region's bias (dx, dy mm) within reach of the point, else None."""
    reach_mm = prm.get(params, "pivot.bias_reach_mm", BIAS_REACH_MM) if reach_mm is None else reach_mm
    near = [r for r in data["regions"] if r["site"] == site and 1000 * math.dist(r["point_m"], point_m) <= reach_mm]
    return min(near, key=lambda r: math.dist(r["point_m"], point_m), default=None)
