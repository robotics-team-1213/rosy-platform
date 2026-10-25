"""Pixel -> arm maps fitted from points the arm placed: exact on a true homography, honest leave-one-out error."""
import importlib.util
import math
from pathlib import Path
import sys

import pytest

np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("cell_calibration", OMX / "cell_calibration.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))

# arm metres -> top-camera pixels: about 1.1 px/mm, image axes turned and mirrored against the arm's
TRUE = np.array([[0.0, -900.0, 230.0], [-900.0, 0.0, 300.0], [0.0, 0.0, 1.0]])  # looking straight down


def pixel(point):
    u, v, w = TRUE @ [point[0], point[1], 1.0]
    return u / w, v / w


def test_the_map_from_placed_points_returns_each_arm_point_and_inverts():
    points = [(pixel(p), p) for p in m.grid((0.072, 0.106), 0.015)]
    h = m.fit(points)
    for (u, v), (x, y) in points:
        assert math.dist(m.to_arm(h, (u, v)), (x, y)) < 1e-6
    assert math.dist(m.to_pixel(h, (0.08, 0.1)), pixel((0.08, 0.1))) < 1e-4
    assert m.yaw_sign(h, pixel((0.072, 0.106))) == -1  # the image mirrors the arm's turns


def test_leave_one_out_error_reports_how_far_a_noisy_point_lands():
    rng = np.random.default_rng(1)
    points = [((u + rng.normal(0, 1.0), v + rng.normal(0, 1.0)), p)
              for (u, v), p in ((pixel(p), p) for p in m.grid((0.072, 0.106), 0.015))]
    error = m.loo_error_mm(points)
    # one pixel is about a millimetre; a left-out corner of a 3x3 grid is extrapolated, so it lands farther
    assert 0 < error["mean"] < 4 and error["mean"] <= error["max"] < 10


def test_a_box_just_outside_a_small_noisy_grid_is_still_located_within_two_millimetres():
    rng = np.random.default_rng(3)
    points = [((u + rng.uniform(-0.5, 0.5), v + rng.uniform(-0.5, 0.5)), p)
              for (u, v), p in ((pixel(p), p) for p in m.grid((0.072, 0.106), 0.010))]
    h = m.fit(points)
    outside = (0.092, 0.100)  # 10 mm past the grid's edge
    assert 1000 * math.dist(m.to_arm(h, pixel(outside)), outside) < 2.0


def test_collinear_points_are_refused():
    points = [(pixel((0.07 + k * 0.01, 0.1)), (0.07 + k * 0.01, 0.1)) for k in range(5)]
    with pytest.raises(ValueError, match="degenerate"):
        m.fit(points)


def test_the_grid_is_walked_one_spacing_at_a_time():
    points = m.grid((0.0, 0.0), 0.01)
    assert len(points) == 9 and len(set(points)) == 9
    assert all(math.dist(a, b) == pytest.approx(0.01) for a, b in zip(points, points[1:]))


def test_a_site_record_needs_five_points_and_round_trips(tmp_path):
    points = [(pixel(p), p) for p in m.grid((0.072, 0.106), 0.015)]
    with pytest.raises(ValueError, match="at least 5"):
        m.site_record(points[:4], "t")
    path = tmp_path / "cal.json"
    m.save(path, "pinky", m.site_record(points, "2026-10-25T00:00:00+00:00"))
    record = m.load(path)["sites"]["pinky"]
    assert record["loo_error_mm"]["max"] < 0.01 and len(record["points"]) == 9
