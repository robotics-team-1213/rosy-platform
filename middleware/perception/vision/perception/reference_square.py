"""Subject: the floor reference square (red ring, blue core) seen by the front camera (D-395 rev. 1 §6).

Fixed output contract, swappable backend: every detector returns
`SquareObservation(bearing_rad, range_m, confidence)` in base_link (bearing
left-positive from the nose, range from base_link, confidence 0..1), best first.
`HsvSquareDetector` is the rule-based backend; a learned `reference_square`
class (proposed for the D-379 label spec) can replace it behind the same
`detect(bgr, ground)` call.

Range comes from the ground plane at the blue core's centroid (the square is
flat on the floor, so the centroid is a floor point). Without a ground plane
there is no honest range or bearing, so nothing is returned. A core whose
centroid is at or above the horizon is not on the floor at all (blue wall tape
behind a red cable, audit 2026-10-02: all 20 false detections in 506 real
frames), so it is dropped. Below the horizon but beyond the plane's trusted
range the bearing is kept and the range is None; Fleet's `square_cue` does not
count such a bearing-only sighting as evidence (D-395 rev. 11).

One square gives one detection: a glare or tape stripe through the core splits
it into two blue blobs, so a weaker blob whose centroid falls inside a stronger
one's ring box, or lands within `MERGE_M` of it on the floor, is the same square.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import cv2
import numpy as np

#: OpenCV HSV (H 0..180). Blue core and red ring; S/V floors reject grey carpet
#: and white paint, which have almost no saturation.
BLUE = ((100, 120, 50), (130, 255, 255))
RED_LOW = ((0, 120, 70), (10, 255, 255))
RED_HIGH = ((170, 120, 70), (180, 255, 255))
#: The ring is 0.03 m wide around a 0.07-0.08 m core, so a box grown by 60% of
#: the core on each side holds the whole ring. Seen by the near-horizontal
#: camera the ring rows are foreshortened and red fills ~0.35-0.55 of that box
#: (synthetic 0.3-0.6 m); 0.35 counts as full confidence, under 0.2 is no ring.
RING_GROW = .6
RING_FULL = .35
#: Two real squares are at least one outer side (0.13 m) apart centre to centre,
#: so floor points closer than this belong to one square.
MERGE_M = .1


@dataclass(frozen=True)
class SquareObservation:
    bearing_rad: float
    range_m: float | None
    confidence: float


@runtime_checkable
class SquareDetector(Protocol):
    def detect(self, bgr: np.ndarray, ground) -> list[SquareObservation]: ...


class HsvSquareDetector:
    def __init__(self, camera_x_offset_m, min_core_px=30, min_ring=.2):
        self.camera_x_offset_m = float(camera_x_offset_m)
        self.min_core_px, self.min_ring = int(min_core_px), float(min_ring)

    def detect(self, bgr, ground):
        if ground is None or bgr is None or bgr.ndim != 3:
            return []
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, *BLUE)
        red = cv2.inRange(hsv, *RED_LOW) | cv2.inRange(hsv, *RED_HIGH)
        count, _, stats, centroids = cv2.connectedComponentsWithStats(blue)
        height, width = blue.shape
        horizon = ground.horizon_row
        found = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if area < self.min_core_px or centroids[i][1] <= horizon:
                continue
            gx, gy = max(1, round(w * RING_GROW)), max(1, round(h * RING_GROW))
            x0, y0 = max(0, x - gx), max(0, y - gy)
            x1, y1 = min(width, x + w + gx), min(height, y + h + gy)
            ring = np.ones((y1 - y0, x1 - x0), dtype=bool)
            ring[y - y0:y - y0 + h, x - x0:x - x0 + w] = False
            ratio = float(np.mean(red[y0:y1, x0:x1][ring] > 0)) if ring.any() else 0.
            if ratio < self.min_ring:
                continue
            obs = self._observe(ground, *centroids[i], min(1., ratio / RING_FULL))
            if obs is not None:
                found.append((obs, int(area), (x0, y0, x1, y1), tuple(centroids[i])))
        return _suppress(found)

    def _observe(self, ground, column, row, confidence):
        ahead = ground.distance(row)
        if ahead is None:
            bearing = -math.atan2(column - ground.principal_x, ground.focal_px)
            return SquareObservation(bearing, None, round(confidence, 3))
        forward = ahead + self.camera_x_offset_m
        left = -ground.lateral(column, row)
        return SquareObservation(math.atan2(left, forward), math.hypot(forward, left), round(confidence, 3))


def _suppress(found):
    """Best first (confidence, then core area); drop any later blob that is the same square."""
    kept = []
    for obs, area, box, centre in sorted(found, key=lambda f: (-f[0].confidence, -f[1])):
        if not any(_same(obs, centre, k_obs, k_box) for k_obs, _, k_box, _ in kept):
            kept.append((obs, area, box, centre))
    return [k[0] for k in kept]


def _same(obs, centre, k_obs, k_box):
    x0, y0, x1, y1 = k_box
    if x0 <= centre[0] < x1 and y0 <= centre[1] < y1:
        return True
    if obs.range_m is None or k_obs.range_m is None:
        return False
    return math.dist(_floor(obs), _floor(k_obs)) < MERGE_M


def _floor(obs):
    return obs.range_m * math.cos(obs.bearing_rad), obs.range_m * math.sin(obs.bearing_rad)
