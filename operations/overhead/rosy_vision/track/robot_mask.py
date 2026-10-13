"""D-600: learn the background with robots left on the mat.

Fleet names the floor regions robots stand on (``occupied`` in the tracking config: map circles
from marker sightings, the map pose and trusted robot poses). A learn never learns those pixels:
in the learning frames they get the previous background where it was not dark (robots are dark,
D-547), else floor inpainted from around them. Inpainted pixels are unknown floor. An unknown
pixel that no region covers and that is not near a dark live pixel for FILL_CONFIRM_FRAMES frames
in a row is filled from the live frame (``detector._heal``), at most every FILL_EVERY_S.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from rosy_vision.track import geometry

#: Region outline points; the hull of the floor and the parallax-shifted top circle is drawn.
CIRCLE_POINTS = 16
#: Regions grow by this many work pixels (MOG2 edge, shadow), like the D-547 ghost zone.
REGION_MARGIN_PX = 4
#: Learning-frame noise kept over the filled floor, clipped so a robot that moved during the
#: learn does not smear into it.
NOISE_CLIP = 12.0
INPAINT_RADIUS_PX = 5
#: An unknown pixel is filled after this many frames in a row free and not near a dark pixel ...
FILL_CONFIRM_FRAMES = 3
#: ... (dark: below the background's dark level, grown by this radius: a robot's lighter top
#: parts, marker and LiDAR, sit within it) ...
FILL_DARK_RADIUS_PX = 12
#: ... and the model is rebuilt for fills at most this often (a rebuild is ~0.3 s).
FILL_EVERY_S = 5.0
MAX_UNKNOWN_REPORTED = 16
_GROW = np.ones((2 * REGION_MARGIN_PX + 1,) * 2, np.uint8)
_DARK_GROW = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * FILL_DARK_RADIUS_PX + 1,) * 2)


def parse_regions(raw) -> tuple[tuple[float, float, float], ...]:
    """Fleet's ``occupied`` rows as (x, y, radius_m); malformed rows are dropped."""
    out = []
    for row in raw if isinstance(raw, list) else ():
        if not isinstance(row, dict):
            continue
        values = (row.get("x"), row.get("y"), row.get("radius_m"))
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values) \
                and 0.0 < values[2] <= 1.0:
            out.append(tuple(float(v) for v in values))
    return tuple(out[:32])


def region_mask(regions, work_to_map, shape, camera, robot_height_m: float) -> np.ndarray:
    """Work pixels a robot standing in any region can cover (floor to top, plus a margin)."""
    out = np.zeros(shape, np.uint8)
    if not regions:
        return out.astype(bool)
    map_to_work = np.linalg.inv(work_to_map)
    angles = np.linspace(0.0, 2.0 * math.pi, CIRCLE_POINTS, endpoint=False)
    ring = np.c_[np.cos(angles), np.sin(angles)]
    for x, y, radius in regions:
        floor = np.array([x, y]) + radius * ring
        points = [floor]
        if camera is not None:  # the top is seen farther from the nadir than the floor point
            nadir, keep = np.array(camera[:2]), (camera[2] - robot_height_m) / camera[2]
            points.append(nadir + (floor - nadir) / keep)
        pixels = geometry.apply(map_to_work, np.vstack(points))
        pixels = pixels[np.all(np.isfinite(pixels), axis=1)]
        if len(pixels) >= 3:
            hull = cv2.convexHull(np.round(pixels).astype(np.int32))
            cv2.fillConvexPoly(out, hull, 1)
    return cv2.dilate(out, _GROW) > 0


def _parts(where: np.ndarray, pad: int = 3 * REGION_MARGIN_PX):
    """(box, part) per connected component of ``where``, box padded for inpainting."""
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(where.astype(np.uint8), connectivity=8)
    height, width = where.shape
    for label in range(1, count):
        left, top, w, h = (int(stats[label, i]) for i in range(4))
        y0, x0 = max(0, top - pad), max(0, left - pad)
        y1, x1 = min(height, top + h + pad), min(width, left + w + pad)
        yield (y0, y1, x0, x1), where[y0:y1, x0:x1]


def mask_frames(frames, where: np.ndarray, previous) -> np.ndarray:
    """Replace ``where`` in every learning frame; return the unknown-floor mask.

    ``previous`` is (background image, dark map) of the last learn of this size, or None."""
    unknown = np.zeros(where.shape, bool)
    for (y0, y1, x0, x1), part in _parts(where):
        stack = np.stack([frame[y0:y1, x0:x1] for frame in frames]).astype(np.float32)
        mean = stack.mean(axis=0)
        known = np.zeros(part.shape, bool)
        target = mean.copy()
        if previous is not None and previous[0].shape[:2] == where.shape:
            known = part & ~previous[1][y0:y1, x0:x1]
            target[known] = previous[0][y0:y1, x0:x1][known]
        guess = part & ~known
        if guess.any():
            painted = cv2.inpaint(np.clip(mean, 0, 255).astype(np.uint8), guess.astype(np.uint8),
                                  INPAINT_RADIUS_PX, cv2.INPAINT_TELEA)
            target[guess] = painted[guess]
            unknown[y0:y1, x0:x1] |= guess
        noise = np.clip(stack - mean, -NOISE_CLIP, NOISE_CLIP)
        noisy = np.clip(target + noise, 0, 255).astype(np.uint8)
        for frame, patch in zip(frames, noisy):
            frame[y0:y1, x0:x1][part] = patch[part]
    return unknown


def fill_ready(image: np.ndarray, unknown: np.ndarray, occupied: np.ndarray, dark_level: float,
               streak: np.ndarray) -> np.ndarray:
    """Advance ``streak`` (uint8, in place) and return the unknown pixels ready to fill."""
    dark = cv2.dilate((image.max(axis=2) < dark_level).astype(np.uint8), _DARK_GROW) > 0
    free = unknown & ~occupied & ~dark
    np.copyto(streak, np.where(free, np.minimum(streak, 254) + 1, 0).astype(np.uint8))
    return free & (streak >= FILL_CONFIRM_FRAMES)


def heal_parts(where: np.ndarray) -> list:
    """``where`` as the (box, part) list ``detector._heal`` takes (unpadded boxes)."""
    return list(_parts(where, pad=0))


def unknown_circles(unknown: np.ndarray, work_to_map) -> tuple[tuple[float, float, float], ...]:
    """Each unknown-floor component as a map circle (centre, radius of equal floor area)."""
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(unknown.astype(np.uint8), connectivity=8)
    out = []
    for label in np.argsort(-stats[1:, cv2.CC_STAT_AREA])[:MAX_UNKNOWN_REPORTED] + 1:
        u, v = centroids[label]
        points = geometry.apply(work_to_map, [[u, v], [u + 1.0, v], [u, v + 1.0]])
        if not np.all(np.isfinite(points)):
            continue
        (ax, ay), (bx, by) = points[1] - points[0], points[2] - points[0]
        area = float(stats[label, cv2.CC_STAT_AREA]) * abs(float(ax * by - ay * bx))
        out.append((float(points[0][0]), float(points[0][1]), math.sqrt(area / math.pi)))
    return tuple(out) if count > 1 else ()
