from test_omx_guarded_native import *

@pytest.mark.parametrize("mode", ["record", "teleoperate"])
def test_native_routes_use_passive_factories_store_sent_commands_and_cleanup(guard, mode, monkeypatch):
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))
    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)

    follower, leader = Follower(), Leader()
    leader.bus.raw["wrist_roll"] += 100
    frames = []
    module = SimpleNamespace(
        make_robot_from_config=lambda config: follower,
        make_teleoperator_from_config=lambda config: leader,
        ACTION="action",
        build_dataset_frame=lambda features, values, prefix: frames.append((prefix, values)) or values)

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        # Native recording connects robot first; teleoperate connects leader first.
        for device in ((robot, teleop) if mode == "record" else (teleop, robot)):
            device.connect()
        assert not any(robot.bus.torque.values()) and not any(teleop.bus.torque.values())
        desired = action(leader.bus)
        sent = robot.send_action(desired)
        sent = robot.send_action(desired)
        assert sent != desired
        recorded = module.build_dataset_frame({}, desired, prefix="action")
        assert recorded == sent
        raise KeyboardInterrupt

    module.main = main
    with pytest.raises(KeyboardInterrupt):
        guard.run_native(module, Follower, Leader)
    assert not follower.bus.is_connected and not leader.bus.is_connected
    assert not any(follower.bus.torque.values()) and not any(leader.bus.torque.values())
    assert [event[0] for event in monitor.events] == ['admit', 'sample', 'fault']
    assert isinstance(monitor.events[-1][2], KeyboardInterrupt)


class Monitor:
    def __init__(self):
        self.events = []

    def admit(self, motion):
        assert not any(motion.follower.torque.values())
        self.events.append(('admit', motion))

    def sample(self, motion, current, pwm, now):
        self.events.append(('sample', motion, dict(current), dict(pwm), now))

    def fault(self, motion, exc):
        assert not any(motion.follower.torque.values())  # OFF happens before potentially slow logging
        self.events.append(('fault', motion, exc))


@pytest.mark.parametrize('phase', ['admit', 'sample'])
@pytest.mark.parametrize('failure', ['latency', 'exception'])
def test_monitor_io_fails_closed_before_any_next_command_and_reports_after_off(guard, phase, failure):
    follower, leader, clock, monitor = Bus(), Bus(leader=True), [10.0], Monitor()
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], monitor=monitor)
    if phase == 'sample':
        motion.send(action(leader))
    def fail(*args):
        if failure == 'exception':
            raise OSError('monitor write failed')
        clock[0] += 0.6
    setattr(monitor, phase, fail)
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises((ValueError, OSError), match='stale|monitor write failed'):
        motion.send(action(leader))
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values()) and motion.failed
    assert monitor.events[-1][0] == 'fault'


@pytest.mark.parametrize('failure', [OSError('fault log unavailable'), KeyboardInterrupt(), SystemExit(2)])
def test_monitor_fault_logging_failure_preserves_original_guard_error(guard, failure):
    follower, leader, monitor = Bus(), Bus(leader=True), Monitor()
    def failed_log(motion, exc):
        assert not any(follower.torque.values())
        raise failure
    monitor.fault = failed_log
    motion = guard.NativeJointMotion(follower, leader, monitor=monitor)
    leader.raw['wrist_roll'] += 1200
    with pytest.raises(ValueError, match='difference >=100'):
        motion.send(action(leader))
    assert not any(follower.torque.values())


def test_a_leader_mounted_half_a_turn_round_states_it_and_keeps_the_100_degree_guard(guard):
    # 2026-11-21 arm_s: the Leader pan rests at 4151 where the Follower is at 2047
    def arms():
        follower, leader = Bus(), Bus(leader=True)
        leader.raw['shoulder_pan'] = follower.raw['shoulder_pan'] + 2048 + 56
        return follower, leader
    follower, leader = arms()
    with pytest.raises(ValueError, match='difference >=100'):
        guard.NativeJointMotion(follower, leader).send(action(leader))
    follower, leader = arms()
    motion = guard.NativeJointMotion(follower, leader, mount={'shoulder_pan': -2048})
    motion.send(action(leader))
    assert motion.offsets['shoulder_pan'] == -2048 and not motion.failed
    follower, leader = arms()
    leader.raw['shoulder_pan'] += 1200  # still a real misalignment on top of the stated mount
    with pytest.raises(ValueError, match='difference >=100'):
        guard.NativeJointMotion(follower, leader, mount={'shoulder_pan': -2048}).send(action(leader))
    for bad in ({'shoulder_pan': -1024}, {'gripper': 2048}, {'shoulder_pan': -2048.0}, [], [('shoulder_pan', -2048)]):
        with pytest.raises(ValueError, match='half a turn'):
            guard.NativeJointMotion(Bus(), Bus(leader=True), mount=bad)


def test_a_commissioned_trigger_map_puts_the_leader_trigger_on_the_follower_jaw_ends(guard):
    ends = {'leader_open': 1906, 'leader_closed': 1983, 'follower_open': 2379, 'follower_closed': 2000}
    for trigger, want in ((1983, 2000), (1906, 2379), (1990, 2000), (1800, 2379)):  # ends, then clamped past them
        follower, leader = Bus(), Bus(leader=True)
        follower.raw['gripper'], leader.raw['gripper'] = want, trigger
        given = dict(ends)
        motion = guard.NativeJointMotion(follower, leader, grip_map=given)
        given.clear()  # the guard keeps its own checked copy
        assert motion.prepare(action(leader))['target']['gripper'] == want
    for bad in ({**ends, 'leader_open': 1983}, {**ends, 'follower_open': 4000}, {**ends, 'leader_open': 1906.0},
                {k: v for k, v in ends.items() if k != 'leader_open'}, [], {**ends, 'follower_open': 5000},
                {**ends, 'leader_closed': -1}):
        with pytest.raises(ValueError, match='gripper map'):
            guard.NativeJointMotion(Bus(), Bus(leader=True), grip_map=bad)


def _lift_arms(follower_lift, leader_lift):
    follower, leader = Bus(), Bus(leader=True)
    follower.raw['shoulder_lift'], leader.raw['shoulder_lift'] = follower_lift, leader_lift
    return follower, leader


def test_follower_floor_keeps_the_target_off_the_follower_stop_while_the_leader_rests_on_its_stand(guard):
    # 2026-11-21 arm_s session 23: Leader lift rests at 704, the Follower stops mechanically near 713
    follower, leader = _lift_arms(742, 704)
    motion = guard.NativeJointMotion(follower, leader, follower_floor={'shoulder_lift': 760})
    assert motion.prepare(action(leader))['target']['shoulder_lift'] == 760  # not 704
    follower, leader = _lift_arms(742, 704)
    assert guard.NativeJointMotion(follower, leader).prepare(action(leader))['target']['shoulder_lift'] == 704  # none declared
    follower, leader = _lift_arms(742, 800)  # above the floor: followed as before
    motion = guard.NativeJointMotion(follower, leader, follower_floor={'shoulder_lift': 760})
    assert motion.prepare(action(leader))['target']['shoulder_lift'] == 800


def test_follower_floor_clips_after_the_100_degree_guard_which_judges_the_raw_leader_target(guard):
    # Leader parked 1296 ticks (>100 degrees = 1138) below the Follower: refused with or without a floor, because the guard judges the
    # raw Leader target; the floor never hides a Leader that far away.
    for floor in (None, {'shoulder_lift': 1500}):
        follower, leader = _lift_arms(2000, 704)
        with pytest.raises(ValueError, match='difference >=100'):
            guard.NativeJointMotion(follower, leader, follower_floor=floor).prepare(action(leader))
    # inside 100 degrees the floor still clips the target that is sent
    follower, leader = _lift_arms(742, 704)
    assert guard.NativeJointMotion(follower, leader, follower_floor={'shoulder_lift': 760}).prepare(
        action(leader))['target']['shoulder_lift'] == 760
    # the Leader's own calibrated range is still checked on the unclipped mapping
    follower, leader = _lift_arms(742, 704)
    leader.calibration['shoulder_lift'].range_min = 800
    with pytest.raises(ValueError, match='outside calibrated range'):
        guard.NativeJointMotion(follower, leader, follower_floor={'shoulder_lift': 760}).prepare(action(leader))


