"""Pinky shape cue for the ceiling camera (panel 2026-11-18, stage 1).

The background model forgets a robot that stands still long enough (or never sees it when it was
parked while learning). The robot itself is easy to see: two teal wheels with a dark body between
them and a round dark LiDAR on top. This finds that shape in one frame, without any background:

1. Floor brightness is the median of max(B, G, R) over the track mask, so every threshold is a ratio
   of it and follows exposure changes.
2. Teal wheel blobs (hue band, saturation, brightness >= TEAL_V_RATIO x floor) are paired when their
   distance is in the pair window. The pair distance is the robot's local scale (the wheel track is
   WHEEL_TRACK_M on the floor), so body radius and core size follow perspective.
3. A pair is a robot when the axle between the wheels is dark (the chassis sits between them) and a
   thick dark core (distance-transform peak: the LiDAR dome and deck) lies near the axle.
4. A wheel belongs to at most one robot: the most robots, then the best total score, wins. Touching
   robots therefore come out as two pairs, not one merged blob.
5. The position is the centroid of the dark body pixels within one body radius of the axle that are
   closer to this axle than to any other found axle (the top silhouette, as background_blob uses).
6. Heading (mod 180, normal to the axle) is given only when the robot's dark blob holds no other robot.

Coordinates are pixels of the image passed in (background_blob passes its WORK_LONG_SIDE copy).
Pixel sizes below are for that 640-wide copy of the 1280 x 720 ceiling frame.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import cv2
import numpy as np

#: Pinky wheel centre distance (URDF wheel joints at +-0.04055 m).
WHEEL_TRACK_M = 0.0811
#: Teal wheel colour: OpenCV hue band, minimum saturation, minimum brightness over the floor.
TEAL_HUE = (92, 107)
TEAL_MIN_S = 70
TEAL_V_RATIO = 0.45
#: Wheel blob area window in work pixels (a wheel seen from above is about 16 x 5 at 640 wide).
WHEEL_AREA_PX = (3, 160)
#: A wheel blob this elongated (long/short axis) shows its rolling direction, which must be
#: across the axle: |cos(rolling axis, axle)| at most ROLL_ALONG_AXLE_MAX (63 degrees off).
WHEEL_ELONGATION = 1.4
ROLL_ALONG_AXLE_MAX = 0.45
#: Smaller wheel blobs (a wheel mostly hidden) are too few pixels to show a direction.
WHEEL_AXIS_MIN_PX = 12
#: Wheel-pair distance window in work pixels (far end of the mat about 15, near end about 30).
PAIR_PX = (12.0, 36.0)
#: Body pixels are darker than this share of the floor (as background_blob's BAKED_DARK_RATIO).
DARK_RATIO = 0.6
#: The axle segment between the wheels must be at least this dark: 1 - median / floor.
AXLE_DARK_MIN = 0.35
#: Body radius and minimum core half-thickness, as shares of the wheel-pair distance.
BODY_RADIUS = 1.0
CORE_MIN = 0.17
#: The core must lie within this share of the pair distance from the axle midpoint.
CORE_REACH = 0.6
#: Two robots' axle midpoints are at least this many pair distances apart (bodies cannot overlap).
MIN_GAP = 1.0
#: Mean-shift steps from the axle midpoint to the body centroid.
CENTRE_STEPS = 2


@dataclass(frozen=True)
class ShapeDetection:
    u: float                        # work pixels, body centre
    v: float
    heading_mod180: float | None    # image degrees of the travel axis, 0..180; None unless alone
    score: float                    # 0..1
    radius_px: float                # body radius used (work pixels)


def find_robots(work_bgr: np.ndarray, track_mask: np.ndarray) -> list[ShapeDetection]:
    """Robots whose wheels lie in track_mask (uint8, nonzero = track) of work_bgr."""
    track = track_mask > 0
    if not track.any():
        return []
    hsv = cv2.cvtColor(work_bgr, cv2.COLOR_BGR2HSV)
    bright = hsv[..., 2]  # V = max(B, G, R), the darkness measure background_blob uses
    floor = float(np.median(bright[track]))
    if floor <= 0:
        return []
    teal = cv2.inRange(hsv, (TEAL_HUE[0], TEAL_MIN_S, min(255, math.ceil(TEAL_V_RATIO * floor))),
                       (TEAL_HUE[1], 255, 255))
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(teal, connectivity=8)
    wheels = [(np.asarray(centroids[i], float), _rolling_axis(labels, stats[i], i)) for i in range(1, count)
              if WHEEL_AREA_PX[0] <= stats[i, cv2.CC_STAT_AREA] <= WHEEL_AREA_PX[1]
              and track[int(round(centroids[i][1])), int(round(centroids[i][0]))]]
    dark = (bright < DARK_RATIO * floor).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    depth = cv2.distanceTransform(dark, cv2.DIST_L2, 3)
    pairs = []
    for i, j in itertools.combinations(range(len(wheels)), 2):
        pair = _pair(wheels[i], wheels[j], bright, depth, floor)
        if pair is not None:
            pairs.append((i, j, *pair))
    return _measure(_assign(pairs), dark, teal > 0)


def _rolling_axis(labels, stat, label):
    """Unit long axis of a clearly elongated wheel blob (a wheel is long along its rolling
    direction, across the axle); None when the blob is too round or small to tell."""
    x, y, w, h = (int(v) for v in stat[:4])
    if stat[cv2.CC_STAT_AREA] < WHEEL_AXIS_MIN_PX:
        return None
    m = cv2.moments((labels[y:y + h, x:x + w] == label).astype(np.uint8), binaryImage=True)
    a, b, c = m["mu20"], m["mu11"], m["mu02"]
    spread = math.hypot(a - c, 2 * b)  # eigenvalues of the covariance: (a + c +- spread) / 2
    if a + c <= 0 or a + c + spread < WHEEL_ELONGATION ** 2 * (a + c - spread):
        return None
    angle = 0.5 * math.atan2(2 * b, a - c)
    return np.array([math.cos(angle), math.sin(angle)])


def _disc(centre, radius, shape):
    """Window origin and the in-disc mask of the window around centre."""
    height, width = shape
    x0, x1 = max(0, int(centre[0] - radius)), min(width, int(centre[0] + radius) + 1)
    y0, y1 = max(0, int(centre[1] - radius)), min(height, int(centre[1] + radius) + 1)
    vs, us = np.mgrid[y0:y1, x0:x1]
    return (y0, y1, x0, x1), us, vs, np.hypot(us - centre[0], vs - centre[1]) <= radius


def _pair(wheel_a, wheel_b, bright, depth, floor):
    """(score, midpoint, axle unit vector, distance) when the two blobs look like one robot's wheels."""
    (a, roll_a), (b, roll_b) = wheel_a, wheel_b
    dist = float(np.hypot(*(b - a)))
    if not PAIR_PX[0] <= dist <= PAIR_PX[1]:
        return None
    axle = (b - a) / dist
    if any(roll is not None and abs(float(roll @ axle)) > ROLL_ALONG_AXLE_MAX for roll in (roll_a, roll_b)):
        return None  # a wheel lying along the axle is not this pair's wheel
    height, width = bright.shape
    # inner 60 % of the axle: the chassis, not the wheels themselves
    samples = [a + (b - a) * t for t in np.linspace(0.2, 0.8, 7)]
    values = [bright[int(round(p[1])), int(round(p[0]))] for p in samples
              if 0 <= p[0] < width and 0 <= p[1] < height]
    if len(values) < 5:
        return None
    axle_dark = 1.0 - float(np.median(values)) / floor
    if axle_dark < AXLE_DARK_MIN:
        return None
    mid = (a + b) / 2.0
    (y0, y1, x0, x1), _us, _vs, near = _disc(mid, CORE_REACH * dist, bright.shape)
    core = float(depth[y0:y1, x0:x1][near].max(initial=0.0))
    if core < CORE_MIN * dist:
        return None
    score = 0.5 * min(1.0, axle_dark / 0.7) + 0.5 * min(1.0, core / (0.4 * dist))
    return score, mid, axle, dist


