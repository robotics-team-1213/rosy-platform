"""Subject: the floor reference square (red ring, blue core) seen by the front camera (D-395 rev. 1 §6).

Fixed output contract, swappable backend: every detector returns
`SquareObservation(bearing_rad, range_m, confidence)` in base_link (bearing
left-positive from the nose, range from base_link, confidence 0..1), best first.
`HsvSquareDetector` is the rule-based backend; a learned `reference_square`
class (proposed for the D-379 label spec) can replace it behind the same
`detect(bgr, ground)` call.

Range comes from the ground plane at the blue core's centroid (the square is
flat on the floor, so the centroid is a floor point). Without a ground plane
there is no honest range or bearing, so nothing is returned; beyond the plane's
trusted range the bearing is kept and the range is None.
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
        found = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if area < self.min_core_px:
                continue
            gx, gy = max(1, round(w * RING_GROW)), max(1, round(h * RING_GROW))
            x0, y0 = max(0, x - gx), max(0, y - gy)
            x1, y1 = min(width, x + w + gx), min(height, y + h + gy)
            ring = np.ones((y1 - y0, x1 - x0), dtype=bool)
            ring[y - y0:y - y0 + h, x - x0:x - x0 + w] = False
            ratio = float(np.mean(red[y0:y1, x0:x1][ring] > 0)) if ring.any() else 0.
            if ratio < self.min_ring:
                continue
            found.append(self._observe(ground, *centroids[i], min(1., ratio / RING_FULL)))
        return sorted((f for f in found if f is not None), key=lambda f: -f.confidence)

    def _observe(self, ground, column, row, confidence):
        ahead = ground.distance(row)
        if ahead is None:
            bearing = -math.atan2(column - ground.principal_x, ground.focal_px)
            return SquareObservation(bearing, None, round(confidence, 3))
        forward = ahead + self.camera_x_offset_m
        left = -ground.lateral(column, row)
        return SquareObservation(math.atan2(left, forward), math.hypot(forward, left), round(confidence, 3))
