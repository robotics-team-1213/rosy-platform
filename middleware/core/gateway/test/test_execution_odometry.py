"""Original odom -> actual CORE budget -> sole writer; synthetic profile only."""
from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from core.bridge import odometry
from core_features.command._execution_budget import Budget, Pose
from core_features.command.manager import Twist
from test_native_execution_binding import robot, start_nav, wheels  # noqa: F401


def message():
    return NS(header=NS(frame_id='odom', stamp=NS(sec=1, nanosec=100000000)),
        child_frame_id='base_link', pose=NS(pose=NS(position=NS(x=.01, y=0., z=0.),
        orientation=NS(x=0., y=0., z=0., w=1.))),
        twist=NS(twist=NS(linear=NS(x=.1, y=0., z=0.), angular=NS(x=0., y=0., z=0.))))


def bridge(r):
    return NS(_svc=r.svc, _frame_prefix='', _bounded_trial_guard=None,
        _line_clock=lambda: r.clock[0], _node=NS(get_clock=lambda: NS(
            now=lambda: NS(nanoseconds=1100000000))))


def receive(b, msg):
    return odometry.receive_odom(b, msg, station=None)


def test_original_sample_updates_actual_budget_without_resetting_window(robot):
    r = robot
    start_nav(r)
    r.clock[0] = 10.1
    sample = receive(bridge(r), message())
    assert sample['x'] == .01
    assert r.budget._pose == Pose(1100000000, 1100000000, 'odom', '0', .01, 0.)
    assert r.budget._start == 10. and r.budget._duration == 10.
    assert r.ledger.read().state == 'ACTIVE'
    assert wheels(r) == [Twist(.1, 0.)]


@pytest.mark.parametrize('fault', ['stamp_bool', 'negative_sec', 'bad_ns', 'foreign_frame',
    'foreign_body', 'zero_quaternion', 'tilted_body', 'nan_position', 'future_stamp'])
def test_invalid_original_input_closes_same_final_writer(robot, fault):
    r = robot
    start_nav(r)
    r.clock[0] = 10.1
    m = message()
    if fault == 'stamp_bool': m.header.stamp.sec = True
    elif fault == 'negative_sec': m.header.stamp.sec = -1
    elif fault == 'bad_ns': m.header.stamp.nanosec = 1000000000
    elif fault == 'foreign_frame': m.header.frame_id = 'other/odom'
    elif fault == 'foreign_body': m.child_frame_id = 'other/base_link'
    elif fault == 'zero_quaternion': m.pose.pose.orientation.w = 0.
    elif fault == 'tilted_body': m.pose.pose.orientation = NS(x=.6, y=0., z=0., w=.8)
    elif fault == 'nan_position': m.pose.pose.position.x = float('nan')
    elif fault == 'future_stamp': m.header.stamp.sec = 2
    receive(bridge(r), m)
    assert wheels(r) == [Twist()]
    assert r.ledger.read().state == 'STOPPED'


def test_replayed_original_cannot_renew_capture_or_hide_missing_source(robot):
    r = robot
    start_nav(r)
    b = bridge(r)
    r.clock[0] = 10.1
    receive(b, message())
    capture = r.budget._capture_mono
    r.clock[0] = 10.2
    receive(b, message())
    assert r.budget._capture_mono <= capture
    r.clock[0] = 10.51
    assert wheels(r) == [Twist()]
    assert r.ledger.read().state == 'STOPPED'


def test_source_clock_and_read_latency_preserve_original_lower_bound(robot):
    r = robot
    start_nav(r)
    b = bridge(r)
    b._line_clock = lambda: 777.
    r.svc.state._monotonic = lambda: 888.
    r.clock[0] = 10.1
    def slow_source():
        r.clock[0] = 10.2
        return NS(nanoseconds=1150000000)
    b._node.get_clock = lambda: NS(now=slow_source)
    receive(b, message())
    assert r.budget._capture_mono < 10.05
    assert r.budget._last_read_end == 10.2
    assert r.budget._start == 10.


def test_actual_callback_delegates_translation_to_original_read_adapter():
    """Narrow wiring guard; callback values are tested in the ROS-free adapter."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parents[1] / 'core/bridge/ros_bridge.py').read_text(encoding='utf-8'))
    callback = next(node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == '_on_odom')
    sample = next(node for node in callback.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'sample' for target in node.targets))
    assert isinstance(sample.value, ast.Call)
    assert ast.unparse(sample.value.func) == 'odometry.receive_odom'
    assert not any(isinstance(node, ast.Attribute) and node.attr == 'odom_sample'
        for node in ast.walk(callback))


def test_atomic_state_receipt_does_not_relabel_older_sample_with_later_epoch(robot):
    r = robot
    b = bridge(r)
    original = r.svc.state._record_odom_pose
    def intervening(*args, **kwargs):
        receipt = original(*args, **kwargs)
        r.svc.state.set_odom_pose(2., 0., 0., frame='odom', source_stamp_ns=1200000000)
        return receipt
    r.svc.state._record_odom_pose = intervening
    # Avoid recursion through the compatibility wrapper for the intervening write.
    r.svc.state.set_odom_pose = lambda *args, **kwargs: original(*args, **kwargs)
    r.clock[0] = 10.1
    receive(b, message())
    assert r.svc.state.station_scope(max_age_s=1., wait=True)['odom_epoch'] == '1'
    assert r.budget._pose.epoch == '0' and r.budget._pose.x == .01


@pytest.mark.parametrize('source_error', [False, True])
def test_slow_old_read_cannot_observe_or_stop_replacement_parent(robot, source_error):
    r = robot
    b = bridge(r)
    r.clock[0] = 10.1
    replacement = []
    def replace_parent():
        if replacement:
            return NS(nanoseconds=1100000000)
        assert r.binding.fence.stop(r.parent, 'explicit-test-boundary')
        assert r.binding.fence.retire(r.parent)
        pose = Pose(1050000000, 1050000000, 'odom', '0', 0., 0.)
        budget = Budget(limits=r.limits, initial=pose, before_mono=10.1, after_mono=10.1,
            now_utc=100.1, captured_utc=100., admit_until_utc=100.2,
            duration_s=10., path_m=10., rotation_rad=20., radius_m=5.)
        parent = r.binding.fence.admit(replace(r.identity, parent_id=uuid4()), budget)
        assert parent is not None
        replacement.append(parent)
        if source_error: raise ValueError('source read failed after replacement')
        return NS(nanoseconds=1100000000)
    b._node.get_clock = lambda: NS(now=replace_parent)
    receive(b, message())
    parent = replacement[0]
    assert r.ledger._current is parent and r.ledger.read().state == 'ACTIVE'
    assert parent.budget._pose.stamp_ns == 1050000000


def test_state_discontinuity_stops_original_parent(robot):
    r = robot
    start_nav(r)
    r.svc.state.set_odom_pose(1., 0., 0., frame='odom', source_stamp_ns=1000000000)
    r.clock[0] = 10.1
    receive(bridge(r), message())
    assert wheels(r) == [Twist()]
    assert r.ledger.read().state == 'STOPPED'
