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


def _blur_roi(frame, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    return cv2.GaussianBlur(cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.int16)


def _beyond_mask(x0: int, y0: int, x1: int, y1: int, base_px, target_px, beyond_px: float) -> np.ndarray:
    away = np.array(target_px, float) - np.array(base_px, float)
    away /= np.linalg.norm(away)
    along = ((np.arange(x0, x1) - target_px[0]) * away[0])[None, :] + ((np.arange(y0, y1) - target_px[1]) * away[1])[:, None]
    return along < beyond_px


def moved_blobs(before, after, roi, base_px, target_px, params=None, _pre=None) -> list:
    """Changed regions of the ROI past the target from the base: [{"px", "area"}], largest first. A shift of the whole
    picture's brightness is taken out first: the lab's exposure moves between frames."""
    x0, y0, x1, y1 = (int(v) for v in roi)
    if _pre is None:
        g0 = _blur_roi(before, x0, y0, x1, y1)
        near = _beyond_mask(x0, y0, x1, y1, base_px, target_px, prm.get(params, "scene.beyond_px"))
    else:
        g0, near = _pre
    diff = _blur_roi(after, x0, y0, x1, y1) - g0
    mask = (np.abs(diff - int(np.median(diff))) > prm.get(params, "scene.diff")).astype(np.uint8)
    mask[near] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, centres = cv2.connectedComponentsWithStats(mask)
    blobs = [{"px": [round(float(centres[i][0]) + x0), round(float(centres[i][1]) + y0)], "area": int(stats[i, 4])}
             for i in range(1, n) if stats[i, 4] >= prm.get(params, "scene.min_area_px")]
    return sorted(blobs, key=lambda b: -b["area"])


def scene_moved(before, after) -> list:
    """Regions that differ between two whole top views taken with the arms folded: [area, x0, y0, x1, y1]. Folded, the arm is in
    both views, so unlike moved_blobs the whole frame can be compared."""
    diff = cv2.GaussianBlur(cv2.absdiff(before, after), (5, 5), 0).max(2)
    mask = cv2.morphologyEx((diff > 45).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    return [[int(stats[i, 4]), int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 0] + stats[i, 2]), int(stats[i, 1] + stats[i, 3])]
            for i in range(1, n) if stats[i, 4] > 150]


def hook(cell, config: dict, before, roi, base_px, target_px):
    """The hover hook; no pixel for the base or the target means nothing can be compared, so the carry does not go on."""
    params = config.get("params")
    pre = None
    if before is not None and base_px is not None and target_px is not None:
        x0, y0, x1, y1 = (int(v) for v in roi)
        pre = (_blur_roi(before, x0, y0, x1, y1), _beyond_mask(x0, y0, x1, y1, base_px, target_px, prm.get(params, "scene.beyond_px")))

    def run() -> dict:
        out = {"dx_mm": 0.0, "dy_mm": 0.0, "total_mm": 0.0}
        if base_px is None or target_px is None:
            return {**out, "verdict": "refuse", "why": "scene guard: the base or the target has no pixel"}
        moved = moved_blobs(before, cell.frame("top"), roi, base_px, target_px, params, _pre=pre)
        if moved:
            return {**out, "verdict": "refuse", "why": f"scene changed past the arm: {moved[:3]}", "moved": moved[:3]}
        return {**out, "verdict": "pass"}
    return run
