"""D-491 2: the state snapshot carries a stamped odom-frame pose beside `pose`."""

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