def test_a_bad_follower_floor_declaration_is_refused_before_any_torque(guard):
    for bad in ({'shoulder_lift': 5000}, {'shoulder_lift': -1}, {'shoulder_lift': 760.0}, {'shoulder_lift': True},
                {'gripper': 2000}, {'lift': 760}, [], [('shoulder_lift', 760)]):
        follower = Bus()
        with pytest.raises(ValueError, match='follower_floor'):
            guard.NativeJointMotion(follower, Bus(leader=True), follower_floor=bad)
        assert not any(follower.torque.values()) and follower.events == []


def _paused(guard, gap, boundary=True, move=None):
    """Two commands (seed, one step), then `gap` seconds of pause, then the first command of the next record loop."""
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    clock[0] += 0.1
    motion.send(action(leader))
    motion.boundary = boundary  # run_native sets it when a record loop starts
    clock[0] += gap
    if move:
        device, name, ticks = move
        {'leader': leader, 'follower': follower}[device].raw[name] += ticks
    return motion, follower, leader, clock


def _goals(follower):
    return [e[1] for e in follower.events if e[0] == 'goal']


def test_a_declared_pause_resumes_from_the_held_command_without_a_jump(guard):
    # 2026-11-21 session 25: save_episode encoded for 29 s between the reset loop and episode 1
    motion, follower, leader, clock = _paused(guard, 29.0, move=('leader', 'elbow_flex', 300))
    before = _goals(follower)[-1]
    motion.send(action(leader))  # no stale error, and the Goal_Position stays on the last command
    assert _goals(follower)[-1] == before and before['elbow_flex'] == 2028
    assert follower.events.count(('on',)) == 1 and not motion.failed and not motion.tracking and not motion.resuming
    clock[0] += 0.1  # the 26 degree lead is then approached at 1 degree/s
    motion.send(action(leader))
    assert 0 < _goals(follower)[-1]['elbow_flex'] - 2028 <= 4096 / 360 * 0.1 + 1e-9


def test_after_a_declared_pause_the_5_degree_following_error_still_ends_the_session(guard):
    motion, follower, leader, _ = _paused(guard, 29.0, move=('follower', 'shoulder_lift', 4096 * 6 / 360))
    with pytest.raises(ValueError, match='following error'):  # the arm was pushed off the held command during the pause
        motion.send(action(leader))
    assert not any(follower.torque.values()) and motion.failed


def test_after_a_declared_pause_a_leader_100_degrees_away_is_refused(guard):
    motion, follower, leader, _ = _paused(guard, 29.0, move=('leader', 'wrist_roll', 4096 * 100 / 360))
    with pytest.raises(ValueError, match='100'):
        motion.send(action(leader))
    assert not any(follower.torque.values()) and motion.failed


def test_a_short_pause_is_unchanged_and_other_gaps_stay_stale(guard):
    motion, follower, leader, _ = _paused(guard, 0.4)
    motion.send(action(leader))
    assert motion.boundary is False and not motion.resuming and follower.events.count(('on',)) == 1
    motion, follower, leader, _ = _paused(guard, 29.0, boundary=False)  # no record loop start: a stalled loop
    with pytest.raises(ValueError, match='stale control loop'):
        motion.send(action(leader))
    assert not any(follower.torque.values())
    motion, follower, clock, here = teacher(guard)  # teacher/replay pauses across save_episode() on declared record_loop boundaries
    motion.send(here)
    clock[0] += 0.1
    motion.send(here)
    prev_goal = _goals(follower)[-1]['shoulder_pan']
    motion.boundary = True
    clock[0] += 29.0
    moved = {**here, 'shoulder_pan.pos': here['shoulder_pan.pos'] + 20.0}
    motion.send(moved)  # declared boundary resumes without stale control loop and holds previous command
    assert _goals(follower)[-1]['shoulder_pan'] == prev_goal and motion.boundary is False and not motion.tracking and not motion.resuming
    motion_u, follower_u, clock_u, here_u = teacher(guard)
    motion_u.send(here_u)
    clock_u[0] += 0.1
    motion_u.send(here_u)
    motion_u.boundary = False  # undeclared stall in teacher mode still cuts torque
    clock_u[0] += 29.0
    with pytest.raises(ValueError, match='stale control loop'):
        motion_u.send(here_u)
    assert not any(follower_u.torque.values())
    motion_o, follower_o, clock_o, here_o = teacher(guard)
    motion_o.send(here_o)
    clock_o[0] += 0.1
    motion_o.send(here_o)
    motion_o.boundary = True
    clock_o[0] += guard.BOUNDARY_MAX_S + 1.0  # over-bound declared pause still expires fail-closed keeping torque
    with pytest.raises(guard.BoundaryExpired):
        motion_o.send(here_o)
    assert any(follower_o.torque.values()) and motion_o.failed


def test_run_native_marks_the_loop_start_for_its_first_command_only_and_restores_the_loop_first(guard, monkeypatch):
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)

    follower, leader, seen = Follower(), Leader(), []
    original_loop = lambda *a, **kw: seen.append(monitor.events[0][1].boundary if monitor.events else None)  # noqa: E731
    module = SimpleNamespace(make_robot_from_config=lambda config: follower, make_teleoperator_from_config=lambda config: leader,
                             ACTION='action', build_dataset_frame=lambda features, values, prefix: values, record_loop=original_loop)

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        module.record_loop()  # before the first command there is no motion to mark
        robot.send_action(action(leader.bus))
        motion = monitor.events[0][1]
        module.record_loop()  # marked while the loop runs, and unmarked again when it returned without a command
        assert seen == [None, True] and motion.boundary is False
        raise KeyboardInterrupt

    module.main = main
    with pytest.raises(KeyboardInterrupt):
        guard.run_native(module, Follower, Leader)
    assert module.record_loop is original_loop


def test_teacher_mode_starts_boundary_watch_across_episode_pauses(guard, monkeypatch):
    events = []

    class RecordingWatch:
        expired = False
        fault_exc = None

        def __init__(self, motion, on_expire=None):
            events.append(('init', motion.teacher))

        def start(self):
            events.append(('start',))

        def stop(self):
            events.append(('stop',))
            return True

    import guarded_native_cli
    monkeypatch.setattr(guarded_native_cli, 'BoundaryWatch', RecordingWatch)
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class DummyTeleop:
        pass

    follower = Follower()
    loops = []
    module = SimpleNamespace(
        record=None,
        make_robot_from_config=lambda config: follower,
        make_teleoperator_from_config=lambda config: DummyTeleop(),
        ACTION='action',
        build_dataset_frame=lambda features, values, prefix: values,
        record_loop=lambda *a, **kw: loops.append(len(events)),
    )

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        module.make_teleoperator_from_config(None)
        robot.connect()
        robot.send_action(action(follower.bus))
        module.record_loop()
        module.record_loop()

    module.main = main
    guard.run_native(module, Follower, Bus, teacher=True)
    assert events == [('init', True), ('start',), ('stop',), ('init', True), ('start',), ('stop',)] and len(loops) == 2


def _full(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], label='arm_s')
    motion.send(action(leader))

    def step(dt=0.05):
        clock[0] += dt
        sent = motion.send(action(leader))
        follower.raw.update(follower.goals)  # the arm follows its command exactly
        return sent
    return motion, follower, leader, clock, step


def test_full_arm_teleop_aligns_at_1_degree_per_second_before_it_tracks(guard):
    motion, follower, leader, clock, step = _full(guard)
    leader.raw['shoulder_pan'] += 200  # 17.6 degrees: never inside the 2.5 degree alignment window
    leader.raw['gripper'] += 200
    for _ in range(20):  # 1 s
        step()
    assert not motion.tracking
    for name in ('shoulder_pan', 'gripper'):
        assert 0 < follower.goals[name] - 2028 <= 1 * guard.TICKS_PER_DEGREE + 2  # the gripper aligns at 1 degree/s too


