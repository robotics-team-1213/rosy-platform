"""Pure helpers for robot-anchored drivable drafts (D-465 addendum 2026-10-07).

SAM and VLM points find "carpet", not "road". The robot's own position is the
trusted anchor: drivable is the carpet component the robot stands on, bounded by
white lines (D-475 §8). Carpet beyond a line is reported as unsure for a person.
No I/O, no models.
"""
import re

import cv2
import numpy as np

FLOOR, LANE, WALL, DRIVABLE, IGNORE = 0, 1, 2, 3, 255
BRIGHT_DELTA = 50   # luminance above the lower-half floor median counted as tape/wall
_POINT = re.compile(r'"point_2d"\s*:\s*\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]')


def parse_points(raw, width, height, cap=16, cell=6):
    """Qwen3-VL point_2d (0-1000 relative) to pixel [x, y]; tolerant of truncated JSON."""
    seen, out = set(), []
    for x, y in _POINT.findall(raw):
        px = min(width - 1, round(float(x) / 1000 * width))
        py = min(height - 1, round(float(y) / 1000 * height))
        if (px // cell, py // cell) not in seen:
            seen.add((px // cell, py // cell))
            out.append([px, py])
    return out[:cap]


def luminance(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def bright_mask(lum):
    return lum >= np.median(lum[lum.shape[0] // 2:]) + BRIGHT_DELTA


def yellow_mask(rgb):
    return (rgb[..., 0] > 150) & (rgb[..., 1] > 110) & (rgb[..., 2] < 90)


def footprint_band(height, width):
    """Rows/cols just in front of the robot (bottom centre of a forward camera)."""
    return slice(height * 5 // 6, height), slice(width // 4, width * 3 // 4)


def footprint_seed(bright, lane):
    """Carpet pixel nearest the bottom centre: the road the robot stands on. None if all tape."""
    rows, cols = footprint_band(*bright.shape)
    ys, xs = np.nonzero(~bright[rows, cols] & ~lane[rows, cols])
    if not len(xs):
        return None
    h, w = bright.shape
    ys, xs = ys + rows.start, xs + cols.start
    j = np.argmin((xs - w // 2) ** 2 + 4 * (ys - (h - 5)) ** 2)
    return [int(xs[j]), int(ys[j])]


def gate_road_points(points, bright, lane):
    """Keep VLM road points that sit on dark, non-lane pixels."""
    return [[x, y] for x, y in points if not bright[y, x] and not lane[y, x]]


def close_mask(mask, radius=2):
    k = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
    return cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0


def robot_road(carpet, lane):
    """(road, unsure): the carpet component with the largest footprint overlap,
    not crossing a 1 px dilated line; other carpet is unsure (maybe another road, maybe off-road)."""
    free = carpet & ~cv2.dilate(lane.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    _, lab = cv2.connectedComponents(free.astype(np.uint8), connectivity=4)
    band = lab[footprint_band(*lab.shape)]
    ids, counts = np.unique(band[band > 0], return_counts=True)
    road = lab == ids[counts.argmax()] if len(ids) else np.zeros_like(carpet)
    return road, carpet & ~road & ~lane


def compose(base, road, yellow):
    """Drivable on top of a base class map; base lane/wall and yellow ramps are kept."""
    out = base.copy()
    out[road & ~np.isin(base, (LANE, WALL)) & ~yellow] = DRIVABLE
    return out
