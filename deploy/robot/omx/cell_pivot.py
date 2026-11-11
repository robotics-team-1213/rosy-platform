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
from cell_pipeline_io import fold  # noqa: E402

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
    # pieces this close are one mark: over a box top the gripper body hid the fingers and the open-closed change came
    # in 2-3 pieces of 72-260 px, none reaching min_blob (2026-11-02); the merge only groups, the area is the changed px
    merge = int(prm.get(params, "pivot.merge_px"))
    grouped = cv2.dilate(mask, np.ones((2 * merge + 1, 2 * merge + 1), np.uint8)) if merge else mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(grouped)
    blobs = []
    for i in range(1, n):
        x0, y0, bw, bh = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        ys, xs = np.nonzero((labels[y0:y0 + bh, x0:x0 + bw] == i) & (mask[y0:y0 + bh, x0:x0 + bw] > 0))
        if len(xs) >= prm.get(params, "pivot.min_blob", MIN_BLOB) and np.ptp(xs) < max_blob and np.ptp(ys) < max_blob:
            blobs.append((float(xs.mean()) + x0, float(ys.mean()) + y0, int(len(xs))))
    return blobs


def jaw_centre(closed, opened, params=None) -> list:
    """[(cx, cy, area)] of the midpoint of the jaws' two sides in the open-closed difference, or [] when both do not show.
    Either side alone is about 30 mm from the TCP, and which one is largest flips: a map on one side and a pivot on the
    other read 54 mm apart (arm_b 2026-11-06, free air: sides 75-80 px apart at z 0.14, one hidden over a dark box)."""
    import cv2

    mask = _changed_mask(closed, opened, prm.get(params, "pivot.diff_px", DIFF_PX))
    merge = int(prm.get(params, "jaw_centre.merge_px"))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask, np.ones((2 * merge + 1, 2 * merge + 1), np.uint8)))
    sides = []
    for i in range(1, n):
        x0, y0, bw, bh = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        ys, xs = np.nonzero((labels[y0:y0 + bh, x0:x0 + bw] == i) & (mask[y0:y0 + bh, x0:x0 + bw] > 0))
        if len(xs) >= prm.get(params, "jaw_centre.min_side_px"):
            sides.append((float(xs.mean()) + x0, float(ys.mean()) + y0, len(xs)))
    pairs = [(a, b) for k, a in enumerate(sides) for b in sides[k + 1:]
             if prm.get(params, "jaw_centre.gap_lo_px") <= math.dist(a[:2], b[:2]) <= prm.get(params, "jaw_centre.gap_hi_px")]
    if not pairs:
        return []
    a, b = max(pairs, key=lambda q: q[0][2] + q[1][2])
    return [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2] + b[2])]


def mark_open(config: dict) -> float:
    """The value the jaw mark opens the jaws to: the mark's own, never the pick's (a pick's 53.84 left no blob)."""
    return config.get("jaw_mark", {}).get("open", prm.get(config.get("params"), "pivot.grip_open", config.get("plan", {}).get("grip_open")))


def mark_jaws(cell, config: dict, sleep=time.sleep, clock=time.monotonic, max_marks: int = 6, near=None):
    """The jaw mark in the top view as (cx, cy), or None when no two marks agree. `near` = ([pixel, ...], radius_px):
    only blobs that close to one of the places the jaws should show count, nearest first - with the arm stretched out,
    opening the jaws shook the whole link and the largest changed blob was not the jaws (2026-10-29, a look 30 mm off).
    Several places: either finger can be the one the camera sees (cell_look)."""
    import cell_pipeline as cp

    plan, mark_cfg = config["plan"], config.get("jaw_mark", {})
    p = config.get("params")
    closed_to, marks = mark_cfg.get("closed", prm.get(p, "pivot.grip_closed")), []
    follow, agree = prm.get(p, "pivot.follow_px", FOLLOW_PX), prm.get(p, "pivot.agree_px", AGREE_PX)
    for _ in range(max_marks):
        if not cp.grip_to(cell, closed_to):
            return None
        closed = settled_frame(cell, sleep, clock, params=p)
        # the mark's own opening, not the pick's: a pick opened only to its box width (53.84 against 50.5 closed)
        # moved the jaws too little to leave a blob, and every look at the hover saw nothing (2026-10-29)
        if not cp.grip_to(cell, mark_open(config)):
            return None
        now = settled_frame(cell, sleep, clock, params=p)
        blobs = jaw_centre(closed, now, p) if mark_cfg.get("centre") else jaw_blobs(closed, now, p)
        if marks:
            blobs = [b for b in blobs if math.dist(b[:2], marks[-1]) <= follow]
            pick = min(blobs, key=lambda b: math.dist(b[:2], marks[-1]), default=None)
        elif near is not None:
            def gap(b):
                return min(math.dist(b[:2], q) for q in near[0])
            blobs = [b for b in blobs if gap(b) <= near[1]]
            pick = min(blobs, key=gap, default=None)
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


