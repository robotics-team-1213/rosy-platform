"""Subject: how well one pose hypothesis explains the paint the camera sees (D-395 §7, D-375).

The track walls are 180-degree symmetric; the floor paint is not. Placing the
camera's paint points on the map from a hypothesis and measuring how far they
land from real paint separates a pose from its mirror (measured on
map_v2_fleet: about 1.0 for the truth, under 0.05 for the mirror). Same
distance score as the paint particle filter, so the two never disagree on
what "on paint" means.
"""
from __future__ import annotations

import math

import numpy as np

from .lane import _WASHED_FRACTION
from .lane_bev import BirdsEye
from .lane_keep_lines import floor_white_mask
from .paint_localizer import MATCH_SCALE_M, MATCH_TRUNCATE_M

#: Fewer paint points than this is no evidence either way (None, not 0).
MIN_POINTS = 10
#: Points handed to paint_score from one frame; an even subsample keeps the shape.
MAX_CAMERA_POINTS = 400


def paint_score(paint_map, points, pose):
    """exp(-mean capped distance / scale) for base_link (forward, left) paint points at `pose`; None if too few."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    points = points[np.all(np.isfinite(points), axis=1)]
    if len(points) < MIN_POINTS or not all(math.isfinite(v) for v in pose):
        return None
    c, s = math.cos(pose[2]), math.sin(pose[2])
    on_map = np.column_stack((pose[0] + c * points[:, 0] - s * points[:, 1],
                              pose[1] + s * points[:, 0] + c * points[:, 1]))
    distance = np.minimum(paint_map.distance_at(on_map), MATCH_TRUNCATE_M)
    return float(math.exp(-float(np.mean(distance)) / MATCH_SCALE_M))


def camera_paint_points(bgr, ground, camera_x_offset_m, view=None):
    """Base_link (forward, left) floor points of white paint in one camera frame.

    The same front end as the keep lane mode: `floor_white_mask` sampled on the
    `lane_bev.BirdsEye` floor grid. Empty without a ground plane or when the
    floor is washed out. Pass `view` (a BirdsEye for this ground and frame size)
    to skip rebuilding the grid."""
    if ground is None or bgr is None or getattr(bgr, 'ndim', 0) not in (2, 3):
        return np.empty((0, 2))
    height, width = bgr.shape[:2]
    view = BirdsEye(ground, width, height, camera_x_offset_m) if view is None else view
    grid = view.sample(floor_white_mask(bgr, ground.horizon_row)).astype(bool)
    observable = int(view.observable.sum())
    lit = int(grid.sum())
    if observable == 0 or lit > _WASHED_FRACTION * observable:
        return np.empty((0, 2))
    points = np.column_stack((view.x[grid], view.y[grid]))
    if len(points) > MAX_CAMERA_POINTS:
        points = points[np.linspace(0, len(points) - 1, MAX_CAMERA_POINTS).astype(int)]
    return points
