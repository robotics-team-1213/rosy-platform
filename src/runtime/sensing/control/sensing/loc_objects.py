"""Subject: lidar returns the map does not explain, grouped into objects (D-395 §4.2).

Another robot is the commonest unmapped object on the track. The Fleet arbiter
projects each object through every pose hypothesis and asks which one puts it on
a robot that is already LOCALIZED. Returns are judged at one candidate pose: on
a symmetric map the mirror explains exactly the same returns, so the list does
not depend on which hypothesis is used. Output is base_link (forward, left), m.
"""
from __future__ import annotations

import math

import numpy as np

from .localization import valid_beams

#: Neighbouring unexplained returns farther apart than this start a new object.
#: A Pinky is ~0.12 m across; two robots side by side are farther apart than 6 cm.
GAP_M = .06
MIN_POINTS = 2
MAX_OBJECTS = 16


def unmapped_objects(field, sensor_pose, ranges, angles, mount, gap_m=GAP_M, min_points=MIN_POINTS):
    """Centroids of unexplained return clusters as base_link (x, y) tuples, at most MAX_OBJECTS."""
    ranges, angles = valid_beams(ranges, angles)
    if not len(ranges):
        return []
    order = np.argsort(angles)
    ranges, angles = ranges[order], angles[order]
    heading = sensor_pose[2] + angles
    wx = sensor_pose[0] + np.cos(heading) * ranges
    wy = sensor_pose[1] + np.sin(heading) * ranges
    ix = np.floor((wx - field.origin[0]) / field.resolution).astype(int)
    iy = np.floor((wy - field.origin[1]) / field.resolution).astype(int)
    h, w = field.near.shape
    inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    unexplained = np.zeros(len(ranges), dtype=bool)
    unexplained[inside] = ~field.near[iy[inside], ix[inside]]
    # Sensor-frame points into base_link through the rotated mount.
    sx, sy = np.cos(angles) * ranges, np.sin(angles) * ranges
    c, s = math.cos(mount.yaw), math.sin(mount.yaw)
    bx, by = mount.x + c * sx - s * sy, mount.y + s * sx + c * sy
    objects, cluster = [], []
    for i in np.flatnonzero(unexplained):
        if cluster and math.hypot(bx[i] - bx[cluster[-1]], by[i] - by[cluster[-1]]) > gap_m:
            objects.append(cluster)
            cluster = []
        cluster.append(i)
    if cluster:
        objects.append(cluster)
    # The scan is a ring: the last and first clusters meet at +-pi, which the
    # rotated mount puts straight ahead of the robot.
    if len(objects) > 1:
        first, last = objects[0][0], objects[-1][-1]
        if math.hypot(bx[first] - bx[last], by[first] - by[last]) <= gap_m:
            objects[0] = objects.pop() + objects[0]
    out = [(float(np.mean(bx[c_])), float(np.mean(by[c_]))) for c_ in objects if len(c_) >= min_points]
    return out[:MAX_OBJECTS]