def test_full_arm_teleop_tracks_body_and_gripper_at_the_full_limit_after_alignment(guard, capsys):
    motion, follower, leader, clock, step = _full(guard)
    for _ in range(14):
        step()
    assert motion.tracking and guard.FULL_TRACK_DEG_S == 25  # the user's 30, held at 25 under the 27.5 deg/s servo profile
    assert capsys.readouterr().out.count('full-arm tracking (body and gripper) limit 25 deg/s, acceleration 10 deg/s^2') == 1
    limit = guard.FULL_TRACK_DEG_S * guard.TICKS_PER_DEGREE
    leader.raw['shoulder_pan'] += 95 * guard.TICKS_PER_DEGREE  # inside the 100 degree gate
    leader.raw['gripper'] += 800  # 70 degrees
    peak, previous = 0.0, follower.goals['shoulder_pan']
    for index in range(240):  # 12 s
        step()
        peak = max(peak, abs(motion.velocity['shoulder_pan']))
        assert abs(motion.velocity['shoulder_pan']) <= limit + 1e-8 and abs(motion.velocity['gripper']) <= limit + 1e-8
        assert abs(follower.goals['shoulder_pan'] - previous) <= limit * 0.05 + 1
        previous = follower.goals['shoulder_pan']
        if index == 39:  # 2 s of 10 deg/s^2: about 20 deg/s, far beyond the 1 degree/s alignment rate
            assert follower.goals['gripper'] - 2028 > 15 * guard.TICKS_PER_DEGREE
    assert peak == pytest.approx(limit)
    assert abs(follower.goals['shoulder_pan'] - leader.raw['shoulder_pan']) <= 0.5 * guard.TICKS_PER_DEGREE
    assert not motion.failed


def test_full_arm_teleop_hold_freezes_the_command_and_a_pause_resumes_into_alignment(guard):
    motion, follower, leader, clock, step = _full(guard)
    for _ in range(14):
        step()
    assert motion.tracking
    leader.raw['elbow_flex'] += 300
    frozen, motion.frozen = follower.goals['elbow_flex'], (lambda: motion.active)  # an overload hold freezes every joint
    for _ in range(10):
        step()
    assert follower.goals['elbow_flex'] == frozen
    del motion.frozen
    for _ in range(10):
        step()
    assert follower.goals['elbow_flex'] > frozen
    motion.boundary = True  # a record loop starts after a 29 s save: tracking is earned again, from alignment
    clock[0] += 29.0
    before = dict(follower.goals)
    step(0.0)
    assert not motion.tracking and follower.goals == before
    assert motion.alignment_deadline > clock[0]


def _tracking(guard, gripper_far=0):
    motion, follower, leader, clock, step = _full(guard)
    leader.raw['gripper'] += gripper_far
    for _ in range(14):
        step()
    assert motion.tracking
    return motion, follower, leader, clock, step


def test_full_arm_tracking_never_carries_more_speed_than_the_remaining_distance_allows(guard):
    motion, follower, leader, clock, step = _tracking(guard)
    leader.raw['shoulder_pan'] += 80 * guard.TICKS_PER_DEGREE
    for _ in range(60):  # 3 s: the command is moving at the tracking limit
        step()
    assert abs(motion.velocity['shoulder_pan']) > 20 * guard.TICKS_PER_DEGREE
    stop_at = motion.command['shoulder_pan']
    leader.raw['shoulder_pan'] = stop_at  # the Leader stops where the command is now
    for _ in range(40):
        step()
        assert motion.command['shoulder_pan'] - stop_at <= 0.5 * guard.TICKS_PER_DEGREE


def test_the_gripper_keeps_1_degree_per_second_until_its_own_command_reached_its_target(guard):
    motion, follower, leader, clock, step = _tracking(guard, gripper_far=400)  # trigger 35 degrees from the jaws
    for _ in range(80):  # 4 s: the body tracks, the gripper has not reached its target once
        step()
    assert motion.tracking and not motion.grip_ready
    assert 0 < follower.goals['gripper'] - 2028 <= 5 * guard.TICKS_PER_DEGREE + 2  # about 4.7 s at 1 degree/s
    leader.raw['shoulder_pan'] += 60 * guard.TICKS_PER_DEGREE
    for _ in range(40):
        step()
    assert abs(motion.velocity['shoulder_pan']) > 15 * guard.TICKS_PER_DEGREE  # body at the tracking limit
    assert abs(motion.velocity['gripper']) <= guard.TICKS_PER_DEGREE + 1e-8  # gripper still at the alignment rate


def test_the_5_degree_check_uses_the_integer_that_was_written(guard):
    motion, follower, leader, clock, step = _full(guard)
    leader.raw['shoulder_pan'] += 300
    for _ in range(4):
        clock[0] += 0.1
        motion.send(action(leader))
    assert follower.goals['shoulder_pan'] == 2033 and int(motion.command['shoulder_pan']) == 2032  # 2032.55 was written as 2033
    follower.raw['shoulder_pan'] = 2033 - 57  # 5.009 degrees from what the motor was told; 4.92 from the floored command
    clock[0] += 0.1
    with pytest.raises(ValueError, match='shoulder_pan: following error'):
        motion.send(action(leader))
    assert not any(follower.torque.values())


def test_a_declared_pause_restarts_the_real_motor_health_sample_age_but_a_late_sample_still_stops(guard, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location('motor_health_pause', Path(guard.__file__).parent / 'motor_health.py')
    health_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health_module)
    health = health_module.MotorHealth(tmp_path / 'health.jsonl')
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    base, extra = follower.read, {'Temperature_Limit': 70, 'Min_Voltage_Limit': 60, 'Max_Voltage_Limit': 140, 'Present_Input_Voltage': 120}
    follower.read = lambda register, motor, **kw: extra[register] if register in extra else base(register, motor, **kw)
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], monitor=health, label='arm_s')
    motion.send(action(leader))
    clock[0] += 0.1
    motion.send(action(leader))
    assert health.motions[health.key(motion)]['last'] is not None  # a sample exists to age
    motion.boundary = True  # a record loop starts after the 29 s save
    clock[0] += 29.0
    motion.send(action(leader))  # the guard resumes and so does the monitor
    assert not motion.failed
    with pytest.raises(ValueError, match='stale motor health sample'):  # a delay nobody declared still stops
        health.sample(motion, dict(follower.raw), dict.fromkeys(NAMES, 0), clock[0] + 30)


def test_full_arm_commit_rechecks_the_alignment_deadline(guard):
    motion, follower, leader, clock, step = _full(guard)
    leader.raw['shoulder_pan'] += 200  # never aligned
    clock[0] += 0.05
    motion.alignment_deadline = clock[0] + 0.05
    prepared = motion.prepare(action(leader))  # still inside the deadline
    clock[0] += 0.2  # the other arm's preparation took long
    with pytest.raises(ValueError, match='alignment deadline exceeded before command commit'):
        motion.commit(prepared)


def test_releasing_an_overload_hold_returns_a_full_arm_to_alignment(guard):
    motion, follower, leader, clock, step = _tracking(guard)
    motion.held['shoulder_lift'] = {'since': clock[0] - 5.0}
    motion.release_hold()
    assert not motion.tracking and motion.resuming
    step()
    assert not motion.tracking and not motion.resuming and motion.alignment_deadline > clock[0]


def test_the_first_episode_waits_for_the_alignment_in_an_unrecorded_pre_roll(guard, monkeypatch):
    import time as real_time
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)

    follower, leader, calls, sends = Follower(), Leader(), [], []
    episode_dataset = object()

    def fake_loop(*, robot, events, dataset=None, policy=None, control_time_s=None, **kw):
        calls.append((dataset, control_time_s))
        for _ in range(100):
            if events['exit_early']:
                events['exit_early'] = False
                break
            sends.append(robot.send_action(action(leader.bus)))
            real_time.sleep(0.05)
            if dataset is not None:
                break  # an episode is one tick here

    module = SimpleNamespace(make_robot_from_config=lambda config: follower, make_teleoperator_from_config=lambda config: leader,
                             ACTION='action', build_dataset_frame=lambda features, values, prefix: values, record_loop=fake_loop)

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        events = {'exit_early': False, 'stop_recording': False}
        module.record_loop(robot=robot, events=events, dataset=episode_dataset, policy=None, control_time_s=30, teleop=teleop)
        before = len(sends)
        module.record_loop(robot=robot, events=events, dataset=episode_dataset, policy=None, control_time_s=30, teleop=teleop)
        assert len(sends) == before + 1 and events['exit_early'] is False  # the pre-roll runs once, and leaves the flag alone

    module.main = main
    guard.run_native(module, Follower, Leader)
    assert calls == [(None, 120), (episode_dataset, 30), (episode_dataset, 30)]
    assert monitor.events[0][1].tracking  # tracking was reached before episode 0, with no dataset to write to
    assert 11 <= len(sends) < 100


def _lagging(guard, tau=0.3, stage=None):
    """A full-arm guard on a follower whose measured pose trails its last goal like a first-order servo (time constant tau)."""
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], label='arm_s', stage=stage)
    motion.send(action(leader))

    def step(dt=0.05, blocked=()):
        clock[0] += dt
        motion.send(action(leader))
        for name in NAMES:
            if name not in blocked:
                follower.raw[name] += (follower.goals[name] - follower.raw[name]) * min(1.0, dt / tau)
    for _ in range(14):
        step()
    assert motion.tracking
    return motion, follower, leader, clock, step


