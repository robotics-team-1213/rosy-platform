"""LaneKeeper front end (D-364): floor-only white mask and bird's-eye line fitting.

Split out of lane_keep.py (file budget, D-362): the image-to-lines stage is ROS-free
and stateless; LaneKeeper keeps the stateful sides, pairing, corner and hold logic.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


#: Half the painted line width. The keeper fits the paint centre; the containment payload
#: sends the paint's inner (drivable) edge, so each boundary moves this far toward the lane,
#: and the G-16 fit band is this plus one fit cell. 260919 STL straights: tape 25.0 mm,
#: centres 185 mm apart (lane_half_width_m 0.0925), the map bundle's own lane_graph.py
#: clearance basis. STL nominal, unmeasured: a tape measurement of the physical mat replaces
#: it. Tested against the STL; node parameter lane_paint_half_width_m.
PAINT_HALF_WIDTH_M = 0.0125
#: Tape is 2-4 cm: RANSAC inlier half-band and the flank band that must stay dark.
CORE_HALF_M = 0.025
FLANK_INNER_M = 0.035
FLANK_OUTER_M = 0.08
#: Lit flank cells per lit core cell above which a line is a blob, not tape:
#: half of this on each side, or MAX_ONE_FLANK_RATIO in all.
MAX_FLANK_RATIO = 0.45
MAX_ONE_FLANK_RATIO = 0.6
#: Shortest boundary piece and the fewest lit cells on it.
MIN_LINE_LENGTH_M = 0.06
MIN_LINE_CELLS = 40
#: Collinear paint separated by more than this is two pieces.
MAX_GAP_M = 0.06
#: RANSAC budget.
RANSAC_HYPOTHESES = 120
MAX_LINES = 8
#: Floor mask: rows start this far below the horizon; the carpet reference is
#: this percentile of the row; white is this much brighter (absolute, or this
#: fraction of the headroom to 255, whichever is larger).
HORIZON_MARGIN_PX = 3
CARPET_PERCENTILE = 30
CARPET_ROW_WINDOW = 41
CARPET_ROW_EXCESS = 20
MIN_CONTRAST = 40
CONTRAST_HEADROOM = 0.35
MAX_SATURATION = 80
#: Walls: runs brighter than this (V channel, blue tape included) that start
#: this many rows above the horizon; bases median-filtered over this many columns.
WALL_START_ABOVE_HORIZON_PX = 4
WALL_MEDIAN_COLUMNS = 31
WALL_BASE_MARGIN_PX = 3
#: A wall run also ends at a drop of more than this (V, over WALL_STEP_ROWS):
#: the tape just below the wall base (brighter than the carpet, darker than the
#: wall) stays floor.
WALL_TAPE_STEP = 16
#: The carpet under a wall that fills most of the view: this low percentile.
WALL_CARPET_PERCENTILE = 10
WALL_STEP_ROWS = 3


def _validate_positive(name, value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not value > 0.0):
        raise ValueError(f"{name} must be a positive finite number")


def floor_white_mask(bgr: np.ndarray, horizon_row: float) -> np.ndarray:
    """uint8 0/1 mask of white floor paint below the horizon and wall bases."""
    if bgr.ndim == 2:
        value = bgr
        saturation = np.zeros_like(bgr)
    else:
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        value, saturation = hsv[..., 2], hsv[..., 1]
    height, width = value.shape
    top = max(0, min(height, int(math.ceil(horizon_row)) + HORIZON_MARGIN_PX))
    mask = np.zeros((height, width), np.uint8)
    if top >= height:
        return mask
    floor = value[top:].astype(np.float32)
    reference = np.percentile(floor, CARPET_PERCENTILE, axis=1)
    # Smooth the carpet reference over rows and cap it near the whole floor's
    # median: rows full of tape (a stop line seen across, near) must not lift
    # their own threshold.
    reference = _median_filter_1d(reference, CARPET_ROW_WINDOW)
    reference = np.minimum(reference, float(np.median(floor)) + CARPET_ROW_EXCESS)
    threshold = reference + np.maximum(MIN_CONTRAST, CONTRAST_HEADROOM * (255.0 - reference))
    # Coloured paint and overlays (and their blended, paler edges) are not tape.
    coloured = cv2.dilate((saturation[top:] > MAX_SATURATION).astype(np.uint8),
                          np.ones((5, 5), np.uint8))
    lit = (floor >= threshold[:, None]) & (coloured == 0)
    mask[top:] = lit
    # Walls: a bright run through the row just above the horizon, followed down.
    start = max(0, int(math.floor(horizon_row)) - WALL_START_ABOVE_HORIZON_PX)
    if start < height:
        # A wall filling the upper floor rows lifts their carpet reference (up
        # to 255, no wall found); the darkest floor bounds it.
        carpet = float(np.percentile(floor, WALL_CARPET_PERCENTILE))
        wall_threshold = min(float(np.median(threshold[:max(1, len(threshold) // 4)])),
                             carpet + max(MIN_CONTRAST, CONTRAST_HEADROOM * (255.0 - carpet)))
        bright = value[start:] >= wall_threshold
        # Tape laid at the wall base is bright too: the run ends where the
        # (smoothed) column drops by a step, not only where it turns dark.
        smooth = cv2.blur(value, (3, 3)).astype(np.int16)[start:]
        step = np.zeros_like(bright)
        step[WALL_STEP_ROWS:] = (smooth[:-WALL_STEP_ROWS] - smooth[WALL_STEP_ROWS:]) > WALL_TAPE_STEP
        run = np.cumprod(bright & ~step, axis=0).sum(axis=0)
        base = start + run
        base = _median_filter_1d(base, WALL_MEDIAN_COLUMNS)
        rows = np.arange(height)[:, None]
        mask[rows < (base[None, :] + WALL_BASE_MARGIN_PX)] = 0
    return mask


def paint_half_width(value):
    """``value`` as a float; a negative (edges moved outward, past the paint) or non-finite one is refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("lane_paint_half_width_m must be a finite number >= 0")
    return float(value)


