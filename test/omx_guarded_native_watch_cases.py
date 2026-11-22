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


def _human_speed(guard, tau, stage, steps=32, speed=60):
    motion, follower, leader, clock, step = _lagging(guard, tau=tau, stage=stage)
    start = follower.raw['shoulder_pan']
    for _ in range(steps):  # the Leader moves at a human's pace: 60 deg/s for 1.6 s (96 degrees, under the 100 degree test)
        leader.raw['shoulder_pan'] += speed * guard.TICKS_PER_DEGREE * 0.05
        step()
    assert not motion.failed
    return (follower.raw['shoulder_pan'] - start) / guard.TICKS_PER_DEGREE, motion


@pytest.mark.parametrize('tau', [0.1, 0.27])
def test_a_staged_session_follows_well_past_the_legacy_speed_ceiling_without_a_stop(guard, tau):
    legacy, _ = _human_speed(guard, tau, None)  # legacy: the lead limit caps the speed at 3 degrees / tau
    staged, motion = _human_speed(guard, tau, 60)
    assert staged > 1.5 * legacy and staged > 15 and not motion.held


@pytest.mark.parametrize('factor', [0.7, 1.3])
def test_a_servo_30_percent_off_the_model_is_followed_without_a_false_stop(guard, factor):
    travel, motion = _human_speed(guard, 0.17 * factor, 60)
    assert travel > 20 and not motion.failed


@pytest.mark.parametrize('tau, push', [(0.17, 8), (0.1, 14)])  # a model that is slower than the servo leaves some slack on the behind side: the push must exceed it
def test_a_joint_pushed_back_off_the_models_path_is_still_stopped(guard, tau, push):
    motion, follower, leader, clock, step = _lagging(guard, tau=tau, stage=60)
    for _ in range(20):
        leader.raw['shoulder_pan'] += 60 * guard.TICKS_PER_DEGREE * 0.05
        step()
    follower.raw['shoulder_pan'] -= push * guard.TICKS_PER_DEGREE  # an outside force
    with pytest.raises(ValueError, match='following error'):
        step()
    assert not any(follower.torque.values())


def test_a_blocked_joint_in_a_staged_session_is_pushed_with_3_degrees_only_and_then_held(guard):
    motion, follower, leader, clock, step = _lagging(guard, stage=60)
    leader.raw['shoulder_lift'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(100):  # 5 s: a measured speed of 0 keeps the allowed lead at 3 degrees however fast the stage is
        step(blocked=('shoulder_lift',))
        assert motion.command['shoulder_lift'] - follower.raw['shoulder_lift'] <= 3 * guard.TICKS_PER_DEGREE + 1.0
    assert motion.held['shoulder_lift']['stall'] and any(follower.torque.values()) and not motion.failed


def test_a_staged_start_aligns_at_10_degrees_per_second_and_the_legacy_start_at_1(guard):
    def aligned_after(stage, limit):
        follower, leader, clock = Bus(), Bus(leader=True), [10.0]
        leader.raw['elbow_flex'] += 20 * guard.TICKS_PER_DEGREE  # the Leader starts 20 degrees away
        motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], label='arm_s', stage=stage)
        motion.send(action(leader))
        for count in range(1, limit + 1):
            clock[0] += 0.05
            motion.send(action(leader))
            follower.raw.update(follower.goals)
            if motion.tracking:
                return count
        return None
    assert 40 <= aligned_after(60, 100) <= 70  # about 2 s of travel at 10 deg/s plus the 0.5 s settle: not 20 s
    assert aligned_after(None, 100) is None  # legacy: 1 degree/s, still aligning after 5 s


def test_following_a_leader_100_degrees_ahead_keeps_the_torque_on_but_a_jump_or_a_start_that_far_still_stops(guard, capsys):
    motion, follower, leader, clock, step = _lagging(guard, stage=60)
    start = follower.raw['wrist_flex']
    leader.raw['wrist_flex'] += 90 * guard.TICKS_PER_DEGREE
    step()
    leader.raw['wrist_flex'] += 60 * guard.TICKS_PER_DEGREE  # 150 degrees ahead of the arm, reached in steps of under 100 degrees
    for _ in range(40):
        step()
    assert not motion.failed and any(follower.torque.values()) and 'wrist_flex' in motion.far
    assert follower.raw['wrist_flex'] > start + 10 * guard.TICKS_PER_DEGREE  # it keeps following at the speed limit
    assert capsys.readouterr().out.count('wrist_flex is 100 degrees or more behind the Leader') == 1
    motion, follower, leader, clock, step = _lagging(guard, stage=60)
    leader.raw['elbow_flex'] += 105 * guard.TICKS_PER_DEGREE  # one tick: the target jumped 100 degrees
    with pytest.raises(ValueError, match='difference >=100'):
        step()
    assert not any(follower.torque.values())
    motion, follower, leader, clock, step = _lagging(guard)  # legacy session: unchanged, 150 degrees ahead in two steps stops
    leader.raw['wrist_flex'] += 90 * guard.TICKS_PER_DEGREE
    step()
    leader.raw['wrist_flex'] += 60 * guard.TICKS_PER_DEGREE
    with pytest.raises(ValueError, match='difference >=100'):
        step()


