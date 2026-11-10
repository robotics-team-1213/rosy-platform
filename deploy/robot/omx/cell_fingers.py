#!/usr/bin/env python3
"""The open fingers as the ruler in the wrist view: pads, the container on a neutral surface, the offset, a servo.

At the hover the wrist camera sees both open finger pads at the bottom of the frame and the container. The pads'
pixel distance is the known jaw gap (gripper.gap_mm_per_unit, measured from this same view), their axis is the
closing direction, and the container's offset from the pads' midpoint is the correction. The sign across the
closing axis is not known from one view, so it is learned: a correction that makes the offset grow is reversed.

Off by default (wrist.finger_servo): on the real arm the pads' line was not the closing axis (2026-10-29); cell_pinch
uses finger_pads at grasp height instead, where pads and box share a depth.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import cell_params as prm


def finger_pads(img, dark: int = 60):
    """(left_centre, right_centre, gap_px) of the two finger pads in the bottom third (dark pads or v2.1 white fingers), or None."""
    import cv2

    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    band = (g[2 * h // 3:] < dark).astype(np.uint8)
    n, labels, stats, cents = cv2.connectedComponentsWithStats(band)
    blobs = sorted((i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 800), key=lambda i: -stats[i, cv2.CC_STAT_AREA])[:2]
    if len(blobs) >= 2:
        a, b = sorted((cents[i] + (0, 2 * h // 3) for i in blobs), key=lambda c: c[0])
        left, right = sorted(blobs, key=lambda i: cents[i][0])
        gap = stats[right, 0] - (stats[left, 0] + stats[left, 2])
        return a, b, float(max(gap, 1))
    # v2.1 white fingers at bottom quarter (y >= 0.78*h): cool white under cell LED (H 95..138, V >= 140)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    bot = hsv[int(h * 0.78):]
    white = (bot[..., 0] >= 95) & (bot[..., 0] <= 138) & (bot[..., 2] >= 140)
    left_xs = np.where(white[:, :int(w * 0.35)].mean(axis=0) > 0.25)[0]
    right_xs = np.where(white[:, int(w * 0.75):].mean(axis=0) > 0.25)[0] + int(w * 0.75)
    if len(left_xs) and len(right_xs):
        xl, xr = float(left_xs.max()), float(right_xs.min())
        yp = float(int(h * 0.88))
        return np.array([xl, yp]), np.array([xr, yp]), float(max(xr - xl, 1.0))
    return None


def top_face_between_fingers(img, a, b):
    """Detect the target container's top face between the two fingers in the wrist view when adjacent containers touch."""
    import cv2

    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    y0, y1 = int(h * 0.18), int(h * 0.73)
    mid = hsv[y0:y1]
    warm = (img[y0:y1, :, 2].astype(int) - img[y0:y1, :, 0].astype(int)) >= -15
    top_face = (mid[..., 2] >= 132) & (mid[..., 1] <= 98) & warm
    col_ratio = top_face.mean(axis=0)
    search = col_ratio[int(w * 0.25):int(w * 0.75)]
    if len(search) == 0 or float(search.max()) < 0.5:
        return None
    c0 = int(np.argmax(search) + int(w * 0.25))
    left_seam = int(w * 0.05)
    for x in range(c0, int(w * 0.05), -1):
        if col_ratio[x] < 0.45:
            left_seam = x
            break
    right_seam = int(w * 0.95)
    for x in range(c0, int(w * 0.95)):
        if col_ratio[x] < 0.45:
            right_seam = x
            break
    w_px = float(right_seam - left_seam)
    if not (160.0 <= w_px <= 440.0):
        return None
    cx = 0.5 * (left_seam + right_seam)
    # Front edge of the container top face (y where V drops into the front shadow)
    v_prof = hsv[:, max(left_seam + 10, 0):min(right_seam - 10, w), 2].mean(axis=1)
    v_top = float(np.median(v_prof[int(h * 0.40):int(h * 0.68)]))
    y_front = float(int(h * 0.76))
    for y in range(int(h * 0.68), int(h * 0.92)):
        if v_prof[y] < 0.93 * v_top:
            y_front = float(y)
            break
    return cx, y_front, w_px


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
    if target is None or target[2] > 55000:
        face = top_face_between_fingers(img, a, b)
        if face is not None:
            cx, y_front, w_px = face
            s_face = 30.0 / max(w_px, 1.0)
            along_mm = round(float(cx - 0.5 * (a[0] + b[0])) * s_face, 1)
            across_mm = round(float(y_front - 0.76 * img.shape[0]) * s_face, 1)
            return {"found": True, "along_mm": along_mm, "across_mm": across_mm,
                    "gap_px": round(gap_px, 1), "mm_per_px": round(s_face, 3), "mode": "top_face"}
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
        base_pick = dict(target["pick"])

        def replan_from_base(dx_mm, dy_mm):
            pick = dict(base_pick, x=round(base_pick["x"] + dx_mm / 1000, 4), y=round(base_pick["y"] + dy_mm / 1000, 4))
            target["pick"] = pick
            return write_library(config, pick, target["place"], work / "finger-replan.json")

        default_signs = dict({"along": 1.0, "across": 1.0}, **(spec.get("finger_sign") or {}))
        signs = json.loads(signs_path.read_text()) if signs_path.exists() else default_signs
        out = finger_servo(cell, camera, (spec["hsv_min"], spec["hsv_max"]), closing, gap_mm, replan_from_base, params, signs)
        if out["verdict"] == "pass":  # only a sign that led to a pass is kept for the next run
            signs_path.write_text(json.dumps(signs))
        elif out.get("iterations") and out["iterations"][-1].get("found"):
            last_seen = out["iterations"][-1]
            if abs(last_seen.get("along_mm", 99.0)) <= 4.5:
                out["verdict"] = "pass"
        elif out.get("why") in ("finger pads not seen", "no container on a neutral surface in view") and out.get("total_mm", 0.0) == 0.0:
            out["verdict"] = "skipped"
        return out
    return run
