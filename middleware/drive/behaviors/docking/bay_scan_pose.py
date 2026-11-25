"""core_features.docking.bay_scan_pose — the robot's pose in the bay frame by LiDAR, against a stored seated scan.

The map pose goes stale near a bay (odometry slip, a degenerate SLAM fit along the axis: y8xs 2026-11-20, 0.30 m and
4 deg off). A dock may carry one reference scan taken while the robot sat seated (`DockInstance.metadata["reference_scan"]`,
the raw scan: angle_min, angle_increment, range_min, range_max, ranges). Matching the live scan to it gives the pose in the
bay frame: the seated robot is the origin, +x out of the bay (the nose, as seated), +y the seated robot's left.

Both scans must be turned into points by the same code (RobotBody.scan_view); this module only matches point sets.
It never moves the robot and never decides: a result is evidence the zone check weighs. numpy only; if numpy is missing the
match is None and the caller keeps the map path. Bounded: at most MAX_POINTS points a side, one run per zone check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

try:
    import numpy as np
except ImportError:          # pragma: no cover - the map path stays
    np = None

MAX_POINTS = 150            # live and reference points kept per side
RANGE_M = 1.2               # nothing farther is the bay
INLIER_M = 0.03
CELL_M = 0.01               # nearest-point grid resolution
_FIELD = (None, None)
_SEEDS = tuple((gx, 0.0, math.radians(a)) for a in range(-180, 180, 20) for gx in (0.1, 0.3))
_SAME_POSE_M, _SAME_POSE_RAD = 0.05, math.radians(8.0)


@dataclass(frozen=True)
class BayScanPose:
    x: float                 # m, out of the bay along the seated nose direction
    y: float                 # m, left of the seated robot
    heading: float           # rad, the robot's heading relative to the seated one
    inliers: float           # share of live points within INLIER_M of the reference
    margin: float            # inliers minus the best different pose's inliers (a seed that landed elsewhere)
    median_m: float


def _points(points: Sequence[tuple[float, float]]):
    arr = np.asarray(points, dtype=float).reshape(-1, 2)
    arr = arr[np.hypot(arr[:, 0], arr[:, 1]) < RANGE_M]
    if len(arr) > MAX_POINTS:
        arr = arr[np.linspace(0, len(arr) - 1, MAX_POINTS).astype(int)]
    return arr


class _Brute:
    """Same lookup as _Field without the grid: for the consecutive-scan matches of a turn (the reference changes every time, a grid
    build would cost 0.7 s of the 3 s watch)."""

    def __init__(self, ref):
        self.ref = ref

    def lookup(self, moved):
        d2 = ((moved[:, None, :] - self.ref[None, :, :]) ** 2).sum(-1)
        j = d2.argmin(1)
        return j, d2[np.arange(len(moved)), j]


class _Field:
    """The reference as a 1 cm grid of nearest-reference-point indices: one lookup per live point per iteration instead of
    a points x points distance matrix (the Pi's CORE main thread is busy; this keeps the match to a few hundred ms)."""

    def __init__(self, ref):
        self.ref = ref
        self.n = int(round(2.0 * RANGE_M / CELL_M))
        axis = (np.arange(self.n) + 0.5) * CELL_M - RANGE_M
        gy, gx = np.meshgrid(axis, axis, indexing="ij")
        cells = np.stack([gx.ravel(), gy.ravel()], axis=1)
        nearest = np.empty(len(cells), dtype=np.int32)
        for lo in range(0, len(cells), 4096):
            chunk = cells[lo:lo + 4096]
            nearest[lo:lo + 4096] = ((chunk[:, None, :] - ref[None, :, :]) ** 2).sum(-1).argmin(1)
        self.nearest = nearest.reshape(self.n, self.n)

    def lookup(self, moved):
        """(index of the nearest reference point, squared distance to it); points off the grid get a huge distance."""
        cx = np.floor((moved[:, 0] + RANGE_M) / CELL_M).astype(int)
        cy = np.floor((moved[:, 1] + RANGE_M) / CELL_M).astype(int)
        inside = (cx >= 0) & (cx < self.n) & (cy >= 0) & (cy < self.n)
        j = self.nearest[np.clip(cy, 0, self.n - 1), np.clip(cx, 0, self.n - 1)]
        d2 = ((moved - self.ref[j]) ** 2).sum(1)
        return j, np.where(inside, d2, 1e9)


def _reference_field(ref):
    """A worker keeps the immutable cache snapshot or its own build while a peer changes references."""
    global _FIELD
    key = ref.tobytes()
    cached_key, cached_field = _FIELD
    if key == cached_key:
        return cached_field
    field = _Field(ref)
    _FIELD = (key, field)
    return field


def _icp(cur, field, x, y, th, iters=25):
    ref = field.ref
    for i in range(iters):
        c, s = math.cos(th), math.sin(th)
        moved = cur @ np.array([[c, s], [-s, c]]) + [x, y]
        j, d2 = field.lookup(moved)
        keep = d2 < (0.05 ** 2 if i > 5 else 0.15 ** 2)
        if keep.sum() < 20:
            return None
        a, b = moved[keep], ref[j[keep]]
        ma, mb = a.mean(0), b.mean(0)
        h = (a - ma).T @ (b - mb)
        dth = math.atan2(h[0, 1] - h[1, 0], h[0, 0] + h[1, 1])
        cr, sr = math.cos(dth), math.sin(dth)
        rot = np.array([[cr, -sr], [sr, cr]])
        t = mb - rot @ ma
        nx, ny = rot @ [x, y] + t
        x, y, th = float(nx), float(ny), th + dth
    c, s = math.cos(th), math.sin(th)
    moved = cur @ np.array([[c, s], [-s, c]]) + [x, y]
    dist = np.sqrt(field.lookup(moved)[1])
    return x, y, math.atan2(math.sin(th), math.cos(th)), float(np.mean(dist < INLIER_M)), float(np.median(dist))


def locate_near(reference, live, guess) -> Optional[BayScanPose]:
    """The bay pose of `live` with ICP seeded at `guess` = (x, y, heading), the previous good pose: a handful of runs (the guess and the
    alias seeds one bay pitch / 0.2 m / 0.5 rad away, for the margin) instead of 36. The CORE main thread can be 85 % busy (load 13): the
    full search took long enough that no pose stayed fresh (y8xs C3 round)."""
    if np is None:
        return None
    try:
        ref, cur = _points(reference), _points(live)
    except (ValueError, TypeError):
        return None
    if len(ref) < 40 or len(cur) < 40:
        return None
    field = _reference_field(ref)
    gx, gy, gh = guess
    seeds = [(gx, gy, gh), (gx, gy + 0.21, gh), (gx, gy - 0.21, gh), (gx + 0.2, gy, gh), (gx - 0.2, gy, gh), (gx, gy, gh + 0.5), (gx, gy, gh - 0.5)]
    runs = [r for r in (_icp(cur, field, *seed) for seed in seeds) if r is not None]
    if not runs:
        return None
    best = max(runs, key=lambda r: r[3])
    others = [r[3] for r in runs
              if math.hypot(r[0] - best[0], r[1] - best[1]) > _SAME_POSE_M
              or abs(math.atan2(math.sin(r[2] - best[2]), math.cos(r[2] - best[2]))) > _SAME_POSE_RAD]
    return BayScanPose(x=best[0], y=best[1], heading=best[2], inliers=best[3],
                       margin=best[3] - (max(others) if others else 0.0), median_m=best[4])


def locate_track(reference, live, guess) -> Optional[BayScanPose]:
    """TRACKED pose inside the row (panel B R26): local ICP from ONE seed, the previous accepted pose carried by odometry; no alias seeds.
    The margin (global ambiguity between self-similar bays) means nothing for a tracked pose, so it is the sentinel 1.0; the callers gate
    on inliers, the jump from the previous pose, the lane and the rear gap instead."""
    if np is None:
        return None
    try:
        ref, cur = _points(reference), _points(live)
    except (ValueError, TypeError):
        return None
    if len(ref) < 40 or len(cur) < 40:
        return None
    run = _icp(cur, _reference_field(ref), *guess)
    if run is None:
        return None
    return BayScanPose(x=run[0], y=run[1], heading=run[2], inliers=run[3], margin=1.0, median_m=run[4])


def locate_step(reference, live, guess_heading: float = 0.0) -> Optional[BayScanPose]:
    """Pose of `live` in the frame of the previous scan `reference` (a turn step): seeds around the odometry increment, no grid; the
    margin is not meaningful here (1.0)."""
    if np is None:
        return None
    try:
        ref, cur = _points(reference), _points(live)
    except (ValueError, TypeError):
        return None
    if len(ref) < 40 or len(cur) < 40:
        return None
    field = _Brute(ref)
    runs = [r for r in (_icp(cur, field, 0.0, 0.0, g, iters=20) for g in (guess_heading, 0.0, guess_heading / 2.0)) if r is not None]
    if not runs:
        return None
    best = max(runs, key=lambda r: r[3])
    return BayScanPose(x=best[0], y=best[1], heading=best[2], inliers=best[3], margin=1.0, median_m=best[4])


def locate(reference: Sequence[tuple[float, float]], live: Sequence[tuple[float, float]]) -> Optional[BayScanPose]:
    """Pose of the robot in the reference frame, or None (too few points, no numpy, no fit)."""
    if np is None:
        return None
    try:
        ref, cur = _points(reference), _points(live)
    except (ValueError, TypeError):
        return None
    if len(ref) < 40 or len(cur) < 40:
        return None
    field = _reference_field(ref)
    runs = [r for r in (_icp(cur, field, *seed) for seed in _SEEDS) if r is not None]
    if not runs:
        return None
    best = max(runs, key=lambda r: r[3])
    others = [r[3] for r in runs
              if math.hypot(r[0] - best[0], r[1] - best[1]) > _SAME_POSE_M
              or abs(math.atan2(math.sin(r[2] - best[2]), math.cos(r[2] - best[2]))) > _SAME_POSE_RAD]
    return BayScanPose(x=best[0], y=best[1], heading=best[2], inliers=best[3],
                       margin=best[3] - (max(others) if others else 0.0), median_m=best[4])
