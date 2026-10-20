"""Actual pre-parent ROS adapter receipts; no map/energy/native admission claim."""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace as NS

import pytest

from core.bridge.odometry import receive_odom
from core.drive.execution import install_native_execution
from core_features.command._execution_budget import Limits
from core_features.command._execution_ledger import Ledger
from core_common.protocol.native_receipts import BOOT_ID
from test_execution_odometry import message
from test_docking_parking_wiring import sim_overrides


@pytest.fixture
def source(core_client):
    _, svc = core_client(config_overrides=sim_overrides())
    mono, ros = [10.], [1100000000]
    limits = Limits('SYNTHETIC', 1., 2., 2., 4., .1, .2, .1, .01, .5, .4, 10.)
    ledger = Ledger(robot_id=svc.identity.robot_id, boot_id=BOOT_ID,
        profile_revision=limits.revision, max_parents=8, max_children=8, clock=lambda: mono[0])
    binding = install_native_execution(svc, ledger, source_limits=limits)
    assert binding is not None
    svc.state._monotonic = lambda: mono[0]
    svc.state.set_map_id('floor')
    bridge = NS(_svc=svc, _frame_prefix='', _bounded_trial_guard=None, _line_clock=lambda: mono[0],
        _node=NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=ros[0]))))
    return NS(**locals())


def read(r, msg=None):
    receive_odom(r.bridge, message() if msg is None else msg)
    return r.binding.source_snapshot()


def test_original_receipt_exists_before_any_parent_and_is_immutable(source):
    r = source
    assert r.binding.source_snapshot() is None and r.ledger.read().state == 'REQUIRED_WAIT'
    receipt = read(r)
    assert receipt is not None
    assert (receipt.robot_id, receipt.boot_id, receipt.map_id, receipt.epoch) == (
        r.svc.identity.robot_id, BOOT_ID, 'floor', '0')
    assert (receipt.stamp_ns, receipt.source_now_ns, receipt.frame, receipt.child_frame) == (
        1100000000, 1100000000, 'odom', 'base_link')
    assert (receipt.x, receipt.y, receipt.yaw, receipt.linear, receipt.angular) == (.01, 0., 0., .1, 0.)
    assert receipt.before_mono == receipt.after_mono == 10.
    assert receipt.captured_mono < 10. and receipt.expires_mono <= 10.5
    with pytest.raises(FrozenInstanceError): receipt.x = 2.
    assert r.ledger.read().state == 'REQUIRED_WAIT'


def test_repeated_header_keeps_original_expiry_and_expired_receipt_stays_gone(source):
    r = source
    first = read(r)
    r.mono[0] = 10.2
    r.ros[0] = 1300000000
    again = read(r)
    assert again.expires_mono <= first.expires_mono
    r.mono[0] = 10.51
    assert r.binding.source_snapshot() is None
    r.mono[0] = 10.2
    assert r.binding.source_snapshot() is None


def test_slow_read_preserves_original_capture_lower_bound(source):
    r = source
    def slow():
        r.mono[0] = 10.2
        return NS(nanoseconds=1200000000)
    r.bridge._node.get_clock = lambda: NS(now=slow)
    receipt = read(r)
    assert receipt.before_mono == 10. and receipt.after_mono == 10.2
    assert receipt.captured_mono < 9.9 and receipt.expires_mono <= 10.4


def test_pending_read_snapshot_does_not_reinterpret_read_start_as_clock_reversal(source):
    r = source
    entered = []
    def interpose():
        if not entered:
            entered.append(True)
            r.mono[0] = 10.1
            assert r.binding.source_snapshot() is None
            r.mono[0] = 10.2
        return NS(nanoseconds=1200000000)
    r.bridge._node.get_clock = lambda: NS(now=interpose)
    receipt = read(r)
    assert receipt is not None and receipt.before_mono == 10. and receipt.after_mono == 10.2
    assert receipt.expires_mono <= 10.4


