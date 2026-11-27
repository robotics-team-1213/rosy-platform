"""What a push measured (owner decision 2026-11-28: a push runs and completes on measured evidence, not on its exit code).

The same blob detection that planned the push is read again after the arm is clear: the object that stood under the
pixel before, and the object nearest the planned end after. A push whose object is not found on either side, or whose
displacement is not measurable, reports measured=false and is a failure for the worker and for Fleet (never retried
with the same pixel).
"""
from __future__ import annotations

import math

import numpy as np


def _near(objects, point_mm, within_mm: float):
    """The matched object whose centre is nearest point_mm and within within_mm, else None."""
    best = None
    for o in objects:
        c = o.get("centre_mm")
        if not o.get("matched") or c is None or len(c) < 2:
            continue
        gap = math.hypot(float(c[0]) - point_mm[0], float(c[1]) - point_mm[1])
        if gap <= within_mm and (best is None or gap < best[0]):
            best = (gap, np.array([float(c[0]), float(c[1])]))
    return None if best is None else best[1]


def displacement(before, after, pixel_mm, direction, push_mm: float, tol_mm: float) -> dict:
    """Raw-map mm: {measured, commanded_mm, moved_mm, along_dir_mm, lateral_mm} or {measured: false, why}.
    pixel_mm is where the pixel lies in the map, direction the push as a unit vector, tol_mm how far the pixel may lie from
    the object's centre (its half length plus a margin)."""
    start = _near(before, pixel_mm, tol_mm)
    if start is None:
        return {"measured": False, "why": "no matched object under the pixel before the push", "commanded_mm": push_mm}
    d = np.asarray(direction, float) / np.linalg.norm(direction)
    end = _near(after, start + d * push_mm, push_mm + tol_mm)
    if end is None:
        return {"measured": False, "why": "no matched object near the planned end after the push", "commanded_mm": push_mm}
    delta = end - start
    return {"measured": True, "commanded_mm": push_mm, "moved_mm": round(float(np.hypot(*delta)), 1),
            "along_dir_mm": round(float(delta @ d), 1), "lateral_mm": round(abs(float(delta[0] * d[1] - delta[1] * d[0])), 1)}


def last_park(steps) -> dict | None:
    """The park step that ended the run, with the readback it carried (the fold check reads state/settled/ok from it)."""
    last = steps[-1] if steps else None
    return last if isinstance(last, dict) and last.get("command") == "park" else None