def test_the_command_never_leads_a_lagging_arm_by_more_than_3_degrees_and_the_5_degree_stop_stays_quiet(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    peak = 0.0
    for _ in range(60):  # the Leader moves at 20 deg/s for 3 s; an arm 0.3 s behind would trail by 6 degrees
        leader.raw['shoulder_pan'] += 20 * guard.TICKS_PER_DEGREE * 0.05
        before = follower.raw['shoulder_pan']
        step()
        lead = abs(motion.command['shoulder_pan'] - before)
        assert lead <= guard.LEAD_DEG * guard.TICKS_PER_DEGREE + 1e-6
        peak = max(peak, lead)
    assert peak >= 2.9 * guard.TICKS_PER_DEGREE and not motion.held and not motion.failed  # the clamp was working, the arm was moving


def test_a_blocked_joint_stops_at_3_degrees_then_holds_with_torque_on_and_resumes_from_alignment(guard, capsys):
    motion, follower, leader, clock, step = _lagging(guard)
    leader.raw['shoulder_pan'] += 40 * guard.TICKS_PER_DEGREE
    blocked_at = follower.raw['shoulder_pan']
    for _ in range(40):  # 2 s: pushing, not yet a stall
        step(blocked=NAMES)
    assert abs(motion.command['shoulder_pan'] - blocked_at - 3 * guard.TICKS_PER_DEGREE) < 1.0 and not motion.held
    for _ in range(60):  # 3 s without advancing 0.5 degree
        step(blocked=NAMES)
    assert motion.held['shoulder_pan']['stall'] and motion.command['shoulder_pan'] == blocked_at
    assert any(follower.torque.values()) and not motion.failed
    assert capsys.readouterr().out.count('stall-hold on shoulder_pan: command frozen at present, torque stays ON') == 1
    leader.raw['shoulder_pan'] = follower.raw['shoulder_pan']  # the Leader comes back to where the arm is
    step()
    assert not motion.held and not motion.tracking and not motion.failed
    for _ in range(20):
        step()
    assert motion.tracking


def test_a_blocked_gripper_keeps_the_arm_on_and_the_command_3_degrees_ahead(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    leader.raw['gripper'] += 600
    blocked_at = follower.raw['gripper']
    for _ in range(40):
        step(blocked=('gripper',))
    assert abs(motion.command['gripper'] - blocked_at - 3 * guard.TICKS_PER_DEGREE) < 1.0 and not motion.held and not motion.failed
    # CHANGED in LAND-fix-9: this used to assert that a blocked gripper stall-holds (freezes the whole arm, command = present, squeeze lost). The gripper
    # now keeps its bounded lead for as long as the trigger asks; the stall hold is for the five body joints only
    for _ in range(80):
        step(blocked=('gripper',))
    assert not motion.held and any(follower.torque.values()) and not motion.failed
    assert abs(motion.command['gripper'] - blocked_at - 3 * guard.TICKS_PER_DEGREE) < 1.0  # the squeeze is still there


def test_an_arm_pushed_5_degrees_off_its_command_is_still_stopped(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    follower.raw['shoulder_lift'] += 6 * guard.TICKS_PER_DEGREE
    with pytest.raises(ValueError, match='shoulder_lift: following error'):
        step()
    assert not any(follower.torque.values())


def test_body_only_does_not_clamp_its_command_lead(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0], label='arm_a')
    motion.send(action(leader))
    for _ in range(14):  # aligned and tracking first: the alignment deadline is not what this test is about
        clock[0] += 0.05
        motion.send(action(leader))
    assert motion.tracking
    leader.raw['shoulder_pan'] += 40 * guard.TICKS_PER_DEGREE
    with pytest.raises(ValueError, match='following error'):  # a static arm: the command runs on until the 5 degree stop
        for _ in range(300):
            clock[0] += 0.05
            motion.send(action(leader))
    assert motion.command['shoulder_pan'] - 2028 > 3 * guard.TICKS_PER_DEGREE


def _preroll_module(monkeypatch, on_preroll):
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)

    follower, leader, calls = Follower(), Leader(), []

    def fake_loop(*, robot, events, dataset=None, policy=None, control_time_s=None, **kw):
        calls.append((dataset, control_time_s))
        on_preroll(events) if dataset is None else None

    module = SimpleNamespace(make_robot_from_config=lambda config: follower, make_teleoperator_from_config=lambda config: leader,
                             ACTION='action', build_dataset_frame=lambda features, values, prefix: values, record_loop=fake_loop)

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        module.record_loop(robot=robot, events={'exit_early': False, 'stop_recording': False}, dataset=object(), policy=None,
                           control_time_s=30, teleop=teleop)
    module.main = main
    return module, Follower, Leader, calls


def test_a_stop_request_during_the_pre_roll_starts_no_episode(guard, monkeypatch):
    module, Follower, Leader, calls = _preroll_module(monkeypatch, lambda events: events.__setitem__('stop_recording', True))
    with pytest.raises(KeyboardInterrupt, match='stop requested'):
        guard.run_native(module, Follower, Leader)
    assert calls == [(None, 120)]


def test_a_pre_roll_that_ends_without_tracking_is_a_failure_and_starts_no_episode(guard, monkeypatch):
    module, Follower, Leader, calls = _preroll_module(monkeypatch, lambda events: None)
    with pytest.raises(ValueError, match='leader alignment did not finish'):
        guard.run_native(module, Follower, Leader)
    assert calls == [(None, 120)]


def test_a_measured_position_that_drifts_away_is_not_followed_and_the_5_degree_stop_fires(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    with pytest.raises(ValueError, match='shoulder_lift: following error'):
        for _ in range(40):  # the Leader stands still, the arm sags 10 degrees over 2 s
            follower.raw['shoulder_lift'] -= 10 * guard.TICKS_PER_DEGREE / 40
            clock[0] += 0.05
            motion.send(action(leader))
    assert motion.command['shoulder_lift'] == 2028  # the command did not follow the drift down
    assert not any(follower.torque.values())


def test_the_first_tick_after_a_stall_hold_release_obeys_the_alignment_rate(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    leader.raw['shoulder_pan'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(100):
        step(blocked=NAMES)
    assert motion.held['shoulder_pan']['stall']
    before = follower.goals['shoulder_pan']
    follower.raw['shoulder_pan'] -= 4.48 * guard.TICKS_PER_DEGREE  # sagged under the held command, still inside the 5 degree stop
    leader.raw['shoulder_pan'] = follower.raw['shoulder_pan']  # the Leader comes back to where the arm is now
    step(blocked=NAMES)
    assert not motion.held and follower.goals['shoulder_pan'] - before in (0, -1, 1)  # 1 degree/s * 0.05 s is under a tick; the sent integers


def test_stall_release_clears_the_effort_timer_and_the_log_names_the_judgement(guard, capsys):
    motion, follower, leader, clock, step = _lagging(guard)
    motion.held['shoulder_pan'] = {'since': clock[0], 'saturated_since': None, 'temp': 30, 'stall': True}
    motion.effort_since['shoulder_pan'] = 5.0
    target = {n: follower.raw[n] for n in NAMES}
    guard.stall_watch(motion, target, dict(target), clock[0])
    assert not motion.held and motion.effort_since['shoulder_pan'] is None
    leader.raw['shoulder_pan'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(170):  # after a release the arm aligns at 1 deg/s: 3 degrees of lead take about 3 s, then 3 s of stall
        step(blocked=NAMES)
    assert 'slow real progress holds too' in capsys.readouterr().out


def test_a_squeezing_gripper_saturated_for_hold_s_is_relaxed_never_cut_and_re_arms_when_the_trigger_opens(guard, capsys):
    motion, follower, leader, clock, step = _lagging(guard)
    leader.raw['gripper'] += 600
    for _ in range(40):
        step(blocked=('gripper',))
    assert 'gripper' in motion.squeeze and motion.grip_way is None  # squeezing, watched
    base = follower.read
    follower.read = lambda register, motor, **kw: 330 if (register == 'Present_PWM' and motor == 'gripper') else base(register, motor, **kw)
    writes = []
    follower.disable_torque = lambda *a, **k: writes.append(a)
    for _ in range(100):  # 5 s at the cap, HOLD_S is 3: relaxed, no exception, no torque write
        step(blocked=('gripper',))
    assert writes == [] and any(follower.torque.values()) and not motion.failed and motion.grip_way == 1
    assert abs(motion.command['gripper'] - follower.raw['gripper']) < 1.0  # the command equals the present position: the motor stops pushing
    assert capsys.readouterr().out.count('gripper squeeze relaxed') == 1  # reported once
    leader.raw['gripper'] = follower.raw['gripper'] + 100  # the trigger still on the squeeze side: not re-armed
    for _ in range(20):
        step(blocked=('gripper',))
    assert motion.grip_way == 1 and abs(motion.command['gripper'] - follower.raw['gripper']) < 1.0
    leader.raw['gripper'] = follower.raw['gripper'] - 5 * guard.TICKS_PER_DEGREE  # 5 degrees to the open side of the jaws: re-armed
    step(blocked=('gripper',))
    assert motion.grip_way is None
    follower.read = base
    leader.raw['gripper'] = follower.raw['gripper'] + 600  # squeezed again: the lead is applied again
    for _ in range(40):
        step(blocked=('gripper',))
    assert abs(motion.command['gripper'] - follower.raw['gripper'] - 3 * guard.TICKS_PER_DEGREE) < 1.0 and motion.grip_way is None


@pytest.mark.parametrize('dt', [1 / 30, 0.05])
def test_a_reversal_from_full_speed_overruns_by_less_than_3_degrees(guard, dt):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], label='arm_s')
    motion.send(action(leader))

    def step():
        clock[0] += dt
        motion.send(action(leader))
        follower.raw.update(follower.goals)  # the arm follows its command exactly
    for _ in range(int(0.7 / dt) + 1):
        step()
    assert motion.tracking
    leader.raw['shoulder_pan'] += 80 * guard.TICKS_PER_DEGREE
    for _ in range(int(4 / dt)):
        step()
        if abs(motion.velocity['shoulder_pan']) >= 0.99 * guard.FULL_TRACK_DEG_S * guard.TICKS_PER_DEGREE:
            break
    assert motion.velocity['shoulder_pan'] > 0.99 * guard.FULL_TRACK_DEG_S * guard.TICKS_PER_DEGREE
    reversal = motion.command['shoulder_pan']
    leader.raw['shoulder_pan'] = reversal - 10 * guard.TICKS_PER_DEGREE  # the target jumps 10 degrees behind the command
    overrun, speeds = 0.0, []
    for _ in range(int(1.5 / dt)):
        step()
        overrun = max(overrun, motion.command['shoulder_pan'] - reversal)
        speeds.append(motion.velocity['shoulder_pan'])
    assert overrun < 3 * guard.TICKS_PER_DEGREE
    assert all(b <= a + 1e-9 or b <= 0 or a <= 0 for a, b in zip(speeds[:6], speeds[1:6]))  # braking never speeds the old direction up


def test_the_100_degree_guard_judges_both_the_raw_and_the_floored_target(guard):
    # the raw Leader target is 90 degrees (1024 ticks) from the Follower, the floor sits 110 degrees (1252 ticks) away and inside the range
    follower, leader = _lift_arms(1000, 2024)
    guard.NativeJointMotion(follower, leader).prepare(action(leader))  # without the floor: fine
    follower, leader = _lift_arms(1000, 2024)
    with pytest.raises(ValueError, match='difference >=100'):
        guard.NativeJointMotion(follower, leader, follower_floor={'shoulder_lift': 2252}).prepare(action(leader))


def test_a_declared_pause_is_within_the_bound_and_resumes_or_over_it_and_ends_with_torque_kept(guard):
    # the edge two clocks disagreed on: 119.99 s resumes, 120.02 s takes the healthy over-bound path; no gap reaches the stale torque cut
    for gap in (guard.BOUNDARY_MAX_S - 1.0, guard.BOUNDARY_MAX_S - 0.01):
        motion, follower, leader, _ = _paused(guard, gap)
        motion.send(action(leader))
        assert not motion.failed
    for gap in (guard.BOUNDARY_MAX_S + 0.02, guard.BOUNDARY_MAX_S + 1.0):
        motion, follower, leader, _ = _paused(guard, gap)
        with pytest.raises(KeyboardInterrupt, match='longer than the bound'):
            motion.send(action(leader))
        assert motion.failed and any(follower.torque.values())  # no new motion, torque kept
        with pytest.raises(ValueError, match='guard stopped'):
            motion.send(action(leader))


def test_the_100_degree_guard_also_judges_the_raw_target_at_the_re_measure_before_torque_on(guard):
    # raw Leader target 1137.5 ticks (99.97 deg) below the Follower, floor 500 ticks away: both pass the first sample;
    # one tick of drift at the re-measure takes the raw target past 100 degrees while the floored one stays at 499
    follower, leader = _lift_arms(2500, 1362.5)
    write = follower.sync_write
    follower.sync_write = lambda register, values, **kw: (write(register, values, **kw), follower.raw.__setitem__('shoulder_lift', follower.raw['shoulder_lift'] + 1))[0]
    motion = guard.NativeJointMotion(follower, leader, follower_floor={'shoulder_lift': 2000})
    with pytest.raises(ValueError, match='seed difference >=100'):
        motion.prepare(action(leader))
    assert not any(follower.torque.values()) and ('on',) not in follower.events


def _watched(guard):
    import guarded_native_watch as watch_module
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))  # seeded: torque ON, PWM limits admitted
    base = follower.read
    follower.read = lambda register, motor, **kw: 70 if register == 'Temperature_Limit' else base(register, motor, **kw)
    watch = watch_module.BoundaryWatch(motion, period_s=0.01)
    watch.began = 0.0
    return watch_module, watch, motion, follower


def test_the_pause_watch_sees_a_hardware_error_a_hot_motor_and_a_pause_that_runs_too_long(guard):
    watch_module, watch, motion, follower = _watched(guard)
    watch.check(1.0)  # a quiet pause is fine
    base = follower.read
    follower.read = lambda register, motor, **kw: 32 if (register == 'Hardware_Error_Status' and motor == 'shoulder_lift') else base(register, motor, **kw)
    with pytest.raises(ValueError, match='shoulder_lift: hardware error'):
        watch.check(1.0)
    follower.read = base
    follower.temps['elbow_flex'] = 70
    with pytest.raises(ValueError, match='elbow_flex: temperature'):
        watch.check(1.0)
    follower.temps['elbow_flex'] = 30
    asked = []
    watch.on_expire = lambda: asked.append(1)
    watch.start_time = 0.0  # the boundary's start is the guard's last command time; this test's clock starts at 0
    watch.check(guard.BOUNDARY_MAX_S + 1.0)  # healthy readings past the bound: NO cut, but no new motion and a request to end like a stop
    assert watch.expired and motion.failed and asked == [1] and any(follower.torque.values())
    watch.check(guard.BOUNDARY_MAX_S + 2.0)
    assert asked == [1]  # asked once
    follower.temps['elbow_flex'] = 70
    with pytest.raises(ValueError, match='elbow_flex: temperature'):  # the watch goes on: a real fault still cuts
        watch.check(guard.BOUNDARY_MAX_S + 3.0)


def test_a_pause_fault_cuts_the_arm_through_the_guards_fault_path_from_the_watch_thread(guard):
    import time as real_time
    watch_module, watch, motion, follower = _watched(guard)
    base = follower.read
    follower.read = lambda register, motor, **kw: 32 if register == 'Hardware_Error_Status' else base(register, motor, **kw)
    assert any(follower.torque.values())
    watch.began = real_time.monotonic()
    watch.start()
    deadline = real_time.monotonic() + 2.0  # bounded
    while not motion.failed and real_time.monotonic() < deadline:
        real_time.sleep(0.01)
    assert watch.stop() is True
    assert motion.failed and not any(follower.torque.values())
    with pytest.raises(ValueError, match='guard stopped'):  # the next command meets the failed flag
        motion.send(action(leader_of(motion)))


def leader_of(motion):
    return motion.leader


def test_run_native_watches_every_pause_between_record_loops_and_hands_the_bus_back(guard, monkeypatch):
    import guarded_native_cli
    log = []

    class Watch:
        expired = False

        def __init__(self, motion, on_expire=None):
            self.on_expire = on_expire

        def start(self):
            log.append('start')

        def stop(self):
            log.append('stop')
            return True
    monkeypatch.setattr(guarded_native_cli, 'BoundaryWatch', Watch)
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)
    follower, leader, in_loop = Follower(), Leader(), []
    module = SimpleNamespace(make_robot_from_config=lambda config: follower, make_teleoperator_from_config=lambda config: leader,
                             ACTION='action', build_dataset_frame=lambda features, values, prefix: values,
                             record_loop=lambda *a, **kw: in_loop.append(log[-1] if log else None))

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        robot.send_action(action(leader.bus))  # the guard exists from here
        module.record_loop()
        module.record_loop()
    module.main = main
    guard.run_native(module, Follower, Leader)
    # the first loop ran with no watch, the second after one pause was watched and stopped before it ran; stopped again at the end
    assert log == ['start', 'stop', 'start', 'stop'] and in_loop == [None, 'stop']


