"""Subject: lane keeping ('keep' mode) on a real, near-horizontal camera (D-353 §2).

A lane keeper, not a line tracer: the target is the middle of the lane the
robot is in, never the tape. Per frame, no odometry:

  floor mask    white = bright relative to the carpet of the same image row
                (a low percentile of the row, so tape covering half a row does
                not raise its own threshold) and low saturation (blue wall
                tape, the pilot overlay and yellow/black signs drop out); only
                below the horizon and below the base of the white walls. A
                wall is a bright run that starts above the horizon; per image
                column its base is where that run ends, median-filtered across
                columns so a far tape line touching the wall is not eaten.
  bird's-eye    the mask sampled on the lane_bev robot-frame floor grid
                (base_link, x ahead, y LEFT positive, REP 103), so width and
                heading are metres and radians, not pixels
  boundaries    straight ground lines found by RANSAC on the lit cells. A line
                whose flanks are lit too is a blob (a wall wedge, glare), not
                tape, and is dropped; so is one crossing the path at more than
                TRANSVERSE_MIN_ANGLE_RAD (stop lines, crosswalks: those belong
                to the traffic policy, D-151)
  side          each boundary's lateral offset at the lookahead decides left
                (y > 0) or right (y < 0) -- ground geometry, not image row
                position; a line almost under the robot takes its side from the
                previous target
  target        midpoint of the nearest left and right boundary that are a
                lane width apart; one side only: that boundary moved a
                half-width inward; none: no output (HOLD)
  corner        an L-corner shows a transverse line ahead that runs past the
                lane on one side only (the open side) -- the outer boundary of
                the lane after the turn. Its centre line is that line moved a
                half-width toward the robot; the robot pursues the corner path
                (straight on, then along that centre line toward the open side)
                at CORNER_LOOKAHEAD_M, and goes straight while the corner is
                further. Near the corner the open side is out of view, so the
                side is latched (frame count, no pose) while a transverse line
                stays ahead. Opt-in (corner_turning; the node's
                lane_corner_turning, off on the device).

Output keeps the lane contract: error > 0 means steer right (CORE:
angular = -gain * error); error = -target_y / lane_half_width, clipped to
[-1, 1] -- the target's lateral offset at the lookahead, which also carries
the heading error (lookahead x heading), like `detect_lane_centre`. Not the
pure-pursuit curvature law of the odometry modes: at CORE's gain 0.8 and
~0.05 m/s this loop is overdamped (poles ~ -0.24 and -1.9 1/s), while the
pursuit law is underdamped and five times softer on a one-sided target. `last` holds a debug bundle for the pilot overlay and the replay
bench. Short temporal smoothing uses previous targets only (no pose).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from .lane import LaneObservation
from .lane_bev import BirdsEye

#: Lookahead from base_link where the lane centre is read.
LOOKAHEAD_M = 0.25
#: Boundaries are sided and paired by their lateral offset this far ahead of
#: base_link: inside the camera's floor view, where NOMINAL geometry errs least.
SIDE_X_M = 0.22
#: A boundary line may be extrapolated this far past its seen paint.
MAX_EXTRAPOLATION_M = 0.15
#: Tape is 2-4 cm: RANSAC inlier half-band and the flank band that must stay dark.
CORE_HALF_M = 0.025
FLANK_INNER_M = 0.035
FLANK_OUTER_M = 0.08
#: Lit flank cells per lit core cell above which a line is a blob, not tape.
MAX_FLANK_RATIO = 0.45
#: Shortest boundary piece and the fewest lit cells on it.
MIN_LINE_LENGTH_M = 0.06
MIN_LINE_CELLS = 40
#: Lines are fitted on the bird's-eye grid thinned to this cell (2 lane_bev cells).
FIT_STRIDE = 2
#: Collinear paint separated by more than this is two pieces.
MAX_GAP_M = 0.06
#: A line this far off the robot's heading is a transverse mark.
TRANSVERSE_MIN_ANGLE_RAD = math.radians(65.0)
#: Two boundaries of one lane run within this angle of each other.
PAIR_MAX_ANGLE_RAD = math.radians(30.0)
#: A lone boundary further than this fraction of the lane width is not ours.
ONE_MAX_DISTANCE_FRACTION = 1.5
#: A boundary pair must be this fraction of the lane width apart.
PAIR_MIN_FRACTION = 0.6
PAIR_MAX_FRACTION = 1.6
#: A boundary nearer the robot than this takes its side from the last target.
AMBIGUOUS_LATERAL_M = 0.03
#: Confidence: both boundaries / one boundary (CORE drives slower on one).
BOTH_CONFIDENCE = 0.9
ONE_CONFIDENCE = 0.6
#: RANSAC budget.
RANSAC_HYPOTHESES = 120
MAX_LINES = 8
MAX_POINTS = 6000
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
#: Lit fraction of the floor above which the frame is washed out.
WASHED_FRACTION = 0.5
#: Corners: the lookahead on the corner path (shorter than LOOKAHEAD_M, or the
#: robot cuts the inner corner), how far ahead a corner line may be, how far
#: past the lane (beyond the half-width) and how much further than the other
#: end its open end must run, and for how many frames without a line across
#: the path a seen side stays latched (it holds while such a line stays ahead).
CORNER_LOOKAHEAD_M = 0.12
CORNER_MAX_AHEAD_M = 0.45
CORNER_OPEN_M = 0.02
CORNER_ASYMMETRY_M = 0.02
#: The closed end sits on the outer lane line: within this of the half-width.
CORNER_CLOSED_TOLERANCE_M = 0.03
CORNER_LATCH_FRAMES = 12


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
        wall_threshold = float(np.median(threshold[:max(1, len(threshold) // 4)]))
        bright = value[start:] >= wall_threshold
        run = np.cumprod(bright, axis=0).sum(axis=0)
        base = start + run
        base = _median_filter_1d(base, WALL_MEDIAN_COLUMNS)
        rows = np.arange(height)[:, None]
        mask[rows < (base[None, :] + WALL_BASE_MARGIN_PX)] = 0
    return mask


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


def extract_lines(points: np.ndarray, rng: np.random.Generator):
    """Thin straight paint lines in `points` (N x 2, metres). Returns
    (lines, blobs): each a dict with centre, direction, along range, cells."""
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
        best = int(np.argmax((distance <= CORE_HALF_M).sum(axis=0)))
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
        # carpet either side, a wall wedge or a blob does not.
        rel_all = points - centre
        along_all = rel_all @ direction
        across_all = np.abs(rel_all @ normal_vec)
        span = (along_all >= lo) & (along_all <= hi)
        core = int((span & (across_all <= CORE_HALF_M)).sum())
        flank = int((span & (across_all > FLANK_INNER_M) & (across_all <= FLANK_OUTER_M)).sum())
        # Refit on the piece for the final axis.
        fitted_centre, fitted_direction = _fit_axis(remaining[piece])
        fitted_along = (remaining[piece] - fitted_centre) @ fitted_direction
        entry = {"centre": fitted_centre, "direction": fitted_direction,
                 "along": (float(fitted_along.min()), float(fitted_along.max())),
                 "cells": int(piece.sum()),
                 "flank_ratio": flank / max(1, core)}
        if flank > MAX_FLANK_RATIO * core:
            blobs.append(entry)
            # The whole blob goes, not just the band, so it is not re-found.
            drop = (along >= lo) & (along <= hi) & (across <= FLANK_OUTER_M)
        else:
            if hi - lo >= MIN_LINE_LENGTH_M and piece.sum() >= MIN_LINE_CELLS:
                lines.append(entry)
            drop = piece | ((along >= lo) & (along <= hi) & (across <= FLANK_INNER_M))
        remaining = remaining[~drop]
    return lines, blobs


class LaneKeeper:
    """Keep the middle of the lane on a real camera, memoryless ('keep' mode)."""

    def __init__(self, *, camera_x_offset_m: float = 0.0,
                 lookahead_m: float = LOOKAHEAD_M,
                 smoothing: float = 0.5, seed: int = 0,
                 corner_turning: bool = False) -> None:
        if (isinstance(camera_x_offset_m, bool)
                or not isinstance(camera_x_offset_m, (int, float))
                or not math.isfinite(camera_x_offset_m)):
            raise ValueError("camera_x_offset_m must be a finite number")
        _validate_positive("lookahead_m", lookahead_m)
        if (isinstance(smoothing, bool) or not isinstance(smoothing, (int, float))
                or not 0.0 <= smoothing < 1.0):
            raise ValueError("smoothing must be in [0, 1)")
        self._x_offset = float(camera_x_offset_m)
        self._lookahead = float(lookahead_m)
        self._smoothing = float(smoothing)
        self._seed = int(seed)
        self._corner_turning = bool(corner_turning)
        self._view = None
        self._view_key = None
        self._previous_target = None
        self._corner_side = None
        self._corner_frames = 0
        self.last: dict = {}

    def reset(self) -> None:
        self._previous_target = None
        self._corner_side = None
        self._corner_frames = 0
        self.last = {}

    def _birds_eye(self, ground, width: int, height: int) -> BirdsEye:
        key = (id(ground), ground.height_m, ground.pitch_rad, ground.focal_px,
               ground.principal_x, ground.principal_y, width, height)
        if key != self._view_key:
            self._view = BirdsEye(ground, width, height, self._x_offset)
            self._view_key = key
        return self._view

    def to_pixel(self, ground, x: float, y: float):
        """(column, row) of a base_link floor point, or None behind the camera."""
        forward = x - self._x_offset
        if forward <= 0.0:
            return None
        ray = math.atan2(ground.height_m, forward) - ground.pitch_rad
        row = ground.principal_y + ground.focal_px * math.tan(ray)
        denominator = (ground.focal_px * math.sin(ground.pitch_rad)
                       + (row - ground.principal_y) * math.cos(ground.pitch_rad))
        column = ground.principal_x - y * denominator / ground.height_m
        return (round(column, 1), round(row, 1))

    def update(self, bgr: np.ndarray, ground, *, lane_half_width_m: float = 0.0925,
               **_ignored) -> LaneObservation | None:
        _validate_positive("lane_half_width_m", lane_half_width_m)
        if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
            raise ValueError("camera frame must be a non-empty grayscale or BGR array")
        self.last = {"strategy": "none", "boundaries": [], "transverse": [], "blobs": 0,
                     "lookahead_m": self._lookahead, "target_m": None, "target_px": None}
        if ground is None:
            self.last["reason"] = "no_ground"
            self._previous_target = None
            return None
        half = float(lane_half_width_m)
        height, width = bgr.shape[:2]
        mask = floor_white_mask(bgr, ground.horizon_row)
        view = self._birds_eye(ground, width, height)
        grid = view.sample(mask)
        observable = int(view.observable.sum())
        lit = int(grid.sum())
        if observable == 0 or lit > WASHED_FRACTION * observable:
            self.last["reason"] = "washed"
            self._previous_target = None
            return None
        coarse = grid[::FIT_STRIDE, ::FIT_STRIDE]
        cells = np.flatnonzero(coarse.ravel())
        points = np.stack([view.x[::FIT_STRIDE, ::FIT_STRIDE].ravel()[cells],
                           view.y[::FIT_STRIDE, ::FIT_STRIDE].ravel()[cells]], axis=1)
        rng = np.random.default_rng(self._seed)
        if len(points) > MAX_POINTS:
            points = points[rng.choice(len(points), MAX_POINTS, replace=False)]
        lines, blobs = extract_lines(points, rng) if len(points) else ([], [])
        self.last["blobs"] = len(blobs)
        previous = self._previous_target
        left, right, transverse = [], [], []
        for line in lines:
            centre, direction = line["centre"], line["direction"]
            heading = math.atan2(direction[1], direction[0])
            ends = [centre + direction * line["along"][0], centre + direction * line["along"][1]]
            record = {"heading_deg": round(math.degrees(heading), 1),
                      "length_m": round(line["along"][1] - line["along"][0], 3),
                      "ends_m": [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in ends],
                      "ends_px": [self.to_pixel(ground, float(p[0]), float(p[1])) for p in ends]}
            if abs(heading) > TRANSVERSE_MIN_ANGLE_RAD:
                self.last["transverse"].append(record)
                transverse.append((centre, direction, ends))
                continue
            # Side by ground geometry: the line's lateral offset (base_link y,
            # left +) where the lane is read. Almost under the robot, the last
            # target decides instead.
            lateral = _lateral_at(centre, direction, SIDE_X_M)
            reference = 0.0
            if abs(lateral) < AMBIGUOUS_LATERAL_M and previous is not None:
                reference = previous[1]
            side = "left" if lateral > reference else "right"
            inward = (np.array([direction[1], -direction[0]]) if side == "left"
                      else np.array([-direction[1], direction[0]]))
            point, along = _pursuit_point(centre + inward * half, direction, self._lookahead)
            if not (line["along"][0] - MAX_EXTRAPOLATION_M <= along
                    <= line["along"][1] + MAX_EXTRAPOLATION_M):
                continue
            record.update(side=side, y_at_side_x_m=round(lateral, 3),
                          pursuit_m=[round(float(point[0]), 3), round(float(point[1]), 3)],
                          centre=centre, direction=direction)
            (left if side == "left" else right).append(record)
        target, strategy = self._choose(left, right, half)
        corner = self._corner(transverse, half) if self._corner_turning else None
        if corner is not None and (target is None or corner[1] != "corner_ahead"):
            target, strategy = corner
        for record in left + right:
            record.pop("direction")
            record.pop("centre")
            self.last["boundaries"].append(record)
        if target is None:
            self.last["reason"] = "no_boundary"
            self._previous_target = None
            return None
        if previous is not None and self._smoothing > 0.0 and not strategy.startswith("corner"):
            target = self._smoothing * np.asarray(previous) + (1.0 - self._smoothing) * target
        tx, ty = float(target[0]), float(target[1])
        self._previous_target = (tx, ty)
        confidence = BOTH_CONFIDENCE if strategy == "both" else ONE_CONFIDENCE
        if strategy == "both":
            self._corner_side, self._corner_frames = None, 0
        error = max(-1.0, min(1.0, -ty / half))
        self.last.update(strategy=strategy, target_m=[round(tx, 3), round(ty, 3)],
                         target_px=self.to_pixel(ground, tx, ty),
                         error=round(error, 3), confidence=confidence)
        return LaneObservation(error=error, confidence=confidence)

    def _corner(self, transverse, half):
        """(target, strategy) from the nearest L-corner line ahead, or None.
        Updates the latched corner side."""
        best = None
        for centre, direction, ends in transverse:
            ys = sorted(float(p[1]) for p in ends)
            if ys[0] > half or ys[1] < -half:
                continue  # beside the path, not across it
            ahead = float(centre[0] - centre[1] * direction[0] / direction[1])
            if not 0.0 < ahead <= CORNER_MAX_AHEAD_M:
                continue
            if best is None or ahead < best[0]:
                best = (ahead, centre, direction, ys)
        if best is None:
            if self._corner_frames > 0:
                self._corner_frames -= 1
            if self._corner_frames == 0:
                self._corner_side = None
            return None
        ahead, centre, direction, ys = best
        left_reach, right_reach = ys[1], -ys[0]
        side = None
        if max(left_reach, right_reach) > half + CORNER_OPEN_M:
            # The closed end is where the corner line meets the outer lane line.
            if (left_reach - right_reach > CORNER_ASYMMETRY_M
                    and abs(right_reach - half) <= CORNER_CLOSED_TOLERANCE_M):
                side = "left"
            elif (right_reach - left_reach > CORNER_ASYMMETRY_M
                    and abs(left_reach - half) <= CORNER_CLOSED_TOLERANCE_M):
                side = "right"
        if side is not None:
            self._corner_side, self._corner_frames = side, CORNER_LATCH_FRAMES
        side = self._corner_side
        if side is None:
            return None  # a stop line or a T: not a corner
        # The new lane's centre line: the corner line moved half a lane toward
        # the robot, pursued toward the open side (left = +y).
        normal = np.array([-direction[1], direction[0]])
        if float(np.dot(normal, centre)) > 0.0:
            normal = -normal
        origin = centre + normal * half
        along = direction if (direction[1] > 0.0) == (side == "left") else -direction
        meet = float(origin[0] - origin[1] * along[0] / along[1])
        if meet > CORNER_LOOKAHEAD_M:
            return np.array([CORNER_LOOKAHEAD_M, 0.0]), "corner_ahead"
        point, _ = _pursuit_point(origin, along, CORNER_LOOKAHEAD_M)
        return point, f"corner_{side}"

    def _choose(self, left, right, half):
        """Target (x, y) and strategy from the side-classified boundaries."""
        lane = 2.0 * half
        pairs = []
        for l in left:
            for r in right:
                parallel = float(np.dot(l["direction"], r["direction"]))
                separation = l["y_at_side_x_m"] - r["y_at_side_x_m"]
                if (parallel >= math.cos(PAIR_MAX_ANGLE_RAD)
                        and PAIR_MIN_FRACTION * lane <= separation <= PAIR_MAX_FRACTION * lane):
                    pairs.append((separation, l, r))
        if pairs:
            # The nearest pair: the robot is inside it (adjacent lanes lie beyond).
            # Pursue the centre line: midway at SIDE_X_M, along the mean heading
            # (on a NOMINAL floor the two lines rarely come out exactly parallel).
            _, l, r = min(pairs, key=lambda p: p[0])
            middle = np.array([SIDE_X_M, (l["y_at_side_x_m"] + r["y_at_side_x_m"]) / 2.0])
            heading = l["direction"] + r["direction"]
            point, _ = _pursuit_point(middle, heading / np.linalg.norm(heading), self._lookahead)
            return point, "both"
        candidates = [r for r in left + right
                      if abs(r["y_at_side_x_m"]) <= ONE_MAX_DISTANCE_FRACTION * lane]
        if not candidates:
            return None, "none"
        record = min(candidates, key=lambda r: (round(abs(r["y_at_side_x_m"]), 2), -r["length_m"]))
        return np.asarray(record["pursuit_m"], float), f"{record['side']}_only"


def _lateral_at(centre, direction, x) -> float:
    return float(centre[1] + (x - centre[0]) * direction[1] / direction[0])


def _pursuit_point(origin, direction, radius):
    """Point of the line origin + t*direction at `radius` from base_link, ahead
    (the larger root); the closest point when the line passes further away.
    Returns (point, t)."""
    b = float(np.dot(origin, direction))
    disc = b * b - float(np.dot(origin, origin)) + radius * radius
    t = -b + math.sqrt(disc) if disc > 0.0 else -b
    return origin + direction * t, t
