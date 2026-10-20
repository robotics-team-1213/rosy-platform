"""Cached TF must not become a new map coordinate on every state timer tick."""
import ast
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from core.bridge.odometry import odom_owns_pose
from core_features.state.manager import StateManager


def transform(stamp_ns=19500000000, x=1.):
    return NS(header=NS(frame_id='map', stamp=NS(sec=stamp_ns//1000000000,
        nanosec=stamp_ns % 1000000000)), child_frame_id='unit/base_footprint',
        transform=NS(translation=NS(x=x, y=2., z=0.), rotation=NS(x=0., y=0., z=0., w=1.)))


@pytest.fixture
def pose(core_client):
    from core.bridge.map_pose import MapPoseLease
    _, svc = core_client()
    wall, state_mono = [100.], [50.]
    assert type(svc.state) is StateManager
    svc.state._clock = lambda: wall[0]
    svc.state._monotonic = lambda: state_mono[0]
    svc.state.set_pose(-5., -6., 0., frame='odom')
    line, ros = [10.], [20000000000]
    bridge = NS(_svc=svc, _map_frame='map', _base_frame='unit/base_footprint',
        _map_pose_ts=float('-inf'), _map_pose_lease=MapPoseLease(), _line_clock=lambda: line[0],
        _node=NS(get_clock=lambda: NS(now=lambda: NS(nanoseconds=ros[0]))))
    return NS(**locals())


def receive(r, value=None, lookup=None):
    from core.bridge.map_pose import receive_map_pose
    return receive_map_pose(r.bridge, (lambda: transform() if value is None else value) if lookup is None else lookup)


def test_fresh_transform_keeps_its_original_source_age_in_real_state(pose):
    r = pose
    assert receive(r)
    assert r.svc.state.pose_sample()[:4] == (1., 2., 0., 'map')
    assert r.bridge._map_pose_ts <= 9.5
    assert not odom_owns_pose(r.bridge._map_pose_ts, r.line[0])
    assert r.svc.state.pose_sample()[4] >= .5


def test_old_transform_lookup_success_cannot_publish_a_current_map_coordinate(pose):
    r = pose
    assert not receive(r, transform(10000000000))
    assert r.svc.state.pose_sample()[:4] == (-5., -6., 0., 'odom')
    assert odom_owns_pose(r.bridge._map_pose_ts, r.line[0])


def test_same_tf_timestamp_does_not_renew_when_ros_clock_stalls(pose):
    r = pose
    assert receive(r)
    original = r.bridge._map_pose_ts
    r.line[0] = 10.6  # Source clock and cached transform remain unchanged.
    r.wall[0] += .6
    r.state_mono[0] += .6
    assert receive(r)
    assert r.bridge._map_pose_ts <= original
    assert r.svc.state.pose_sample()[4] >= 1.1
    r.line[0] = 11.5
    assert not receive(r) and odom_owns_pose(r.bridge._map_pose_ts, r.line[0])
    assert r.svc.state.pose_sample()[4] == float('inf')  # No odom callback is required.
    assert r.svc.state.snapshot().evidence['pose'].evidence.value != 'fresh'


def test_slow_lookup_counts_original_source_age_and_the_entire_read(pose):
    r = pose
    def lookup():
        r.line[0] = 11.
        r.ros[0] = 20500000000
        return transform()
    assert not receive(r, lookup=lookup)  # 1 s source age + 1 s read reaches the 2 s bound.
    assert r.svc.state.pose_sample()[:4] == (-5., -6., 0., 'odom')


def test_repeated_tf_does_not_renew_state_receipt_when_sim_clock_is_paused(pose):
    r = pose
    assert receive(r)
    r.wall[0] += .6
    r.state_mono[0] += .6
    assert receive(r)
    assert r.svc.state.pose_sample()[4] >= 1.1


def test_lookup_failure_does_not_renew_the_original_grace_window(pose):
    r = pose
    assert receive(r)
    original = r.bridge._map_pose_ts
    def missing(): raise LookupError('no TF path')
    r.line[0] = 10.5
    assert not receive(r, lookup=missing)
    assert r.bridge._map_pose_ts <= original
    assert not odom_owns_pose(r.bridge._map_pose_ts, r.line[0])
    r.line[0] = 11.6
    assert odom_owns_pose(r.bridge._map_pose_ts, r.line[0])


