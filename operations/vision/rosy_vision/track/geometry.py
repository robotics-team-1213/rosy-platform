"""Homography helpers for overhead tracking (numpy only, no OpenCV)."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

#: A camera solved from a homography outside this height is not trusted (no parallax step).
MIN_CAMERA_HEIGHT_M = 0.3
MAX_CAMERA_HEIGHT_M = 10.0


def as_matrix(values) -> np.ndarray:
    matrix = np.asarray(values, dtype=float).reshape(3, 3)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("homography must be finite")
    return matrix


def normalized(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=float)
    return matrix / matrix[2, 2] if abs(matrix[2, 2]) > 1e-12 else matrix


def apply(matrix, points) -> np.ndarray:
    """Map (N, 2) points through a 3x3 homography.

    A point on the horizon (|w| ~ 0) or behind the camera (w of the opposite sign to the
    homography's own sign, taken from its [2, 2] element) comes back as (nan, nan).
    """
    matrix = np.asarray(matrix, dtype=float)
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    out = np.c_[pts, np.ones(len(pts))] @ matrix.T
    w = out[:, 2]
    bad = np.abs(w) < 1e-12
    if abs(matrix[2, 2]) > 1e-12:
        bad |= w * matrix[2, 2] < 0
    result = np.full((len(pts), 2), np.nan)
    result[~bad] = out[~bad, :2] / w[~bad, None]
    return result


def scaled(image_to_map, sx: float, sy: float) -> np.ndarray:
    """Image-to-map for an image resized by (sx, sy) from the size the matrix is for."""
    return np.asarray(image_to_map, dtype=float) @ np.diag([1.0 / sx, 1.0 / sy, 1.0])


def centre_scale(kx: float, ky: float) -> np.ndarray:
    """Pixel of an image to the pixel of one ``kx`` x ``ky`` times its size, by pixel centres.

    Pixel index u covers [u, u + 1); its centre u + 0.5 lands at k (u + 0.5) in the other
    image, which is pixel index k (u + 0.5) - 0.5 there. Right-multiply an image-to-map
    homography of the other image by this to use it on this image.
    """
    return np.array([[kx, 0.0, 0.5 * kx - 0.5], [0.0, ky, 0.5 * ky - 0.5], [0.0, 0.0, 1.0]])


def camera_from_homography(image_to_map, image_size: Sequence[int],
                           hfov_deg: float | None) -> tuple[float, float, float] | None:
    """Camera nadir (x, y) and height above the floor in map metres, or None.

    Lens model and its limits: pinhole camera, principal point at the image centre, square
    pixels, and ``hfov_deg`` is the lens FOV across the LONG image side. Lens distortion is
    ignored and a cropped or re-scaled stream that no longer matches the lens FOV biases the
    focal length, hence the camera height. A solution whose rotation is not close to
    orthonormal (r1 and r2 differing in length or not perpendicular by more than 10 %) means
    the lens model does not fit this homography, and None is returned.
    """
    if hfov_deg is None or not 0.0 < hfov_deg < 180.0:
        return None
    width, height = float(image_size[0]), float(image_size[1])
    focal = (max(width, height) / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    k = np.array([[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]])
    try:
        i2m = as_matrix(image_to_map)
        b = np.linalg.solve(k, np.linalg.inv(i2m))  # K^-1 (map -> image) = s [r1 r2 t]
    except (ValueError, np.linalg.LinAlgError):
        return None
    norm = (np.linalg.norm(b[:, 0]) + np.linalg.norm(b[:, 1])) / 2.0
    if not math.isfinite(norm) or norm < 1e-12:
        return None
    n1, n2 = float(np.linalg.norm(b[:, 0])), float(np.linalg.norm(b[:, 1]))
    if n1 < 1e-12 or n2 < 1e-12:
        return None
    if abs(n1 / n2 - 1.0) > 0.1 or abs(float(b[:, 0] @ b[:, 1]) / (n1 * n2)) > 0.1:
        return None
    r1, r2, t = b[:, 0] / norm, b[:, 1] / norm, b[:, 2] / norm
    centre = apply(i2m, [[width / 2.0, height / 2.0]])[0]
    if (r1 * centre[0] + r2 * centre[1] + t)[2] < 0:  # the floor point in view is in front
        r1, r2, t = -r1, -r2, -t
    u, _, vt = np.linalg.svd(np.column_stack([r1, r2]), full_matrices=False)
    r1, r2 = (u @ vt).T
    rotation = np.column_stack([r1, r2, np.cross(r1, r2)])
    camera = -rotation.T @ t
    camera_height = abs(float(camera[2]))
    if not MIN_CAMERA_HEIGHT_M <= camera_height <= MAX_CAMERA_HEIGHT_M:
        return None
    return float(camera[0]), float(camera[1]), camera_height


def parallax_correct(point: Sequence[float], camera: Sequence[float],
                     height_m: float) -> tuple[float, float]:
    """The floor point under an object top seen at ``point``: pulled toward the camera nadir."""
    cx, cy, camera_height = camera
    if not 0.0 <= height_m < camera_height:
        raise ValueError("object height must be non-negative and below the camera")
    keep = (camera_height - height_m) / camera_height
    return cx + (point[0] - cx) * keep, cy + (point[1] - cy) * keep