def test_a_pause_watch_that_does_not_end_is_not_followed_by_control_or_a_closed_port(guard):
    watch_module, watch, motion, follower = _watched(guard)
    watch._thread = SimpleNamespace(join=lambda timeout=None: None, is_alive=lambda: True)  # a thread stuck in a bus read
    assert watch.stop() is False


def _loop_module(guard, monkeypatch, watch_class):
    import guarded_native_cli
    monkeypatch.setattr(guarded_native_cli, 'BoundaryWatch', watch_class)
    monitor = Monitor()
    monkeypatch.setitem(sys.modules, 'motor_health', SimpleNamespace(MotorHealth=lambda: monitor))

    class Follower:
        def __init__(self):
            self.bus, self.cameras = Bus(), {}

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)
    follower, leader, ran = Follower(), Leader(), []
    module = SimpleNamespace(make_robot_from_config=lambda config: follower, make_teleoperator_from_config=lambda config: leader,
                             ACTION='action', build_dataset_frame=lambda features, values, prefix: values,
                             record_loop=lambda *a, **kw: ran.append(1))

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        robot.send_action(action(leader.bus))
        module.record_loop(events=module.events)
        module.record_loop(events=module.events)
    module.main, module.events = main, {'exit_early': False, 'stop_recording': False}
    return module, Follower, Leader, follower, ran