def test_snapshot_between_read_end_and_seal_does_not_fault_original_window(source):
    r = source
    cache = r.binding.fence._odometry
    complete = cache.complete
    def interpose(*args, **kwargs):
        assert kwargs['after_mono'] == 10.2
        r.mono[0] = 10.3
        assert r.binding.source_snapshot() is None
        return complete(*args, **kwargs)
    cache.complete = interpose
    entered = []
    def source_clock():
        if not entered:
            entered.append(True)
            r.mono[0] = 10.2
        return NS(nanoseconds=1200000000)
    r.bridge._node.get_clock = lambda: NS(now=source_clock)
    receipt = read(r)
    assert receipt is not None and receipt.after_mono == 10.2 and receipt.expires_mono <= 10.4


@pytest.mark.parametrize('fault', ['replay_changed', 'lateral', 'roll_rate', 'missing_axis',
    'zero_rotation', 'future_stamp', 'foreign_body'])
def test_invalid_original_sample_clears_bootstrap_authority(source, fault):
    r = source
    assert read(r) is not None
    m = message()
    if fault == 'replay_changed': m.twist.twist.linear.x = 0.
    elif fault == 'lateral': m.twist.twist.linear.y = .1
    elif fault == 'roll_rate': m.twist.twist.angular.x = .1
    elif fault == 'missing_axis': del m.twist.twist.linear.y
    elif fault == 'zero_rotation': m.pose.pose.orientation.w = 0.
    elif fault == 'future_stamp': m.header.stamp.sec = 2
    elif fault == 'foreign_body': m.child_frame_id = 'other/base_link'
    assert read(r, m) is None


@pytest.mark.parametrize('first_valid', [False, True])
def test_rejected_new_header_cannot_be_corrected_and_reused(source, first_valid):
    r = source
    if first_valid:
        assert read(r) is not None
    r.ros[0] = 1200000000
    m = message()
    m.header.stamp.nanosec = 200000000
    m.twist.twist.linear.y = .1
    assert read(r, m) is None
    m.twist.twist.linear.y = 0.
    assert read(r, m) is None
    r.ros[0] = 1300000000
    m.header.stamp.nanosec = 300000000
    assert read(r, m) is not None


@pytest.mark.parametrize('change', ['pose', 'map_roundtrip', 'invalid_pose'])
def test_later_state_write_cannot_keep_a_cached_original_receipt(source, change):
    r = source
    assert read(r) is not None
    if change == 'map_roundtrip':
        r.svc.state.set_map_id('other')
        r.svc.state.set_map_id('floor')
    else:
        r.svc.state.set_odom_pose(float('nan') if change == 'invalid_pose' else .01, 0., 0.,
            frame='odom', source_stamp_ns=1100000000)
    assert r.binding.source_snapshot() is None


def test_atomic_write_replaced_before_source_seal_cannot_be_relabelled(source):
    r = source
    original = r.svc.state._record_odom_pose
    def interpose(*args, **kwargs):
        receipt = original(*args, **kwargs)
        original(2., 0., 0., frame='odom', source_stamp_ns=1200000000)
        return receipt
    r.svc.state._record_odom_pose = interpose
    assert read(r) is None


def test_older_read_finishing_last_cannot_replace_newer_source(source):
    r = source
    entered = []
    def interpose():
        if not entered:
            entered.append(True)
            newer = message()
            newer.header.stamp.nanosec = 200000000
            newer.pose.pose.position.x = .02
            r.ros[0] = 1200000000
            receive_odom(r.bridge, newer)
        return NS(nanoseconds=1200000000)
    r.bridge._node.get_clock = lambda: NS(now=interpose)
    receipt = read(r)
    # The old callback's subsequent state write invalidates the newer receipt;
    # neither source may be relabelled to that reversed state epoch.
    assert receipt is None


@pytest.mark.parametrize('bad_clock', [float('nan'), 9.9])
def test_bad_clock_cannot_recover_bootstrap_after_normal_values_return(source, bad_clock):
    r = source
    assert read(r) is not None
    r.mono[0] = bad_clock
    assert r.binding.source_snapshot() is None
    r.mono[0] = 10.
    r.ros[0] = 1200000000
    m = message()
    m.header.stamp.nanosec = 200000000
    assert read(r, m) is None
