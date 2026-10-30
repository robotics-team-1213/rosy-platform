#!/usr/bin/env python3
"""Lower, then look: with the open fingers down at the box's height, is the box between them? (2026-10-29)

At the hover the oblique wrist camera sees the fingertips and the box at different depths, so "centred" depends on a
reference pixel or a calibrated camera; both were 4-5 cm wrong on the real arm. Down at grasp height the pads and the
box's sides are at the same depth: the gap between each pad and the box, scaled by the known jaw opening between the
pads (mm per pixel at that depth), says directly whether the jaws will close on the box, and by how much to shift if
not. Nothing is calibrated, and the same check holds for every box size: the measured width is compared with the
catalogue width (a long box seen where a short one was planned is the wrong box) and each side needs a free gap.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_params as prm
from cell_fingers import finger_pads


def measure(img, hsv, gap_mm: float, width_mm: float | None = None, params=None) -> dict:
    """Gaps (mm) between each pad's inner edge and the box along the pads' line, the box width and the shift that
    centres it (+ toward the right pad in the image)."""
    import cv2

    pads = finger_pads(img)
    if pads is None:
        return {"found": False, "why": "finger pads not seen"}
    a, b, _ = pads
    axis = (b - a) / np.linalg.norm(b - a)
    across = np.array([-axis[1], axis[0]])
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h = g.shape[0]
    dark = np.argwhere(g[2 * h // 3:] < 60)[:, ::-1] + (0, 2 * h // 3)
    mid = (a + b) / 2
    proj = (dark - mid) @ axis
    near = np.abs((dark - mid) @ across) < prm.get(params, "pinch.band_px")
    left_in = proj[near & (proj < 0)].max() if (near & (proj < 0)).any() else None
    right_in = proj[near & (proj > 0)].min() if (near & (proj > 0)).any() else None
    if left_in is None or right_in is None or right_in - left_in < 10:
        return {"found": False, "why": "pad inner edges not found"}
    s = gap_mm / float(right_in - left_in)
    hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    green = np.argwhere(cv2.inRange(hsv_img, np.array(hsv[0]), np.array(hsv[1])) > 0)[:, ::-1]
    band = green[np.abs((green - mid) @ across) < prm.get(params, "pinch.band_px")]
    if len(band) < 50:
        return {"found": True, "between": False, "why": "no box at the pads' height", "mm_per_px": round(s, 3),
                "pads": [[round(float(v), 1) for v in a], [round(float(v), 1) for v in b]]}
    gp = (band - mid) @ axis
    lo, hi = np.percentile(gp, 0.5), np.percentile(gp, 99.5)
    out = {"found": True, "pads": [[round(float(v), 1) for v in a], [round(float(v), 1) for v in b]], "gap_left_mm": round(float(lo - left_in) * s, 1), "gap_right_mm": round(float(right_in - hi) * s, 1),
           "width_mm": round(float(hi - lo) * s, 1), "shift_mm": round(float((lo + hi) / 2) * s, 1), "mm_per_px": round(s, 3)}
    need = prm.get(params, "pinch.min_gap_mm")
    sized = width_mm is None or abs(out["width_mm"] - width_mm) <= prm.get(params, "pinch.width_tol") * width_mm
    out["between"] = out["gap_left_mm"] >= need and out["gap_right_mm"] >= need
    out["sized"] = bool(sized)
    return out


def check(cell, camera: str, hsv, closing_deg: float, gap_mm: float, width_mm, redescend, params=None, sign=None,
          mount=None) -> dict:
    """Measure at grasp height; when the box is not between the pads, lift, shift along the closing axis and lower
    again (pinch.max_iter). The image->arm sign of the pads' line is learned: a step that made it worse flips it.
    `mount` is the pads' pixels from the last pass: the fingers are fixed to the camera, so pads far from there mean the
    camera was turned (2026-10-29: the base plate and cables of a turned camera passed as pads)."""
    sign = sign if sign is not None else {"along": 1.0}
    c = math.radians(closing_deg)
    along = np.array([math.cos(c), math.sin(c)])
    dx = dy = 0.0
    rows, last = [], None
    for i in range(int(prm.get(params, "pinch.max_iter")) + 1):
        seen = measure(cell.frame(camera), hsv, gap_mm, width_mm, params)
        rows.append({"iteration": i, **seen})
        if not seen["found"]:
            return {"verdict": "refuse", "why": seen["why"], "dx_mm": dx, "dy_mm": dy, "iterations": rows}
        if mount and max(math.dist(p, q) for p, q in zip(seen["pads"], mount)) > prm.get(params, "pinch.mount_tol_px"):
            return {"verdict": "refuse", "why": "wrist camera moved: the fingers are not where they were", "dx_mm": dx, "dy_mm": dy, "iterations": rows}
        if seen.get("between") and seen.get("sized"):
            return {"verdict": "pass", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "iterations": rows}
        if "shift_mm" not in seen:
            return {"verdict": "refuse", "why": seen["why"], "dx_mm": dx, "dy_mm": dy, "iterations": rows}
        if seen["between"]:  # whole and still the wrong width: another box (a finger hides part of one not between)
            return {"verdict": "refuse", "why": f"box width {seen['width_mm']} mm, planned {width_mm}", "dx_mm": dx, "dy_mm": dy, "iterations": rows}
        if last is not None and abs(seen["shift_mm"]) > abs(last) + 1.0:
            sign["along"] = -sign["along"]
        if i == int(prm.get(params, "pinch.max_iter")):
            break
        step = sign["along"] * float(np.clip(seen["shift_mm"], -prm.get(params, "pinch.max_step_mm"), prm.get(params, "pinch.max_step_mm"))) * along
        dx, dy, last = dx + step[0], dy + step[1], seen["shift_mm"]
        if not redescend(dx, dy):
            return {"verdict": "refuse", "why": "re-descent refused", "dx_mm": dx, "dy_mm": dy, "iterations": rows}
    return {"verdict": "refuse", "why": "not between the fingers", "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "iterations": rows}


def hook(config: dict, cell, target: dict, write_library, gap_mm: float, width_mm=None):
    """The check as a hook run right after descend_pick (pinch.enabled), or None. The sign that led to a pass is kept."""
    params, spec = config.get("params"), config.get("wrist") or {}
    if not prm.get(params, "pinch.enabled") or not spec.get("hsv_min"):
        return None
    work = Path(config["work_dir"]).expanduser()
    signs_path = work / f"pinch-sign-{config.get('arm_id', 'arm_s')}.json"
    mount_path = work / f"pinch-mount-{config.get('arm_id', 'arm_s')}.json"

    def redescend(dx_mm, dy_mm):
        pick = dict(target["pick"], x=round(target["pick"]["x"] + dx_mm / 1000, 4), y=round(target["pick"]["y"] + dy_mm / 1000, 4))
        library = write_library(config, pick, target["place"], work / "pinch-replan.json")
        return all(cell.act(c).get("ok") for c in ("run lift_pick", f"load {library}", "goto above_pick", "run descend_pick"))

    def run():
        sign = json.loads(signs_path.read_text()) if signs_path.exists() else {"along": 1.0}
        closing = target["pick"]["yaw_deg"] + prm.get(params, "auto.closing_theory_deg")
        mount = json.loads(mount_path.read_text())["pads"] if mount_path.exists() else None
        out = check(cell, spec.get("camera", "wrist"), (spec["hsv_min"], spec["hsv_max"]), closing, gap_mm, width_mm,
                    redescend, params, sign, mount)
        if out["verdict"] == "pass":
            signs_path.write_text(json.dumps(sign))
            mount_path.write_text(json.dumps({"pads": out["iterations"][-1]["pads"]}))
        return out
    return run