def test_a_watch_that_will_not_end_fails_the_session_without_closing_the_port(guard, monkeypatch):
    class Hung:
        expired = False

        def __init__(self, motion, on_expire=None):
            pass

        def start(self):
            pass

        def stop(self):
            return False
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, Hung)
    with pytest.raises(RuntimeError, match='boundary watch did not end'):
        guard.run_native(module, Follower, Leader)
    assert follower.bus.connected is True and ran == [1]  # the second loop never ran and nothing closed the port under the watch


def test_a_pause_past_the_bound_ends_the_session_like_a_stop_and_asks_lerobot_to_stop(guard, monkeypatch):
    made = []

    class Expired:
        expired = True

        def __init__(self, motion, on_expire=None):
            self.on_expire = on_expire
            made.append(self)

        def start(self):
            pass

        def stop(self):
            return True
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, Expired)

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        robot.send_action(action(teleop.bus))
        module.record_loop(events=module.events)
        made[-1].on_expire()  # the watcher reached the bound during the pause that followed
        module.record_loop(events=module.events)
    module.main = main
    with pytest.raises(KeyboardInterrupt, match='longer than the bound'):
        guard.run_native(module, Follower, Leader)
    assert module.events['stop_recording'] is True and module.events['exit_early'] is True  # lerobot is asked to stop as well
    assert ran == [1]  # no new loop ran


def test_the_watch_judges_from_the_guards_last_command_time_and_clock_like_the_first_command(guard):
    watch_module, watch, motion, follower = _watched(guard)
    now, asked = [0.0], []
    motion.last_time = watch.start_time = 0.0  # the boundary's one start
    watch.motion_clock, watch.on_expire = lambda: now[0], lambda: asked.append(1)
    watch.check(guard.BOUNDARY_MAX_S - 0.01)  # the tick (its own clock) saw 119.99 s: inside
    now[0] = guard.BOUNDARY_MAX_S + 0.02  # the hand-back, judged by the guard's clock, sees 120.02 s: over, by the same function
    assert watch.stop() is True and watch.expired and motion.failed and asked == [1]
    assert any(follower.torque.values())  # the guard is failed, the torque is not cut
    watch.stop()
    assert asked == [1]
    watch_module, watch, motion, follower = _watched(guard)
    motion.last_time = watch.start_time = 0.0
    watch.motion_clock = lambda: guard.BOUNDARY_MAX_S - 0.01
    assert watch.stop() is True and not watch.expired and not motion.failed  # inside the bound: control goes back as usual


def test_an_over_bound_pause_never_reaches_the_stale_guards_torque_cut(guard, monkeypatch):
    import functools
    now = [10.0]
    for mod in (guard, sys.modules.get('guarded_native'), sys.modules.get('omx_guard_test')):  # run_native resolves the class through _gn_attr
        if mod is not None and hasattr(mod, 'NativeJointMotion'):
            monkeypatch.setattr(mod, 'NativeJointMotion', functools.partial(mod.NativeJointMotion, clock=lambda: now[0]))
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, functools.partial(__import__('guarded_native_watch').BoundaryWatch, period_s=3600.0))

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        robot.send_action(action(teleop.bus))
        module.record_loop(events=module.events)
        now[0] += guard.BOUNDARY_MAX_S + 5.0  # the next loop starts after a save that took too long; no tick ran in between
        module.record_loop(events=module.events)
    module.main = main
    with pytest.raises(KeyboardInterrupt, match='longer than the bound'):  # the healthy over-bound path, not a stale ValueError and a cut
        guard.run_native(module, Follower, Leader)
    assert ran == [1]  # the second loop (and its first command) never ran


def test_every_disconnect_lerobot_makes_stops_the_single_arm_watch_first(guard, monkeypatch):
    log = []

    class Watch:
        expired = False

        def __init__(self, motion, on_expire=None):
            pass

        def start(self):
            log.append('start')

        def stop(self):
            log.append(('stop', bus['leader'].connected, bus['follower'].connected))
            return True
    bus = {}
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, Watch)

    def main():
        robot = module.make_robot_from_config(SimpleNamespace(use_degrees=False))
        teleop = module.make_teleoperator_from_config(None)
        robot.connect(), teleop.connect()
        bus.update(leader=teleop.bus, follower=robot.bus)
        robot.send_action(action(teleop.bus))
        module.record_loop(events=module.events)
        teleop.disconnect()  # lerobot's own teardown, before run_native's finally
        assert log[-1] == ('stop', True, True)  # stopped while both buses were still open
        robot.disconnect()
    module.main = main
    guard.run_native(module, Follower, Leader)
    assert log[0] == 'start' and ('stop', True, True) in log


def teacher(guard):
    follower, clock = Bus(), [10.0]
    motion = guard.NativeJointMotion(follower, None, teacher=True, clock=lambda: clock[0])
    here = {n + ".pos": v for n, v in follower.norm(follower.raw).items()}
    return motion, follower, clock, here

def test_teacher_mode_follows_the_action_at_the_guard_speed(guard):
    motion, follower, clock, here = teacher(guard)
    motion.send(here)  # seed at the present pose, torque on
    assert all(follower.torque.values())
    for _ in range(14):  # the replay starts where the arm is: aligned, then tracking
        clock[0] += 0.05
        motion.send(here)
    assert motion.tracking
    goal = {**here, "shoulder_pan.pos": here["shoulder_pan.pos"] + 10}  # about 18 degrees away
    start = follower.goals["shoulder_pan"]
    for _ in range(40):
        clock[0] += 0.05
        motion.send(goal)
        follower.raw.update({n: int(v) for n, v in follower.goals.items()})
    speed = (follower.goals["shoulder_pan"] - start) / guard.TICKS_PER_DEGREE / 2.0
    assert 5 < speed <= 10 + 0.1  # accelerates to, and never passes, 10 deg/s (2 s window; ticks are integers)


def test_teacher_mode_lets_the_gripper_stop_on_the_box_but_not_a_body_joint(guard):
    motion, follower, clock, here = teacher(guard)
    motion.send(here)
    follower.raw["gripper"] += 300  # the jaws held open by the box: about 26 degrees from the command
    clock[0] += 0.05
    motion.send(here)
    follower.raw["elbow_flex"] += 57  # a body joint more than 5 degrees off is still a stop
    clock[0] += 0.05
    with pytest.raises(ValueError, match="elbow_flex: following error"):
        motion.send(here)
    assert not any(follower.torque.values())


