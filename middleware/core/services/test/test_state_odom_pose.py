"""D-491 2: the state snapshot carries a stamped odom-frame pose beside `pose`."""

import math

import pytest
from pydantic import ValidationError

from core_common.protocol.localization import OdomPose
from core_common.protocol.schemas import HeartbeatPayload, StateSnapshot
from core_features.state.manager import StateManager


def test_odom_pose_is_null_until_odometry_then_stamped_with_wall_time():
    state = StateManager(robot_id="rosy_01", clock=lambda: 1_790_000_000.25)
    assert state.snapshot().odom_pose is None
    state.set_pose(1.0, 2.0, 0.5)               # map pose owns `pose`
    state.set_odom_pose(0.3, -0.1, 1.2)          # odom pose still rides along
    snap = state.snapshot()
    assert (snap.pose.x, snap.pose.y) == (1.0, 2.0)
    assert snap.odom_pose.model_dump() == {"x": 0.3, "y": -0.1, "yaw": 1.2, "stamp": 1_790_000_000.25}


def test_odom_pose_round_trips_and_old_snapshots_still_parse():
    state = StateManager(robot_id="rosy_01", clock=lambda: 12.5)
    state.set_odom_pose(0.1, 0.2, 0.3)
    wire = HeartbeatPayload(state_snapshot=state.snapshot()).model_dump(mode="json")
    again = HeartbeatPayload.model_validate(wire).state_snapshot
    assert again.odom_pose == state.snapshot().odom_pose
    old = StateSnapshot.model_validate({"robot_id": "rosy_01"})
    assert old.odom_pose is None


def test_non_finite_odom_is_dropped_and_the_previous_pose_kept():
    state = StateManager(robot_id="rosy_01", clock=lambda: 3.0)
    state.set_odom_pose(0.1, 0.2, 0.3)
    for bad in ((math.nan, 0.0, 0.0), (0.0, math.inf, 0.0), (0.0, 0.0, -math.inf)):
        state.set_odom_pose(*bad)
    assert state.snapshot().odom_pose == OdomPose(x=0.1, y=0.2, yaw=0.3, stamp=3.0)
    with pytest.raises(ValidationError):
        OdomPose(x=math.nan, y=0.0, yaw=0.0, stamp=1.0)
    with pytest.raises(ValidationError):
        state.snapshot().odom_pose.x = 1.0          # frozen
