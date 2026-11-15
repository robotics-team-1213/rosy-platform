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
from cell_pivot_bias import (  # noqa: E402,F401  (re-exported)
    BIAS_REACH_MM,
    SCHEMA,
    bias_at,
    bias_path,
    load_bias,
    save_bias,
    validate_bias,
)

STILL_PX, DIFF_PX, MIN_BLOB, MAX_BLOB, FOLLOW_PX, AGREE_PX = (
    prm.default(f"pivot.{k}") for k in ("still_px", "diff_px", "min_blob", "max_blob", "follow_px", "agree_px"))
_KERNEL_3X3 = np.ones((3, 3), np.uint8)


def _changed_mask(a, b, threshold: int = DIFF_PX, colour: bool = False):  # the 3x3 opening is fixed: noise removal
    import cv2

    if colour and a.ndim == 3:  # 2026-11-15: black fingers over orange/pink can match in grey; the channel max keeps hue
        diff = cv2.absdiff(a, b).max(axis=2)  # only mark_jaws' fallback: settled_frame and jaw_axis keep the grey diff
    else:
        diff = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    return cv2.morphologyEx((diff > threshold).astype(np.uint8) * 255, cv2.MORPH_OPEN, _KERNEL_3X3)


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


def jaw_blobs(closed, opened, params=None, colour: bool = False) -> list:
    """(cx, cy, area) of the changed blobs of plausible size; [] when the frames barely differ."""
    import cv2

    diff_px, max_blob = prm.get(params, "pivot.diff_px", DIFF_PX), prm.get(params, "pivot.max_blob", MAX_BLOB)
    mask = _changed_mask(closed, opened, diff_px, colour)
    if int(np.count_nonzero(mask)) <= diff_px:
        return []
    # pieces this close are one mark: over a box top the gripper body hid the fingers and the open-closed change came
    # in 2-3 pieces of 72-260 px, none reaching min_blob (2026-11-02); the merge only groups, the area is the changed px
    merge = int(prm.get(params, "pivot.merge_px"))
    grouped = cv2.dilate(mask, np.ones((2 * merge + 1, 2 * merge + 1), np.uint8)) if merge else mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(grouped)
    min_blob = prm.get(params, "pivot.min_blob", MIN_BLOB)
    blobs = []
    for i in range(1, n):
        if int(stats[i, cv2.CC_STAT_AREA]) < min_blob:  # the grouped blob's area bounds its own mask px: skip early
            continue
        x0, y0, bw, bh = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
        ys, xs = np.nonzero((labels[y0:y0 + bh, x0:x0 + bw] == i) & (mask[y0:y0 + bh, x0:x0 + bw] > 0))
        if len(xs) >= min_blob and np.ptp(xs) < max_blob and np.ptp(ys) < max_blob:
            blobs.append((float(xs.mean()) + x0, float(ys.mean()) + y0, int(len(xs))))
    return blobs


def _jaw_pairs(closed, opened, params=None, colour: bool = False) -> list:
    """Pairs of changed-finger blobs matching the gap window; retries unmerged when dilation fuses narrow jaws."""
    import cv2

    mask = _changed_mask(closed, opened, prm.get(params, "pivot.diff_px", DIFF_PX), colour)
    min_side = prm.get(params, "jaw_centre.min_side_px")
    gap_lo, gap_hi = prm.get(params, "jaw_centre.gap_lo_px"), prm.get(params, "jaw_centre.gap_hi_px")
    cfg_merge = int(prm.get(params, "jaw_centre.merge_px"))
    for merge in ((cfg_merge, 0) if cfg_merge > 0 else (0,)):
        dilated = cv2.dilate(mask, np.ones((2 * merge + 1, 2 * merge + 1), np.uint8)) if merge else mask
        n, labels, stats, _ = cv2.connectedComponentsWithStats(dilated)
        sides = []
        for i in range(1, n):
            if int(stats[i, cv2.CC_STAT_AREA]) < min_side:  # the grouped blob's area bounds its own mask px: skip early
                continue
            x0, y0, bw, bh = (int(stats[i, k]) for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
            ys, xs = np.nonzero((labels[y0:y0 + bh, x0:x0 + bw] == i) & (mask[y0:y0 + bh, x0:x0 + bw] > 0))
            if len(xs) >= min_side:
                sides.append((float(xs.mean()) + x0, float(ys.mean()) + y0, len(xs)))
        pairs = [(a, b) for k, a in enumerate(sides) for b in sides[k + 1:]
                 if gap_lo <= math.dist(a[:2], b[:2]) <= gap_hi]
        if pairs:
            return pairs
    return []


def jaw_centres(closed, opened, params=None, colour: bool = False) -> list:
    """[(cx, cy, area), ...] of every valid two-side midpoint so `near` can pick the finger pair over reflections."""
    return [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2] + b[2])
            for a, b in _jaw_pairs(closed, opened, params, colour)]


