"""D-424: one robot body for every near/stop check (Pinky Pro URDF nominal numbers)."""

import math

import pytest

from core_common.calibration_store import CalibrationStore
from core_common.robot_body import (PINKY_PRO, PINKY_PRO_GEOMETRY, RobotBody, from_geometry,
                                    inside_body, resolve_body, stop_gap_m)

B = PINKY_PRO


def _scan(points_by_deg, *, count=360, range_min=0.15, default=3.0):
    """A 360-beam scan in the LiDAR frame (0 deg = scan 0); values by integer degree."""
    ranges = [default] * count
    for deg, value in points_by_deg.items():
        ranges[int(deg) % count] = value
    return {"ranges": ranges, "angle_min": 0.0, "angle_max": 2 * math.pi * (count - 1) / count,
            "range_min": range_min, "range_max": 12.0}


def test_pinky_numbers_follow_the_d422_gap_rule():
    assert B.lidar_to_front_m == pytest.approx(0.05905)
    assert B.lidar_to_rear_m == pytest.approx(0.059)
    assert B.lidar_stop_m(0.014) == pytest.approx(0.0813, abs=5e-4)
    assert B.lidar_clear_m(0.014) == pytest.approx(0.1113, abs=5e-4)
    assert B.lidar_stop_m(0.03) == pytest.approx(0.0845, abs=5e-4)
    assert B.rotation_clear_m() == pytest.approx(0.0926, abs=1e-4)
    assert B.rotation_clear_m(0.02) == pytest.approx(0.1026, abs=1e-4)
    assert B.box_bounds() == (0.076, 0.04205, 0.05655)
    assert stop_gap_m(0.04) == pytest.approx(0.0276)


def test_scan_points_are_base_frame_and_the_body_is_masked():
    # forward_deg 180: scan 180 deg is the robot's forward.
    view = B.scan_view(_scan({180: 0.10, 0: 0.03, 90: 0.0}))
    xs = sorted(round(x, 3) for x, y in view.points if abs(y) < 1e-6)
    assert 0.083 in xs                       # 0.10 ahead of the LiDAR = base x 0.083
    assert all(not B.contains(x, y) for x, y in view.points)
    assert len(view.unknown) == 1            # the 0.0 beam: unknown out to range_min


def test_a_near_return_below_range_min_is_an_obstacle():
    view = B.scan_view(_scan({180: 0.07}, range_min=0.15))
    assert B.translation_gap(view.points) == pytest.approx(0.07 - 0.05905, abs=1e-6)
    assert not B.can_rotate(view.points, 0.02)


def test_side_points_outside_the_strip_do_not_block_translation():
    points = [(0.0, 0.07), (0.0, -0.07)]
    assert B.translation_gap(points) is None
    assert B.translation_gap(points, reverse=True) is None
    assert B.translation_gap([(0.0, 0.06)]) == 0.0      # inside W + 0.010


def test_unknown_band_blocks_translation_into_it():
    view = B.scan_view(_scan({180: math.inf}, range_min=0.15))
    assert B.unknown_blocks(view)                         # forward: band reaches past the front
    assert not B.unknown_blocks(view, reverse=True)
    assert B.can_rotate(view.points)                      # seen points alone are clear
    # A blind zone inside the body (range_min 0.05) is no band at all.
    assert not B.unknown_blocks(B.scan_view(_scan({180: math.inf}, range_min=0.05)))


def test_rotation_needs_rho_plus_margin_in_base_frame():
    side = B.scan_view(_scan({270: 0.13}))                # side wall 0.13 from the LiDAR
    assert B.can_rotate(side.points, 0.02)
    front = B.scan_view(_scan({180: 0.12}))                # base 0.103 > 0.1026
    assert B.can_rotate(front.points, 0.02)


def test_nominal_body_selection_refuses_unknown_robot_kinds():
    from core_common.robot_body import nominal_body_for, NOMINAL_BODY

    assert nominal_body_for("pinky_pro") is NOMINAL_BODY
    assert nominal_body_for("unrecognized") is None


def test_body_validation_refuses_a_rotation_radius_below_the_extent():
    with pytest.raises(ValueError):
        RobotBody(front_x_m=0.04, rear_x_m=-0.08, half_width_m=0.05, rotation_radius_m=0.07,
                  lidar_x_m=0.0)


def test_overlay_wins_over_the_urdf_nominal():
    body = from_geometry(PINKY_PRO_GEOMETRY, overlay={"half_width_m": 0.06, "bogus": 1})
    assert body.half_width_m == 0.06 and "operator overlay half_width_m" in body.source


def test_an_accepted_lidar_mount_record_refines_the_forward_angle(tmp_path):
    store = CalibrationStore(tmp_path)
    record = store.add("pinky", "lidar_mount", {"lidar_yaw_offset": math.radians(181.5)}, method="test")
    store.set_status("pinky", "lidar_mount", record, "accepted", actor="test")
    body = resolve_body(robot="pinky", root=tmp_path)
    assert body.lidar_forward_deg == pytest.approx(181.5)
    assert body.source.startswith("calibration record")
    assert resolve_body(robot="other", root=tmp_path).lidar_forward_deg == pytest.approx(180.0)


# --- D-424 review M1/M2/M6 -------------------------------------------------------------

def test_a_turn_needs_returns_in_every_sector_around_the_base():
    """M1: one finite beam (or an empty scan) is not a clear sweep."""
    ranges = [math.inf] * 360
    ranges[90] = 2.0
    one = {"ranges": ranges, "angle_min": 0.0, "angle_max": 2 * math.pi * 359 / 360,
           "range_min": 0.05, "range_max": 12.0}
    assert "sectors" in B.rotation_reason(B.scan_view(one))
    assert not B.can_rotate([])
    assert B.rotation_reason(B.scan_view(_scan({}, range_min=0.05))) is None


def test_rear_unknown_never_clears_the_sweep_front_needs_a_real_echo():
    """M2/M6: no rear sensor; in front only a finite echo inside the cone clears the band."""
    rear = B.scan_view(_scan({0: math.inf}, range_min=0.15))         # scan 0 = robot rear
    assert "behind" in B.rotation_reason(rear, ultrasonic_m=1.0)
    front = B.scan_view(_scan({180: math.inf}, range_min=0.15))
    assert "in front" in B.rotation_reason(front)
    assert "in front" in B.rotation_reason(front, ultrasonic_m=math.inf)   # no echo proves nothing
    assert B.rotation_reason(front, ultrasonic_m=0.5) is None
    assert not B.unknown_blocks(front, ultrasonic_m=0.5)
    assert B.unknown_blocks(front, ultrasonic_m=0.05)                     # echo nearer than the band
    corner = B.scan_view(_scan({180 + 40: math.inf}, range_min=0.15))     # 40 deg off: outside the cone
    assert B.unknown_blocks(corner, ultrasonic_m=0.5)


def test_strict_outline_leaves_the_boundary_outside():
    """D-507 10: the open outline (memory entry) keeps a point on the edge outside."""
    outline = (B.front_x_m, B.rear_x_m, B.half_width_m, B.rotation_radius_m)
    for point in ((B.front_x_m, 0.0), (0.0, B.half_width_m), (B.rear_x_m, 0.0)):
        assert inside_body(*point, *outline) and not inside_body(*point, *outline, strict=True)
    assert inside_body(0.0, 0.0, *outline, strict=True)
    assert not inside_body(B.front_x_m + 1e-6, 0.0, *outline, strict=True)
