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
