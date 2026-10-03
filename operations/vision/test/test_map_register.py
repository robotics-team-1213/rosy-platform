"""Paint-line map registration on synthetic frames rendered from the site map paint."""

from __future__ import annotations

import numpy as np
import pytest

import rosy_vision.map_register as mr
from map_paint_frames import STL, pose_error_m, raster_region, render, similarity, tilt
from rosy_vision.map_register import load_map_paint, register_map


@pytest.fixture(scope="module")
def paint():
    return load_map_paint(STL)


def test_paint_mesh_is_the_map_v2_fleet_track(paint):
    xmin, xmax, ymin, ymax = paint.bounds
    assert xmax - xmin == pytest.approx(2.81, abs=0.01)
    assert ymax - ymin == pytest.approx(1.26, abs=0.01)


def test_rotated_180_with_west_cut_off(paint):
    # Like the lab frame: track turned 180 deg, map west third outside the frame.
    truth = similarity(440.0, 180.0, (780.0, 360.0))
    result = register_map(render(paint, truth), paint)
    assert result.accepted, result.reason
    reg = result.registration
    assert pose_error_m(paint, reg, truth) < 0.01
    assert not reg.mirrored
    assert abs(((reg.rotation_deg - 180.0) + 180.0) % 360.0 - 180.0) < 2.0
    assert reg.cut_sides == ("-x",)
    assert reg.to_dict()["cut_directions"] == ["west"]
    assert 0.6 < reg.coverage < 0.9
    assert reg.orientation_margin > 0.1


@pytest.mark.parametrize("pitch, roll, yaw, scale, barrel", [
    (12.0, 0.0, 20.0, 380.0, 0.03),    # mild tilt, yaw, barrel distortion
    (30.0, 0.0, 0.0, 380.0, 0.0),      # installation-like pitch
    (-30.0, 0.0, 200.0, 330.0, 0.0),   # pitch the other way, track turned past 180 deg
    (30.0, 0.0, 30.0, 330.0, 0.02),    # pitch + yaw + distortion
    (0.0, 25.0, 10.0, 330.0, 0.0),     # roll instead of pitch
])
def test_tilted_camera_up_to_30_degrees(paint, pitch, roll, yaw, scale, barrel):
    size = (1280, 720)
    truth = tilt(*size, pitch, roll) @ similarity(scale, yaw, (640.0, 360.0))
    frame = render(paint, truth, size, seed=1, barrel=barrel)
    result = register_map(frame, paint)
    assert result.accepted, result.reason
    assert not result.registration.mirrored
    assert pose_error_m(paint, result.registration, truth) < 0.03


def test_mirrored_image_is_flagged_not_accepted(paint):
    truth = similarity(380.0, 0.0, (640.0, 360.0), mirror=True)
    result = register_map(render(paint, truth, seed=2), paint)
    assert not result.accepted
    assert result.reason.startswith("image is mirrored")
    assert result.registration is not None and result.registration.mirrored


def test_blank_floor_is_rejected(paint):
    rng = np.random.default_rng(3)
    frame = rng.normal(105, 12, (720, 1280, 3)).clip(0, 255).astype(np.uint8)
    result = register_map(frame, paint)
    assert not result.accepted


# -- each accept gate rejects a real failure (fails if that gate is disabled) --------


def test_track_with_paint_missing_fails_on_recall(paint):
    # The right pose exists, but 45% of the painted blocks are not on the floor.
    blocks = np.random.default_rng(5).random((8, 16)) < 0.45
    keep = raster_region(paint, lambda x, y: ~blocks[
        np.clip(((y + 0.7) / 1.4 * 8).astype(int), 0, 7),
        np.clip(((x + 1.45) / 2.9 * 16).astype(int), 0, 15)])
    truth = similarity(400.0, 0.0, (640.0, 360.0))
    result = register_map(render(paint, truth, mask=keep), paint)
    assert not result.accepted
    assert result.reason.startswith("weak paint match"), result.reason


def test_doubled_lines_fail_on_precision(paint):
    # A second copy of the paint 10 cm / 7 cm off: every map line is matched, but half
    # of the lines on the floor are not map paint (a neighbouring or repainted track).
    first = render(paint, similarity(400.0, 0.0, (640.0, 360.0)), seed=1)
    second = render(paint, similarity(400.0, 0.0, (680.0, 388.0)), seed=1)
    result = register_map(np.maximum(first, second), paint)
    assert not result.accepted
    assert result.reason.startswith("too many unmatched lines"), result.reason


def test_roundabout_only_view_fails_on_orientation_margin(paint):
    # Around the roundabout the paint is nearly symmetric: a perfect fit and its turned
    # twin score alike, so the orientation cannot be told.
    size = (640, 720)
    truth = similarity(550.0, 0.0, (320.0 + 0.33 * 550.0, 360.0))
    result = register_map(render(paint, truth, size), paint)
    assert not result.accepted
    assert result.reason.startswith("orientation ambiguous"), result.reason


def test_narrow_view_of_one_end_is_rejected(paint):
    # A strip of the east end only: no pose may be accepted from it.
    size = (170, 720)
    truth = similarity(300.0, 0.0, (85.0 - 0.9 * 300.0, 360.0))
    result = register_map(render(paint, truth, size), paint)
    assert not result.accepted


@pytest.mark.parametrize("values, prefix", [
    ((0.19, 0.99, 0.99, 0.9, False), "too little of the map in view"),
    ((0.9, 0.79, 0.99, 0.9, False), "weak paint match"),
    ((0.9, 0.99, 0.79, 0.9, False), "too many unmatched lines"),
    ((0.9, 0.84, 0.86, 0.9, False), "weak overall match"),
    ((0.9, 0.99, 0.99, None, False), "orientation ambiguous"),
    ((0.9, 0.99, 0.99, 0.05, False), "orientation ambiguous"),
    ((0.9, 0.99, 0.99, 0.9, True), "image is mirrored"),
    ((0.9, 0.99, 0.99, 0.9, False), "ok"),
])
def test_gate_order_and_thresholds(values, prefix):
    # The coverage gate is not reachable from a rendered frame: the coarse search keeps
    # only poses with at least 30 % of the paint in view. It is pinned here instead.
    accepted, reason = mr._verdict(*values)
    assert reason.startswith(prefix)
    assert accepted is (prefix == "ok")
