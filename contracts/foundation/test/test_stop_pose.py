import math

import pytest

from core_common.stop_pose import offset_in_frame, stop_error


def test_offset_is_forward_and_left_of_the_origin_heading():
    assert offset_in_frame((1.0, 1.0, math.pi / 2), (1.0, 1.2)) == pytest.approx((0.2, 0.0))
    assert offset_in_frame((0.0, 0.0, 0.0), (0.0, 0.05)) == pytest.approx((0.0, 0.05))


def test_stop_error_reports_short_left_and_wrapped_heading():
    # Target facing -x (yaw pi); robot 3 cm before it along that heading, 1 cm to its right, turned 2 degrees.
    target = (0.745, -0.207, math.pi)
    pose = (0.775, -0.217 + 0.0, math.pi + math.radians(2) - math.tau)
    error = stop_error(target, pose)
    assert error["longitudinal_m"] == pytest.approx(0.03)
    assert error["lateral_m"] == pytest.approx(-0.01)
    assert error["heading_rad"] == pytest.approx(math.radians(2))