@pytest.mark.parametrize('fault', ['future', 'bool_stamp', 'zero_stamp', 'frame', 'child',
                                  'nan_pose', 'zero_rotation', 'nonplanar', 'height'])
def test_invalid_original_transform_cannot_update_pose_or_keep_map_ownership(pose, fault):
    r = pose
    m = transform()
    if fault == 'future': m.header.stamp.sec = 21
    elif fault == 'bool_stamp': m.header.stamp.sec = True
    elif fault == 'zero_stamp': m.header.stamp.sec = m.header.stamp.nanosec = 0
    elif fault == 'frame': m.header.frame_id = 'other/map'
    elif fault == 'child': m.child_frame_id = 'other/base_footprint'
    elif fault == 'nan_pose': m.transform.translation.x = float('nan')
    elif fault == 'zero_rotation': m.transform.rotation.w = 0.
    elif fault == 'nonplanar': m.transform.rotation.x = 1.
    elif fault == 'height': m.transform.translation.z = .5
    assert not receive(r, m)
    assert r.svc.state.pose_sample()[:4] == (-5., -6., 0., 'odom')
    assert odom_owns_pose(r.bridge._map_pose_ts, r.line[0])


@pytest.mark.parametrize('fault', ['line_reverse', 'line_nan', 'source_reverse'])
def test_observed_clock_fault_cannot_revive_when_normal_values_return(pose, fault):
    r = pose
    assert receive(r)
    if fault == 'line_reverse': r.line[0] = 9.9
    elif fault == 'line_nan': r.line[0] = float('nan')
    else:
        r.line[0] = 10.1
        r.ros[0] = 19900000000
    assert not receive(r)
    assert odom_owns_pose(r.bridge._map_pose_ts, r.line[0])
    r.line[0], r.ros[0] = 10.2, 20200000000
    assert not receive(r, transform(20200000000))
    assert odom_owns_pose(r.bridge._map_pose_ts, r.line[0])


def test_fresh_new_transform_can_recover_after_normal_expiry(pose):
    r = pose
    assert receive(r)
    r.line[0], r.ros[0] = 12., 22000000000
    assert not receive(r)
    assert receive(r, transform(22000000000, x=3.))
    assert r.svc.state.pose_sample()[:4] == (3., 2., 0., 'map')


def test_old_lookup_finishing_last_cannot_replace_a_new_coordinate(pose):
    r = pose
    def lookup():
        assert receive(r, transform(20000000000, x=3.))
        return transform(x=1.)
    assert not receive(r, lookup=lookup)
    assert r.svc.state.pose_sample()[:4] == (3., 2., 0., 'map')


def test_invalid_map_read_does_not_invalidate_fresh_odom_state(pose):
    r = pose
    assert not receive(r, transform(10000000000))
    assert r.svc.state.pose_sample()[4] == 0.


@pytest.mark.parametrize('delivery', ['map', 'lifecycle'])
def test_map_delivery_during_lookup_discards_late_tf_and_requires_new_source(pose, delivery):
    from core.bridge import map_observation
    r = pose
    assert receive(r)
    def lookup():
        if delivery == 'map':
            assert not map_observation.receive_map(r.bridge, NS(), warn=lambda _: None)
        else:
            map_observation.lifecycle(r.bridge, False)
        return transform()
    assert not receive(r, lookup=lookup)
    assert r.svc.state.pose_sample()[4] == float('inf')
    assert not receive(r)  # Cached TF cannot re-enter after the map event.
    r.line[0], r.ros[0] = 10.1, 20100000000
    assert receive(r, transform(20100000000))


def test_expired_original_tf_refuses_subsequent_localization_admission(pose):
    r = pose
    r.svc.localization.on_state('{"status":{"state":"LOCALIZED","pose_frame":"map"}}')
    assert receive(r)
    r.svc.localization.tick(odom_owns_pose(r.bridge._map_pose_ts, r.line[0]))
    assert r.svc.localization.autonomy_allowed()
    r.line[0], r.ros[0] = 12., 22000000000
    assert not receive(r)
    r.svc.localization.tick(odom_owns_pose(r.bridge._map_pose_ts, r.line[0]))
    assert not r.svc.localization.autonomy_allowed()


