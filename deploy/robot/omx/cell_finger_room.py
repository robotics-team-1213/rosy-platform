#!/usr/bin/env python3
"""How much room the open fingers really have beside an object, in mm, and the jaw margin that fits (2026-10-29).

The old check (side_clear, removed 2026-10-30) refused on any foreground at 0.5, 1 and 2 finger widths past the box edge
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
            own_mm: float = 0.0, outside_blocks: bool = False) -> float:
    """Distance (mm) from `start` along `direction` to the first foreground, sampled at each across offset (mm);
    reach_mm when nothing is met. Foreground running on from `start` up to own_mm is the object's own; a 1 mm gap
    does not end that run (a slightly skewed outline starts the side face a step out on one pad edge). With
    outside_blocks, what the mask does not cover (past the roi or the image) is not known free but a hit."""
    d = np.asarray(direction, float)
    n = np.array([-d[1], d[0]])
    t, clear = step_mm, 0.0
    while t <= reach_mm:
        hit = False
        for s in across_offsets:
            px = pixel_fn(tuple(np.asarray(start, float) + (t * d + s * n) / 1000))
            if px is None:
                hit = hit or outside_blocks
                continue
            col, row = round(px[0]) - roi[0], round(px[1]) - roi[1]
            inside = 1 <= row < mask.shape[0] - 1 and 1 <= col < mask.shape[1] - 1
            hit = hit or (not inside and outside_blocks) or (inside and bool(mask[row - 1:row + 2, col - 1:col + 2].any()))
        leaving = clear < 2.0
        if hit and not (leaving and t <= own_mm):
            return t - step_mm
        clear = 0.0 if hit and leaving else clear + step_mm
        t += step_mm
    return reach_mm


def mark_half_gap_mm(params=None, open_value: float | None = None) -> float:
    """Half the finger gap when the jaws are opened to the jaw-mark value (pivot.grip_open unless given), from the 30 mm
    hold and the gap per unit; past the measured 48.8-55.6 this is a line through the data, and 62 is 6 units past it."""
    value = prm.get(params, "pivot.grip_open") if open_value is None else open_value
    return (30.0 + (value - prm.get(params, "gripper.held_30mm")) * prm.get(params, "gripper.gap_mm_per_unit")) / 2


def mark_room(mask, roi, pixel_fn, centre, across, half_mm: float, params=None, own_mm: float = 0.0) -> list:
    """Distance (mm) from `centre` along the closing axis `across` to the first foreground (or the edge of what the mask
    covers) on each side, as far as the fully opened jaw-mark needs: half the opened gap plus look.mark_err_mm. The lane
    is the pad's width plus the same error, since the jaws may stand that far off the centre. Returns [side -, side +],
    each at most the need, so a side that reads the need is clear to the full opening."""
    err, pad = prm.get(params, "look.mark_err_mm"), prm.get(params, "auto.finger_pad_mm")
    need, w = mark_half_gap_mm(params) + err, pad / 2 + err
    centre, across = np.asarray(centre, float), np.asarray(across, float)
    return [round(half_mm + free_mm(mask, roi, pixel_fn, centre + side * half_mm * across / 1000, side * across,
                                    (-w, -w / 2, 0.0, w / 2, w), max(need - half_mm, 1.0), own_mm=own_mm, outside_blocks=True), 1)
            for side in (-1, 1)]


def own_removed(mask, roi, pixel_fn, o: dict):
    """The finger mask without the object's own pixels (its outline, or its blob): its sides are not a neighbour."""
    import cv2

    centre = pixel_fn(tuple(o["raw_m"]))
    if o.get("hull_px"):  # only its own pixels: a box split from a touching neighbour (cell_split) must still see it
        own = np.zeros(mask.shape, np.uint8)
        cv2.fillPoly(own, [np.asarray(o["hull_px"], np.int32) - [roi[0], roi[1]]], 1)
        mask = np.where(cv2.dilate(own, np.ones((5, 5), np.uint8)) > 0, 0, mask).astype(mask.dtype)
    else:
        n, labels = cv2.connectedComponents(mask)
        c_col, c_row = round(centre[0]) - roi[0], round(centre[1]) - roi[1]
        if 0 <= c_row < mask.shape[0] and 0 <= c_col < mask.shape[1] and labels[c_row, c_col]:
            mask = np.where(labels == labels[c_row, c_col], 0, mask).astype(mask.dtype)  # its own blob (side faces) is not a neighbour
    return mask


def jaw_margin(mask, roi, pixel_fn, o: dict, closing_deg: float | None = None, params=None) -> dict:
    """{'margin_mm', 'free_mm': [side -, side +]} for the fingers closing across `o` (along closing_deg when given),
    margin None when either side has less than finger + min margin. The margin is as wide as the room and the jaws
    allow (up to auto.jaw_margin_max_mm): the top map alone errs 6 mm mean, 14 mm worst, and with a fixed 8 mm
    35 of 64 real attempts put a finger on the box (2026-10-30)."""
    finger, pad = prm.get(params, "auto.finger_mm"), prm.get(params, "auto.finger_pad_mm")
    least = prm.get(params, "auto.min_jaw_margin_mm")
    own = prm.get(params, "auto.own_side_mm")
    u = math.radians(o["long_axis_deg"] if closing_deg is None else closing_deg - 90)
    across = np.array([-math.sin(u), math.cos(u)])
    half = (o["width_mm"] if closing_deg is None else max(o["width_mm"], o["length_mm"])) / 2
    widest = 30.0 + (prm.get(params, "gripper.open_max") - prm.get(params, "gripper.held_30mm")) * prm.get(
        params, "gripper.gap_mm_per_unit")  # the opening at open_max, from the 30 mm hold and the gap per unit
    most = min(prm.get(params, "auto.jaw_margin_max_mm"), (widest - 2 * half) / 2)
    centre = np.asarray(o["raw_m"], float)
    free = [free_mm(mask, roi, pixel_fn, centre + side * half * across / 1000, side * across, (-pad / 2, 0.0, pad / 2),
                    most + finger + 2.0, own_mm=own) for side in (-1, 1)]
    margin = min(most, min(free) - finger)
    # the jaw mark opens wider than any pick (62 against open_max 56): its own room, from the box's centre, kept with it
    return {"margin_mm": round(margin, 1) if margin >= least else None, "free_mm": [round(f, 1) for f in free],
            "mark_half_mm": mark_room(mask, roi, pixel_fn, centre, across, half, params, own_mm=own)}
