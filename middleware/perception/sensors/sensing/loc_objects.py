"""Subject: lidar returns the map does not explain, grouped into objects (D-395 §4.2).

Another robot is the commonest unmapped object on the track. The Fleet arbiter
projects each object through every pose hypothesis and asks which one puts it on
a robot that is already LOCALIZED. Returns are judged at one candidate pose: on
a symmetric map the mirror explains exactly the same returns, so the list does
not depend on which hypothesis is used. Output is base_link (forward, left), m.

With the robot `radius` (body.URDF_RADIUS unless calibrated; peers are the
same Pinky) three things happen that the 2026-10-02 audit measured as needed:
beams shorter than radius + SELF_MARGIN_M are this robot's own body and are
dropped before clustering (S2 q1: a phantom 0.158 m out passed the old
centroid filter); a cluster wider than SPLIT_DIAMETERS robot diameters is cut
at its largest internal gap (two peers under 6 cm apart always merged); and
each centroid is pushed back along the lidar ray to the disc centre (peers
matched with a 3.7-7 cm bias toward the observer).
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
#: Beams this much past the body radius are still this robot (cables, wheel guards).
SELF_MARGIN_M = .03
#: One Pinky never spans more than this many diameters; a wider cluster is two.
SPLIT_DIAMETERS = 1.6
#: The returns from a disc are its near half; their centroid sits 2R/pi in front
#: of the centre (pushing by R overshoots by ~R/3, loc_world 1.5 cm vs 0.7 cm).
ARC_CENTROID = 2 / math.pi


def unmapped_objects(field, sensor_pose, ranges, angles, mount, gap_m=GAP_M, min_points=MIN_POINTS,
                     radius=None):
    """Centroids of unexplained return clusters as base_link (x, y) tuples, at most MAX_OBJECTS.

    `radius`: the robot body radius; None skips the self, split and centre steps."""
    ranges, angles = valid_beams(ranges, angles)
    if radius is not None:
        keep = ranges >= radius + SELF_MARGIN_M
        ranges, angles = ranges[keep], angles[keep]
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
    if radius is not None:
        objects = [part for c_ in objects for part in _split(c_, bx, by, SPLIT_DIAMETERS * 2 * radius)]
    out = []
    for c_ in objects:
        if len(c_) < min_points:
            continue
        x, y = float(np.mean(bx[c_])), float(np.mean(by[c_]))
        if radius is not None:
            dx, dy = x - mount.x, y - mount.y
            scale = 1 + radius * ARC_CENTROID / max(math.hypot(dx, dy), 1e-9)
            x, y = mount.x + dx * scale, mount.y + dy * scale
        out.append((x, y))
    return out[:MAX_OBJECTS]


def _split(cluster, bx, by, max_width):
    """Cut a cluster wider than max_width (end to end) at its largest gap, recursively."""
    out, todo = [], [cluster]
    while todo:
        c_ = todo.pop()
        if len(c_) < 2 or math.hypot(bx[c_[-1]] - bx[c_[0]], by[c_[-1]] - by[c_[0]]) <= max_width:
            out.append(c_)
            continue
        gaps = np.hypot(np.diff(bx[c_]), np.diff(by[c_]))
        cut = int(np.argmax(gaps)) + 1
        todo += [c_[cut:], c_[:cut]]
    return out
