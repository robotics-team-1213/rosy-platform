"""D-379 auto-label geometry on synthetic scenes (no recordings needed)."""
import dataclasses
import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import labels as L  # noqa: E402
from geometry import Camera, Lidar, PoseSeries, to_frame  # noqa: E402

CAM = Camera(width=320, height=240, fx=281.6, cx=160.0, cy=120.0, pitch_rad=math.radians(8.0),
             height_m=0.067, x_offset_m=0.034)


def expected_row(forward_m, z=0.0, cam=CAM):
    """Closed form for a point straight ahead of base."""
    dx, dz = forward_m - cam.x_offset_m, z - cam.height_m
    # angle of the ray below horizontal, minus the pitch, is the angle below the axis
    below = math.atan2(-dz, dx) - cam.pitch_rad
    return cam.cy + cam.fx * math.tan(below)


def test_profile_loads_nominal_numbers():
    cam = Camera.from_profile()
    assert (cam.width, cam.height) == (320, 240)
    assert cam.fx == pytest.approx(281.6)
    assert math.degrees(cam.pitch_rad) == pytest.approx(8.0, abs=0.01)
    assert cam.horizon_row == pytest.approx(80.3, abs=0.2)
    scaled = Camera.from_profile(width=640, height=480)
    assert scaled.fx == pytest.approx(563.2) and scaled.cy == pytest.approx(240.0)


@pytest.mark.parametrize("r", [0.3, 0.6, 1.0, 2.0])
def test_wall_contact_row_matches_closed_form(r):
    row = CAM.ground_row(r)
    assert row == pytest.approx(expected_row(r), abs=1e-6)
    # a wall r ahead (a straight run of returns across the view)
    ys = np.linspace(-1.5, 1.5, 301)
    xy = np.column_stack([np.full_like(ys, r), ys])
    wall, floor, contact, dist = L.wall_label(CAM, xy)
    assert np.nanmax(np.abs(contact - row)) < 0.6
    c = 160
    col_wall = np.nonzero(wall[:, c])[0]
    col_floor = np.nonzero(floor[:, c])[0]
    margin = min(L.CONTACT_MARGIN_PX + CAM.fx * CAM.height_m * L.RANGE_SIGMA_M / r ** 2, L.MAX_MARGIN_PX)
    assert col_wall.max() == pytest.approx(row - margin, abs=1.5)
    assert col_floor.min() == pytest.approx(row + margin, abs=1.5)
    top = expected_row(r, L.WALL_HEIGHT_M)
    if top >= 0:
        assert col_wall.min() == pytest.approx(top, abs=1.5)
    assert dist[c] == pytest.approx(r, abs=0.01)


def test_nearer_wall_owns_the_contact_row():
    ys = np.linspace(-1.5, 1.5, 301)
    far = np.column_stack([np.full_like(ys, 1.5), ys])
    near_y = np.linspace(-0.05, 0.05, 11)
    near = np.column_stack([np.full_like(near_y, 0.5), near_y])
    xy = np.vstack([far[:150], near, far[151:]])
    _, floor, contact, _ = L.wall_label(CAM, xy)
    assert contact[160] == pytest.approx(CAM.ground_row(0.5), abs=0.6)
    assert contact[20] == pytest.approx(CAM.ground_row(1.5), abs=0.6)
    assert not floor[int(CAM.ground_row(0.5)) - 10, 160]


def test_no_returns_means_unknown_not_floor():
    wall, floor, contact, _ = L.wall_label(CAM, np.zeros((0, 2)))
    assert not wall.any() and not floor.any() and np.isnan(contact).all()


def test_small_column_gap_is_filled_as_floor_only():
    ys = np.concatenate([np.linspace(-1.0, -0.03, 50), np.linspace(0.03, 1.0, 50)])
    xy = np.column_stack([np.full_like(ys, 1.0), ys])  # 6 cm hole straight ahead
    wall, floor, contact, _ = L.wall_label(CAM, xy)
    assert not np.isnan(contact[160])
    assert floor[int(CAM.ground_row(1.0)) + 10, 160]


def test_lidar_mount_faces_backwards():
    lidar = Lidar()
    # scan angle +-pi is the robot's front, angle 0 its rear
    ranges = np.full(4, np.inf)
    ranges[0] = 1.0  # angle -pi: the front
    ranges[1] = 0.5  # angle -pi/2
    xy, r, idx = lidar.points(ranges, -math.pi, math.pi / 2, 0.05, 40.0)
    by_idx = dict(zip(idx.tolist(), xy.tolist()))
    assert by_idx[0] == pytest.approx([1.0 + lidar.x_offset_m, 0.0], abs=1e-9)
    assert by_idx[1][0] == pytest.approx(lidar.x_offset_m, abs=1e-9)
    assert by_idx[1][1] == pytest.approx(0.5, abs=1e-9)  # angle -pi/2 -> left
    assert lidar.height_m == pytest.approx(0.125)


def test_invalid_ranges_dropped():
    xy, r, _ = Lidar().points([np.nan, 0.01, np.inf, 50.0, 1.0], 0.0, 0.1, 0.05, 40.0)
    assert r.tolist() == [1.0]


def test_motion_compensation_moves_points_with_the_robot():
    # a point 1 m ahead at the scan; the robot then drives 0.2 m forward
    p = to_frame((0.0, 0.0, 0.0), (0.2, 0.0, 0.0), [[1.0, 0.0]])
    assert p[0] == pytest.approx([0.8, 0.0])
    # and turns left 90 deg: the point is now on the robot's right
    p = to_frame((0.0, 0.0, 0.0), (0.0, 0.0, math.pi / 2), [[1.0, 0.0]])
    assert p[0] == pytest.approx([0.0, -1.0], abs=1e-12)


