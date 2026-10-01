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

from .paint_localizer import MATCH_SCALE_M, MATCH_TRUNCATE_M

#: Fewer paint points than this is no evidence either way (None, not 0).
MIN_POINTS = 10


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
