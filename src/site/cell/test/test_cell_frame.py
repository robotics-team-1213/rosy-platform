import math

import pytest

from rosy_cell.geometry import Frame, FrameError

RULES = {"min_span_m": 0.02, "min_angle_deg": 10.0}


def _close(a, b, tol=1e-9):
    assert all(abs(x - y) < tol for x, y in zip(a, b)), (a, b)


def test_axis_aligned_points_give_the_identity_frame():
    f = Frame.from_three_points((0, 0, 0), (1, 0, 0), (0, 1, 0), **RULES)
    _close(f.to_base((0.1, 0.2, 0.3)), (0.1, 0.2, 0.3))
    assert f.yaw_to_base(0.3) == pytest.approx(0.3)
    assert f.tilt_deg() == pytest.approx(0.0)


def test_rotated_offset_frame_maps_points_and_yaw():
    f = Frame.from_three_points((1, 2, 0), (1, 3, 0), (0, 2, 0), **RULES)
    _close(f.to_base((0.5, 0.25, 0.0)), (0.75, 2.5, 0.0))
    assert f.yaw_to_base(0.0) == pytest.approx(math.pi / 2)


def test_plane_point_on_the_right_hand_side_points_z_down():
    f = Frame.from_three_points((0, 0, 0), (1, 0, 0), (0, -1, 0), **RULES)
    assert f.tilt_deg() == pytest.approx(180.0)


@pytest.mark.parametrize(
    "x_point, plane_point",
    [((0.01, 0, 0), (0, 1, 0)), ((1, 0, 0), (0, 0.01, 0)), ((1, 0, 0), (2, 0.05, 0))],
)
def test_degenerate_teaching_is_rejected(x_point, plane_point):
    with pytest.raises(FrameError):
        Frame.from_three_points((0, 0, 0), x_point, plane_point, **RULES)
