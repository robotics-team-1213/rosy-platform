"""Same-message motion evidence for actual station stop gating; no physical ACK."""
from types import SimpleNamespace as NS

import pytest

from core.bridge import odometry
from test_execution_odometry import message
from test_station_docking_wiring import configured_station


@pytest.fixture
def motion(core_client):
    svc = configured_station(core_client)
    now, utc = [10.], [100.]
    svc.state._clock = lambda: utc[0]
    svc.state._monotonic = lambda: now[0]
    svc.state.set_map_id('floor')
    svc.docking._clock = lambda: now[0]
    owner = svc.station_docking
    owner.motion_feed.clock = lambda: now[0]
    owner.motion_feed.source_clock = lambda: utc[0]
    owner.source_clock = lambda: utc[0]
    b = NS(_svc=svc, _frame_prefix='', _bounded_trial_guard=None, _line_clock=lambda: now[0],
        _node=NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=1100000000))))
    return NS(**locals())


def assert_admission_rejects_motion(owner):
    scope = owner.local_scope_nowait()
    with pytest.raises(ValueError, match='STATION_LOCAL_SCOPE_CHANGED'):
        owner._scope(NS(**scope), scope['odom_epoch'], nowait=True)


def test_same_message_epoch_cannot_be_relabelled_after_a_state_discontinuity(motion):
    r = motion
    original = r.svc.state._record_odom_pose
    def intervening(*args, **kwargs):
        receipt = original(*args, **kwargs)
        original(2., 0., 0., frame='odom', source_stamp_ns=1200000000)
        return receipt
    r.svc.state._record_odom_pose = intervening
    m = message()
    m.twist.twist.linear.x = 0.
    odometry.receive_odom(r.b, m, station=r.owner)
    sample = r.owner.motion_feed.snapshot()
    assert sample is not None and sample['odom_epoch'] == '0'
    scope = r.owner.local_scope_nowait()
    assert scope['odom_epoch'] == '1' and scope['odom_fresh'] is False
    assert_admission_rejects_motion(r.owner)


def test_slow_source_read_cannot_refresh_station_stop_evidence(motion):
    r = motion
    calls = []
    def slow_clock():
        if not calls:
            r.now[0] += .3
            r.utc[0] += .3
            calls.append(True)
        return NS(nanoseconds=1100000000)
    r.b._node.get_clock = lambda: NS(now=slow_clock)
    odometry.receive_odom(r.b, message(), station=r.owner)
    assert r.owner.motion_feed.snapshot() is None
    assert r.owner.local_scope_nowait()['odom_fresh'] is False
    assert_admission_rejects_motion(r.owner)


@pytest.mark.parametrize('fault', ['zero_rotation', 'nan_pose', 'tilted_body'])
def test_invalid_original_pose_clears_previous_measured_motion(motion, fault):
    r = motion
    odometry.receive_odom(r.b, message(), station=r.owner)
    assert r.owner.motion_feed.snapshot() is not None
    m = message()
    m.header.stamp.nanosec = 200000000
    r.b._node.get_clock = lambda: NS(now=lambda: NS(nanoseconds=1200000000))
    if fault == 'zero_rotation': m.pose.pose.orientation.w = 0.
    elif fault == 'nan_pose': m.pose.pose.position.x = float('nan')
    else: m.pose.pose.orientation = NS(x=.6, y=0., z=0., w=.8)
    odometry.receive_odom(r.b, m, station=r.owner)
    assert r.owner.motion_feed.snapshot() is None
    assert_admission_rejects_motion(r.owner)


def test_unscoped_direct_adapter_cannot_manufacture_motion_from_current_state(motion):
    r = motion
    r.svc.state.set_odom_pose(0., 0., 0., frame='odom', source_stamp_ns=1100000000)
    odometry.observe_station_motion(r.b, message(), dict(linear_x=0., angular_z=0.), r.owner)
    assert r.owner.motion_feed.snapshot() is None


def test_failed_translation_clears_old_stop_evidence_before_propagating_error(motion):
    r = motion
    odometry.receive_odom(r.b, message(), station=r.owner)
    assert r.owner.motion_feed.snapshot() is not None
    m = message()
    m.pose.pose.orientation = None
    with pytest.raises(AttributeError):
        odometry.receive_odom(r.b, m, station=r.owner)
    assert r.owner.motion_feed.snapshot() is None
    assert_admission_rejects_motion(r.owner)


def test_delayed_utc_capture_is_projected_to_original_read_start(motion):
    r = motion
    calls = []
    def slow_source():
        if not calls:
            r.now[0] += .05
            r.utc[0] += .05
            calls.append(True)
        return r.utc[0]
    r.owner.motion_feed.source_clock = slow_source
    odometry.receive_odom(r.b, message(), station=r.owner)
    sample = r.owner.motion_feed.snapshot()
    assert sample is not None and sample['captured_at'] <= 100.
