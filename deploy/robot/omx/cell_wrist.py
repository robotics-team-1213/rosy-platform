#!/usr/bin/env python3
"""Final alignment with an arm's wrist camera at the hover pose, before the descent.

The top-camera map was about 2 cm off far from its calibration points (2026-10-28): open jaws and pushes came down
on a container's top edge. At the hover pose the wrist camera sees the container; its centre's shift from a
reference pixel, times a per-arm 2x2 J (fitted from arm-only offset hovers over a container the pipeline placed),
gives the arm-frame correction. The camera looks obliquely forward (facts 16), so only shifts from the reference are
used, never an absolute centring. Plan: Rosy/docs/superpowers/plans/2026-10-28-arm-s-wrist-final-alignment.md.

Everything is keyed by arm id (two arms will share a cell): calibration file {"schema", "arms": {arm_id: {"camera",
"bands": [{"yaw_lo", "yaw_hi", "J", "ref": {"u", "v", "area", "axis_deg"}, "rms_px", "measured"}]}}}.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

import cell_params as prm

SCHEMA = "rosy.omx-wrist-cal.v1"


def observe(img, hsv_min, hsv_max, params=None, near=None) -> dict:
    """The container in one wrist frame: centre, area, axis, fill, cut by the frame edge. With `near` (the reference
    pixel) the blob closest to it is the target, else the largest; `blobs` counts it plus the sizeable blobs right
    beside it (a neighbour farther off in the frame is not in the way: 2026-10-28 tray view had one)."""
    import cv2

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.morphologyEx(cv2.inRange(hsv, np.array(hsv_min), np.array(hsv_max)), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return {"found": False}
    areas = stats[1:, cv2.CC_STAT_AREA]
    sizeable = [i + 1 for i, a in enumerate(areas) if a >= 0.2 * areas.max()]
    centroids = {i: np.array(np.nonzero(labels == i)[::-1]).mean(axis=1) for i in sizeable}
    big = (min(sizeable, key=lambda i: np.hypot(*(centroids[i] - near))) if near is not None
           else int(np.argmax(areas)) + 1)
    if big not in centroids:
        centroids[big] = np.array(np.nonzero(labels == big)[::-1]).mean(axis=1)
    pts = np.column_stack(np.nonzero(labels == big))[:, ::-1].astype(np.float32)
    (_, _), (w, h), _ = cv2.minAreaRect(pts)
    vals, vecs = np.linalg.eigh(np.cov((pts - pts.mean(axis=0)).T))  # long axis: the principal direction
    long_axis = vecs[:, int(np.argmax(vals))]
    x, y, bw, bh = (int(v) for v in stats[big, :4])
    edge = prm.get(params, "wrist.edge_margin_px")
    height, width = mask.shape
    return {"found": True, "cx": float(pts[:, 0].mean()), "cy": float(pts[:, 1].mean()), "area": int(areas[big - 1]),
            "axis_deg": float(np.degrees(np.arctan2(long_axis[1], long_axis[0])) % 180),
            "fill": float(areas[big - 1] / max(w * h, 1.0)),
            "blobs": 1 + sum(1 for i in sizeable if i != big and np.hypot(*(centroids[i] - centroids[big])) <= 1.2 * max(bw, bh)),
            "cut": x <= edge or y <= edge or x + bw >= width - edge or y + bh >= height - edge}


def fit(xy_mm, uv_px, params=None) -> dict:
    """Least squares [u, v] = A [x, y] + b over the offset hovers; J = A^-1 maps a pixel shift to arm mm.
    A poor fit or a near-singular A is refused (nothing is saved from it)."""
    xy, uv = np.asarray(xy_mm, float), np.asarray(uv_px, float)
    X = np.column_stack([xy, np.ones(len(xy))])
    coef, *_ = np.linalg.lstsq(X, uv, rcond=None)
    A, b = coef[:2].T, coef[2]
    rms = float(np.sqrt(np.mean(np.sum((X @ coef - uv) ** 2, axis=1))))
    cond = float(np.linalg.cond(A))
    if rms > prm.get(params, "wrist.fit_rms_max_px") or not math.isfinite(cond) or cond > 20:
        raise ValueError(f"wrist fit refused: rms {rms:.1f} px, cond {cond:.1f}")
    return {"A": A.tolist(), "b": b.tolist(), "J": np.linalg.inv(A).tolist(), "rms_px": round(rms, 2), "cond": round(cond, 2)}


def band_for(cal: dict, arm: str, yaw_deg: float):
    for band in (cal.get("arms", {}).get(arm, {}).get("bands") or []):
        if band["yaw_lo"] <= yaw_deg < band["yaw_hi"]:
            return band
    return None


def judge(obs: dict, band: dict, params=None, total_mm: float = 0.0) -> dict:
    """pass (within tolerance), correct (dx, dy mm to add to the pick), or refuse (with why)."""
    g = lambda name: prm.get(params, f"wrist.{name}")  # noqa: E731
    ref = band["ref"]
    why = None
    if not obs.get("found"):
        why = "container not seen"
    elif obs["cut"]:
        why = "cut by the frame edge"
    elif obs["blobs"] > 1:
        why = f"{obs['blobs']} blobs: another object or a split view"
    elif not g("area_lo") <= obs["area"] / ref["area"] <= g("area_hi"):
        why = f"area {obs['area'] / ref['area']:.2f} of the reference"
    elif obs["fill"] < g("fill_min"):
        why = f"fill {obs['fill']:.2f}: partly hidden"
    elif min(abs(obs["axis_deg"] - ref["axis_deg"]) % 180, 180 - abs(obs["axis_deg"] - ref["axis_deg"]) % 180) > g("axis_tol_deg"):
        why = f"axis {obs['axis_deg']:.0f} vs {ref['axis_deg']:.0f} deg"
    if why:
        return {"verdict": "refuse", "why": why}
    d = np.asarray(band["J"]) @ np.array([obs["cx"] - ref["u"], obs["cy"] - ref["v"]])
    step = float(np.hypot(*d))
    out = {"dx_mm": round(float(d[0]), 1), "dy_mm": round(float(d[1]), 1), "step_mm": round(step, 1)}
    if step <= g("tol_mm"):
        return {"verdict": "pass", **out}
    if step > g("max_step_mm"):
        return {"verdict": "refuse", "why": f"step {step:.1f} mm over {g('max_step_mm')}", **out}
    if total_mm + step > min(g("max_total_mm"), g("topmap_disagree_mm")):
        return {"verdict": "refuse", "why": f"total {total_mm + step:.1f} mm: the top map and the wrist disagree", **out}
    return {"verdict": "correct", **out}


def median_view(cell, camera: str, hsv, params, frames: int = 3, near=None) -> dict:
    """Three frames; any frame without the container makes the view not found (a hand or a shadow passing)."""
    seen = [observe(cell.frame(camera), hsv[0], hsv[1], params, near) for _ in range(frames)]
    if not all(s.get("found") for s in seen):
        return {"found": False}
    med = {k: float(np.median([s[k] for s in seen])) for k in ("cx", "cy", "area", "axis_deg", "fill")}
    return {"found": True, **med, "blobs": max(s["blobs"] for s in seen), "cut": any(s["cut"] for s in seen)}


def align(cell, camera: str, band: dict, hsv, replan, params=None, emit=None) -> dict:
    """Up to wrist.max_iter corrections at the hover; each re-plans the pick from the corrected xy, loads it and goes
    above it again. Returns {verdict, total_mm, dx_mm, dy_mm, iterations}; refuse means do not descend."""
    total, dx, dy, rows = 0.0, 0.0, 0.0, []
    for i in range(int(prm.get(params, "wrist.max_iter")) + 1):
        obs = median_view(cell, camera, hsv, params, near=np.array([band["ref"]["u"], band["ref"]["v"]]))
        verdict = judge(obs, band, params, total)
        rows.append({"iteration": i, "view": obs, **verdict})
        if emit:
            emit("wrist_align", {"iteration": i, "view": obs, "correction_so_far_mm": [round(dx, 1), round(dy, 1)]},
                 ["pass", "correct", "refuse"], verdict["verdict"], "measurement", verdict.get("why") or f"step {verdict.get('step_mm')} mm")
        if verdict["verdict"] != "correct":
            break
        if i == int(prm.get(params, "wrist.max_iter")):
            rows[-1].update(verdict="refuse", why="not within tolerance after the last correction")
            break
        dx, dy, total = dx + verdict["dx_mm"], dy + verdict["dy_mm"], total + verdict["step_mm"]
        for command in (f"load {replan(dx, dy)}", "goto above_pick"):
            status = cell.act(command)
            if not status.get("ok"):
                rows[-1].update(verdict="refuse", why=f"{command.split()[0]}: {status.get('error')}")
                return {"verdict": "refuse", "total_mm": round(total, 1), "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "iterations": rows}
    return {"verdict": rows[-1]["verdict"], "total_mm": round(total, 1), "dx_mm": round(dx, 1), "dy_mm": round(dy, 1),
            "iterations": rows}


def hook(config: dict, cell, target: dict, write_library, emit=None):
    """The callable transfer_folded runs after `goto above_pick`, or None (disabled, or this arm/yaw is uncalibrated:
    the pick runs as before and the attempt row says why)."""
    params, spec = config.get("params"), config.get("wrist") or {}
    if not prm.get(params, "wrist.enabled") or not spec.get("cal_path"):
        return None
    path = Path(spec["cal_path"]).expanduser()
    cal = json.loads(path.read_text()) if path.exists() else {}
    if cal and cal.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: not a {SCHEMA} file")
    band = band_for(cal, config.get("arm_id", "arm_s"), target["pick"]["yaw_deg"])
    if band is None:
        return None
    work = Path(config["work_dir"]).expanduser()

    def replan(dx_mm, dy_mm):
        pick = dict(target["pick"], x=round(target["pick"]["x"] + dx_mm / 1000, 4), y=round(target["pick"]["y"] + dy_mm / 1000, 4))
        return write_library(config, pick, target["place"], work / "wrist-replan.json")

    camera = (config.get("arms", {}).get(config.get("arm_id", "arm_s"), {}) or {}).get("wrist_camera", spec.get("camera", "wrist"))
    return lambda: align(cell, camera, band, (spec["hsv_min"], spec["hsv_max"]), replan, params, emit)


# --- finger-referenced alignment: no calibration file; the open fingers are the ruler (2026-10-29) ---------------
# At the hover the wrist camera sees both open finger pads at the bottom of the frame and the container. The pads'
# pixel distance is the known jaw gap (gripper.gap_mm_per_unit, measured from this same view), their axis is the
# closing direction, and the container's offset from the pads' midpoint is the correction. The sign across the
# closing axis is not known from one view, so it is learned: a correction that makes the offset grow is reversed.

def finger_pads(img, dark: int = 60):
    """(left_centre, right_centre, gap_px) of the two dark finger pads in the bottom third, or None."""
    import cv2

    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h = g.shape[0]
    band = (g[2 * h // 3:] < dark).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(band)
    blobs = sorted((i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 800), key=lambda i: -stats[i, cv2.CC_STAT_AREA])[:2]
    if len(blobs) < 2:
        return None
    a, b = sorted((cents[i] + (0, 2 * h // 3) for i in blobs), key=lambda c: c[0])
    left, right = sorted(blobs, key=lambda i: cents[i][0])
    gap = stats[right, 0] - (stats[left, 0] + stats[left, 2])
    return a, b, float(max(gap, 1))


def on_surface_blob(img, hsv, params=None):
    """The container standing on a neutral surface (floor, tray, belt: grey/white/black), not one on a coloured
    neighbour surface (the orange board): the ring just outside each green blob decides. On 13 recorded hover frames
    (2026-10-29) the target's ring chroma was 6-20 and the board's containers 21-53; the nearest blob to the pads was
    a board container. Returns (cx, cy, area) of the largest qualifying blob, or None."""
    import cv2

    hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(int)
    mask = cv2.morphologyEx(cv2.inRange(hsv_img, np.array(hsv[0]), np.array(hsv[1])), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < prm.get(params, "wrist.min_blob_px"):
            continue
        blob = (labels == i).astype(np.uint8)
        ring = (cv2.dilate(blob, np.ones((25, 25), np.uint8)) - blob) & (mask == 0)
        if ring.sum() < 200:
            continue
        chroma = float(np.hypot(lab[..., 1][ring > 0] - 128, lab[..., 2][ring > 0] - 128).mean())
        if chroma <= prm.get(params, "wrist.neutral_ring_chroma") and (best is None or stats[i, cv2.CC_STAT_AREA] > best[2]):
            best = (float(cents[i][0]), float(cents[i][1]), int(stats[i, cv2.CC_STAT_AREA]))
    return best


def finger_offset_mm(img, hsv, gap_mm: float, params=None) -> dict:
    """The container's offset from the pads' midpoint in mm: along (the closing axis, left->right) and across."""
    pads = finger_pads(img)
    if pads is None:
        return {"found": False, "why": "finger pads not seen"}
    a, b, gap_px = pads
    target = on_surface_blob(img, hsv, params)
    if target is None:
        return {"found": False, "why": "no container on a neutral surface in view"}
    seen = {"cx": target[0], "cy": target[1]}
    axis = (b - a) / np.linalg.norm(b - a)
    across_dir = np.array([-axis[1], axis[0]])
    d = np.array([seen["cx"], seen["cy"]]) - (a + b) / 2
    s = gap_mm / gap_px
    return {"found": True, "along_mm": round(float(d @ axis) * s, 1), "across_mm": round(float(d @ across_dir) * s, 1),
            "gap_px": round(gap_px, 1), "mm_per_px": round(s, 3)}


def finger_servo(cell, camera: str, hsv, closing_deg: float, gap_mm: float, replan, params=None, sign=None) -> dict:
    """Up to wrist.max_iter corrections from the finger-referenced offset; the across sign is learned."""
    import math

    sign = sign or {"along": 1.0, "across": 1.0}
    moved_axis = None
    total, dx, dy, rows, last = 0.0, 0.0, 0.0, [], None
    c = math.radians(closing_deg)
    along_arm, across_arm = np.array([math.cos(c), math.sin(c)]), np.array([-math.sin(c), math.cos(c)])
    for i in range(int(prm.get(params, "wrist.servo_iter")) + 1):
        seen = finger_offset_mm(cell.frame(camera), hsv, gap_mm, params)
        rows.append({"iteration": i, **seen})
        if not seen["found"]:
            return {"verdict": "refuse", "why": seen["why"], "dx_mm": dx, "dy_mm": dy, "total_mm": total, "iterations": rows}
        # only the closing axis has an exact reference (the pads lie on it); across, "centred" is not the pads' row in
        # the oblique view and needs a calibrated reference first (wrist.servo_across)
        across = seen["across_mm"] if prm.get(params, "wrist.servo_across") else 0.0
        offset = math.hypot(seen["along_mm"], across)
        if offset <= prm.get(params, "wrist.tol_mm"):
            return {"verdict": "pass", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "total_mm": round(total, 1), "iterations": rows}
        if last is not None and offset > last + 1.0 and moved_axis:
            # the last step made it worse: the image->arm direction of the axis it moved along is reversed (the wrist
            # camera's mounting decides it; 2026-10-29 the first real step along the closing axis grew 38 -> 40 mm)
            sign[moved_axis] = -sign[moved_axis]
        # move part of the way and look again: the pads' scale overstates distances ahead of them (oblique view; the
        # recorded frames read 35/-46 mm for a box ~2-3 cm off), so a gain and a step cap let close range converge
        step = prm.get(params, "wrist.servo_gain") * (sign["along"] * seen["along_mm"] * along_arm + sign["across"] * across * across_arm)
        moved_axis = "along" if abs(seen["along_mm"]) >= abs(across) else "across"
        if np.hypot(*step) > prm.get(params, "wrist.max_step_mm"):
            step = step / np.hypot(*step) * prm.get(params, "wrist.max_step_mm")
        size = float(np.hypot(*step))
        if i == int(prm.get(params, "wrist.servo_iter")) or total + size > prm.get(params, "wrist.servo_total_mm"):
            break
        dx, dy, total, last = dx + step[0], dy + step[1], total + size, offset
        for command in (f"load {replan(dx, dy)}", "goto above_pick"):
            if not cell.act(command).get("ok"):
                return {"verdict": "refuse", "why": f"{command.split()[0]} refused", "dx_mm": dx, "dy_mm": dy, "total_mm": total, "iterations": rows}
    return {"verdict": "refuse", "why": "not within tolerance", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "total_mm": round(total, 1), "iterations": rows}


def finger_hook(config: dict, cell, target: dict, write_library, gap_mm: float):
    """The finger-referenced alignment as a hover hook (wrist.finger_servo), or None."""
    params, spec = config.get("params"), config.get("wrist") or {}
    if not prm.get(params, "wrist.finger_servo") or not spec.get("hsv_min"):
        return None
    work = Path(config["work_dir"]).expanduser()

    def replan(dx_mm, dy_mm):
        pick = dict(target["pick"], x=round(target["pick"]["x"] + dx_mm / 1000, 4), y=round(target["pick"]["y"] + dy_mm / 1000, 4))
        return write_library(config, pick, target["place"], work / "finger-replan.json")

    camera = spec.get("camera", "wrist")
    closing = target["pick"]["yaw_deg"] + prm.get(params, "auto.closing_theory_deg")
    signs_path = work / f"wrist-signs-{config.get('arm_id', 'arm_s')}.json"  # the camera mounting stays: keep what was learned

    def run():
        signs = json.loads(signs_path.read_text()) if signs_path.exists() else {"along": 1.0, "across": 1.0}
        out = finger_servo(cell, camera, (spec["hsv_min"], spec["hsv_max"]), closing, gap_mm, replan, params, signs)
        if out["verdict"] == "pass":  # only a sign that led to a pass is kept for the next run
            signs_path.write_text(json.dumps(signs))
        return out
    return run


# --- reference-pixel servo with a learned image Jacobian (2026-10-29) ---------------------------------------------
# The oblique wrist view has no fixed relation between the pads' line and the closing axis on the floor (a 19 mm
# move along the closing axis showed up "across"). So: the reference is where a container appears when it is truly
# between the jaws - recorded by the arm itself right after a confirmed place, from the same hover pose - and the
# image Jacobian J (px per arm mm) is measured with two small probe moves, then refined by Broyden after each step.

def ref_path(work: Path, arm: str, site: str = "any") -> Path:
    """One reference per arm: the hover is always the same height above the container's grasp point, so the
    container sits at the same wrist pixel on every site (the site name is kept for older callers)."""
    return Path(work) / f"wrist-ref-{arm}.json"


def broyden(J, d_arm, d_px):
    """Broyden's rank-one update of the 2x2 image Jacobian from one step (d_arm mm -> d_px px)."""
    J, d_arm, d_px = np.asarray(J, float), np.asarray(d_arm, float), np.asarray(d_px, float)
    denom = float(d_arm @ d_arm)
    return J if denom < 1e-9 else J + np.outer(d_px - J @ d_arm, d_arm) / denom


