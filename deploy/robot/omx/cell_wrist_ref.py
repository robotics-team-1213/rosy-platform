#!/usr/bin/env python3
"""Reference-pixel servo with a learned image Jacobian, from the wrist camera at the hover (2026-10-29).

The oblique wrist view has no fixed relation between the pads' line and the closing axis on the floor (a 19 mm
move along the closing axis showed up "across"). So: the reference is where a container appears when it is truly
between the jaws - recorded by the arm itself right after a confirmed place, from the same hover pose - and the
image Jacobian J (px per arm mm) is measured with two small probe moves, then refined by Broyden after each step.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import cell_params as prm
from cell_fingers import on_surface_blob


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
