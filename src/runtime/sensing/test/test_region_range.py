"""D-423 step 1: a range per camera region -- LiDAR when it sees the thing, else the floor."""
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from control.sensing.body import LIDAR_X
from control.sensing.lidar import NOSE_YAW
from control.sensing.perception.camera_ground import GroundPlane, nominal_ground_plane
from control.sensing.perception.region_range import (
    GROUND, LIDAR, choose_range, floor_distance_unbounded, pixel_bearing, range_regions,
    region_span, scan_in_camera)

PROFILE = yaml.safe_load((Path(__file__).resolve().parents[3] / "products" / "pinky_pro" / "profile"
                          / "config" / "camera_nominal.yaml").read_text(encoding="utf-8"))
CAMERA_X = PROFILE["x_offset_m"]


def plane():
    return nominal_ground_plane(source="NOMINAL", allowed=True, width_px=320, height_px=240,
                                profile=PROFILE)


def region(bbox, distance_m=None):
    return {'bbox_xyxy': list(bbox), 'area_px': 100, 'near_path': False, 'kind': 'foreground_region',
            'distance_m': distance_m, 'range_source': GROUND if distance_m is not None else None,
            'motion': 'unknown'}


def scan_with(beams, n=720, nose=NOSE_YAW, fill=float('inf')):
    """A C1-shaped scan (720 beams, 0..2pi) with `beams` {robot_yaw_rad: range_m} set."""
    increment = 2 * math.pi / n
    ranges = np.full(n, fill)
    for yaw, metres in beams.items():
        ranges[int(round(((yaw + nose) % (2 * math.pi)) / increment)) % n] = metres
    return dict(ranges=ranges, angle_min=0.0, angle_increment=increment, range_min=0.05,
                range_max=12.0)


def points(scan, nose=NOSE_YAW):
    return scan_in_camera(**scan, nose_rad=nose, lidar_x_m=LIDAR_X, camera_x_m=CAMERA_X)


def test_centre_column_looks_straight_ahead_and_left_is_positive():
    g = plane()
    assert pixel_bearing(g, g.principal_x, 200) == pytest.approx(0.0, abs=1e-12)
    assert pixel_bearing(g, 0, 200) > 0 > pixel_bearing(g, 319, 200)
    assert pixel_bearing(g, 100, 150) == pytest.approx(-pixel_bearing(g, 220, 150), abs=1e-12)


@pytest.mark.parametrize("column,row", [(30, 200), (160, 239), (300, 120), (240, 130)])
def test_bearing_agrees_with_the_floor_point_the_ground_plane_projects(column, row):
    """The pitched formula, not the zero-pitch atan((cx-u)/f) approximation."""
    g = plane()
    expected = math.atan2(-g.lateral(column, row), floor_distance_unbounded(g, row))
    assert pixel_bearing(g, column, row) == pytest.approx(expected, abs=1e-9)


def test_region_span_covers_all_four_corners_and_needs_pinhole_geometry():
    g = plane()
    lo, hi = region_span(g, [100, 150, 140, 200])
    corners = [pixel_bearing(g, u, v) for u in (100, 140) for v in (150, 200)]
    assert (lo, hi) == (pytest.approx(min(corners)), pytest.approx(max(corners)))
    assert region_span(object(), [100, 150, 140, 200]) is None   # e.g. a homography model
    assert region_span(g, [1, 2]) is None


def test_unbounded_floor_distance_ignores_max_range_but_not_the_horizon():
    g = plane()
    far_row = g.horizon_row + 3
    assert g.distance(far_row) is None
    assert floor_distance_unbounded(g, far_row) > g.max_range_m
    assert floor_distance_unbounded(g, g.horizon_row - 1) is None
    assert floor_distance_unbounded(g, 200) == pytest.approx(g.distance(200))


def test_scan_moves_from_the_lidar_to_the_camera_using_the_mount_forward_angle():
    """URDF: scan angle pi is the nose; the LiDAR sits LIDAR_X, the camera CAMERA_X ahead of base."""
    bearing, forward = points(scan_with({0.0: 0.5}))
    assert len(forward) == 1
    assert forward[0] == pytest.approx(0.5 + LIDAR_X - CAMERA_X, abs=1e-9)
    assert bearing[0] == pytest.approx(0.0, abs=1e-9)
    # A beam to the robot's left, seen from the camera further forward, lies wider left.
    bearing, _ = points(scan_with({math.radians(20): 0.4}))
    assert bearing[0] > math.radians(20)