def ref_servo(cell, camera: str, hsv, ref: dict, replan, params=None, J=None) -> dict:
    """Move the hover until the container sits at the reference pixel. Returns verdict, offset dx/dy (mm), J."""
    def seen():
        b = on_surface_blob(cell.frame(camera), hsv, params)
        return None if b is None else np.array(b[:2])

    def hover(dx, dy):
        for command in (f"load {replan(dx, dy)}", "goto above_pick"):
            if not cell.act(command).get("ok"):
                return False
        return True

    target, rows = np.array([ref["u"], ref["v"]]), []
    pos, now = np.zeros(2), seen()
    if now is None:
        return {"verdict": "refuse", "why": "container not seen", "dx_mm": 0.0, "dy_mm": 0.0, "J": None, "iterations": rows}
    probe = prm.get(params, "wrist.probe_mm")
    if J is None:  # two small probe moves measure J's columns (px per mm along arm x and y)
        cols = []
        for step in (np.array([probe, 0.0]), np.array([0.0, probe])):
            if not hover(*(pos + step)):
                return {"verdict": "refuse", "why": "probe move refused", "dx_mm": 0.0, "dy_mm": 0.0, "J": None, "iterations": rows}
            after = seen()
            if after is None:
                return {"verdict": "refuse", "why": "container lost while probing", "dx_mm": 0.0, "dy_mm": 0.0, "J": None, "iterations": rows}
            cols.append((after - now) / probe)
            pos, now = pos + step, after
        J = np.column_stack(cols)
    J = np.asarray(J, float)
    for i in range(int(prm.get(params, "wrist.servo_iter")) + 1):
        err = target - now
        rows.append({"iteration": i, "error_px": [round(float(v), 1) for v in err], "pos_mm": [round(float(v), 1) for v in pos]})
        if np.hypot(*err) <= prm.get(params, "wrist.ref_tol_px"):
            return {"verdict": "pass", "dx_mm": round(float(pos[0]), 1), "dy_mm": round(float(pos[1]), 1), "J": J.tolist(), "iterations": rows}
        if abs(np.linalg.det(J)) < 1e-3 or i == int(prm.get(params, "wrist.servo_iter")):
            break
        step = prm.get(params, "wrist.servo_gain") * np.linalg.solve(J, err)
        if np.hypot(*step) > prm.get(params, "wrist.max_step_mm"):
            step = step / np.hypot(*step) * prm.get(params, "wrist.max_step_mm")
        if np.hypot(*(pos + step)) > prm.get(params, "wrist.servo_total_mm"):
            break
        if not hover(*(pos + step)):
            break
        after = seen()
        if after is None:
            break
        J = broyden(J, step, after - now)
        pos, now = pos + step, after
    return {"verdict": "refuse", "why": "not at the reference pixel", "dx_mm": round(float(pos[0]), 1), "dy_mm": round(float(pos[1]), 1),
            "J": J.tolist(), "iterations": rows}


