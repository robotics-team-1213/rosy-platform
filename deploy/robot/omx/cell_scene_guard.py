"""Stop a carry when something moved beyond the arm's reach in the top view (2026-11-06).

On arm_b the jaws opened over a packed ship, shoved two containers, and the hover chain still went up and came back to
open again; the contact judge cannot feel 16 g. The first hook of the hover chain compares the view from before the
motion with the one at the hover, only past the target as seen from the arm's base: the arm and its shadow cannot be
there. A corridor around the arm failed on real carries: the raised link passes far from the straight line, and hue or
brightness rules either fired on the arm or missed the shove (replayed on the 2026-11-03..06 episodes).
shortcut: the neighbours on the arm's side of the target are not watched; upgrade with a mask of the arm from its joints.
"""
from __future__ import annotations

import cv2
import numpy as np

import cell_params as prm


def moved_blobs(before, after, roi, base_px, target_px, params=None) -> list:
    """Changed regions of the ROI past the target from the base: [{"px", "area"}], largest first. A shift of the whole
    picture's brightness is taken out first: the lab's exposure moves between frames."""
    x0, y0, x1, y1 = (int(v) for v in roi)
    gray = [cv2.GaussianBlur(cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.int16)
            for f in (before, after)]
    diff = gray[1] - gray[0]
    mask = (np.abs(diff - int(np.median(diff))) > prm.get(params, "scene.diff")).astype(np.uint8)
    away = np.array(target_px, float) - np.array(base_px, float)
    away /= np.linalg.norm(away)
    ys, xs = np.mgrid[y0:y1, x0:x1]
    along = (xs - target_px[0]) * away[0] + (ys - target_px[1]) * away[1]
    mask[along < prm.get(params, "scene.beyond_px")] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, centres = cv2.connectedComponentsWithStats(mask)
    blobs = [{"px": [round(float(centres[i][0]) + x0), round(float(centres[i][1]) + y0)], "area": int(stats[i, 4])}
             for i in range(1, n) if stats[i, 4] >= prm.get(params, "scene.min_area_px")]
    return sorted(blobs, key=lambda b: -b["area"])


def hook(cell, config: dict, before, roi, base_px, target_px):
    """The hover hook; no pixel for the base or the target means nothing can be compared, so the carry does not go on."""
    params = config.get("params")

    def run() -> dict:
        out = {"dx_mm": 0.0, "dy_mm": 0.0, "total_mm": 0.0}
        if base_px is None or target_px is None:
            return {**out, "verdict": "refuse", "why": "scene guard: the base or the target has no pixel"}
        moved = moved_blobs(before, cell.frame("top"), roi, base_px, target_px, params)
        if moved:
            return {**out, "verdict": "refuse", "why": f"scene changed past the arm: {moved[:3]}", "moved": moved[:3]}
        return {**out, "verdict": "pass"}
    return run