@pytest.mark.parametrize("kwargs", [dict(teacher=True, leader=Bus(leader=True)), dict(teacher=True, body_only=True),
                                    dict(teacher=False)])
def test_teacher_mode_has_no_leader_and_a_leader_mode_needs_one(guard, kwargs):
    leader = kwargs.pop("leader", None)
    with pytest.raises(ValueError, match="teacher mode"):
        guard.NativeJointMotion(Bus(), leader, **kwargs)


def test_teacher_recording_refuses_a_leader_teleop_and_a_non_recording(guard):
    class Follower:
        pass

    class Leader:
        def __init__(self):
            self.bus = Bus(leader=True)

    calls = []
    record = SimpleNamespace(record=None, make_robot_from_config=None, ACTION="action",
                             make_teleoperator_from_config=lambda config: Leader())

    def main():
        record.make_teleoperator_from_config(None)
        calls.append("made")

    record.main = main
    with pytest.raises(ValueError, match="not a leader"):
        guard.run_native(record, Follower, Leader, teacher=True)
    with pytest.raises(ValueError, match="recording"):
        guard.run_native(SimpleNamespace(), Follower, Leader, teacher=True)
    assert calls == []


def test_effort_check_uses_sync_read_on_dynamixel_bus_to_avoid_5hz_unicast_stall(guard):
    follower, clock = Bus(), [10.0]
    follower.model_ctrl_table = {}
    pwm_sync_calls = []
    original_sync = follower.sync_read

    def sync_read(register, motors=None, *, normalize=True, num_retry=0):
        if register in ("Present_PWM", "Hardware_Error_Status", "Torque_Enable", "PWM_Limit",
                        "Operating_Mode", "Profile_Acceleration", "Profile_Velocity", "Drive_Mode"):
            pwm_sync_calls.append((register, tuple(motors), normalize, num_retry))
            if register == "PWM_Limit":
                return {n: 330 for n in motors}
            if register == "Operating_Mode":
                return {n: 5 if n == "gripper" else 4 for n in motors}
            if register in ("Profile_Acceleration", "Profile_Velocity"):
                return {n: 8 if register == "Profile_Acceleration" else 20 for n in motors}
            return {n: 0 for n in motors}
        return original_sync(register, motors=motors, normalize=normalize, num_retry=num_retry)

    follower.sync_read = sync_read
    guard.connect_passive(SimpleNamespace(bus=follower, cameras={}), follower=True)
    assert ("Operating_Mode", guard.NAMES, False, guard.READ_RETRY) in pwm_sync_calls
    motion = guard.NativeJointMotion(follower, None, teacher=True, clock=lambda: clock[0])
    here = {n + ".pos": v for n, v in follower.norm(follower.raw).items()}
    motion.send(here)
    clock[0] += 0.25
    motion.send(here)
    assert ("Hardware_Error_Status", guard.NAMES, False, guard.READ_RETRY) in pwm_sync_calls
    assert ("PWM_Limit", guard.BODY, False, guard.READ_RETRY) in pwm_sync_calls
    assert ("Present_PWM", guard.BODY, False, guard.READ_RETRY) in pwm_sync_calls
    assert not any(e[:2] == ("read", "Present_PWM") for e in follower.events)
    assert not any(e[:2] == ("read", "PWM_Limit") for e in follower.events)


def test_teacher_mode_feedforward_tracks_streamed_ramp_without_braking_chaser_lag(guard):
    motion, follower, clock, here = teacher(guard)
    motion.send(here)
    for _ in range(18):
        clock[0] += 1 / 30
        motion.send(here)
    assert motion.tracking
    # Stream a C2 eased trajectory (matching retime/flow: 0.9s ramp up, 1.0s cruise at 4.5 units/s, 0.9s ramp down).
    streamed = dict(here)
    lags_deg = []
    pos = here["shoulder_pan.pos"]
    for k in range(1, 85):
        clock[0] += 1 / 30
        if k <= 27:
            v_u = 4.5 * (k / 27)
        elif k <= 57:
            v_u = 4.5
        else:
            v_u = 4.5 * max(0.0, (84 - k) / 27)
        pos += v_u / 30
        streamed = {**here, "shoulder_pan.pos": pos}
        sent = motion.send(streamed)
        follower.raw.update({n: int(v) for n, v in follower.goals.items()})
        if 34 <= k <= 57:  # steady-state cruise at 4.5 units/s (~8.1 deg/s)
            lags_deg.append(abs(streamed["shoulder_pan.pos"] - sent["shoulder_pan.pos"]) * 1.8)
    # Feedforward velocity matching keeps steady-state tracking lag well under 0.5 deg (vs ~3.9 deg without v_ff)
    assert max(lags_deg) < 0.5
    for _ in range(8):
        clock[0] += 1 / 30
        sent = motion.send(streamed)
        follower.raw.update({n: int(v) for n, v in follower.goals.items()})
    assert sent["shoulder_pan.pos"] == pytest.approx(streamed["shoulder_pan.pos"], abs=0.1)