def ref_hook(config: dict, cell, target: dict, write_library, site: str):
    """The reference-pixel servo as a hover hook when this arm has a reference for the site; J is reused."""
    params, spec = config.get("params"), config.get("wrist") or {}
    work = Path(config["work_dir"]).expanduser()
    arm = config.get("arm_id", "arm_s")
    path = ref_path(work, arm, site)
    estimate = prm.get(params, "wrist.ref_estimate")
    if not prm.get(params, "wrist.ref_servo") or not spec.get("hsv_min") or not (path.exists() or estimate):
        return None
    hsv = (spec["hsv_min"], spec["hsv_max"])

    def replan(dx_mm, dy_mm, dz_mm=0.0):
        pick = dict(target["pick"], x=round(target["pick"]["x"] + dx_mm / 1000, 4), y=round(target["pick"]["y"] + dy_mm / 1000, 4),
                    z=round(target["pick"]["z"] + dz_mm / 1000, 4))
        return write_library(config, pick, target["place"], work / "ref-replan.json")

    def hover_up(mm):
        return all(cell.act(c).get("ok") for c in (f"load {replan(0.0, 0.0, mm)}", "goto above_pick"))

    def run():
        ref = json.loads(path.read_text()) if path.exists() else estimate_reference(cell, spec.get("camera", "wrist"), hsv, hover_up, params)
        if ref is None:
            return {"verdict": "refuse", "why": "no wrist reference (estimate failed)", "dx_mm": 0.0, "dy_mm": 0.0, "total_mm": 0.0}
        out = ref_servo(cell, spec.get("camera", "wrist"), hsv, ref, replan, params, ref.get("J"))
        out["reference"] = ref.get("source", "confirmed place")
        if out["verdict"] == "pass" and out.get("J") and path.exists():
            path.write_text(json.dumps(dict(ref, J=out["J"])))  # a J that led to a pass is kept for the next pick
        return {**out, "total_mm": round(float(np.hypot(out["dx_mm"], out["dy_mm"])), 1)}
    return run