def test_pose_series_interpolates_and_refuses_gaps():
    s = PoseSeries([0.0, 1.0, 5.0], [0.0, 1.0, 2.0], [0, 0, 0], [3.1, -3.1, -3.1])
    x, _, yaw = s.at(0.5, max_gap=2.0)
    assert x == pytest.approx(0.5)
    assert abs(yaw) == pytest.approx(math.pi, abs=0.05)  # unwrapped, not through zero
    assert s.at(3.0) is None and s.at(-1.0) is None


def test_trajectory_band_straight_ahead():
    xs = np.linspace(0.0, 0.8, 81)
    band, travel = L.trajectory_band(CAM, (0.0, 0.0, 0.0), (xs, np.zeros_like(xs), np.zeros_like(xs)))
    assert travel == pytest.approx(0.8)
    near_row = int(round(CAM.ground_row(0.3)))
    cols = np.nonzero(band[near_row])[0]
    # 0.10 m wide at 0.3 m: centred, width fx*w/depth
    depth = (0.3 - CAM.x_offset_m) * math.cos(CAM.pitch_rad) + CAM.height_m * math.sin(CAM.pitch_rad)
    assert cols.mean() == pytest.approx(CAM.cx, abs=1.0)
    assert cols.size == pytest.approx(CAM.fx * 0.10 / depth, abs=2.5)
    assert not band[: int(CAM.horizon_row)].any()


def test_trajectory_band_needs_motion_and_stops_at_a_turn():
    xs = np.linspace(0.0, 0.05, 10)
    band, travel = L.trajectory_band(CAM, (0, 0, 0), (xs, 0 * xs, 0 * xs))
    assert band is None and travel == pytest.approx(0.05)
    # 0.3 m straight, then a 90 deg left turn: only the straight part is used
    t = np.linspace(0, math.pi / 2, 30)
    x = np.concatenate([np.linspace(0, 0.3, 31), 0.3 + 0.2 * np.sin(t)])
    y = np.concatenate([np.zeros(31), 0.2 - 0.2 * np.cos(t)])
    yaw = np.concatenate([np.zeros(31), t])
    band, travel = L.trajectory_band(CAM, (0, 0, 0), (x, y, yaw))
    assert 0.3 <= travel <= 0.3 + 0.2 * L.TRAJ_MAX_TURN_RAD + 0.02


def test_combine_trusts_lidar_over_the_rule_and_finds_paint():
    bgr = np.full((240, 320, 3), 90, np.uint8)       # grey carpet
    row = int(CAM.ground_row(1.0))
    bgr[:row] = 235                                  # white wall above the contact row
    bgr[200:206, 100:220] = 240                      # a white tape strip on the floor
    ys = np.linspace(-1.5, 1.5, 301)
    wall, floor, _, dist = L.wall_label(CAM, np.column_stack([np.full_like(ys, 1.0), ys]))
    rule = np.zeros((240, 320), bool)
    rule[row - 20:row] = True                        # rule calls the wall bottom paint
    rule[200:206, 100:220] = True
    cls, conf, rec = L.combine(bgr, wall=wall, floor=floor, rules={"r": rule}, wall_dist=dist)
    assert (cls[row - 20:row - L.CONTACT_MARGIN_PX - 2] == L.WALL).all()
    assert (cls[201:205, 110:210] == L.LANE).all()
    assert (cls[220, :] == L.FLOOR).all()
    st = rec["rules"]["r"]
    assert st["on_wall"] > 0 and st["on_lane"] > 0
    assert conf[202, 150] == int(L.CONF["paint_rule_agrees"] * 255)


def test_band_on_a_lidar_wall_is_a_conflict():
    ys = np.linspace(-1.5, 1.5, 301)
    wall, floor, _, _ = L.wall_label(CAM, np.column_stack([np.full_like(ys, 0.3), ys]))
    xs = np.linspace(0.0, 0.8, 81)
    band, _ = L.trajectory_band(CAM, (0, 0, 0), (xs, 0 * xs, 0 * xs))
    cls, _, rec = L.combine(np.full((240, 320, 3), 90, np.uint8), wall=wall, floor=floor, band=band)
    assert rec["conflict"] and rec["disagreement"]["trajectory_on_lidar_wall_px"] >= L.CONFLICT_PX
    assert not ((cls == L.DRIVABLE) & wall).any()


def test_fit_pitch_recovers_a_remounted_camera():
    true = dataclasses.replace(CAM, pitch_rad=math.radians(11.0))
    samples = []
    for r in (0.6, 0.9, 1.3):
        ys = np.linspace(-0.8, 0.8, 161)
        xy = np.column_stack([np.full_like(ys, r), ys])
        img = np.full((240, 320, 3), 40, np.uint8)            # dark room
        _, vt, _ = true.project([[r, 0.0, L.WALL_HEIGHT_M]])
        img[int(round(vt[0])):int(round(true.ground_row(r)))] = 230   # white wall
        img[int(round(true.ground_row(r))):] = 110                    # carpet
        samples.append((xy, L.edge_image(img)))
    pitch, curve = L.fit_pitch(CAM, samples)
    assert math.degrees(pitch) == pytest.approx(11.0, abs=0.3)


def test_classes_follow_the_shared_contract():
    roles = {c["role"] for c in L.CLASSES}
    assert roles <= {"background", "lane_marking", "drivable", "stop_line", "ignore"}
    assert [c["index"] for c in L.CLASSES] == list(range(len(L.CLASSES)))
    assert sum(c["role"] == "lane_marking" for c in L.CLASSES) >= 1
    assert L.CLASSES[L.IGNORE_INDEX]["role"] == "ignore"
