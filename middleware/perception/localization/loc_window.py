"""Bounded full-scan candidate fallback for a supplied native-map window."""
from __future__ import annotations

import math
import time

import numpy as np

from .sensing.loc_candidates import PoseCandidate, base_from_sensor
from .sensing.localization import valid_beams, wrap


OFFSETS = np.stack(np.meshgrid(
    np.arange(-12, 13) * .01, np.arange(-12, 13) * .01,
    np.radians(np.arange(-14, 15, 2)), indexing='ij'), axis=-1).reshape(-1, 3)
MAX_EVALUATIONS = 128
BUDGET_S = 1.25


def _ray_quality(field, poses, ranges, angles):
    """Rank proposals by endpoints with a coarse interior wall penalty."""
    start = (poses[:, :2] - field.origin) / field.resolution
    theta = poses[:, 2, None] + angles
    dx, dy = np.cos(theta) * ranges / field.resolution, np.sin(theta) * ranges / field.resolution
    h, w = field.grid.shape

    def cells(fraction):
        ix = np.floor(start[:, 0, None] + fraction * dx).astype(int)
        iy = np.floor(start[:, 1, None] + fraction * dy).astype(int)
        inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        return ix[inside], iy[inside], inside

    blocked = np.zeros(dx.shape, dtype=bool)
    for fraction in (.2, .4, .6, .8):
        ix, iy, inside = cells(fraction)
        blocked[inside] |= field.grid[iy, ix] >= 65
    ix, iy, inside = cells(1.)
    score = np.zeros(dx.shape)
    score[inside] = field.likelihood[iy, ix]
    score[blocked] = -.5
    return score.mean(axis=1)


def window_candidate(field, clear, center, mount, ranges, angles, minimum_fit,
                     *, clock=time.monotonic):
    """One full-scan-checked candidate, with no global uniqueness claim."""
    ranges, angles = valid_beams(ranges, angles)
    if len(ranges) < 30:
        return None
    center = np.asarray(center, dtype=float)
    h, w = field.grid.shape
    if not np.all((field.origin <= center[:2]) &
                  (center[:2] < field.origin + np.array([w, h]) * field.resolution)):
        return None

    deadline = clock() + BUDGET_S
    bases = OFFSETS + center
    cos, sin = np.cos(bases[:, 2]), np.sin(bases[:, 2])
    poses = np.column_stack((bases[:, 0] + cos * mount.x - sin * mount.y,
                             bases[:, 1] + sin * mount.x + cos * mount.y,
                             bases[:, 2] + mount.yaw))
    ix, iy = np.floor((poses[:, :2] - field.origin) / field.resolution).astype(int).T
    inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    poses = poses[inside][clear[iy[inside], ix[inside]]]
    if not len(poses):
        return None

    # The endpoint ranking and the ray ranking capture different occlusions.
    # Neither substitutes for the same full robust scorer used by verification.
    endpoint = field._qualities(poses, ranges[::8], angles[::8])
    rays = _ray_quality(field, poses, ranges[::12], angles[::12])
    endpoint_order = np.argsort(-endpoint, kind='stable')[:MAX_EVALUATIONS]
    ray_order = np.argsort(-rays, kind='stable')[:MAX_EVALUATIONS]
    order = list(dict.fromkeys(np.column_stack((endpoint_order, ray_order)).ravel()))
    for index in order[:MAX_EVALUATIONS]:
        if clock() >= deadline:
            return None
        pose = poses[index].copy()
        pose[2] = wrap(pose[2])
        fit = field.robust_score(pose, ranges, angles)
        if fit >= minimum_fit:
            return PoseCandidate(*base_from_sensor(pose, mount), scan_fit=fit, origin='window')
    return None