def capture_reference(cell, camera: str, hsv, work: Path, arm: str, site: str, params=None) -> dict | None:
    """Right after the arm itself placed a container and hovers above it again: where it appears = 'centred'."""
    b = on_surface_blob(cell.frame(camera), hsv, params)
    if b is None:
        return None
    ref = {"u": round(b[0], 1), "v": round(b[1], 1), "area": b[2], "measured": time.strftime("%Y-%m-%dT%H:%M:%S")}
    old = ref_path(work, arm, site)
    if old.exists():
        ref["J"] = json.loads(old.read_text()).get("J")
    pending = old.with_suffix(".pending.json")
    pending.write_text(json.dumps(ref))
    return ref


def fingertip_point(img):
    """Where the open fingertips' centreline meets their top in the wrist view: (mid of the pads' inner edges, top
    row of the pads), or None."""
    import cv2

    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h = g.shape[0]
    band = (g[2 * h // 3:] < 60).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(band)
    blobs = sorted((i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 800), key=lambda i: -stats[i, cv2.CC_STAT_AREA])[:2]
    if len(blobs) < 2:
        return None
    left, right = sorted(blobs, key=lambda i: stats[i, 0])
    mid = (stats[left, 0] + stats[left, 2] + stats[right, 0]) / 2
    top = min(stats[left, 1], stats[right, 1]) + 2 * h // 3
    return np.array([float(mid), float(top)])


def estimate_reference(cell, camera: str, hsv, hover_up, params=None) -> dict | None:
    """No confirmed place yet: reference ~ the fingertip point + the box's image shift per mm of height x the height
    from the fingertips down to the container top at the hover (wrist.tip_to_top_mm). The shift per mm comes from
    one probe: hover_up(mm) raises the hover, the container's pixel moves. Never saved: a confirmed place replaces it."""
    first = cell.frame(camera)
    tip, box0 = fingertip_point(first), on_surface_blob(first, hsv, params)
    if tip is None or box0 is None:
        return None
    up = prm.get(params, "wrist.z_probe_mm")
    if not hover_up(up):
        return None
    box1 = on_surface_blob(cell.frame(camera), hsv, params)
    if not hover_up(0.0) or box1 is None:
        return None
    per_mm = (np.array(box1[:2]) - np.array(box0[:2])) / up
    ref = tip + per_mm * prm.get(params, "wrist.tip_to_top_mm")
    return {"u": round(float(ref[0]), 1), "v": round(float(ref[1]), 1), "area": box0[2], "source": "estimated",
            "tip": tip.round(1).tolist(), "per_mm": per_mm.round(2).tolist()}


def pick_hooks(config: dict, cell, target: dict, write_library, source: str, dest_site: str, emit=None):
    """(hover hook chain, after-place reference capture, after-descent pinch check, empty-grasp feel search) for one
    pick; None where off.
    `config` carries the pick's own plan values (jaw opening): the gap between the open pads comes from it."""
    import cell_feel
    import cell_pinch
    import cell_reach

    params, spec = config.get("params"), config.get("wrist") or {}
    gap = 30.0 + (config["plan"]["grip_open"] - prm.get(params, "gripper.held_30mm")) * prm.get(params, "gripper.gap_mm_per_unit")
    wrist = cell_reach.chain(cell_reach.hook(config, cell, target, write_library),
                             ref_hook(config, cell, target, write_library, source),
                             finger_hook(config, cell, target, write_library, gap),
                             hook(config, cell, target, write_library, emit))
    capture = None
    if prm.get(params, "wrist.ref_servo") and spec.get("hsv_min"):
        work, arm = Path(config["work_dir"]).expanduser(), config.get("arm_id", "arm_s")
        capture = lambda: cell.act("goto above_place").get("ok") and capture_reference(  # noqa: E731
            cell, spec.get("camera", "wrist"), (spec["hsv_min"], spec["hsv_max"]), work, arm, dest_site, params)
    return (wrist, capture, cell_pinch.hook(config, cell, target, write_library, gap, target["entry"]["width_mm"]),
            cell_feel.feel_hook(config, cell, target, write_library))