def with_site_maps(config: dict, calibration: dict) -> dict:
    """A site with `map_from` uses that site's map: one map is fitted per arm, whatever stands on the table today."""
    sites = dict(calibration.get("sites", {}))
    for name, site in config["sites"].items():
        if "map_from" in site and name not in sites:
            if site["map_from"] not in sites:
                raise SystemExit(f"site {name!r}: map_from {site['map_from']!r} has no map")
            sites[name] = sites[site["map_from"]]
    return {**calibration, "sites": sites}


def mark_to_arm(record: dict, config: dict, site: str, pixel, jaw_z: float):
    """The mark pixel (seen at the jaws' height) to the height the map was fitted at, then through the map."""
    fit_z = record.get("z_view", config["sites"][site]["z"])
    return cal.to_arm(record["homography"], cal.parallax(pixel, jaw_z, fit_z, config["cameras"]["top"]))


def mark_pixel(record: dict, config: dict, site: str, raw, jaw_z: float):
    """mark_to_arm backwards: where a raw map point at the jaws' height shows in the top view."""
    fit_z = record.get("z_view", config["sites"][site]["z"])
    return cal.parallax(cal.to_pixel(record["homography"], raw), fit_z, jaw_z, config["cameras"]["top"])


def pivot_z_view(config: dict, site: str) -> float:
    """The TCP height the jaws are marked at: the configured view height, but never closer to the site's surface than
    pivot.clear_above_m. The view height was one absolute number tuned on the floor (0.08); over the Pinky tray
    (surface 0.0467) the jaws swung 3 mm above a box's top and knocked it off the tray (2026-10-29)."""
    z_view = config.get("pivot", {}).get("z_view", config["coarse"]["z_view"])
    surface = config["sites"][site].get("surface_z")
    if surface is None:
        return z_view
    return round(max(z_view, surface + prm.get(config.get("params"), "pivot.clear_above_m")), 4)


def joints_tcp(state, tcp_x_m: float | None = None):
    """FK of the measured joints (planner units): x, y, z in metres and the FK yaw in degrees."""
    import grasp_planner as gp

    kin = gp.load_kinematics(None, tcp_x_m)[0]
    fk = kin.fk([gp.norm_to_rad(v) for v in state[:5]])
    return fk.x, fk.y, fk.z, math.degrees(fk.yaw)


