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
_FIELD: list = [None, None]
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
    key = ref.tobytes()
    if _FIELD[0] != key:                     # one reference per dock: build its grid once, not per zone check
        _FIELD[:] = [key, _Field(ref)]
    field = _FIELD[1]
    runs = [r for r in (_icp(cur, field, *seed) for seed in _SEEDS) if r is not None]
    if not runs:
        return None
    best = max(runs, key=lambda r: r[3])
    others = [r[3] for r in runs
              if math.hypot(r[0] - best[0], r[1] - best[1]) > _SAME_POSE_M
              or abs(math.atan2(math.sin(r[2] - best[2]), math.cos(r[2] - best[2]))) > _SAME_POSE_RAD]
    return BayScanPose(x=best[0], y=best[1], heading=best[2], inliers=best[3],
                       margin=best[3] - (max(others) if others else 0.0), median_m=best[4])
