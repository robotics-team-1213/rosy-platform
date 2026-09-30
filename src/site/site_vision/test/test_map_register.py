"""Paint-line map registration on synthetic frames rendered from the site map paint."""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from site_vision.map_register import load_map_paint, register_map

STL = (Path(__file__).resolve().parents[4] / "src" / "runtime" / "sensing" / "map"
       / "map_v2_fleet" / "meshes" / "road_lines.stl")


@pytest.fixture(scope="module")
def paint():
    return load_map_paint(STL)


def _similarity(scale: float, rotation_deg: float, centre_px, mirror: bool = False) -> np.ndarray:
    """Map metres -> image px for a camera looking straight down (image y down)."""
    c, s = math.cos(math.radians(rotation_deg)), math.sin(math.radians(rotation_deg))
    flip = -1.0 if mirror else 1.0
    linear = scale * np.array([[c, flip * s], [-s, flip * c]]) @ np.diag([1.0, -1.0])
    return np.array([[*linear[0], centre_px[0]], [*linear[1], centre_px[1]], [0.0, 0.0, 1.0]])


def _tilt(width: int, height: int, degrees: float) -> np.ndarray:
    """Image-plane homography of a camera pitched about the image x axis."""
    focal = 1.2 * width
    k = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1.0]])
    a = math.radians(degrees)
    rot = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    return k @ rot @ np.linalg.inv(k)


def _render(paint, map_to_image: np.ndarray, size=(1280, 720), seed=0, barrel=0.0) -> np.ndarray:
    width, height = size
    to_raster = np.vstack([paint.raster_matrix, [0.0, 0.0, 1.0]])
    mask = cv2.warpPerspective(paint.raster, map_to_image @ np.linalg.inv(to_raster), size,
                               flags=cv2.INTER_LINEAR)
    rng = np.random.default_rng(seed)
    grey = rng.normal(105, 12, (height, width)).clip(0, 255)
    image = np.where(mask > 127, 235.0, grey)
    image = cv2.GaussianBlur(image.astype(np.float32), (0, 0), 1.0)
    frame = cv2.cvtColor(image.clip(0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if barrel:
        ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
        nx, ny = (xs - width / 2) / (width / 2), (ys - height / 2) / (width / 2)
        factor = 1 + barrel * (nx * nx + ny * ny)
        frame = cv2.remap(frame, width / 2 + nx * factor * width / 2,
                          height / 2 + ny * factor * width / 2, cv2.INTER_LINEAR)
    return frame


def _pose_error_m(paint, registration, map_to_image, size=(1280, 720)) -> float:
    """Median floor error (m) of paint points visible in the frame."""
    points = paint.samples.reshape(-1, 1, 2)
    image_pts = cv2.perspectiveTransform(points, map_to_image).reshape(-1, 2)
    inside = ((image_pts[:, 0] >= 0) & (image_pts[:, 0] < size[0])
              & (image_pts[:, 1] >= 0) & (image_pts[:, 1] < size[1]))
    back = cv2.perspectiveTransform(image_pts[inside].reshape(-1, 1, 2),
                                    registration.image_to_map).reshape(-1, 2)
    return float(np.median(np.hypot(*(back - paint.samples[inside]).T)))


def test_paint_mesh_is_the_map_v2_fleet_track(paint):
    xmin, xmax, ymin, ymax = paint.bounds
    assert xmax - xmin == pytest.approx(2.81, abs=0.01)
    assert ymax - ymin == pytest.approx(1.26, abs=0.01)


def test_rotated_180_with_west_cut_off(paint):
    # Like the lab frame: track turned 180 deg, map west third outside the frame.
    truth = _similarity(440.0, 180.0, (780.0, 360.0))
    result = register_map(_render(paint, truth), paint)
    assert result.accepted, result.reason
    reg = result.registration
    assert _pose_error_m(paint, reg, truth) < 0.01
    assert not reg.mirrored
    assert abs(((reg.rotation_deg - 180.0) + 180.0) % 360.0 - 180.0) < 2.0
    assert reg.cut_sides == ("-x",)
    assert reg.to_dict()["cut_directions"] == ["west"]
    assert 0.6 < reg.coverage < 0.9
    assert reg.orientation_margin > 0.1


def test_tilt_yaw_and_mild_barrel_distortion(paint):
    size = (1280, 720)
    truth = _tilt(*size, 12.0) @ _similarity(380.0, 20.0, (640.0, 360.0))
    frame = _render(paint, truth, size, seed=1, barrel=0.03)
    result = register_map(frame, paint)
    assert result.accepted, result.reason
    assert _pose_error_m(paint, result.registration, truth) < 0.03


def test_mirrored_image_is_flagged_not_accepted(paint):
    truth = _similarity(380.0, 0.0, (640.0, 360.0), mirror=True)
    result = register_map(_render(paint, truth, seed=2), paint)
    assert not result.accepted
    assert result.registration is not None and result.registration.mirrored


def test_blank_floor_is_rejected(paint):
    rng = np.random.default_rng(3)
    frame = rng.normal(105, 12, (720, 1280, 3)).clip(0, 255).astype(np.uint8)
    result = register_map(frame, paint)
    assert not result.accepted