def _assign(pairs):
    """Each wheel in at most one robot and no two bodies overlapping: the most robots, then the
    highest total score."""
    pairs = sorted(pairs, key=lambda p: -p[2])[:24]  # shortcut: exhaustive search; cap 24 pairs, raise if more robots
    best = ([], 0.0)

    def walk(start, used, chosen, total):
        nonlocal best
        if (len(chosen), total) > (len(best[0]), best[1]):
            best = (list(chosen), total)
        for k in range(start, len(pairs)):
            i, j, _score, mid, _axle, dist = pairs[k]
            if i not in used and j not in used and all(
                    np.hypot(*(mid - p[3])) >= MIN_GAP * (dist + p[5]) / 2 for p in chosen):
                chosen.append(pairs[k])
                walk(k + 1, used | {i, j}, chosen, total + pairs[k][2])
                chosen.pop()

    walk(0, frozenset(), [], 0.0)
    return best[0]


def _measure(chosen, dark, teal) -> list[ShapeDetection]:
    body = dark.astype(bool) & ~teal
    mids = [p[3] for p in chosen]
    _count, blobs = cv2.connectedComponents(dark, connectivity=8)
    found = []
    for k, (_i, _j, score, mid, axis, dist) in enumerate(chosen):
        radius = BODY_RADIUS * dist
        u, v = float(mid[0]), float(mid[1])
        for _step in range(CENTRE_STEPS):  # mean shift from the axle onto the body
            (y0, y1, x0, x1), us, vs, inside = _disc((u, v), radius, dark.shape)
            inside &= body[y0:y1, x0:x1]
            own = np.hypot(us - mid[0], vs - mid[1])
            for other, centre in enumerate(mids):  # the nearest axle owns a pixel (touching robots)
                if other != k:
                    inside &= own <= np.hypot(us - centre[0], vs - centre[1])
            if np.count_nonzero(inside) < 4:
                break
            u, v = float(us[inside].mean()), float(vs[inside].mean())
        owner = set(np.unique(blobs[y0:y1, x0:x1][inside]).tolist()) - {0}
        found.append((u, v, score, radius, axis, owner))
    out = []
    for k, (u, v, score, radius, axis, owner) in enumerate(found):
        alone = not any(owner & other[5] for o, other in enumerate(found) if o != k)
        heading = math.degrees(math.atan2(axis[0], -axis[1])) % 180.0 if alone else None
        out.append(ShapeDetection(u, v, heading, round(float(score), 3), float(radius)))
    return out
