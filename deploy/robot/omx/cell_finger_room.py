#!/usr/bin/env python3
"""How much room the open fingers really have beside an object, in mm, and the jaw margin that fits (2026-10-29).

The old check (cell_auto_pick.side_clear) refused on any foreground at 0.5, 1 and 2 finger widths past the box edge
and at +-30 % of the box's length. With the jaws opened 8 mm past each side the fingers stand 8-16 mm out, so the
4 mm sample was free space no finger enters, and the length samples reached far past a ~20 mm finger pad: boxes with
room were refused. Here the free distance on each side is measured along the closing axis across the pad's own width,
and the jaw margin is the largest one (up to auto.jaw_margin_mm) that leaves the finger clear; under
auto.min_jaw_margin_mm there is no room.
"""
from __future__ import annotations

import math

import numpy as np

import cell_params as prm


def free_mm(mask, roi, pixel_fn, start, direction, across_offsets, reach_mm: float, step_mm: float = 1.0) -> float:
    """Distance (mm) from `start` along `direction` to the first foreground, sampled at each across offset (mm);
    reach_mm when nothing is met."""
    d = np.asarray(direction, float)
    n = np.array([-d[1], d[0]])
    t = step_mm
    while t <= reach_mm:
        for s in across_offsets:
            p = np.asarray(start, float) + (t * d + s * n) / 1000
            px = pixel_fn(tuple(p))
            if px is None:
                continue
            col, row = round(px[0]) - roi[0], round(px[1]) - roi[1]
            if 1 <= row < mask.shape[0] - 1 and 1 <= col < mask.shape[1] - 1 and mask[row - 1:row + 2, col - 1:col + 2].any():
                return t - step_mm
        t += step_mm
    return reach_mm


def jaw_margin(mask, roi, pixel_fn, o: dict, closing_deg: float | None = None, params=None) -> dict:
    """{'margin_mm', 'free_mm': [side -, side +]} for the fingers closing across `o` (along closing_deg when given),
    margin None when either side has less than finger + min margin."""
    finger, pad = prm.get(params, "auto.finger_mm"), prm.get(params, "auto.finger_pad_mm")
    most, least = prm.get(params, "auto.jaw_margin_mm"), prm.get(params, "auto.min_jaw_margin_mm")
    u = math.radians(o["long_axis_deg"] if closing_deg is None else closing_deg - 90)
    across = np.array([-math.sin(u), math.cos(u)])
    half = (o["width_mm"] if closing_deg is None else max(o["width_mm"], o["length_mm"])) / 2
    centre = np.asarray(o["raw_m"], float)
    free = [free_mm(mask, roi, pixel_fn, centre + side * half * across / 1000, side * across, (-pad / 2, 0.0, pad / 2),
                    most + finger + 2.0) for side in (-1, 1)]
    margin = min(most, min(free) - finger)
    return {"margin_mm": round(margin, 1) if margin >= least else None, "free_mm": [round(f, 1) for f in free]}
