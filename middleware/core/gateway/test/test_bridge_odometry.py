"""`travelled_m` is the only thing undocking measures itself against.

No sensor confirms it. Wrong high and the robot stops before it is clear of the
dock; wrong low and it keeps reversing. It lived inline in `ros_bridge.py`,
which host pytest cannot import, so neither case had an assertion.
"""

from __future__ import annotations

import math

from core.bridge.odometry import travelled_m


def test_distance_is_straight_line_from_the_mark():
    assert travelled_m((1.0, 1.0), (4.0, 5.0)) == 5.0


def test_direction_does_not_matter():
    assert travelled_m((4.0, 5.0), (1.0, 1.0)) == 5.0


def test_no_mark_reads_as_no_progress():
    """The safe direction: the caller waits instead of concluding it is clear."""
    assert travelled_m(None, (4.0, 5.0)) == 0.0


def test_no_current_pose_reads_as_no_progress():
    assert travelled_m((1.0, 1.0), None) == 0.0


def test_standing_still_is_zero_not_noise():
    assert travelled_m((2.5, -1.25), (2.5, -1.25)) == 0.0


def test_a_reverse_along_one_axis_measures_that_axis():
    """The undocking case: negative displacement is still positive distance."""
    assert travelled_m((0.0, 0.0), (-0.35, 0.0)) == 0.35


def test_diagonal_drift_is_included():
    assert travelled_m((0.0, 0.0), (0.3, 0.4)) == 0.5
    assert math.isclose(travelled_m((0.0, 0.0), (1.0, 1.0)), math.sqrt(2))


# --- 보고 pose 의 임자 --------------------------------------------------------


def test_odom_yields_the_pose_while_the_map_frame_is_fresh():
    """브리지에는 pose 를 쓰는 곳이 둘이고, 주기가 높은 odom 이 그냥 두면 이긴다.

    미로 주행 뒤 AMCL 은 Gazebo 정답과 4 cm 안에 있었는데 API 는 3.3 m 떨어진 odom 값을
    돌려줬다. 관제 화면도 미션 판정도 그 좌표를 읽으므로, map 프레임이 권위여야 한다.
    """
    from core.bridge.odometry import odom_owns_pose

    assert not odom_owns_pose(map_pose_ts=100.0, now=100.5)
    assert not odom_owns_pose(map_pose_ts=100.0, now=101.9)


def test_odom_takes_the_pose_back_when_the_map_frame_goes_stale():
    """맵도 SLAM 도 없는 teleop 구성에서는 map→base 가 아예 없다. 그때도 화면에
    무엇이라도 떠야 한다 — 아무 좌표도 없는 대시보드는 odom 좌표보다 나쁘다."""
    from core.bridge.odometry import odom_owns_pose

    assert odom_owns_pose(map_pose_ts=0.0, now=100.0)
    assert odom_owns_pose(map_pose_ts=100.0, now=102.1)
