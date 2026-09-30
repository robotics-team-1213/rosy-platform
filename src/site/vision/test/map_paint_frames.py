"""Synthetic camera frames rendered from the site map paint, shared by the D-375 tests."""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

STL = (Path(__file__).resolve().parents[4] / "src" / "runtime" / "sensing" / "map"
       / "map_v2_fleet" / "meshes" / "road_lines.stl")


def similarity(scale: float, rotation_deg: float, centre_px, mirror: bool = False) -> np.ndarray:
    """Map metres -> image px for a camera looking straight down (image y down)."""
    c, s = math.cos(math.radians(rotation_deg)), math.sin(math.radians(rotation_deg))
    flip = -1.0 if mirror else 1.0
    linear = scale * np.array([[c, flip * s], [-s, flip * c]]) @ np.diag([1.0, -1.0])
    return np.array([[*linear[0], centre_px[0]], [*linear[1], centre_px[1]], [0.0, 0.0, 1.0]])


def tilt(width: int, height: int, degrees: float, roll: float = 0.0) -> np.ndarray:
    """Image-plane homography of a camera pitched about the image x axis (and rolled
    about the y axis). Apply it to a straight-down view centred in the frame; the
    result is re-centred so the track stays in view, as an installer would aim it."""
    focal = 1.2 * width
    k = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1.0]])
    a, b = math.radians(degrees), math.radians(roll)
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    h = k @ rx @ ry @ np.linalg.inv(k)
    centre = h @ np.array([width / 2, height / 2, 1.0])
    shift = np.array([[1, 0, width / 2 - centre[0] / centre[2]],
                      [0, 1, height / 2 - centre[1] / centre[2]], [0, 0, 1.0]])
    return shift @ h


def render(paint, map_to_image: np.ndarray, size=(1280, 720), seed=0, barrel=0.0,
           mask=None) -> np.ndarray:
    """White paint on a noisy grey floor. ``mask`` (raster-shaped, optional) keeps only
    part of the paint, to draw a track that differs from the map."""
    width, height = size
    raster = paint.raster if mask is None else np.where(mask, paint.raster, 0).astype(np.uint8)
    to_raster = np.vstack([paint.raster_matrix, [0.0, 0.0, 1.0]])
    drawn = cv2.warpPerspective(raster, map_to_image @ np.linalg.inv(to_raster), size,
                                flags=cv2.INTER_LINEAR)
    rng = np.random.default_rng(seed)
    grey = rng.normal(105, 12, (height, width)).clip(0, 255)
    image = np.where(drawn > 127, 235.0, grey)
    image = cv2.GaussianBlur(image.astype(np.float32), (0, 0), 1.0)
    frame = cv2.cvtColor(image.clip(0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if barrel:
        ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
        nx, ny = (xs - width / 2) / (width / 2), (ys - height / 2) / (width / 2)
        factor = 1 + barrel * (nx * nx + ny * ny)
        frame = cv2.remap(frame, width / 2 + nx * factor * width / 2,
                          height / 2 + ny * factor * width / 2, cv2.INTER_LINEAR)
    return frame


def raster_region(paint, predicate) -> np.ndarray:
    """Boolean raster mask of the map cells whose centre (x, y in metres) satisfies ``predicate``."""
    height, width = paint.raster.shape
    inverse = np.linalg.inv(np.vstack([paint.raster_matrix, [0.0, 0.0, 1.0]]))
    vs, us = np.mgrid[0:height, 0:width]
    x = inverse[0, 0] * us + inverse[0, 1] * vs + inverse[0, 2]
    y = inverse[1, 0] * us + inverse[1, 1] * vs + inverse[1, 2]
    return predicate(x, y)


def pose_error_m(paint, registration, map_to_image, size=(1280, 720)) -> float:
    """Median floor error (m) of paint points visible in the frame."""
    points = paint.samples.reshape(-1, 1, 2)
    image_pts = cv2.perspectiveTransform(points, map_to_image).reshape(-1, 2)
    inside = ((image_pts[:, 0] >= 0) & (image_pts[:, 0] < size[0])
              & (image_pts[:, 1] >= 0) & (image_pts[:, 1] < size[1]))
    back = cv2.perspectiveTransform(image_pts[inside].reshape(-1, 1, 2),
                                    registration.image_to_map).reshape(-1, 2)
    return float(np.median(np.hypot(*(back - paint.samples[inside]).T)))