def known_geometry_bias(marks, tcps, geometry: dict, site: str, record: dict, params=None) -> dict:
    """The bias from marks over a narrow yaw arc, with the jaw mark's radius and phase from a full circle measured on
    this arm. Where a stalling wrist leaves too few yaws for a circle (arm_b 2026-11-06), each mark still gives the
    circle's centre; they must agree, so one wrong blob is refused and never averaged in."""
    if len(marks) < 2:
        return {"result": f"jaws marked at {len(marks)} yaws, need 2 with a known geometry"}
    radius_m, phase = geometry["radius_mm"] / 1000, geometry["phase_deg"]
    centres = [(m[0] - radius_m * math.cos(math.radians(t[3] + phase)), m[1] - radius_m * math.sin(math.radians(t[3] + phase)))
               for m, t in zip(marks, tcps)]
    centre = [float(v) for v in np.mean(centres, axis=0)]  # plain floats: validate_bias takes nothing else
    spread = max(1000 * math.dist(c, centre) for c in centres)
    tx, ty = (float(np.mean([t[i] for t in tcps])) for i in (0, 1))
    bias = {"site": site, "point_m": [round(tx, 4), round(ty, 4)],
            "bias_mm": [round(1000 * (centre[0] - tx), 1), round(1000 * (centre[1] - ty), 1)],
            "radius_mm": geometry["radius_mm"], "phase_deg": phase, "rms_mm": round(spread, 1),
            "yaws_fk_deg": [round(t[3], 1) for t in tcps], "n": len(marks), "geometry_from": geometry.get("measured"),
            "map_sha": cell_attempts.digest(record), "measured": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if spread > prm.get(params, "pivot.max_rms_mm"):
        return {"result": f"marks disagree: {round(spread, 1)} mm from their centre", "bias": bias}
    if math.hypot(*bias["bias_mm"]) > prm.get(params, "pivot.max_bias_mm"):
        return {"result": f"bias refused: {bias['bias_mm']} mm is past pivot.max_bias_mm", "bias": bias}
    return {"result": "calibrated", "bias": bias}


def pivot_calibrate(cell, config: dict, point, yaws, calibration: dict, site: str, work: Path,
                    sleep=time.sleep, log=print) -> dict:
    """Hold the TCP at `point` (x, y metres) over a clear surface at each yaw, mark the jaws, fit the circle.
    Returns {"result": "calibrated", "bias": record} or {"result": "stopped"/..., ...}; the arm is parked."""
    import cell_pipeline as cp

    record = map_record(calibration, site)
    if record is None:
        return {"result": "no map for the site"}
    z_view = pivot_z_view(config, site)
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
            x, y, z, fk_yaw = joints_tcp(state, config.get("tcp_x_m"))
            marks.append(mark_to_arm(record, config, site, pixel, z))
            tcps.append((x, y, z, fk_yaw))
    finally:
        fold(cell, sleep)
    geometry = config.get("pivot", {}).get("geometry")
    if geometry is not None:
        return known_geometry_bias(marks, tcps, geometry, site, record, config.get("params"))
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
    # 2026-11-06: 29.6 mm passed the circle test, the target moved 3 cm over a packed ship and nothing questioned it
    try:
        validate_bias(bias, params)
    except ValueError as exc:
        return {"result": str(exc), "bias": bias}
    return {"result": "calibrated", "bias": bias}


def bias_path(calibration_path) -> Path:
    return Path(calibration_path).with_suffix(".bias.json")


def validate_bias(region: dict, params=None) -> None:
    for key in ("point_m", "bias_mm"):
        values = region.get(key)
        if (not isinstance(values, (list, tuple)) or len(values) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
            raise ValueError(f"bias refused: {key} must have two finite coordinates")
    limit = prm.get(params, "pivot.max_bias_mm")
    if type(limit) not in (int, float) or not math.isfinite(limit) or limit <= 0:
        raise ValueError("bias refused: pivot.max_bias_mm must be finite and positive")
    if math.hypot(*region["bias_mm"]) > limit:
        raise ValueError("bias refused: magnitude is past pivot.max_bias_mm")


def load_bias(path, params=None) -> dict:
    path = Path(path)
    data = json.loads(path.read_text()) if path.exists() else {"schema": SCHEMA, "regions": []}
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: not a {SCHEMA} file")
    for region in data["regions"]:
        validate_bias(region, params)
    return data


def save_bias(path, bias: dict, params=None) -> None:
    """Keep one region per site and place: a new one within 10 mm replaces the older."""
    validate_bias(bias, params)
    data = load_bias(path, params)
    data["regions"] = [r for r in data["regions"] if r["site"] != bias["site"]
                       or math.dist(r["point_m"], bias["point_m"]) > 0.010] + [bias]
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def bias_at(data: dict, site: str, point_m, reach_mm: float | None = None, params=None):
    """The nearest region's bias (dx, dy mm) within reach of the point, else None."""
    reach_mm = prm.get(params, "pivot.bias_reach_mm", BIAS_REACH_MM) if reach_mm is None else reach_mm
    for region in data["regions"]:
        validate_bias(region, params)
    near = [r for r in data["regions"] if r["site"] == site and 1000 * math.dist(r["point_m"], point_m) <= reach_mm]
    return min(near, key=lambda r: math.dist(r["point_m"], point_m), default=None)