def test_a_joint_blocked_while_moving_at_stage_60_enters_stall_hold_with_torque_on(guard):
    motion, follower, leader, clock, step = _lagging(guard, tau=0.17, stage=60)
    for _ in range(20):
        leader.raw['shoulder_pan'] += 60 * guard.TICKS_PER_DEGREE * 0.05
        step()
    for _ in range(80):  # blocked mid-motion: must hold with torque ON instead of tripping following error
        leader.raw['shoulder_pan'] += 20 * guard.TICKS_PER_DEGREE * 0.05
        step(blocked=('shoulder_pan',))
    assert motion.held['shoulder_pan']['stall'] and any(follower.torque.values()) and not motion.failed


def test_stage_120_with_a_short_tick_following_the_model_does_not_trip_hard_bound(guard):
    motion, follower, leader, clock, step = _lagging(guard, tau=0.12, stage=120)
    for _ in range(20):
        leader.raw['shoulder_pan'] += 120 * guard.TICKS_PER_DEGREE * 0.05
        step()
    clock[0] += 0.005
    leader.raw['shoulder_pan'] += 120 * guard.TICKS_PER_DEGREE * 0.005
    motion.send(action(leader))
    assert not motion.failed and any(follower.torque.values())


def test_a_joint_blocked_while_moving_at_stage_120_enters_stall_hold_with_torque_on(guard):
    motion, follower, leader, clock, step = _lagging(guard, tau=0.14, stage=120)
    for _ in range(15):
        leader.raw['shoulder_pan'] += 120 * guard.TICKS_PER_DEGREE * 0.05
        step()
    step(blocked=('shoulder_pan',))
    prev_cmd = motion.command['shoulder_pan']
    clock[0] += 0.10  # 100 ms blocked sample pulls back at most 120 deg/s * 0.10 s = 12 deg, then reaches <= 3 deg lead
    leader.raw['shoulder_pan'] = follower.raw['shoulder_pan'] + 8 * guard.TICKS_PER_DEGREE
    motion.send(action(leader))
    assert prev_cmd - motion.command['shoulder_pan'] <= 120 * guard.TICKS_PER_DEGREE * 0.10 + 1e-6
    assert motion.velocity['shoulder_pan'] == 0.0
    step(blocked=('shoulder_pan',))
    assert motion.command['shoulder_pan'] - follower.raw['shoulder_pan'] <= guard.LEAD_DEG * guard.TICKS_PER_DEGREE + 1.0
    for _ in range(80):
        step(blocked=('shoulder_pan',))
    assert motion.held['shoulder_pan']['stall'] and any(follower.torque.values()) and not motion.failed


def test_stage_60_blocked_retraction_stays_within_stage_rate_limit_without_negative_velocity(guard):
    motion, follower, leader, clock, step = _lagging(guard, tau=0.17, stage=60)
    for i in range(26):
        clock[0] += 1 / 30
        leader.raw['shoulder_pan'] += 60 * guard.TICKS_PER_DEGREE / 30
        motion.send(action(leader))
        if i < 24:  # hold follower still for one full sample before measuring blocked tick
            follower.raw['shoulder_pan'] = int(round(motion.lag.advance({'shoulder_pan': follower.goals['shoulder_pan']}, clock[0])['shoulder_pan']))
    prev_cmd = motion.command['shoulder_pan']
    clock[0] += 1 / 30  # second blocked 30 Hz sample sees delta=0, retracts within stage speed with zero velocity
    leader.raw['shoulder_pan'] += 60 * guard.TICKS_PER_DEGREE / 30
    motion.send(action(leader))
    max_tick = 60 * guard.TICKS_PER_DEGREE / 30 + 1e-6
    assert abs(motion.command['shoulder_pan'] - prev_cmd) <= max_tick
    assert motion.velocity['shoulder_pan'] == 0.0
    clock[0] += 1 / 30  # subsequent unblocked tick does not dip behind current
    follower.raw['shoulder_pan'] += 10
    leader.raw['shoulder_pan'] += 60 * guard.TICKS_PER_DEGREE / 30
    motion.send(action(leader))
    assert motion.command['shoulder_pan'] >= follower.raw['shoulder_pan'] and not motion.failed


def test_restart_after_pause_clears_stale_lag_speed_so_first_tick_uses_3_deg_lead(guard):
    motion, follower, leader, clock, step = _lagging(guard, tau=0.17, stage=60)
    for _ in range(15):
        leader.raw['shoulder_pan'] += 60 * guard.TICKS_PER_DEGREE * 0.05
        step()
    assert motion.lag.speed['shoulder_pan'] > 10.0
    guard.restart_after_pause(motion, clock[0] + 5.0)
    assert motion.lag.speed == {} and motion.lag.delta == {} and motion.lag.blocked_since == {}
    assert motion.lag.lead_ticks('shoulder_pan', guard.LEAD_DEG) == pytest.approx(guard.LEAD_DEG * guard.TICKS_PER_DEGREE)