def _median_filter_1d(values: np.ndarray, size: int) -> np.ndarray:
    pad = size // 2
    padded = np.pad(values.astype(np.float64), pad, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    return np.median(windows, axis=1)


def _fit_axis(points: np.ndarray):
    centre = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - centre, full_matrices=False)
    direction = vt[0]
    if direction[0] < 0:
        direction = -direction
    return centre, direction


def _largest_piece(along: np.ndarray, max_gap: float) -> np.ndarray:
    """Boolean selector of the longest gap-free run of `along` values."""
    order = np.argsort(along)
    sorted_along = along[order]
    breaks = np.flatnonzero(np.diff(sorted_along) > max_gap)
    starts = np.concatenate(([0], breaks + 1))
    stops = np.concatenate((breaks + 1, [len(along)]))
    best = max(range(len(starts)),
               key=lambda k: sorted_along[stops[k] - 1] - sorted_along[starts[k]])
    keep = np.zeros(len(along), bool)
    keep[order[starts[best]:stops[best]]] = True
    return keep


def _paint_fit(points, centre, direction, lo, hi, half_m, usable):
    """G-16: the final axis of a found line from its whole paint stroke.

    Re-read from ALL ``points`` within ``half_m`` (paint half-width + one fit cell) of the
    axis over its along span ``lo..hi``: a blob removed earlier (a crosswalk, whose
    FLANK_OUTER_M drop band reaches over the lane line) must not erode one side of the tape
    and tilt the axis. Then keep only cross-sections whose both edges (axis +- half_m) are
    ``usable`` (floor points -> bool): seen by the camera (near the robot the frame's side
    edges cut the outer part of the tape, and the inner rest leans the axis) and, as the
    caller decides, outside a crosswalk (whose bars beside the line would join the band).
    Twice, so the band follows the corrected axis. Returns (centre, direction, errors):
    errors is (slope_sd, offset_sd), the standard errors of dy/dx and of the line at the
    fit's centroid, from the fit's residuals; or None, with the given centre and direction
    unchanged, when the visible whole cross-sections are fewer than MIN_LINE_CELLS or
    shorter than MIN_LINE_LENGTH_M (a truncated fit would only move the steering axis)."""
    given = centre, direction, None
    normal = np.array([-direction[1], direction[0]])
    ends = (centre + direction * lo, centre + direction * hi)
    for _ in range(2):
        rel = points - centre
        along, across = rel @ direction, rel @ normal
        lo, hi = sorted(float((end - centre) @ direction) for end in ends)
        band = points[(np.abs(across) <= half_m) & (along >= lo) & (along <= hi)]
        foot = centre + np.outer((band - centre) @ direction, direction)
        seen = usable(foot + normal * half_m) & usable(foot - normal * half_m)
        whole = seen.sum() >= MIN_LINE_CELLS and np.ptp((band[seen] - centre) @ direction) >= MIN_LINE_LENGTH_M
        if not whole:
            return given
        fit = band[seen]
        centre, direction = _fit_axis(fit)
        normal = np.array([-direction[1], direction[0]])
    # Slope error from the cross-section centres (one per grid row x: the tape's own width
    # is not scatter), regressed on x: the standard error of dy/dx. The residual is floored
    # at the grid's quantization (one row step, uniform: step / sqrt(12)), so paint that
    # lands exactly on the grid does not state zero.
    rows, index = np.unique(fit[:, 0], return_inverse=True)
    mids = np.bincount(index, fit[:, 1]) / np.bincount(index)
    if len(rows) < 3:
        return given
    slope, offset = np.polyfit(rows, mids, 1)
    variance = max(float(np.sum((mids - slope * rows - offset) ** 2)) / (len(rows) - 2),
                   float(np.diff(rows).min()) ** 2 / 12.0)
    return centre, direction, (math.sqrt(variance / float(np.sum((rows - rows.mean()) ** 2))),
                               math.sqrt(variance / len(rows)))


