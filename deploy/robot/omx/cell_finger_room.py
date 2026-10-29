#!/usr/bin/env python3
"""How much room the open fingers really have beside an object, in mm, and the jaw margin that fits (2026-10-29).

The old check (cell_auto_pick.side_clear) refused on any foreground at 0.5, 1 and 2 finger widths past the box edge
and at +-30 % of the box's length. With the jaws opened 8 mm past each side the fingers stand 8-16 mm out, so the
4 mm sample was free space no finger enters, and the length samples reached far past a ~20 mm finger pad: boxes with
room were refused. Here the free distance on each side is measured along the closing axis across the pad's own width,
and the jaw margin is the largest one (up to auto.jaw_margin_mm) that leaves the finger clear; under
auto.min_jaw_margin_mm there is no room. Foreground running on from the edge for up to auto.own_side_mm is the
object's own side face and shadow, which the camera sees past its top outline (2026-10-29, board: 0-1 mm "free" on
the side away from the arm was the box itself); running on further it is a touching neighbour.
"""
from __future__ import annotations

import math

import numpy as np

import cell_params as prm


def free_mm(mask, roi, pixel_fn, start, direction, across_offsets, reach_mm: float, step_mm: float = 1.0,
            own_mm: float = 0.0) -> float:
    """Distance (mm) from `start` along `direction` to the first foreground, sampled at each across offset (mm);
    reach_mm when nothing is met. Foreground running on from `start` up to own_mm is the object's own; a 1 mm gap
    does not end that run (a slightly skewed outline starts the side face a step out on one pad edge)."""
    d = np.asarray(direction, float)
    n = np.array([-d[1], d[0]])
    t, clear = step_mm, 0.0
    while t <= reach_mm:
        hit = False
        for s in across_offsets:
            px = pixel_fn(tuple(np.asarray(start, float) + (t * d + s * n) / 1000))
            if px is None:
                continue
            col, row = round(px[0]) - roi[0], round(px[1]) - roi[1]
            hit = hit or (1 <= row < mask.shape[0] - 1 and 1 <= col < mask.shape[1] - 1
                          and bool(mask[row - 1:row + 2, col - 1:col + 2].any()))
        leaving = clear < 2.0
        if hit and not (leaving and t <= own_mm):
            return t - step_mm
        clear = 0.0 if hit and leaving else clear + step_mm
        t += step_mm
    return reach_mm


def jaw_margin(mask, roi, pixel_fn, o: dict, closing_deg: float | None = None, params=None) -> dict:
    """{'margin_mm', 'free_mm': [side -, side +]} for the fingers closing across `o` (along closing_deg when given),
    margin None when either side has less than finger + min margin."""
    finger, pad = prm.get(params, "auto.finger_mm"), prm.get(params, "auto.finger_pad_mm")
    most, least = prm.get(params, "auto.jaw_margin_mm"), prm.get(params, "auto.min_jaw_margin_mm")
    own = prm.get(params, "auto.own_side_mm")
    u = math.radians(o["long_axis_deg"] if closing_deg is None else closing_deg - 90)
    across = np.array([-math.sin(u), math.cos(u)])
    half = (o["width_mm"] if closing_deg is None else max(o["width_mm"], o["length_mm"])) / 2
    centre = np.asarray(o["raw_m"], float)
    free = [free_mm(mask, roi, pixel_fn, centre + side * half * across / 1000, side * across, (-pad / 2, 0.0, pad / 2),
                    most + finger + 2.0, own_mm=own) for side in (-1, 1)]
    margin = min(most, min(free) - finger)
    return {"margin_mm": round(margin, 1) if margin >= least else None, "free_mm": [round(f, 1) for f in free]}
