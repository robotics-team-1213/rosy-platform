import json
import sys
from omx_guarded_native_late_cases import (
    Bus, Monitor, SimpleNamespace, action, pair, pytest, _lagging, _loop_module, _watched,
)

def test_an_overrun_at_the_calibrated_range_end_is_held_there_not_cut(guard):
    motion, follower, leader, clock, step = _lagging(guard, stage=60)
    follower.calibration['shoulder_pan'].range_max = 2050
    motion.command['shoulder_pan'] = 2053.0  # an overrun: the command already sits past the range end (the arm is at it)
    follower.raw['shoulder_pan'] = 2050
    leader.raw['shoulder_pan'] = 2050
    step()
    assert motion.command['shoulder_pan'] == 2050 and follower.goals['shoulder_pan'] == 2050 and not motion.failed and any(follower.torque.values())


def test_a_failed_status_read_in_the_pause_is_not_a_fault_but_a_confirmed_one_still_cuts(guard):
    watch_module, watch, motion, follower = _watched(guard)
    asked, base = [], follower.read
    watch.on_expire = lambda: asked.append(1)

    def read(register, motor, **kw):
        if register == 'Present_PWM' and motor == 'wrist_roll':
            raise OSError('packet error after retries')
        return base(register, motor, **kw)
    follower.read = read
    watch.check(1.0)  # no raise, no cut: the healthy over-bound path
    assert watch.expired and motion.failed and asked == [1] and 'packet error' in str(watch.read_failure) and any(follower.torque.values())
    follower.read = lambda register, motor, **kw: 32 if (register == 'Hardware_Error_Status' and motor == 'elbow_flex') else read(register, motor, **kw)
    with pytest.raises(ValueError, match='elbow_flex: hardware error'):  # a confirmed condition read from the motor still cuts
        watch.check(2.0)


def test_the_single_arm_loop_ends_with_a_read_failure_message_and_keeps_the_torque(guard, monkeypatch):
    class Watch:
        expired = True

        def __init__(self, motion, on_expire=None):
            self.fault_exc, self.read_failure = None, RuntimeError('unreadable')

        def start(self):
            pass

        def stop(self):
            return True
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, Watch)
    with pytest.raises(KeyboardInterrupt, match='could not read the arm'):
        guard.run_native(module, Follower, Leader)
    assert ran == [1]


def _saturating(guard, period=0.5):
    import guarded_native_watch as watch_module
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    state = {'fail': False, 'sat': True}
    base = follower.read

    def read(register, motor, **kw):
        if register == 'Temperature_Limit':
            return 70
        if state['fail'] and motor == 'shoulder_lift':
            raise OSError('packet error after retries')
        if register == 'Present_PWM' and motor == 'shoulder_lift' and state['sat']:
            return 330
        return base(register, motor, **kw)
    follower.read = read
    return watch_module.BoundaryWatch(motion, period_s=period, on_expire=lambda: None), motion, follower, state


def test_pwm_saturation_in_the_pause_never_cuts_torque_in_any_timing_it_ends_the_session_closed(guard):
    for times in ([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5], [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 5.0], [0.0, 10.0, 20.0]):  # continuous, a delayed read, sparse
        watch, motion, follower, state = _saturating(guard)
        writes, asked = [], []
        follower.disable_torque = lambda *a, **k: writes.append(a)
        watch.on_expire = lambda: asked.append(1)
        for t in times:
            watch.check(t)  # never raises for saturation
        assert writes == [] and any(follower.torque.values())
    watch, motion, follower, state = _saturating(guard)  # HOLD_S of this watch's own samples: the fail-closed ending, reported
    asked = []
    watch.on_expire = lambda: asked.append(1)
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        watch.check(t)
    assert watch.pause_saturated.startswith('pause_saturated') and watch.expired and motion.failed and asked == [1] and watch.fault_exc is None
    assert any(follower.torque.values())


def test_the_watch_still_cuts_for_a_hardware_error_and_for_the_temperature_limit(guard):
    watch_module, watch, motion, follower = _watched(guard)
    base = follower.read
    follower.read = lambda register, motor, **kw: 32 if (register == 'Hardware_Error_Status' and motor == 'elbow_flex') else base(register, motor, **kw)
    with pytest.raises(ValueError, match='elbow_flex: hardware error'):
        watch.check(1.0)
    follower.read = base
    follower.temps['wrist_flex'] = 70
    with pytest.raises(ValueError, match='wrist_flex: temperature'):
        watch.check(1.0)


