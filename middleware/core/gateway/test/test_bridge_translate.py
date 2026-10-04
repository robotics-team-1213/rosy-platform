"""브리지 변환의 실제 동작 테스트.

`ros_bridge` 는 rclpy 없이 import 되지 않아, 이 코드의 검증은 오랫동안
"소스에 이 문자열이 있는가"였다. 그런 테스트는 `msg.pose.covariance` 라는
글자만 보고 통과하며 그 값이 0 이어도 초록불을 준다. `translate` 는 ROS 타입을
import 하지 않으므로 여기서는 값을 실제로 계산해 확인한다.
"""

from __future__ import annotations

import math
from types import SimpleNamespace as NS

import pytest
from core.bridge import translate


def quat(yaw: float) -> NS:
    return NS(x=0.0, y=0.0, z=math.sin(yaw / 2.0), w=math.cos(yaw / 2.0))


def pose(x: float, y: float, yaw: float) -> NS:
    return NS(position=NS(x=x, y=y, z=0.0), orientation=quat(yaw))


@pytest.mark.parametrize("yaw", [0.0, 0.5, -1.25, math.pi / 2, -math.pi + 1e-6])
def test_yaw_round_trips_through_the_quaternion(yaw):
    assert translate.yaw_from_quat(quat(yaw)) == pytest.approx(yaw, abs=1e-9)


def test_yaw_uses_the_full_quaternion_not_just_z():
    """z 만 보고 각을 읽으면 뒤집힌 부호를 놓친다."""
    q = quat(math.pi * 0.75)
    flipped = NS(x=q.x, y=q.y, z=q.z, w=-q.w)
    assert translate.yaw_from_quat(flipped) != pytest.approx(translate.yaw_from_quat(q))


def test_occupancy_grid_keeps_origin_and_cells():
    msg = NS(
        info=NS(width=3, height=2, resolution=0.05, origin=pose(-1.0, -0.5, math.pi / 2)),
        data=[0, 100, -1, 50, 0, 0],
    )

    grid = translate.grid_from_occupancy(msg)

    assert grid["width"] == 3 and grid["height"] == 2
    assert grid["resolution"] == pytest.approx(0.05)
    assert grid["origin"]["x"] == pytest.approx(-1.0)
    assert grid["origin"]["yaw"] == pytest.approx(math.pi / 2)
    assert grid["data"] == [0, 100, -1, 50, 0, 0]
    assert grid["data"] is not msg.data, "the snapshot must not alias the ROS message"


def test_costmap_reads_size_x_not_width():
    """Costmap 의 메타데이터는 OccupancyGrid 와 필드 이름이 다르다."""
    msg = NS(
        metadata=NS(size_x=4, size_y=2, resolution=0.1, origin=pose(2.0, 3.0, 0.0)),
        data=[0] * 8,
    )

    grid = translate.grid_from_costmap(msg)

    assert (grid["width"], grid["height"]) == (4, 2)
    assert grid["origin"] == {"x": 2.0, "y": 3.0, "yaw": 0.0}


def test_path_keeps_order_and_drops_everything_but_xy():
    msg = NS(poses=[NS(pose=pose(0.0, 0.0, 0.0)), NS(pose=pose(1.5, -2.0, 1.0))])

    assert translate.path_points(msg) == [{"x": 0.0, "y": 0.0}, {"x": 1.5, "y": -2.0}]


def test_odom_carries_pose_and_twist():
    msg = NS(
        pose=NS(pose=pose(1.0, 2.0, math.pi / 4)),
        twist=NS(twist=NS(linear=NS(x=0.2, y=0.0, z=0.0), angular=NS(x=0.0, y=0.0, z=-0.4))),
    )

    sample = translate.odom_sample(msg)

    assert sample["x"] == pytest.approx(1.0)
    assert sample["yaw"] == pytest.approx(math.pi / 4)
    assert sample["linear_x"] == pytest.approx(0.2)
    assert sample["angular_z"] == pytest.approx(-0.4)


def test_lidar_sample_counts_the_ranges_it_copies():
    msg = NS(header=NS(frame_id="laser"), range_min=0.15, range_max=12.0,
             angle_min=-math.pi, angle_max=math.pi, ranges=[1.0, 2.0, 3.0])

    sample = translate.lidar_sample(msg, received_at=100.0)

    assert sample["num_ranges"] == 3 == len(sample["ranges"])
    assert sample["frame_id"] == "laser"
    assert sample["received_at"] == 100.0


def test_imu_sample_reports_yaw_not_the_raw_quaternion():
    msg = NS(orientation=quat(-0.75), angular_velocity=NS(z=0.3),
             linear_acceleration=NS(x=9.8))

    sample = translate.imu_sample(msg, received_at=1.0)

    assert sample["orientation_yaw"] == pytest.approx(-0.75)
    assert "orientation" not in sample


# --- PWR-002: 유효 구간 밖 표본이 로봇을 깨우면 안 된다 ----------------------


def _range_msg(value: float) -> NS:
    return NS(header=NS(frame_id="us"), range=value, min_range=0.02,
              max_range=4.0, field_of_view=0.26)


def test_a_range_inside_the_reported_window_is_usable():
    sample = translate.ultrasonic_sample(_range_msg(1.2), received_at=0.0)
    assert translate.usable_range(sample) == pytest.approx(1.2)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 4.5, 0.01, -1.0])
def test_a_saturated_or_out_of_window_range_is_refused(value):
    sample = translate.ultrasonic_sample(_range_msg(value), received_at=0.0)
    assert translate.usable_range(sample) is None


def test_the_window_edges_are_inclusive():
    for value in (0.02, 4.0):
        sample = translate.ultrasonic_sample(_range_msg(value), received_at=0.0)
        assert translate.usable_range(sample) == pytest.approx(value)


def test_battery_sample_keeps_nan_rather_than_inventing_a_percentage():
    """Pinky Pro 의 batt_state 는 percentage 가 NaN 이다 (D-28).

    0 으로 접어 넣으면 크리티컬 정책이 오발화한다. 그대로 넘기고, 판단은
    전압을 보는 정책 계층이 한다.
    """
    msg = NS(voltage=12.4, percentage=float("nan"), power_supply_status=0, location="pack")

    sample = translate.battery_sample(msg, received_at=5.0)

    assert sample["voltage"] == pytest.approx(12.4)
    assert math.isnan(sample["percentage"])
