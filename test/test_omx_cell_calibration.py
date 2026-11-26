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


def test_touched_heights_are_kept_beside_the_maps_and_unmeasured_ground_is_unknown(tmp_path):
    path = tmp_path / "cal.json"
    m.save(path, "pinky", m.site_record([(pixel(p), p) for p in m.grid((0.072, 0.106), 0.015)], "t0"))
    m.save_surface(path, "pinky_tray", m.surface_record([(0.075, 0.211, 0.0779), (0.074, 0.224, 0.0777)], "fixture", "t1"))
    m.save_surface(path, "container", m.surface_record([(0.053, 0.223, 0.0557)], "object", "t2"))
    data = m.load(path)
    assert "pinky" in data["sites"]  # the maps survive
    assert m.surface_z(data, 0.076, 0.214) == (0.0779, "pinky_tray")
    assert m.surface_z(data, 0.050, 0.223) == (0.0557, "container")
    assert m.surface_z(data, 0.050, 0.223, kinds=("fixture",)) is None
    assert m.surface_z(data, 0.120, -0.050) is None  # never touched: probe, do not guess
    with pytest.raises(ValueError):
        m.surface_record([], "fixture", "t3")


def test_projective_parallax_on_tilted_camera_keeps_nadir_fixed_and_round_trips():
    import cell_object_pose as cop

    K = np.array([[618.5, 0.0, 322.3], [0.0, 618.7, 236.6], [0.0, 0.0, 1.0]])
    normal = np.array([0.08169, -0.17488, -0.98119])  # ~11.13 deg tilt
    cam = {"K": K.tolist(), "normal": normal.tolist(), "height_m": 0.60, "center_px": [322.3, 236.6]}
    down = K @ (-normal / np.linalg.norm(normal))
    nadir = (float(down[0] / down[2]), float(down[1] / down[2]))

    # Nadir point stays fixed across height changes
    assert math.dist(m.parallax(nadir, 0.0, 0.05, cam), nadir) < 1e-6

    # Moving UP (to_z > from_z) shifts a point radially away from nadir_px and round-trips cleanly
    p = (460.0, 140.0)
    up = m.parallax(p, 0.0, 0.05, cam)
    assert math.dist(up, nadir) > math.dist(p, nadir)
    v_in = np.subtract(p, nadir)
    v_out = np.subtract(up, nadir)
    assert float(v_in @ v_out) / (np.linalg.norm(v_in) * np.linalg.norm(v_out)) == pytest.approx(1.0, abs=1e-6)
    assert math.dist(m.parallax(up, 0.05, 0.0, cam), p) < 1e-6

    # Opposite-sign normal input flips inward automatically and matches
    cam_flipped = {**cam, "normal": (-normal).tolist()}
    assert math.dist(m.parallax(p, 0.0, 0.05, cam_flipped), up) < 1e-6

    # cell_object_pose.to_mm uses cal.parallax even without center_px when K/normal are present (0.05 -> 0.0 round-trip)
    cam_only_kn = {"K": K.tolist(), "normal": normal.tolist(), "height_m": 0.60}
    rec = {"homography": np.eye(3).tolist(), "z_view": 0.0}
    mm = cop.to_mm(np.array([up, nadir]), rec, cam_only_kn, 0.05)
    assert mm[0] == pytest.approx([p[0] * 1000.0, p[1] * 1000.0], abs=1e-3)
    assert mm[1] == pytest.approx([nadir[0] * 1000.0, nadir[1] * 1000.0], abs=1e-3)