def jaw_centre(closed, opened, params=None, colour: bool = False) -> list:
    """[(cx, cy, area)] of the midpoint of the jaws' largest-area two sides in the open-closed difference, or [] when both do not show.
    Either side alone is about 30 mm from the TCP, and which one is largest flips: a map on one side and a pivot on the
    other read 54 mm apart (arm_b 2026-11-06, free air: sides 75-80 px apart at z 0.14, one hidden over a dark box)."""
    centres = jaw_centres(closed, opened, params, colour)
    return [max(centres, key=lambda c: c[2])] if centres else []


def mark_open(config: dict) -> float:
    """The value the jaw mark opens the jaws to: the mark's own, never the pick's (a pick's 53.84 left no blob)."""
    return config.get("jaw_mark", {}).get("open", prm.get(config.get("params"), "pivot.grip_open", config.get("plan", {}).get("grip_open")))


def _save_mark_try(keep_dir: Path, idx: int, closed, now, mask, all_blobs: list, pick, rejected: str | None) -> None:
    import cv2

    keep_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(keep_dir / f"try-{idx:02d}-closed.jpg"), closed)
    cv2.imwrite(str(keep_dir / f"try-{idx:02d}-open.jpg"), now)
    cv2.imwrite(str(keep_dir / f"try-{idx:02d}-mask.png"), mask)
    info = {
        "try": idx,
        "blobs": [{"cx": round(float(b[0]), 2), "cy": round(float(b[1]), 2), "area": int(b[2])} for b in all_blobs],
        "picked": [round(float(pick[0]), 2), round(float(pick[1]), 2), int(pick[2])] if pick else None,
        "rejected": rejected,
    }
    (keep_dir / f"try-{idx:02d}.json").write_text(json.dumps(info))


def mark_jaws(cell, config: dict, sleep=time.sleep, clock=time.monotonic, max_marks: int = 6, near=None,
              keep=None, report: dict | None = None):
    """The jaw mark in the top view as (cx, cy), or None when no two marks agree. `near` = ([pixel, ...], radius_px):
    only blobs that close to one of the places the jaws should show count, nearest first - with the arm stretched out,
    opening the jaws shook the whole link and the largest changed blob was not the jaws (2026-10-29, a look 30 mm off).
    Several places: either finger can be the one the camera sees (cell_look)."""
    import cell_pipeline as cp

    mark_cfg, p = config.get("jaw_mark", {}), config.get("params")
    closed_to, marks = mark_cfg.get("closed", prm.get(p, "pivot.grip_closed")), []
    follow, agree = prm.get(p, "pivot.follow_px", FOLLOW_PX), prm.get(p, "pivot.agree_px", AGREE_PX)
    keep_dir, saw_blobs = (Path(keep) if keep is not None else None), False

    def fail(reason: str):
        if report is not None:
            report["reason"] = reason
        return None

    for idx in range(max_marks):
        if not cp.grip_to(cell, closed_to):
            return fail("grip_to failed")
        closed = settled_frame(cell, sleep, clock, params=p)
        # the mark's own opening, not the pick's: a pick opened only to its box width (53.84 against 50.5 closed)
        # moved the jaws too little to leave a blob, and every look at the hover saw nothing (2026-10-29)
        if not cp.grip_to(cell, mark_open(config)):
            return fail("grip_to failed")
        now = settled_frame(cell, sleep, clock, params=p)
        explicit_colour = mark_cfg.get("colour")
        detect = jaw_centres if mark_cfg.get("centre") else jaw_blobs
        if explicit_colour is not None:
            used_colour = bool(explicit_colour)
            all_blobs = detect(closed, now, p, colour=used_colour)
        else:
            all_blobs = detect(closed, now, p, colour=False)
            used_colour = False
            if not all_blobs:
                all_blobs = detect(closed, now, p, colour=True)
                used_colour = True
        saw_blobs |= bool(all_blobs)
        if not all_blobs:
            pick, rejected = None, "no changed blob"
        elif marks:
            blobs = [b for b in all_blobs if math.dist(b[:2], marks[-1]) <= follow]
            pick = min(blobs, key=lambda b: math.dist(b[:2], marks[-1]), default=None)
            rejected = None if pick else "blobs outside follow"
        elif near is not None:
            def gap(b):
                return min(math.dist(b[:2], q) for q in near[0])
            blobs = [b for b in all_blobs if gap(b) <= near[1]]
            pick = min(blobs, key=gap, default=None)
            rejected = None if pick else "blobs outside near"
        else:
            pick, rejected = max(all_blobs, key=lambda b: b[2], default=None), None
        agreed = pick is not None and any(math.dist(pick[:2], m) <= agree for m in marks)
        if pick is not None and not agreed:
            rejected = "awaiting agreement"
        if keep_dir is not None:
            mask = _changed_mask(closed, now, prm.get(p, "pivot.diff_px", DIFF_PX), used_colour)
            _save_mark_try(keep_dir, idx, closed, now, mask, all_blobs, pick, rejected)
        if agreed:
            if report is not None:
                report["reason"] = None
            return pick[0], pick[1]
        if pick is not None:
            marks.append(pick[:2])
    if marks:
        return fail("tries disagree")
    return fail("blobs outside near" if saw_blobs else "no changed blob")


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