def test_smooth_twist_past_calibrated_end_clamps_while_tracking_without_torque_cut(guard, capsys):
    motion, follower, leader, clock, step = _lagging(guard, stage=90)
    follower.calibration['wrist_roll'].range_max = 2120
    leader.calibration['wrist_roll'].range_max = 2120
    for _ in range(5):  # 2028 -> 2178 smoothly past 2120 while tracking
        leader.raw['wrist_roll'] += 30
        step()
    assert not motion.failed and any(follower.torque.values())
    assert motion.prev_target['wrist_roll'] == 2120 and motion.prev_mapped['wrist_roll'] == leader.raw['wrist_roll']
    assert follower.goals['wrist_roll'] <= 2120
    assert capsys.readouterr().out.count('wrist_roll clamped at follower calibrated end (2120)') == 1
    # Smoothly move >100 deg past follower actual end then twist back inside calibrated range
    for _ in range(25):
        leader.raw['wrist_roll'] += 60
        step()
    assert not motion.failed and 'wrist_roll' in motion.clamped
    while leader.raw['wrist_roll'] > 2090:
        leader.raw['wrist_roll'] -= 80
        step()
    assert not motion.failed and 'wrist_roll' not in motion.clamped
    # Restart after pause resets prev_mapped and clamped tracking state
    leader.raw['wrist_roll'] = 2160
    step()
    assert 'wrist_roll' in motion.clamped
    guard.restart_after_pause(motion, clock[0] + 1.0)
    assert motion.prev_mapped is None and motion.clamped == set()


def test_single_tick_wrap_jump_and_untracking_and_follower_range_exit_still_fail_closed(guard):
    # 1) Single-tick >=100 deg wrap jump while tracking still fails closed (at 100-deg check and validate_targets)
    motion, follower, leader, clock, step = _lagging(guard, stage=90)
    follower.calibration['wrist_roll'].range_max = 2120
    leader.calibration['wrist_roll'].range_max = 2120
    leader.raw['wrist_roll'] += int(105 * guard.TICKS_PER_DEGREE)
    with pytest.raises(ValueError, match=r'difference >=100|outside calibrated range'):
        step()
    assert not any(follower.torque.values())
    with pytest.raises(ValueError, match='outside calibrated range'):
        guard.validate_targets(
            SimpleNamespace(follower=follower, leader=leader, full_arm=True, teacher=False, body_only=False,
                            command={'wrist_roll': 2100}, tracking=True, floor={}, prev_mapped={'wrist_roll': 2090},
                            clamped=set(), label='arm_s', grip_map=None),
            dict(leader.raw, wrist_roll=3250), dict(leader.raw, wrist_roll=3250),
            dict(leader.raw, wrist_roll=3250), follower.raw,
        )

    # 2) Startup (command is None), alignment (not tracking), body_only, and follower actual current still fail closed
    f0, l0 = Bus(), Bus(leader=True)
    f0.raw['wrist_roll'], l0.raw['wrist_roll'] = 3900, 4150
    with pytest.raises(ValueError, match='outside calibrated range'):
        guard.NativeJointMotion(f0, l0).prepare(action(l0))
    f1, l1 = Bus(), Bus(leader=True)
    f1.raw['wrist_roll'] = l1.raw['wrist_roll'] = 3900
    m_align = guard.NativeJointMotion(f1, l1, stage=90)
    m_align.send(action(l1))
    assert not m_align.tracking
    l1.raw['wrist_roll'] = 4150
    with pytest.raises(ValueError, match='outside calibrated range'):
        m_align.send(action(l1))
    assert not any(f1.torque.values())
    f2, l2 = Bus(), Bus(leader=True)
    f2.raw['wrist_roll'] = l2.raw['wrist_roll'] = 3900
    m_body = guard.NativeJointMotion(f2, l2, body_only=True)
    m_body.send(action(l2))
    m_body.tracking = True
    l2.raw['wrist_roll'] = 4150
    with pytest.raises(ValueError, match='outside calibrated range'):
        m_body.send(action(l2))
    motion2, follower2, leader2, _, step2 = _lagging(guard, stage=90)
    follower2.calibration['wrist_roll'].range_max = 2030
    follower2.raw['wrist_roll'] = 2035  # within 5 deg of command=2028 so check_following passes and validate_targets rejects
    with pytest.raises(ValueError, match='outside calibrated range'):
        step2()
    assert not any(follower2.torque.values())

    # 3) Smooth gripper trigger excursion while tracking clamps safely instead of cutting torque
    motion3, follower3, leader3, _, step3 = _lagging(guard, stage=90)
    leader3.calibration['gripper'].range_max = 2060
    leader3.raw['gripper'] = 2075
    step3()
    assert not motion3.failed and 'gripper' in motion3.clamped and any(follower3.torque.values())
