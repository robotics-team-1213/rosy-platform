"""Host-only map_v2_fleet world for the D-395 tests: the checked-in occupancy map
at 2 cm, ray-cast lidar scans with other robots as discs, and the floor paint a
camera would see. Truth lives here; the code under test only sees scans."""
from __future__ import annotations

import functools
import math
from pathlib import Path

import cv2
import numpy as np
import yaml

from control.sensing.loc_candidates import Mount, reference_squares, sensor_from_base
from control.sensing.localization import MapAgreement

BUNDLE = Path(__file__).resolve().parents[1] / "map" / "map_v2_fleet"
#: map_v2_fleet.yaml: 5 mm cells, origin (-1.705, -0.93). 4x max-pooled to 2 cm
#: keeps the walls and makes one global search take seconds, not tens of seconds.
RESOLUTION, ORIGIN, DOWNSAMPLE = .005, (-1.705, -.93), 4
#: Lidar 12 mm ahead and 8 mm right of base_link, scan 0 at the rear (D-397 nominal).
MOUNT = Mount(.012, -.008, math.pi)
BEAMS, MAX_RANGE, PEER_RADIUS = 120, 3.5, .06
SQUARES = reference_squares(yaml.safe_load((BUNDLE / "lane_rules.yaml").read_text(encoding="utf-8")))


@functools.lru_cache(maxsize=1)
def field() -> MapAgreement:
    image = cv2.imread(str(BUNDLE / "maps" / "map_v2_fleet.pgm"), cv2.IMREAD_UNCHANGED)
    p = (255. - image) / 255.             # trinary, negate 0: dark is occupied
    grid = np.where(p > .65, 100, np.where(p < .196, 0, -1)).astype(np.int8)[::-1]
    k = DOWNSAMPLE
    h, w = grid.shape[0] // k * k, grid.shape[1] // k * k
    blocks = grid[:h, :w].reshape(h // k, k, w // k, k)
    pooled = np.where((blocks >= 65).any(axis=(1, 3)), 100,
                      np.where((blocks < 0).any(axis=(1, 3)), -1, 0)).astype(np.int8)
    return MapAgreement(pooled, RESOLUTION * k, ORIGIN)


def mirror(pose):
    """The 180-degree twin every scan on this map also fits."""
    return (-pose[0], -pose[1], math.atan2(math.sin(pose[2] + math.pi), math.cos(pose[2] + math.pi)))


def scan(pose, peers=(), beams=BEAMS):
    """Sensor-frame (ranges, angles) seen from base pose `pose`; NaN means no return.
    `beams`: 640 is the Pinky lidar's full scan (0.5625 degrees apart)."""
    f = field()
    sx, sy, syaw = sensor_from_base(pose, MOUNT)
    angles = np.linspace(-math.pi, math.pi, beams, endpoint=False)
    steps = np.arange(.05, MAX_RANGE, f.resolution / 2)
    heading = syaw + angles
    px = sx + np.cos(heading)[:, None] * steps[None, :]
    py = sy + np.sin(heading)[:, None] * steps[None, :]
    ix = np.floor((px - f.origin[0]) / f.resolution).astype(int)
    iy = np.floor((py - f.origin[1]) / f.resolution).astype(int)
    h, w = f.grid.shape
    inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    hit = ~inside
    hit[inside] = f.grid[iy[inside], ix[inside]] >= 65
    for peer in peers:
        hit |= np.hypot(px - peer[0], py - peer[1]) <= PEER_RADIUS
    first = np.argmax(hit, axis=1)
    ranges = np.where(hit.any(axis=1), steps[first], np.nan)
    return ranges, angles


@functools.lru_cache(maxsize=1)
def _paint_xy():
    from control.sensing.perception.paint_localizer import PaintMap
    paint = PaintMap.from_bundle()
    rows, cols = np.nonzero(paint.paint)
    return paint, np.column_stack((paint.x0 + cols * paint.raster_m, paint.y1 - rows * paint.raster_m))


def paint_map():
    return _paint_xy()[0]


def paint_points(pose, ahead=(.08, .40), half_width=.20, every=7):
    """Robot-frame (forward, left) floor points of paint the front camera would see."""
    _, xy = _paint_xy()
    c, s = math.cos(pose[2]), math.sin(pose[2])
    rel = xy - np.asarray(pose[:2])
    forward, left = rel[:, 0] * c + rel[:, 1] * s, -rel[:, 0] * s + rel[:, 1] * c
    keep = (forward > ahead[0]) & (forward < ahead[1]) & (np.abs(left) < half_width)
    return np.column_stack((forward[keep], left[keep]))[::every]