def test_scan_drops_invalid_and_behind_the_camera_returns():
    scan = scan_with({0.0: 0.3, math.pi: 0.3, 0.1: 0.01, -0.1: float('nan')})
    bearing, forward = points(scan)
    assert list(np.round(forward, 6)) == [round(0.3 + LIDAR_X - CAMERA_X, 6)]


def test_a_wrong_nose_angle_moves_the_return_out_of_the_view():
    """The mount angle matters: with the scan's 0 taken as forward, the front wall vanishes."""
    _, forward = points(scan_with({0.0: 0.5}), nose=0.0)
    assert len(forward) == 0


@pytest.mark.parametrize("lidar,ground,unbounded,expected", [
    (0.42, 0.44, 0.44, (0.42, LIDAR)),      # agree: LiDAR wins
    (0.30, 0.55, 0.55, (0.30, LIDAR)),      # nearer than the contact point: pitch over-read or nearer thing
    (0.90, 0.40, 0.40, (0.40, GROUND)),     # farther: the thing is below the scan plane
    (None, 0.40, 0.40, (0.40, GROUND)),
    (0.80, None, None, (0.80, LIDAR)),      # all above the horizon: off the floor, only LiDAR knows
    (0.75, None, 0.70, (0.75, LIDAR)),      # beyond the trusted floor range but consistent
    (1.50, None, 0.80, (None, None)),       # paint beyond range, a wall behind it: no honest answer
    (None, None, None, (None, None)),
])
def test_choose_range(lidar, ground, unbounded, expected):
    assert choose_range(lidar, ground, unbounded, tolerance_m=0.05, tolerance_ratio=0.2) == expected


def test_range_regions_labels_each_region_and_keeps_the_input_unchanged():
    g = plane()
    wall = region([130, 20, 190, 75], distance_m=None)        # wholly above the horizon: off the floor
    low_box = region([20, 170, 70, 215], distance_m=g.distance(215))
    regions = [wall, low_box]
    pts = points(scan_with({0.0: 0.6}))                       # one return dead ahead only
    out = range_regions(regions, g, pts, tolerance_m=0.05, tolerance_ratio=0.2)
    assert out[0]['range_source'] == LIDAR
    assert out[0]['distance_m'] == pytest.approx(0.6 + LIDAR_X - CAMERA_X)
    assert out[1]['range_source'] == GROUND and out[1]['distance_m'] == low_box['distance_m']
    assert wall['distance_m'] is None and wall['range_source'] is None


def test_without_scan_or_pinhole_geometry_the_ground_answer_stands():
    g = plane()
    regions = [region([20, 170, 70, 215], distance_m=0.3), region([130, 20, 190, 60])]
    assert range_regions(regions, g, None, tolerance_m=0.05, tolerance_ratio=0.2) == regions
    assert range_regions(regions, object(), points(scan_with({0.0: 0.6})),
                         tolerance_m=0.05, tolerance_ratio=0.2) == regions


def test_ground_plane_class_is_what_the_bearing_reads():
    g = GroundPlane(0.06, 0.2, 280.0, 160.0, 120.0, 0.6)
    assert pixel_bearing(g, 160, 239) == pytest.approx(0.0)


def test_range_boxes_ranges_detection_boxes_by_the_same_rule():
    """D-423 §2.3: a detection is ranged from its own box, never borrowed from a region."""
    from control.sensing.perception.region_range import range_boxes
    g = plane()
    boxes = [[130, 20, 190, 75], [20, 170, 70, 215], [0, 0, 1, 1]]
    out = range_boxes(boxes, g, points(scan_with({0.0: 0.6})), tolerance_m=0.05, tolerance_ratio=0.2)
    assert out[0] == (pytest.approx(0.6 + LIDAR_X - CAMERA_X), LIDAR)
    assert out[1] == (pytest.approx(g.distance(215)), GROUND)
    assert out[2] == (None, None)
    assert range_boxes(boxes, None, None, tolerance_m=0.05, tolerance_ratio=0.2) == [None] * 3
    assert range_boxes(boxes[1:2], g, None, tolerance_m=0.05, tolerance_ratio=0.2) == [
        (pytest.approx(g.distance(215)), GROUND)]
