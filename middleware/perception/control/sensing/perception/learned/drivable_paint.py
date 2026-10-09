"""Subject: the learned drivable region as the lane keeper's paint (D-597; keep mode, learned_paint_target drivable).

The model finds the drivable region; this module finds the way through it and hands the
keeper the boundaries of that way. Pure numpy, no ROS: the same functions can run where the
inference runs (robot today, Fleet as a later fallback).

drivable_target   logits -> the robot's own drivable way on the model grid, or None and why.
                  The region is lane_bounded_drivable (D-566 item 4, D-576 boundary rule) from
                  the model's drivable class, without its row-growth clamp: the clamp keeps the
                  run nearest the middle of the row below (a tie goes left), which would choose
                  a junction branch against D-384. Holes enclosed by the region (a box, a stray
                  label) are filled: they are not a fork. Where the region splits into branches
                  (the model labels every reachable junction branch drivable), the rightmost
                  branch is followed: D-384 decision 2, keep right when no route says otherwise.
                  Too little of it in the near band (DRIVABLE_MIN_FRACTION, the shadow evidence
                  rule) is no target.
boundary_paint    that way at frame size -> synthetic boundary paint: per row, a strip one painted
                  line wide just outside each side of the way, so the keeper's paint centre lies
                  PAINT_HALF_WIDTH_M outside the drivable edge and its inner (drivable) edge is
                  the drivable edge itself (lane_keep_lines, lane_containment). A side touching
                  the frame border has no strip: what lies beyond it is unseen, not a boundary.
lateral_px_per_m  pixels per metre of floor across one image row (the GroundPlane.lateral law).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .lane_mask import DRIVABLE_MIN_FRACTION, NEAR_FIELD_FRACTION, NonFiniteLogits, _row_runs, lane_bounded_drivable


#: A run narrower than this share of the kept run below it is a ragged edge finger or a speck, not
#: a branch. Replay 2026-10-10 (crop128 model, 36 drive frames): every frame showed 2-5 "branches"
#: before this rule, all from the region's ragged far edge.
MIN_BRANCH_WIDTH_FRACTION = 0.25


def fill_holes(region: np.ndarray) -> np.ndarray:
    """The region with every hole it encloses filled (non-region pixels not reachable from outside
    the frame without crossing the region)."""
    outside = np.pad(~region, 1, constant_values=True).astype(np.uint8)
    cv2.floodFill(outside, None, (0, 0), 2)
    return region | (outside[1:-1, 1:-1] == 1)


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    """(first, last) column of each True run of one row."""
    step = np.diff(np.r_[0, row.astype(np.int8), 0])
    return list(zip(np.flatnonzero(step == 1), np.flatnonzero(step == -1) - 1))


def right_branch(region: np.ndarray) -> tuple[np.ndarray, int]:
    """(the way, most branches seen in a row). From the region's lowest row (the run nearest the
    centre column: the robot's own road), go up keeping the runs that touch the kept run below;
    where more than one at least MIN_BRANCH_WIDTH_FRACTION of its width does, the road splits and
    the rightmost of those is kept (D-384 decision 2); with none that wide, the widest."""
    out = np.zeros(region.shape, bool)
    rows = np.flatnonzero(region.any(axis=1))
    if not rows.size:
        return out, 0
    start = int(rows.max())
    centre = (region.shape[1] - 1) / 2.0
    first, last = min(_runs(region[start]), key=lambda r: 0.0 if r[0] <= centre <= r[1]
                      else min(abs(r[0] - centre), abs(r[1] - centre)))
    out[start, first:last + 1] = True
    below, branches = out[start], 1
    for row in range(start - 1, -1, -1):
        runs = _runs(_row_runs(region[row], below))
        if not runs:
            break
        wide = [r for r in runs if r[1] - r[0] + 1 >= MIN_BRANCH_WIDTH_FRACTION * (last - first + 1)]
        branches = max(branches, len(wide))
        first, last = max(wide) if wide else max(runs, key=lambda r: r[1] - r[0])
        out[row, first:last + 1] = True
        below = out[row]
    return out, branches


def drivable_target(logits: np.ndarray, classes, *, ignore_top: int = 0) -> tuple[np.ndarray | None, dict]:
    """(the drivable way as a bool mask on the logits grid, or None; info for keep_debug).

    info: reason (ok | no_drivable_class | low_coverage), branches, near_fraction."""
    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != len(classes):
        raise ValueError(f"logits shape {logits.shape} does not match {len(classes)} classes")
    if not np.isfinite(logits).all():
        raise NonFiniteLogits("non-finite logits")
    roles: dict[str, list[int]] = {}
    for c in classes:
        roles.setdefault(c.role, []).append(c.index)
    if "drivable" not in roles:
        return None, dict(reason="no_drivable_class", branches=0, near_fraction=0.0)
    labels = logits[0].argmax(axis=0)
    # `ignore` paint inside the road (crosswalk, speed bump) is road for the way: as a pass-through
    # only (lane_bounded_drivable through_idxs) it would leave holes that cut the way's rows apart.
    labels = np.where(np.isin(labels, roles.get("ignore", [])), roles["drivable"][0], labels)
    names = {c.name: c.index for c in classes}
    region = lane_bounded_drivable(
        labels, roles["drivable"][0], roles.get("lane_marking", ()), ignore_top=ignore_top,
        max_row_growth=math.inf,
        boundary=(names["lane_left"], names["lane_right"]) if {"lane_left", "lane_right"} <= set(names) else None)
    way, branches = right_branch(fill_holes(region))
    band = way[int(way.shape[0] * (1 - NEAR_FIELD_FRACTION)):]
    near = float(band.mean())
    if near < DRIVABLE_MIN_FRACTION:
        return None, dict(reason="low_coverage", branches=branches, near_fraction=round(near, 4))
    return way, dict(reason="ok", branches=branches, near_fraction=round(near, 4))


def lateral_px_per_m(rows: np.ndarray, *, focal_px: float, principal_y: float, pitch_rad: float,
                     height_m: float) -> np.ndarray:
    """Image columns per metre of lateral floor offset at each row (GroundPlane.lateral:
    column - cx = y * denominator / height). Rows at or above the horizon give 0."""
    denominator = focal_px * math.sin(pitch_rad) + (np.asarray(rows, float) - principal_y) * math.cos(pitch_rad)
    return np.maximum(denominator, 0.0) / height_m


def boundary_paint(way: np.ndarray, px_per_m: np.ndarray, paint_half_width_m: float) -> np.ndarray:
    """uint8 0/1 boundary paint for the keeper from the way (HxW, frame size): per row, a strip
    2 x paint_half_width_m wide (at that row's px_per_m, at least one pixel) just outside the
    leftmost and rightmost way pixel, unless that pixel is on the frame border."""
    height, width = way.shape
    if len(px_per_m) != height:
        raise ValueError("px_per_m needs one value per row")
    paint = np.zeros((height, width), np.uint8)
    for row in np.flatnonzero(way.any(axis=1)):
        if px_per_m[row] <= 0.0:
            continue
        strip = max(1, int(round(2.0 * paint_half_width_m * px_per_m[row])))
        cols = np.flatnonzero(way[row])
        first, last = int(cols[0]), int(cols[-1])
        if first > 0:
            paint[row, max(0, first - strip):first] = 1
        if last < width - 1:
            paint[row, last + 1:last + 1 + strip] = 1
    return paint