def test_the_loops_saturation_clocks_start_fresh_after_a_pause(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    motion.effort_since['elbow_flex'] = 5.0
    motion.held['shoulder_lift'] = {'since': 0.0, 'saturated_since': 1.0, 'temp': 30}
    motion.squeeze['gripper'] = {'since': 0.0, 'saturated_since': 2.0, 'temp': 30}
    guard.restart_after_pause(motion, 50.0)
    assert motion.effort_since['elbow_flex'] is None and motion.held['shoulder_lift']['saturated_since'] is None
    assert motion.squeeze['gripper']['saturated_since'] is None


def test_the_loops_end_with_the_pause_saturated_reason_and_keep_the_torque(guard, monkeypatch):
    class Watch:
        expired = True

        def __init__(self, motion, on_expire=None):
            self.fault_exc, self.read_failure, self.pause_saturated = None, None, 'pause_saturated: arm_s shoulder_lift'

        def start(self):
            pass

        def stop(self):
            return True
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, Watch)
    with pytest.raises(KeyboardInterrupt, match='pause_saturated'):
        guard.run_native(module, Follower, Leader)
    assert ran == [1]


def _end_run(guard, monkeypatch, tmp_path, watch_class=None, raises=None):
    monkeypatch.chdir(tmp_path)  # the recorder's cwd is the session folder
    class Quiet:
        expired = False
        fault_exc = read_failure = pause_saturated = None

        def __init__(self, motion, on_expire=None):
            pass

        def start(self):
            pass

        def stop(self):
            return True
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, watch_class or Quiet)
    if raises is not None:
        def main():
            raise raises
        module.main = main
    return module, Follower, Leader


def _reason(tmp_path):
    import json
    path = tmp_path / 'guard-end.json'
    return json.loads(path.read_text(encoding='utf-8'))['reason'] if path.exists() else None


@pytest.mark.parametrize('attrs, expected', [({'pause_saturated': 'pause_saturated: x'}, 'pause_saturated'), ({'read_failure': RuntimeError('r')}, 'pause_read_failure'), ({}, 'pause_over_bound')])
def test_a_fail_closed_pause_end_leaves_its_reason_for_the_bench_even_if_lerobot_would_end_normally(guard, monkeypatch, tmp_path, attrs, expected):
    class Watch:
        expired, fault_exc, read_failure, pause_saturated = True, None, None, None

        def __init__(self, motion, on_expire=None):
            self.on_expire = on_expire
            for key, value in attrs.items():
                setattr(self, key, value)

        def start(self):
            self.on_expire()  # the watch asked the session to end

        def stop(self):
            return True
    module, Follower, Leader = _end_run(guard, monkeypatch, tmp_path, Watch)
    with pytest.raises(KeyboardInterrupt):
        guard.run_native(module, Follower, Leader)
    assert _reason(tmp_path) == expected


def test_a_guard_fault_or_any_exception_leaves_a_reason_and_a_user_stop_or_a_clean_end_does_not(guard, monkeypatch, tmp_path):
    module, Follower, Leader = _end_run(guard, monkeypatch, tmp_path, raises=ValueError('shoulder_lift: following error'))
    with pytest.raises(ValueError):
        guard.run_native(module, Follower, Leader)
    assert _reason(tmp_path).startswith('exception: ValueError')
    (tmp_path / 'guard-end.json').unlink()
    module, Follower, Leader = _end_run(guard, monkeypatch, tmp_path, raises=KeyboardInterrupt())  # a plain SIGTERM/Ctrl-C: the user's stop
    with pytest.raises(KeyboardInterrupt):
        guard.run_native(module, Follower, Leader)
    assert _reason(tmp_path) is None
    module, Follower, Leader = _end_run(guard, monkeypatch, tmp_path)  # the planned end
    guard.run_native(module, Follower, Leader)
    assert _reason(tmp_path) is None


def test_a_watch_fault_found_at_the_next_loop_leaves_guard_fault(guard, monkeypatch, tmp_path):
    class Watch:
        expired = False

        def __init__(self, motion, on_expire=None):
            self.fault_exc, self.read_failure, self.pause_saturated = None, None, None

        def start(self):
            pass

        def stop(self):
            self.fault_exc = ValueError('arm_s elbow_flex: hardware error')
            return True
    module, Follower, Leader = _end_run(guard, monkeypatch, tmp_path, Watch)
    with pytest.raises(RuntimeError, match='pause watch fault'):
        guard.run_native(module, Follower, Leader)
    assert _reason(tmp_path).startswith('guard_fault: arm_s elbow_flex')
