"""D-494 2: the state snapshot carries a stamped odom-frame pose beside `pose`."""

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
    assert snap.odom_pose.model_dump() == {"x": 0.3, "y": -0.1, "yaw": 1.2, "stamp": 1_790_000_000.25,
                                           "epoch": 0, "mono_s": pytest.approx(snap.odom_pose.mono_s)}


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
    assert state.snapshot().odom_pose.model_dump(include={"x", "y", "yaw", "stamp", "epoch"}) == dict(
        x=0.1, y=0.2, yaw=0.3, stamp=3.0, epoch=0)
    with pytest.raises(ValidationError):
        OdomPose(x=math.nan, y=0.0, yaw=0.0, stamp=1.0)
    with pytest.raises(ValidationError):
        state.snapshot().odom_pose.x = 1.0          # frozen


def test_odom_sample_ages_on_the_monotonic_clock_not_the_wall_clock():
    """D-581: a backward chrony step must not make a stale odom pose look fresh."""
    clocks = {"wall": 1_790_000_100.0, "mono": 50.0}
    state = StateManager(robot_id="rosy_01", clock=lambda: clocks["wall"], monotonic=lambda: clocks["mono"])
    assert state.odom_sample() is None
    state.set_odom_pose(0.1, 0.2, 0.3)
    clocks["wall"] -= 30.0                       # chrony steps the wall clock back
    clocks["mono"] += 0.8
    assert state.odom_sample() == (0.1, 0.2, 0.3, pytest.approx(0.8))


def _odom_rig():
    clocks = {"wall": 1_790_000_100.0, "mono": 50.0}
    state = StateManager(robot_id="rosy_01", clock=lambda: clocks["wall"], monotonic=lambda: clocks["mono"])

    def feed(x, y=0.0, dt=0.05, **source):
        clocks["wall"] += dt
        clocks["mono"] += dt
        return state.set_odom_pose(x, y, 0.0, **source)
    return state, clocks, feed


def test_odom_pose_carries_its_epoch_and_monotonic_receipt_and_returns_the_published_stamp():
    """D-758 0: the stamp set_odom_pose returns is the one the snapshot publishes (the odom log keys on it)."""
    state, clocks, feed = _odom_rig()
    stamp = feed(0.1)
    odom = state.snapshot().odom_pose
    assert (odom.stamp, odom.epoch, odom.mono_s) == (stamp, 0, clocks["mono"])
    assert stamp == clocks["wall"]
    assert feed(float("nan")) is None                  # dropped: nothing published


def test_only_an_odom_discontinuity_bumps_the_epoch():
    """D-758 0: a step beyond PoseTrail's 0.02 + 0.2 dt m, a frame change or a source stamp going back."""
    state, clocks, feed = _odom_rig()
    epoch = lambda: state.snapshot().odom_pose.epoch
    for i in range(11):                                # driving through the origin is no reset
        feed(-0.05 + 0.01 * i, frame="odom", source_stamp_ns=i)
    assert epoch() == 0
    feed(0.35, dt=2.0, frame="odom", source_stamp_ns=20)  # 0.3 m in 2 s of silence: still one run
    assert epoch() == 0
    feed(0.0, frame="odom", source_stamp_ns=21)        # odom reset to 0 from 0.35 m in one step
    assert epoch() == 1
    feed(0.0, frame="odom2", source_stamp_ns=22)
    assert epoch() == 2
    feed(0.0, frame="odom2", source_stamp_ns=5)        # the source restarted its clock
    assert epoch() == 3
    feed(0.0)                                          # a caller without frame or source stamp: unchanged
    assert epoch() == 3


def test_an_old_snapshot_odom_pose_without_epoch_still_parses():
    old = OdomPose.model_validate({"x": 0.1, "y": 0.2, "yaw": 0.3, "stamp": 4.0})
    assert (old.epoch, old.mono_s) == (None, None)