def test_expired_original_tf_stops_existing_navigation_before_next_wheel_output(pose):
    import time
    from core.bridge.cmd_vel import cmd_vel_cycle
    from core_features.command.arbitration import Mode
    from core_features.command.manager import Twist
    from core_features.navigation.manager import NavGoalSpec
    r = pose
    assert receive(r)
    r.svc.localization.on_state('{"status":{"state":"LOCALIZED","pose_frame":"map"}}')
    r.svc.localization.tick(odom_owns_pose(r.bridge._map_pose_ts, r.line[0]))
    cancels = []
    r.svc.nav.executor = NS(send_goal=lambda *a, **kw: None, cancel_goal=lambda: cancels.append(True))
    assert r.svc.modes.transition(Mode.NAVIGATION)[0]
    r.svc.nav.goal(NavGoalSpec(1., 0., 0.))
    r.svc.command.set_nav_twist(Twist(.1, 0.), now=time.monotonic())
    written = []
    cmd_vel_cycle(r.svc.command, NS(on_activity=lambda _: None), written.append)
    assert written == [Twist(.1, 0.)]
    # No odom callback or localization-state change arrives. Original TF expires.
    r.line[0], r.ros[0] = 12., 22000000000
    assert not receive(r)
    r.svc.localization.tick(odom_owns_pose(r.bridge._map_pose_ts, r.line[0]))
    assert not r.svc.localization.autonomy_allowed() and cancels
    written.clear()
    cmd_vel_cycle(r.svc.command, NS(on_activity=lambda _: None), written.append)
    assert written == [Twist()] and r.svc.modes.mode is Mode.IDLE


@pytest.mark.parametrize('phase', [1, 2, 3])
def test_slow_source_clock_read_counts_the_final_line_clock(pose, phase):
    r = pose
    reads = [0]
    def now():
        reads[0] += 1
        if reads[0] == phase:
            r.line[0] = 12.
        return NS(nanoseconds=r.ros[0])
    r.bridge._node = NS(get_clock=lambda: NS(now=now))
    assert not receive(r)
    assert r.svc.state.pose_sample()[:4] == (-5., -6., 0., 'odom')
    assert odom_owns_pose(r.bridge._map_pose_ts, r.line[0])


@pytest.mark.parametrize('delay', [.1, 2.])
def test_state_lock_wait_preserves_original_capture_and_rechecks_expiry(pose, delay):
    r = pose
    waiting = threading.Event()
    result = []
    def wall():
        waiting.set()
        return r.wall[0]
    r.svc.state._clock = wall
    worker = threading.Thread(target=lambda: result.append(receive(r)), daemon=True)
    r.svc.state._lock.acquire()
    try:
        worker.start()
        assert waiting.wait(2.)
        r.line[0] += delay
        r.ros[0] += int(delay*1000000000)
        r.wall[0] += delay
        r.state_mono[0] += delay
    finally:
        r.svc.state._lock.release()
    worker.join(2.)
    assert not worker.is_alive()
    assert result == [delay < 1.]
    if delay < 1.:
        assert r.svc.state.pose_sample()[4] >= .5+delay
    else:
        assert r.svc.state.pose_sample()[:4] == (-5., -6., 0., 'odom')
        assert odom_owns_pose(r.bridge._map_pose_ts, r.line[0])


@pytest.mark.parametrize('stamp,now', [(float('-inf'), float('nan')), (9., float('inf')),
                                    (float('nan'), 10.), (11., 10.)])
def test_invalid_pose_clock_never_keeps_map_ownership(stamp, now):
    assert odom_owns_pose(stamp, now)


def test_state_timer_delegates_before_localization_without_retimestamping_inline():
    tree = ast.parse((Path(__file__).parents[1]/'core/bridge/ros_bridge.py').read_text(encoding='utf-8'))
    tick = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_tick_state')
    assert any(isinstance(n, ast.Call) and ast.unparse(n.func) == 'map_pose.receive_map_pose'
               for n in ast.walk(tick))
    assert not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == '_map_pose_ts'
                   for t in n.targets) for n in ast.walk(tick))