def fit_cells(seen, crosswalk):
    """G-16 ``usable`` for _paint_fit: floor points ``seen`` by the camera and outside the
    rows (near_m, far_m) of a D-491 crosswalk, whose bars sit beside the lane lines."""
    if crosswalk is None:
        return seen
    return lambda xy: seen(xy) & ((xy[:, 0] < crosswalk[0]) | (xy[:, 0] > crosswalk[1]))


def extract_lines(points: np.ndarray, rng: np.random.Generator, *, usable=None, paint_half_m=None,
                  _prefer_forward=False):
    """Thin straight paint lines in `points` (N x 2, metres). Returns
    (lines, blobs): each a dict with centre, direction, along range, cells.
    With ``usable`` (floor points -> bool, see _paint_fit) and ``paint_half_m``,
    each line's final axis is the _paint_fit one and the line also carries its slope_sd and
    offset_sd (G-16); without them the fit is the found piece's, as before."""
    lines, blobs = [], []
    remaining = points
    for _ in range(MAX_LINES):
        if len(remaining) < MIN_LINE_CELLS:
            break
        first = rng.integers(0, len(remaining), RANSAC_HYPOTHESES)
        second = rng.integers(0, len(remaining), RANSAC_HYPOTHESES)
        delta = remaining[second] - remaining[first]
        norm = np.hypot(delta[:, 0], delta[:, 1])
        good = norm > 0.03
        if not good.any():
            break
        normal = np.stack([-delta[good, 1], delta[good, 0]], axis=1) / norm[good, None]
        offsets = np.einsum("ij,ij->i", normal, remaining[first[good]])
        distance = np.abs(remaining @ normal.T - offsets[None, :])
        support = (distance <= CORE_HALF_M).sum(axis=0)
        if _prefer_forward:
            support = support * normal[:, 1] ** 2
        best = int(np.argmax(support))
        inliers = remaining[distance[:, best] <= CORE_HALF_M]
        if len(inliers) < MIN_LINE_CELLS:
            break
        centre, direction = _fit_axis(inliers)
        normal_vec = np.array([-direction[1], direction[0]])
        rel = remaining - centre
        along = rel @ direction
        across = np.abs(rel @ normal_vec)
        band = across <= CORE_HALF_M
        piece = np.zeros(len(remaining), bool)
        piece[np.flatnonzero(band)[_largest_piece(along[band], MAX_GAP_M)]] = True
        lo, hi = float(along[piece].min()), float(along[piece].max())
        # Flank test on ALL points (earlier lines included): tape has dark
        # carpet on at least one side, a wall wedge or a blob is lit on both
        # (or very lit on one). Crosswalk bars next to a lane line light one
        # flank only.
        rel_all = points - centre
        along_all = rel_all @ direction
        signed_all = rel_all @ normal_vec
        across_all = np.abs(signed_all)
        span = (along_all >= lo) & (along_all <= hi)
        core = int((span & (across_all <= CORE_HALF_M)).sum())
        in_flank = span & (across_all > FLANK_INNER_M) & (across_all <= FLANK_OUTER_M)
        flank_sides = (int((in_flank & (signed_all > 0)).sum()), int((in_flank & (signed_all < 0)).sum()))
        flank = sum(flank_sides)
        # Refit on the piece for the final axis.
        fitted_centre, fitted_direction = _fit_axis(remaining[piece])
        fitted_along = (remaining[piece] - fitted_centre) @ fitted_direction
        extra = {}
        if usable is not None:
            fitted_centre, fitted_direction, errors = _paint_fit(
                points, fitted_centre, fitted_direction, float(fitted_along.min()),
                float(fitted_along.max()), paint_half_m, usable)
            fitted_along = (remaining[piece] - fitted_centre) @ fitted_direction
            extra = dict(zip(("slope_sd", "offset_sd"), errors or (None, None)))
        entry = {"centre": fitted_centre, "direction": fitted_direction,
                 "along": (float(fitted_along.min()), float(fitted_along.max())),
                 "cells": int(piece.sum()),
                 "flank_ratio": flank / max(1, core), **extra}
        if (min(flank_sides) > 0.5 * MAX_FLANK_RATIO * core
                or flank > MAX_ONE_FLANK_RATIO * core):
            blobs.append(entry)
            # The whole blob goes, not just the band, so it is not re-found.
            drop = (along >= lo) & (along <= hi) & (across <= FLANK_OUTER_M)
        else:
            if hi - lo >= MIN_LINE_LENGTH_M and piece.sum() >= MIN_LINE_CELLS:
                lines.append(entry)
            drop = piece | ((along >= lo) & (along <= hi) & (across <= FLANK_INNER_M))
        remaining = remaining[~drop]
    if not lines and blobs and not _prefer_forward:
        # A crosswalk chord can swallow a real boundary during blob removal.
        # Retry the original paint once, favouring support along the heading;
        # keep every flank/length check and never replace an accepted line.
        recovered, _ = extract_lines(points, rng, usable=usable, paint_half_m=paint_half_m,
                                     _prefer_forward=True)
        return recovered, blobs
    return lines, blobs


