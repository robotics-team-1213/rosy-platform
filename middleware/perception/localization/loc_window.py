"""Bounded full-scan candidate fallback for a supplied native-map window."""
from __future__ import annotations

import math
import time

import numpy as np
from pydantic import ValidationError

from core_common.protocol.localization import LocalizationSearchWindow

from .loc_assist import SETTLE_S, localized_objects
from .sensing.loc_candidates import PoseCandidate, base_from_sensor, sensor_from_base
from .sensing.localization import valid_beams, wrap


OFFSETS = np.stack(np.meshgrid(
    np.arange(-12, 13) * .01, np.arange(-12, 13) * .01,
    np.radians(np.arange(-14, 15, 2)), indexing='ij'), axis=-1).reshape(-1, 3)
MAX_EVALUATIONS = 128
BUDGET_S = 1.25
WINDOW_RETRY_NS = 15_000_000_000
WINDOW_EXPIRY_NS = 8_000_000_000
WINDOW_DELIVERY_NS = 1_000_000_000


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


def decode_window(payload, grid_id, last_window_ns, now_ns):
    if not isinstance(payload, dict):
        return None
    issued_ns = payload.get("issued_ns")
    if (type(issued_ns) is not int or not 0 <= now_ns - issued_ns <= WINDOW_DELIVERY_NS
            or issued_ns - last_window_ns < WINDOW_RETRY_NS):
        return None
    try:
        window = LocalizationSearchWindow.model_validate(payload.get("window"))
    except ValidationError:
        return None
    if window.expected_map_grid_id != grid_id:
        return None
    center = window.center
    return (center.x, center.y, center.yaw), issued_ns


def confirm_window_candidate(node, candidate, window, now, generation):
    if (window is None or generation != node.generation or not node.core.search_window_ready(now)
            or time.monotonic_ns() - window[1] > WINDOW_EXPIRY_NS or node.scan is None):
        return [], []
    scan = node.scan
    sample_stamp = scan.header.stamp
    stamp = (sample_stamp.sec * 1_000_000_000 + sample_stamp.nanosec) * 1e-9
    if stamp <= window[0] or not 0. <= now - stamp <= SETTLE_S:
        return [], []
    try:
        mount = node.scan_mount(scan)
    except Exception:
        return [], []
    ranges, angles = node.scan_arrays(scan, 1)
    sensor = sensor_from_base((candidate.x, candidate.y, candidate.yaw), mount)
    fit = node.field.robust_score(sensor, ranges, angles)
    if fit < node.p("candidate_minimum_fit"):
        return [], []
    candidate = PoseCandidate(candidate.x, candidate.y, candidate.yaw, min(candidate.scan_fit, fit), "window")
    return [candidate], localized_objects(node.field, sensor, ranges, angles, mount, node.p("robot_radius"))


def log_by(logger, warn, message):
    """rclpy fixes the severity at each logging call site, so warning and info each keep their own line."""
    if warn:
        logger.warning(message)
    else:
        logger.info(message)