def test_a_null_declaration_in_the_mount_file_stops_before_torque(tmp_path):
    import importlib.util
    import json as _json
    from pathlib import Path as _Path
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location('guarded_native_cli_null', _Path(__file__).resolve().parents[1] / 'deploy/robot/omx/guarded_native_cli.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    leader = SimpleNamespace(calibration_fpath=tmp_path / 'arm_s_leader.json')
    assert cli.leader_mount(leader) == {}  # no file: no declaration
    for key in ('gripper', 'follower_floor'):
        (tmp_path / 'arm_s_leader.mount.json').write_text(_json.dumps({'shoulder_pan': -2048, key: None}), encoding='utf-8')
        with pytest.raises(ValueError, match='is null'):
            cli.leader_mount(leader)


def test_a_fault_read_while_stop_waits_is_applied_before_control_comes_back(guard):
    import threading
    watch_module, watch, motion, follower = _watched(guard)
    watch.clock = lambda: 0.0
    entered, release = threading.Event(), threading.Event()
    base = follower.read

    def read(register, motor, **kw):
        if register == 'Hardware_Error_Status' and motor == 'shoulder_lift':
            entered.set()
            release.wait(2.0)  # bounded: the read is still in flight when stop() is called
            return 32
        return base(register, motor, **kw)
    follower.read = read
    watch.start()
    assert entered.wait(2.0)
    threading.Timer(0.1, release.set).start()
    assert watch.stop() is True  # waits for the read, which returns the error bit
    assert isinstance(watch.fault_exc, ValueError) and 'hardware error' in str(watch.fault_exc)
    assert motion.failed and not any(follower.torque.values())  # applied, not dropped


def test_the_single_arm_loop_does_not_resume_over_a_watch_fault(guard, monkeypatch):
    class Watch:
        expired = False

        def __init__(self, motion, on_expire=None):
            self.fault_exc = None

        def start(self):
            pass

        def stop(self):
            self.fault_exc = ValueError('PWM at the cap for 3 s')
            return True
    module, Follower, Leader, follower, ran = _loop_module(guard, monkeypatch, Watch)
    with pytest.raises(RuntimeError, match='pause watch fault'):
        guard.run_native(module, Follower, Leader)
    assert ran == [1]  # the second loop never ran


def test_a_body_stall_hold_does_not_cut_torque_when_the_leader_moves_over_100_degrees_and_release_needs_it_back(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    leader.raw['shoulder_pan'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(100):  # blocked: 2 s lead, 3 s without progress -> stall hold (as in the test above)
        step(blocked=NAMES)
    assert motion.held['shoulder_pan']['stall']
    frozen = motion.command['shoulder_pan']
    leader.raw['shoulder_pan'] += 70 * guard.TICKS_PER_DEGREE  # 110 degrees from the frozen arm: would have been the 100 degree cut
    for _ in range(10):
        step(blocked=NAMES)
    assert not motion.failed and any(follower.torque.values()) and motion.command['shoulder_pan'] == frozen and motion.held
    leader.raw['shoulder_pan'] = follower.raw['shoulder_pan']  # back within 2.5 degrees: released, the 100 degree test applies again
    step()
    assert not motion.held and not motion.failed
    leader.raw['shoulder_pan'] += 150 * guard.TICKS_PER_DEGREE
    with pytest.raises(ValueError, match='difference >=100'):
        step()
    assert not any(follower.torque.values())


def test_a_squeezing_gripper_does_not_freeze_the_body(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    leader.raw['gripper'] += 600
    leader.raw['shoulder_pan'] += 20 * guard.TICKS_PER_DEGREE
    start = follower.raw['shoulder_pan']
    for _ in range(100):  # 5 s: the gripper is blocked the whole time, the body keeps following
        step(blocked=('gripper',))
    assert not motion.held and follower.raw['shoulder_pan'] - start > 10 * guard.TICKS_PER_DEGREE and not motion.failed


def test_the_pause_watch_reads_with_the_control_loops_retries(guard):
    watch_module, watch, motion, follower = _watched(guard)
    seen = []
    base = follower.read
    follower.read = lambda register, motor, **kw: (seen.append(kw.get('num_retry')), base(register, motor, **kw))[1]
    watch.check(1.0)
    assert seen and set(seen) == {guard.READ_RETRY}  # one bad packet is retried, never a cut


def test_the_stage_sets_the_full_arm_tracking_limit_and_acceleration_and_nothing_else_changes(guard):
    follower, leader = Bus(), Bus(leader=True)
    for stage, track, accel, brake in ((None, 25, 10, 200), (30, 30, 30, 245), (45, 45, 60, 690), (60, 60, 90, 1640), (50, 25, 10, 200), (True, 25, 10, 200)):
        motion = guard.NativeJointMotion(follower, leader, stage=stage)  # an invalid stage is the old behaviour, braking included
        assert (motion.track_deg_s, motion.accel_deg_s2, motion.brake_deg_s2) == (track, accel, brake)
    body = guard.NativeJointMotion(follower, leader, body_only=True, stage=60)  # a body-only session ignores it
    assert (body.track_deg_s, body.accel_deg_s2) == (guard.TRACK_DEG_S, guard.ACCEL_DEG_S2)
    teacher = guard.NativeJointMotion(follower, None, teacher=True, stage=60)
    assert (teacher.track_deg_s, teacher.accel_deg_s2) == (guard.TRACK_DEG_S, guard.ACCEL_DEG_S2)


@pytest.mark.parametrize('tau', [0.3, 0.1])
def test_stage_60_keeps_the_lead_inside_the_models_allowance_and_the_5_degree_stop_quiet_on_a_lagging_follower(guard, tau):
    motion, follower, leader, clock, step = _lagging(guard, tau=tau, stage=60)
    assert motion.tracking and motion.lag is not None
    start = follower.raw['shoulder_pan']
    allowance = (guard.LEAD_DEG + motion.lag.tau_s * 60) * guard.TICKS_PER_DEGREE  # free motion at the limit lags by v * tau; 3 degrees of slack on top
    for _ in range(40):  # the Leader moves at 40 deg/s for 2 s: 80 degrees, inside the 100 degree test
        leader.raw['shoulder_pan'] += 40 * guard.TICKS_PER_DEGREE * 0.05
        before = follower.raw['shoulder_pan']
        step()
        assert abs(motion.command['shoulder_pan'] - before) <= allowance + 1e-6
    assert not motion.failed and not motion.held and follower.raw['shoulder_pan'] > start


def test_the_release_tick_of_a_stall_hold_runs_the_100_degree_test_on_every_joint_first(guard, capsys):
    motion, follower, leader, clock, step = _lagging(guard)
    leader.raw['shoulder_pan'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(100):
        step(blocked=NAMES)
    assert motion.held['shoulder_pan']['stall']
    frozen, goals = dict(motion.command), dict(follower.goals)
    leader.raw['wrist_flex'] += 110 * guard.TICKS_PER_DEGREE  # another joint 110 degrees away while the held one is held
    leader.raw['shoulder_pan'] = follower.raw['shoulder_pan']  # the held joint's Leader is back: the release condition holds
    for _ in range(5):
        step(blocked=NAMES)
    assert motion.held['shoulder_pan']['stall'] and not motion.failed and any(follower.torque.values())  # kept: no release, no cut
    assert motion.command == frozen and follower.goals == goals  # nothing new was sent
    assert capsys.readouterr().out.count('stall-hold kept: wrist_flex') == 1  # said once, with the reason
    leader.raw['wrist_flex'] = follower.raw['wrist_flex']  # every joint within the rules: now it releases
    step()
    assert not motion.held and not motion.failed


def test_every_run_time_guard_read_retries(guard):
    motion, follower, leader, clock, step = _lagging(guard)
    seen, base_read = [], follower.read

    def read(register, motor, **kw):
        seen.append((register, kw.get('num_retry')))
        return base_read(register, motor, **kw)
    follower.read = read
    leader.raw['gripper'] += 600  # the gripper squeeze branch: temperature, PWM and PWM_Limit reads
    for _ in range(30):
        step(blocked=('gripper',))
    leader.raw['elbow_flex'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(100):  # a body stall hold: its held reads
        step(blocked=NAMES)
    registers = {r for r, _ in seen}
    assert {'Present_Temperature', 'Present_PWM', 'PWM_Limit'} <= registers
    assert all(retry == guard.READ_RETRY for _, retry in seen)


@pytest.mark.parametrize('dt', [1 / 30, 0.05])
@pytest.mark.parametrize('stage', [30, 45, 60])
def test_a_reversal_overruns_by_less_than_3_degrees_at_every_stage(guard, stage, dt):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], label='arm_s', stage=stage)
    motion.send(action(leader))

    def step():
        clock[0] += dt
        motion.send(action(leader))
        follower.raw.update(follower.goals)
    for _ in range(int(0.7 / dt) + 1):
        step()
    assert motion.tracking
    leader.raw['shoulder_pan'] += 80 * guard.TICKS_PER_DEGREE
    for _ in range(int(4 / dt)):
        step()
        if abs(motion.velocity['shoulder_pan']) >= 0.99 * stage * guard.TICKS_PER_DEGREE:
            break
    assert motion.velocity['shoulder_pan'] > 0.99 * stage * guard.TICKS_PER_DEGREE
    reversal = motion.command['shoulder_pan']
    leader.raw['shoulder_pan'] = reversal - 10 * guard.TICKS_PER_DEGREE
    overrun = 0.0
    for _ in range(int(1.5 / dt)):
        step()
        overrun = max(overrun, motion.command['shoulder_pan'] - reversal)
    assert overrun < 3 * guard.TICKS_PER_DEGREE and not motion.failed


def test_staged_full_arm_tracks_moving_leader_without_excessive_early_braking_lag(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], label='arm_s', stage=90)
    motion.send(action(leader))
    dt = 0.04  # 25 Hz recorded cadence

    def step():
        clock[0] += dt
        motion.send(action(leader))
        follower.raw.update(follower.goals)

    for _ in range(18):
        step()
    assert motion.tracking
    for _ in range(30):  # 1.2 s moving smoothly at 55 deg/s (full arm extension)
        leader.raw['shoulder_lift'] += 55 * guard.TICKS_PER_DEGREE * dt
        step()
    lag_deg = abs(leader.raw['shoulder_lift'] - motion.command['shoulder_lift']) / guard.TICKS_PER_DEGREE
    assert lag_deg < 3.5 and not motion.failed
    reversal = leader.raw['shoulder_lift']
    overrun = 0.0
    for _ in range(25):  # hold stationary: settles cleanly without overshoot
        step()
        overrun = max(overrun, (motion.command['shoulder_lift'] - reversal) / guard.TICKS_PER_DEGREE)
    assert overrun < 3.0 and abs(motion.command['shoulder_lift'] - reversal) < 0.5 * guard.TICKS_PER_DEGREE


@pytest.mark.parametrize('dt', [0.05, 1 / 15])
@pytest.mark.parametrize('stage', [30, 45, 60, 90, 120])
def test_staged_full_arm_stop_hold_has_zero_overshoot_across_all_stages(guard, stage, dt):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0], label='arm_s', stage=stage)
    motion.send(action(leader))

    def step():
        clock[0] += dt
        motion.send(action(leader))
        follower.raw.update(follower.goals)

    for _ in range(int(0.8 / dt) + 2):
        step()
    assert motion.tracking
    for _ in range(int(1.0 / dt)):
        leader.raw['shoulder_pan'] += 0.9 * stage * guard.TICKS_PER_DEGREE * dt
        step()
    stop_target = leader.raw['shoulder_pan']
    max_ov = 0.0
    for _ in range(int(1.5 / dt)):
        step()
        max_ov = max(max_ov, (motion.command['shoulder_pan'] - stop_target) / guard.TICKS_PER_DEGREE)
    assert max_ov <= 1e-6 and not motion.failed


