"""Guard the native LeRobot path without importing LeRobot or opening a serial port."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).parents[1] / "deploy/robot/omx/guarded_native.py"


@pytest.fixture
def guard():
    spec = importlib.util.spec_from_file_location("omx_guard_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


class Bus:
    def __init__(self, leader=False):
        self.motors = {n: SimpleNamespace(id=i + (1 if leader else 11)) for i, n in enumerate(NAMES)}
        self.calibration = {n: SimpleNamespace(range_min=0, range_max=4095, drive_mode=0,
                                              homing_offset=0) for n in NAMES}
        self.raw = dict.fromkeys(NAMES, 2028)
        self.connected = False
        self.is_calibrated = True
        self.torque = dict.fromkeys(NAMES, 0)
        self.events = []
        self.fail_write = False
        self.goals = {}
        self.profiles = {(n, register): 1 for n in NAMES
                         for register in ('Profile_Velocity', 'Profile_Acceleration')}

    def connect(self):
        self.connected = True

    @property
    def is_connected(self):
        return self.connected

    def disconnect(self, *args):
        self.connected = False

    def disable_torque(self, motors=None, **kwargs):
        self.events.append(("off",))
        self.torque = dict.fromkeys(NAMES, 0)

    def enable_torque(self, motors=None):
        self.events.append(("on",))
        for name in (motors or NAMES):
            self.torque[name] = 1

    def read(self, register, motor, **kwargs):
        if register in ('Present_PWM', 'PWM_Limit'):
            self.events.append(('read', register, motor))
            return 0 if register == 'Present_PWM' else 330
        if register == "Operating_Mode":
            return 5 if motor == "gripper" else 4
        if register == "Hardware_Error_Status":
            return 0
        if register == "Torque_Enable":
            return self.torque[motor]
        if register in ("Profile_Velocity", "Profile_Acceleration"):
            return self.profiles[motor, register]
        raise AssertionError(register)

    def sync_read(self, register, motors=None, *, normalize=True):
        assert register in ("Present_Position", "Goal_Position")
        source = self.raw if register == "Present_Position" else self.goals
        values = {n: source[n] for n in (motors or NAMES)}
        return self.norm(values) if normalize else values

    def norm(self, values):
        result = {n: v / 4095 * (100 if n == "gripper" else 200) - (0 if n == "gripper" else 100)
                  for n, v in values.items()}
        if "gripper" in result and self.calibration["gripper"].drive_mode:
            result["gripper"] = 100 - result["gripper"]
        return result

    def _normalize(self, values):
        by_name = {n: values[m.id] for n, m in self.motors.items() if m.id in values}
        return {self.motors[n].id: v for n, v in self.norm(by_name).items()}

    def _unnormalize(self, values):
        return {m.id: int((values[m.id] + (0 if n == "gripper" else 100)) /
                         (100 if n == "gripper" else 200) * 4095)
                for n, m in self.motors.items() if m.id in values}

    def write(self, register, motor, value, **kwargs):
        self.events.append((register, motor, value))
        if register in ('Profile_Velocity', 'Profile_Acceleration'):
            self.profiles[motor, register] = value

    def sync_write(self, register, values, *, normalize=True):
        assert register == "Goal_Position" and not normalize
        self.events.append(("goal", dict(values), dict(self.torque)))
        if self.fail_write:
            raise OSError("USB disconnected")
        self.goals = dict(values)


def pair(guard):
    follower, leader = Bus(), Bus(leader=True)
    clock = [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0])
    return motion, follower, leader, clock


def action(leader):
    return {n + ".pos": v for n, v in leader.norm(leader.raw).items()}


def test_connect_never_enables_torque_or_changes_eeprom(guard):
    device = SimpleNamespace(bus=Bus(), cameras={})
    guard.connect_passive(device, follower=True)
    assert not any(device.bus.torque.values())
    assert all(e[0] in ("off", "Profile_Velocity", "Profile_Acceleration") for e in device.bus.events)


def test_streamed_follower_commands_disable_internal_profiles_with_readback_while_off(guard):
    device = SimpleNamespace(bus=Bus(), cameras={})
    write = device.bus.write
    def off_write(register, motor, value, **kwargs):
        assert not any(device.bus.torque.values())
        write(register, motor, value, **kwargs)
    device.bus.write = off_write
    guard.connect_passive(device, follower=True)
    assert len(device.bus.profiles) == 12 and set(device.bus.profiles.values()) == {0}
    assert ('on',) not in device.bus.events


@pytest.mark.parametrize('register', ['Profile_Velocity', 'Profile_Acceleration'])
def test_streaming_profile_must_read_back_zero_before_enabling(guard, register):
    device = SimpleNamespace(bus=Bus(), cameras={})
    read = device.bus.read
    device.bus.read = lambda name, motor, **kwargs: 1 if name == register else read(name, motor, **kwargs)
    with pytest.raises(ValueError, match=register + ' readback mismatch'):
        guard.connect_passive(device, follower=True)
    assert ('on',) not in device.bus.events and not device.bus.is_connected


@pytest.mark.parametrize("problem", ["calibration", "mode", "camera"])
def test_connect_failure_turns_torque_off_and_closes_bus(guard, problem):
    device = SimpleNamespace(bus=Bus(), cameras={})
    if problem == "calibration":
        device.bus.is_calibrated = False
    elif problem == "mode":
        device.bus.read = lambda *args, **kwargs: 0
    else:
        device.cameras = {"top": SimpleNamespace(connect=lambda: (_ for _ in ()).throw(OSError("camera")),
                                                is_connected=False)}
    with pytest.raises((ValueError, RuntimeError, OSError)):
        guard.connect_passive(device, follower=True)
    assert not any(device.bus.torque.values()) and not device.bus.is_connected


def test_fixed_one_turn_alias_seed_before_enable_and_actual_action(guard):
    motion, follower, leader, clock = pair(guard)
    leader.raw["shoulder_pan"] = 6129  # adjusted 2033, not the normalizer's clamped 100
    result = motion.send(action(leader))
    first_goal = next(e for e in follower.events if e[0] == "goal")
    assert first_goal[1] == follower.raw and not any(first_goal[2].values())
    assert follower.events.index(first_goal) < follower.events.index(("on",))
    assert result["shoulder_pan.pos"] == pytest.approx(follower.norm(follower.raw)["shoulder_pan"])
    clock[0] += 0.1
    result = motion.send(action(leader))
    goal = [e for e in follower.events if e[0] == "goal"][-1][1]
    assert 2028 <= goal["shoulder_pan"] <= 2028 + 4096 / 360 * 0.1
    assert result["shoulder_pan.pos"] == pytest.approx(follower.norm(goal)["shoulder_pan"])


def test_exactly_100_degrees_refuses_before_enable(guard):
    motion, follower, leader, _ = pair(guard)
    leader.raw["wrist_roll"] += 4096 * 100 / 360
    with pytest.raises(ValueError, match="100"):
        motion.send(action(leader))
    assert ("on",) not in follower.events


def test_ongoing_turn_jump_is_not_hidden_by_recomputing_offset(guard):
    motion, follower, leader, clock = pair(guard)
    leader.raw["wrist_roll"] += 4096
    motion.send(action(leader))
    clock[0] += 0.1
    leader.raw["wrist_roll"] += 4096
    with pytest.raises(ValueError):
        motion.send(action(leader))
    assert not any(follower.torque.values())


def test_elapsed_rate_bound_caps_long_pause_and_does_not_accumulate_motion(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    leader.raw["wrist_roll"] += 500
    clock[0] += 0.4
    motion.send(action(leader))
    goals = [e[1] for e in follower.events if e[0] == "goal"]
    assert abs(goals[-1]["wrist_roll"] - 2028) <= 4096 / 360 * 0.1
    motion.send(action(leader))
    assert [e[1] for e in follower.events if e[0] == "goal"][-1] == goals[-1]


@pytest.mark.parametrize("problem", ["nan", "missing", "range", "write", "stale", "gap"])
def test_bad_samples_or_writes_fail_closed(guard, problem):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    clock[0] += 0.1
    values = action(leader)
    if problem == "nan":
        leader.raw["elbow_flex"] = float("nan")
    elif problem == "missing":
        values.pop("gripper.pos")
    elif problem == "range":
        leader.raw["elbow_flex"] = -1
    elif problem == "write":
        follower.fail_write = True
    elif problem == "gap":
        clock[0] += 1
    else:
        original_read = leader.sync_read
        def delayed_read(*args, **kwargs):
            clock[0] += 1
            return original_read(*args, **kwargs)
        leader.sync_read = delayed_read
    with pytest.raises((ValueError, OSError)):
        motion.send(values)
    assert not any(follower.torque.values())


def test_passive_leader_gripper_and_calibrated_inversion(guard):
    motion, follower, leader, clock = pair(guard)
    leader.calibration["gripper"].drive_mode = 1
    guard.connect_passive(SimpleNamespace(bus=leader, cameras={}), follower=False)
    assert all(e[0] == "off" for e in leader.events)
    motion.send(action(leader))
    clock[0] += 0.1
    sent = motion.send(action(leader))
    assert sent["gripper.pos"] > follower.norm(follower.raw)["gripper"]
    assert not any(leader.torque.values())


def test_target_must_fit_follower_calibration_before_torque(guard):
    motion, follower, leader, _ = pair(guard)
    follower.calibration["wrist_roll"].range_max = 2100
    leader.raw["wrist_roll"] = 2200
    with pytest.raises(ValueError, match="range"):
        motion.send(action(leader))
    assert ("on",) not in follower.events


def test_total_loop_gap_includes_bus_read_latency(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    clock[0] += 0.4
    original_read = leader.sync_read
    def delayed_read(*args, **kwargs):
        clock[0] += 0.2
        return original_read(*args, **kwargs)
    leader.sync_read = delayed_read
    with pytest.raises(ValueError, match="stale"):
        motion.send(action(leader))
    assert not any(follower.torque.values())


def test_prepare_never_enables_and_stale_preparation_cannot_commit(guard):
    motion, follower, leader, clock = pair(guard)
    prepared = motion.prepare(action(leader))
    assert ("on",) not in follower.events
    clock[0] += 0.6
    with pytest.raises(ValueError, match='stale'):
        motion.commit(prepared)
    assert not any(follower.torque.values())


def test_one_tick_gripper_seed_drift_is_the_same_pose(guard):
    motion, follower, leader, _ = pair(guard)
    read = follower.sync_read
    def drift(register, *args, **kwargs):
        if register == "Goal_Position":
            follower.raw["gripper"] += 1
            follower.goals["gripper"] = follower.raw["gripper"]
        return read(register, *args, **kwargs)
    follower.sync_read = drift
    sent = motion.send(action(leader))
    assert ("on",) in follower.events
    assert motion.command == follower.goals == follower.raw
    assert sent["gripper.pos"] == pytest.approx(follower.norm(follower.goals)["gripper"])


@pytest.mark.parametrize("problem", ["body", "large", "not_current", "missing", "slow", "range"])
def test_seed_drift_is_never_accepted_beyond_one_tick(guard, problem):
    motion, follower, leader, clock = pair(guard)
    read = follower.sync_read
    attempts = []
    def drift(register, *args, **kwargs):
        if register == "Goal_Position":
            attempts.append(1)
            if problem == "body":
                follower.goals["wrist_roll"] += 2
            elif problem == "missing":
                return {n: v for n, v in follower.goals.items() if n != "gripper"}
            else:
                follower.goals["gripper"] += 2
                if problem in ("slow", "range"):
                    follower.raw["gripper"] += 1
                if problem == "slow":
                    clock[0] += 0.6
                elif problem == "range":
                    follower.calibration["gripper"].range_max = follower.raw["gripper"] - 1
        return read(register, *args, **kwargs)
    follower.sync_read = drift
    with pytest.raises(ValueError):
        motion.send(action(leader))
    assert len(attempts) <= 3 and ("on",) not in follower.events
    assert not any(follower.torque.values())


@pytest.mark.parametrize('name', NAMES[:-1])
@pytest.mark.parametrize('direction', [-1, 1])
def test_transient_one_tick_body_goal_readback_is_the_same_pose(guard, name, direction):
    motion, follower, leader, _ = pair(guard)
    read, attempts = follower.sync_read, []
    def jitter(register, *args, **kwargs):
        if register == 'Goal_Position':
            attempts.append(1)
            if len(attempts) == 1:
                follower.goals[name] += direction
        return read(register, *args, **kwargs)
    follower.sync_read = jitter
    sent = motion.send(action(leader))
    assert len(attempts) == 1 and ('on',) in follower.events
    assert motion.command == follower.goals
    assert sent[name + '.pos'] == pytest.approx(follower.norm(follower.goals)[name])


@pytest.mark.parametrize('name', NAMES[:-1])
def test_two_tick_goal_readback_is_reseeded_until_consistent(guard, name):
    motion, follower, leader, _ = pair(guard)
    read, attempts = follower.sync_read, []
    def jitter(register, *args, **kwargs):
        if register == 'Goal_Position':
            attempts.append(1)
            if len(attempts) == 1:
                follower.goals[name] += 1
                follower.raw[name] -= 1
        return read(register, *args, **kwargs)
    follower.sync_read = jitter
    sent = motion.send(action(leader))
    assert len(attempts) == 2 and ('on',) in follower.events
    assert motion.command[name] == 2027
    assert sent[name + '.pos'] == pytest.approx(follower.norm(motion.command)[name])


def test_torque_off_goal_readback_lagging_the_pose_by_one_tick_still_seeds(guard):
    """Field 2026-10-23: the servo mirrors Present_Position, so the goal readback is never exact."""
    motion, follower, leader, _ = pair(guard)
    read = follower.sync_read
    def mirror(register, *args, **kwargs):
        values = read(register, *args, **kwargs)
        if register == 'Goal_Position':
            follower.raw['wrist_roll'] += 1
            values['wrist_roll'] = follower.raw['wrist_roll'] - 1
        return values
    follower.sync_read = mirror
    sent = motion.send(action(leader))
    assert ('on',) in follower.events
    assert motion.command['wrist_roll'] == 2028
    assert sent['wrist_roll.pos'] == pytest.approx(follower.norm(motion.command)['wrist_roll'])


def test_body_fresh_snapshot_one_tick_from_the_origin_seeds_from_the_goals_readback(guard):
    motion, follower, leader, _ = pair(guard)
    read = follower.sync_read
    def jitter(register, *args, **kwargs):
        if register == 'Goal_Position':
            follower.goals['shoulder_lift'] += 1
            follower.raw['shoulder_lift'] += 1
        return read(register, *args, **kwargs)
    follower.sync_read = jitter
    sent = motion.send(action(leader))
    assert motion.command['shoulder_lift'] == 2029
    assert follower.goals == follower.raw == motion.command
    assert sent['shoulder_lift.pos'] == pytest.approx(follower.norm(follower.raw)['shoulder_lift'])


def test_seed_refuses_a_pose_more_than_one_tick_from_the_origin(guard):
    motion, follower, leader, _ = pair(guard)
    read, attempts = follower.sync_read, []
    def creeping(register, *args, **kwargs):
        if register == 'Goal_Position':
            attempts.append(1)
            follower.raw['shoulder_lift'] += 2
        return read(register, *args, **kwargs)
    follower.sync_read = creeping
    with pytest.raises(ValueError, match='mismatch'):
        motion.send(action(leader))
    assert len(attempts) == 1 and ('on',) not in follower.events
    assert not any(follower.torque.values())


@pytest.mark.parametrize('name', NAMES)
@pytest.mark.parametrize('direction', [-1, 1])
def test_ongoing_actual_motion_over_five_degrees_from_last_sent_command_stops(guard, name, direction):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    clock[0] += 0.1
    follower.raw[name] += direction * 57  # 5.0098 motor degrees, below the leader-target 100-degree gate
    before = len([event for event in follower.events if event[0] == 'goal'])
    with pytest.raises(ValueError, match=name + r'.*following error.*command=2028.*current='):
        motion.send(action(leader))
    assert len([event for event in follower.events if event[0] == 'goal']) == before
    assert not any(follower.torque.values()) and motion.failed


def test_five_degree_following_bound_uses_last_integer_sent_not_fractional_accumulator(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    leader.raw['wrist_flex'] += 100
    clock[0] += 0.1
    motion.send(action(leader))
    sent = follower.goals['wrist_flex']
    assert motion.command['wrist_flex'] > sent
    clock[0] += 0.1
    follower.raw['wrist_flex'] = sent + 5 * guard.TICKS_PER_DEGREE + 0.01
    with pytest.raises(ValueError, match='following error'):
        motion.send(action(leader))
    assert not any(follower.torque.values())


def test_initial_leader_gap_below_100_degrees_is_not_a_five_degree_following_error(guard):
    motion, follower, leader, clock = pair(guard)
    leader.raw['wrist_flex'] += 1000
    motion.send(action(leader))
    assert any(follower.torque.values())
    clock[0] += 0.1
    motion.send(action(leader))
    assert any(follower.torque.values())


def test_exact_five_degree_actual_following_error_remains_within_limit(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    follower.raw['wrist_flex'] += 5 * guard.TICKS_PER_DEGREE
    clock[0] += 0.1
    motion.send(action(leader))
    assert any(follower.torque.values())


def effort_pair(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    def step():
        clock[0] += 0.05
        return motion.send(action(leader))
    return motion, follower, leader, clock, step


def effort_read(bus, *, pwm=300, limit=330):
    original = bus.read
    def read(register, motor, **kwargs):
        value = original(register, motor, **kwargs)
        if register == 'Present_PWM':
            return pwm if motor == 'shoulder_lift' else 0
        return limit if register == 'PWM_Limit' else value
    bus.read = read


def test_sustained_loaded_tracking_error_latches_before_firmware_overload(guard):
    motion, follower, leader, _, step = effort_pair(guard)
    effort_read(follower, pwm=-300)
    for _ in range(10):
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
        step()
    with pytest.raises(ValueError, match=r'shoulder_lift.*overload risk.*PWM=-300.*limit=330.*duration='):
        for _ in range(20):
            follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
            step()
    assert not any(follower.torque.values()) and motion.failed


def test_effort_guard_resets_on_clear(guard):
    motion, follower, leader, _, step = effort_pair(guard)
    effort_read(follower)
    for index in range(50):
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - (0 if index % 12 >= 8 else 25)
        step()
    assert not motion.failed


@pytest.mark.parametrize('limit', [0, 401, float('nan')])
def test_body_invalid_actual_pwm_limit_refuses_before_enable(guard, limit):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    effort_read(follower, limit=limit)
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0])
    with pytest.raises(ValueError, match='PWM_Limit'):
        motion.send(action(leader))
    assert ('on',) not in follower.events


@pytest.mark.parametrize('error_ticks,pwm,stop', [(23, 297, True), (22, 330, False), (25, 296, False)])
def test_effort_boundaries_apply_to_commanded_body(guard, error_ticks, pwm, stop):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, clock=lambda: clock[0])
    motion.send(action(leader))
    effort_read(follower, pwm=pwm)
    def run():
        for _ in range(9):
            clock[0] += 0.2
            follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - error_ticks
            motion.send(action(leader))
    if stop:
        with pytest.raises(ValueError, match='overload risk'):
            run()
        assert not any(follower.torque.values())
    else:
        run()
        assert not motion.failed


def test_full_mode_slow_effort_sample_cannot_write_or_credit_timer(guard):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    read = follower.read
    def slow_read(register, motor, **kwargs):
        if register == 'Present_PWM':
            clock[0] += 0.11
        return read(register, motor, **kwargs)
    follower.read = slow_read
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError, match='stale'):
        motion.send(action(leader))
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


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