#: D-408 OpenCV fallback: carpet glare reads as scattered single-pixel sparkle that the white
#: threshold joins into false diagonal lines (8kcn 2026-10-01 replay: on-line 36 -> 20).
DENOISE_MEDIAN_PX = 5
DENOISE_OPEN_PX = 3
DENOISE_MIN_AREA_PX = 40


def denoise_white_mask(bgr: np.ndarray, horizon_row: float) -> np.ndarray:
    """floor_white_mask with glare suppression: a median blur before the threshold, a small
    opening after it, and blobs smaller than a tape fragment dropped."""
    img = cv2.medianBlur(bgr, DENOISE_MEDIAN_PX) if DENOISE_MEDIAN_PX > 1 else bgr
    mask = floor_white_mask(img, horizon_row).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DENOISE_OPEN_PX, DENOISE_OPEN_PX))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return drop_small_components(mask)


def drop_small_components(mask: np.ndarray) -> np.ndarray:
    """uint8 0/1 mask without 8-connected blobs smaller than DENOISE_MIN_AREA_PX (shared by the
    denoise fallback and the learned paint mask)."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= DENOISE_MIN_AREA_PX
    return keep[labels].astype(np.uint8)


def clean_learned_mask(mask: np.ndarray, horizon_row: float) -> np.ndarray:
    """A learned paint mask the way the keeper reads it: binary, cut above the horizon (same
    margin as floor_white_mask), then blobs smaller than a tape fragment dropped (D-408)."""
    out = (mask > 0).astype(np.uint8)
    out[:max(0, min(out.shape[0], int(math.ceil(horizon_row)) + HORIZON_MARGIN_PX))] = 0
    return drop_small_components(out)