MIN_YAW_ARC_DEG = 120.0


def _yaw_arc_deg(yaws_deg) -> float:
    """Span of achieved FK yaws around the circle (360 minus the largest empty gap)."""
    angles = sorted(y % 360.0 for y in yaws_deg)
    if len(angles) < 2:
        return 0.0
    gaps = [b - a for a, b in zip(angles, angles[1:])] + [360.0 - angles[-1] + angles[0]]
    return 360.0 - max(gaps)


def pivot_calibrate(cell, config: dict, point, yaws, calibration: dict, site: str, work: Path,
                    sleep=time.sleep, log=print) -> dict:
    """Hold the TCP at `point` (x, y metres) over a clear surface at each yaw, mark the jaws, fit the circle.
    Returns {"result": "calibrated", "bias": record} or {"result": "stopped"/..., ...}; the arm is parked."""
    import cell_pipeline as cp

    record = map_record(calibration, site)
    if record is None:
        return {"result": "no map for the site"}
    params = config.get("params")
    tcp_x_m = config["tcp_x_m"] if config.get("tcp_x_m") is not None else (config.get("plan") or {}).get("tcp_x_m")
    z_view = pivot_z_view(config, site)
    expected_near = None
    H = record.get("homography")
    if isinstance(H, list) and len(H) == 3 and "top" in (config.get("cameras") or {}):
        try:
            expected_near = ([mark_pixel(record, config, site, point, z_view)], prm.get(params, "pivot.follow_px", FOLLOW_PX) + 40)
        except (np.linalg.LinAlgError, KeyError, TypeError, ValueError, ZeroDivisionError):
            expected_near = None
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
            import joint_jitter

            state = (joint_jitter.settled_state(cell, params) or {}).get("state")
            pixel = mark_jaws(cell, config, sleep, near=expected_near)
            log({"pivot": yaw, "mark_px": pixel})
            if state is None or pixel is None:
                continue
            x, y, z, fk_yaw = joints_tcp(state, **({"tcp_x_m": tcp_x_m} if tcp_x_m is not None else {}))
            marks.append(mark_to_arm(record, config, site, pixel, z))
            tcps.append((x, y, z, fk_yaw))
    finally:
        fold(cell, sleep)
    geometry = config.get("pivot", {}).get("geometry")
    if geometry is not None:
        return known_geometry_bias(marks, tcps, geometry, site, record, params)
    if len(marks) < 4:
        return {"result": f"jaws marked at {len(marks)} yaws, need 4"}
    arc_deg = _yaw_arc_deg([t[3] for t in tcps])
    if arc_deg < MIN_YAW_ARC_DEG:
        return {"result": f"circle refused: yaw arc {round(arc_deg, 1)} deg < {int(MIN_YAW_ARC_DEG)} deg",
                "yaws_fk_deg": [round(t[3], 1) for t in tcps]}
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
    if rms * 1000 > prm.get(params, "pivot.max_rms_mm") or not (
            prm.get(params, "pivot.radius_lo_mm") <= radius * 1000 <= prm.get(params, "pivot.radius_hi_mm")):
        return {"result": f"circle refused: radius {bias['radius_mm']} mm, rms {bias['rms_mm']} mm", "bias": bias}
    # 2026-11-06: 29.6 mm passed the circle test, the target moved 3 cm over a packed ship and nothing questioned it
    try:
        validate_bias(bias, params)
    except ValueError as exc:
        return {"result": str(exc), "bias": bias}
    return {"result": "calibrated", "bias": bias}
