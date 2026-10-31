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
        self.bad_reads = 0  # corrupt status packets before a good one
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

    def sync_read(self, register, motors=None, *, normalize=True, num_retry=0):
        assert register in ("Present_Position", "Goal_Position")
        if self.bad_reads:  # like lerobot: retries consume bad packets, then the read fails
            used = min(self.bad_reads, num_retry + 1)
            self.bad_reads -= used
            if used == num_retry + 1:
                raise ConnectionError("Failed to sync read 'Present_Position' [TxRxResult] Incorrect status packet!")
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


@pytest.mark.parametrize("acc, vel, drive_mode, kept", [
    (8, 20, 0, True),     # record_session's session profile: the servo ramps between whole-tick goals
    (1, 1, 0, False),     # joint_tune's resting 1/1 would crawl at 1.4 deg/s
    (8, 0, 0, False),     # velocity 0 is a step profile; half a profile is not admitted
    (200, 20, 0, False),  # above the admitted acceleration
    (8, 20, 4, False),    # time-based drive mode: the same numbers mean milliseconds
])
def test_a_session_profile_within_the_lag_budget_is_kept_and_anything_else_cleared(guard, acc, vel, drive_mode, kept):
    device = SimpleNamespace(bus=Bus(), cameras={})
    for name in NAMES:
        device.bus.profiles[name, "Profile_Acceleration"], device.bus.profiles[name, "Profile_Velocity"] = acc, vel
    read = device.bus.read
    device.bus.read = lambda register, motor, **kw: drive_mode if register == "Drive_Mode" else read(register, motor, **kw)
    guard.connect_passive(device, follower=True)
    expected = {(acc, vel) if kept else (0, 0)}
    assert {(device.bus.profiles[n, "Profile_Acceleration"], device.bus.profiles[n, "Profile_Velocity"])
            for n in NAMES} == expected
    assert not any(device.bus.torque.values())


def test_the_admitted_profile_never_limits_the_stream_and_lags_well_inside_the_bound(guard):
    deg_s2, deg_s = 214.577 * 360 / 3600, 0.229 * 360 / 60  # X-series raw units
    stream = 10.0  # deg/s: the guard's tracking limit in _body_command
    assert guard.PROFILE_VEL[0] * deg_s >= 2 * stream
    assert stream ** 2 / (2 * guard.PROFILE_ACC[0] * deg_s2) <= 0.5 < 5  # added lag vs the following-error bound


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


def test_a_close_that_fails_does_not_replace_the_handshake_error(guard):
    # A motor with a latched hardware error refuses every write, so the torque-OFF in the
    # cleanup fails too. The receipt must name the missing IDs, not the cleanup.
    class Latched(Bus):
        def connect(self):
            self.connected = True
            raise RuntimeError("Missing motor IDs:\n  - 2 (expected model: 1200)")

        def disable_torque(self, motors=None, **kwargs):
            raise RuntimeError("torque OFF not confirmed")

        def disconnect(self, *args):
            raise OSError("port still open")

    device = SimpleNamespace(bus=Latched(), cameras={})
    with pytest.raises(RuntimeError) as caught:
        guard.connect_passive(device, follower=False)
    message = str(caught.value)
    assert "Missing motor IDs" in message
    assert "torque OFF not confirmed" in message and "port still open" in message


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


@pytest.mark.parametrize("bad, survives", [(1, True), (2, True), (3, False)])
def test_a_corrupt_status_packet_is_read_again_and_a_dead_bus_still_stops(guard, bad, survives):
    motion, follower, leader, clock = pair(guard)
    motion.send(action(leader))
    clock[0] += 0.1
    follower.bad_reads = bad
    if survives:
        motion.send(action(leader))
        assert all(follower.torque[n] for n in guard.BODY)
    else:
        with pytest.raises(OSError):
            motion.send(action(leader))
        assert not any(follower.torque.values())


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


def test_body_only_never_commands_or_enables_passive_gripper(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    leader.raw['gripper'], follower.raw['gripper'] = 100, 3000
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    sent = motion.send(action(leader))
    assert set(sent) == {n + '.pos' for n in guard.BODY}
    assert follower.torque['gripper'] == 0 and all(follower.torque[n] == 1 for n in guard.BODY)
    follower.raw['gripper'] += 300  # uncommanded physical finger motion must not be a following error
    clock[0] += 0.1
    motion.send(action(leader))
    assert all('gripper' not in e[1] for e in follower.events if e[0] == 'goal')
    assert follower.raw['gripper'] == 3300 and follower.torque['gripper'] == 0


@pytest.mark.parametrize('failure', ['gripper_torque', 'body_tracking'])
def test_body_only_checks_passive_gripper_torque_and_all_body_guards_each_cycle(guard, failure):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    motion.send(action(leader))
    if failure == 'gripper_torque':
        follower.torque['gripper'] = 1
    else:
        follower.raw['wrist_flex'] += 57
    clock[0] += 0.1
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError):
        motion.send(action(leader))
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


def test_body_only_pre_enable_gripper_read_cannot_extend_freshness_deadline(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    prepared = motion.prepare(action(leader))
    read = follower.read
    def delayed_read(register, motor, **kwargs):
        if register == 'Torque_Enable' and motor == 'gripper':
            clock[0] += 0.6
        return read(register, motor, **kwargs)
    follower.read = delayed_read
    with pytest.raises(ValueError, match='stale'):
        motion.commit(prepared)
    assert ('on',) not in follower.events and not any(follower.torque.values())


def phased_pair(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0], label='arm_a')
    motion.send(action(leader))
    def step(dt=0.05):
        clock[0] += dt
        sent = motion.send(action(leader))
        follower.raw.update(follower.goals)
        return sent
    return motion, follower, leader, clock, step


def align_phase(step):
    for _ in range(14):
        step()


def test_body_startup_stays_slow_until_all_five_actual_and_command_targets_settle(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    leader.raw['wrist_flex'] += 200
    for _ in range(20):
        step()
    assert not motion.tracking
    assert follower.goals['wrist_flex'] - 2028 <= guard.TICKS_PER_DEGREE + 1
    leader.raw.update({n: follower.raw[n] for n in guard.BODY})
    for _ in range(6):
        step()
    assert not motion.tracking and motion.aligned_since is not None
    leader.raw['elbow_flex'] += 3 * guard.TICKS_PER_DEGREE
    step()
    assert motion.aligned_since is None and not motion.tracking
    leader.raw.update({n: follower.raw[n] for n in guard.BODY})
    align_phase(step)
    assert motion.tracking


def test_live_leader_target_outside_alignment_window_keeps_startup_phase(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for _ in range(30):
        leader.raw['shoulder_lift'] = follower.raw['shoulder_lift'] + 3 * guard.TICKS_PER_DEGREE
        step()
    assert not motion.tracking and motion.aligned_since is None
    assert abs(motion.velocity['shoulder_lift']) <= guard.TICKS_PER_DEGREE


def test_measured_static_load_residual_allows_handoff_after_continuous_dwell(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for index in range(12):
        follower.raw['shoulder_lift'] = leader.raw['shoulder_lift'] - 25  # 2.20 degrees
        step()
        if index < 9:
            assert not motion.tracking
    assert motion.tracking


def test_actual_error_above_two_point_five_resets_startup_dwell(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for _ in range(6):
        step()
    assert motion.aligned_since is not None
    follower.raw['shoulder_lift'] = leader.raw['shoulder_lift'] - 29  # 2.55 degrees
    step()
    assert motion.aligned_since is None and not motion.tracking
    for _ in range(8):
        step()
    assert not motion.tracking
    align_phase(step)
    assert motion.tracking


def test_command_not_within_half_degree_prevents_startup_handoff(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    for _ in range(20):
        leader.raw['shoulder_lift'] = motion.command['shoulder_lift'] + 7  # 0.62 degrees
        step()
    assert motion.aligned_since is None and not motion.tracking


def test_tracking_phase_slews_to_ten_degrees_per_second_and_prints_once(guard, capsys):
    motion, follower, leader, _, step = phased_pair(guard)
    align_phase(step)
    assert motion.tracking
    leader.raw['wrist_roll'] += 30 * guard.TICKS_PER_DEGREE
    previous_velocity, previous_goal = motion.velocity['wrist_roll'], follower.goals['wrist_roll']
    for _ in range(30):
        step()
        velocity, goal = motion.velocity['wrist_roll'], follower.goals['wrist_roll']
        assert abs(velocity) <= 10 * guard.TICKS_PER_DEGREE + 1e-8
        assert abs(velocity - previous_velocity) <= 10 * guard.TICKS_PER_DEGREE * 0.05 + 1e-8
        assert abs(goal - previous_goal) <= 10 * guard.TICKS_PER_DEGREE * 0.05 + 1
        previous_velocity, previous_goal = velocity, goal
    assert motion.velocity['wrist_roll'] == pytest.approx(10 * guard.TICKS_PER_DEGREE)
    output = capsys.readouterr().out
    changes = [line for line in output.splitlines() if ': aligned; body tracking limit' in line]
    assert len(changes) == 1 and changes[0].startswith('arm_a:') and '10 deg/s' in changes[0]


def test_moving_target_reversal_brakes_without_instant_velocity_flip(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    align_phase(step)
    leader.raw['wrist_roll'] += 40 * guard.TICKS_PER_DEGREE
    for _ in range(24):
        step()
    assert motion.velocity['wrist_roll'] > 0
    leader.raw['wrist_roll'] = follower.raw['wrist_roll'] - 20 * guard.TICKS_PER_DEGREE
    previous = motion.velocity['wrist_roll']
    step()
    assert 0 < motion.velocity['wrist_roll'] < previous
    for _ in range(30):
        before = motion.velocity['wrist_roll']
        step()
        assert abs(motion.velocity['wrist_roll'] - before) <= 10 * guard.TICKS_PER_DEGREE * 0.05 + 1e-8
    assert motion.velocity['wrist_roll'] < 0 and motion.tracking


def test_slew_caps_long_dt_and_zero_dt_never_moves_or_changes_velocity(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    align_phase(step)
    leader.raw['wrist_roll'] += 30 * guard.TICKS_PER_DEGREE
    step(0.4)
    assert motion.velocity['wrist_roll'] == pytest.approx(guard.TICKS_PER_DEGREE)
    command, velocity = dict(motion.command), dict(motion.velocity)
    step(0)
    assert motion.command == command and motion.velocity == velocity


def test_fast_slew_candidate_outside_calibration_fails_before_goal_write(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    follower.raw['wrist_roll'] = leader.raw['wrist_roll'] = motion.command['wrist_roll'] = 4094
    motion.tracking = True
    motion.velocity['wrist_roll'] = 10 * guard.TICKS_PER_DEGREE
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError, match='range'):
        step()
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


def test_five_degree_tracking_guard_and_backward_clock_still_stop_fast_phase(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    align_phase(step)
    assert motion.tracking
    follower.raw['wrist_flex'] += 57
    with pytest.raises(ValueError, match='following error'):
        step()
    assert not any(follower.torque.values())
    motion, follower, leader, clock, step = phased_pair(guard)
    align_phase(step)
    with pytest.raises(ValueError, match='stale'):
        step(-0.1)
    assert not any(follower.torque.values())


def test_alignment_diagnostic_reports_both_blocking_joints_at_most_once_per_second(guard, capsys):
    motion, follower, leader, _, step = phased_pair(guard)
    leader.raw['shoulder_lift'] += 80
    leader.raw['wrist_flex'] += 100
    follower.raw['wrist_flex'] += 25
    for _ in range(25):
        step()
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert all('arm_a' in line and 'phase=aligning' in line for line in lines)
    assert 'actual_joint=shoulder_lift' in lines[0] and 'actual=2028' in lines[0] and 'target=2108' in lines[0]
    assert 'Present_PWM=0' in lines[0] and 'PWM_Limit=330' in lines[0]
    limits = [e[2] for e in follower.events if e[:2] == ('read', 'PWM_Limit')]
    assert sorted(limits) == sorted(guard.BODY)  # actual limits cached once, never passive gripper
    assert 'command_joint=wrist_flex' in lines[0] and 'command=2028' in lines[0] and 'target=2128' in lines[0]
    assert not motion.tracking


def test_slow_alignment_pwm_read_cannot_send_stale_body_command(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    read = follower.read
    def slow_read(register, motor, **kwargs):
        if register == 'Present_PWM':
            clock[0] += 0.6
        return read(register, motor, **kwargs)
    follower.read = slow_read
    before = len([e for e in follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError, match='stale'):
        step()
    assert len([e for e in follower.events if e[0] == 'goal']) == before
    assert not any(follower.torque.values())


def effort_read(bus, *, pwm=300, limit=330):
    original = bus.read
    def read(register, motor, **kwargs):
        value = original(register, motor, **kwargs)
        if register == 'Present_PWM':
            return pwm if motor == 'shoulder_lift' else 0
        return limit if register == 'PWM_Limit' else value
    bus.read = read


def test_sustained_loaded_tracking_error_latches_before_firmware_overload(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    effort_read(follower, pwm=-300)
    for _ in range(10):
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
        step()
    with pytest.raises(ValueError, match=r'shoulder_lift.*overload risk.*PWM=-300.*limit=330.*duration='):
        for _ in range(20):
            follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - 25
            step()
    assert not any(follower.torque.values()) and motion.failed


def test_effort_guard_resets_on_clear_and_ignores_passive_gripper(guard):
    motion, follower, leader, _, step = phased_pair(guard)
    effort_read(follower)
    for index in range(50):
        follower.raw['shoulder_lift'] = int(motion.command['shoulder_lift']) - (0 if index % 12 >= 8 else 25)
        follower.raw['gripper'] = 0
        step()
    assert not motion.failed


@pytest.mark.parametrize('limit', [0, 401, float('nan')])
def test_body_invalid_actual_pwm_limit_refuses_before_enable(guard, limit):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    effort_read(follower, limit=limit)
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    with pytest.raises(ValueError, match='PWM_Limit'):
        motion.send(action(leader))
    assert ('on',) not in follower.events


def test_xl430_joints_admit_600_and_the_xl330_wrist_still_refuses_above_400(guard):
    for limits, admitted in (({'shoulder_lift': 600, 'elbow_flex': 600}, True), ({'shoulder_lift': 601}, False),
                             ({'shoulder_lift': 600, 'wrist_flex': 401}, False)):
        follower, leader, clock = Bus(), Bus(leader=True), [10.0]
        effort_read(follower)
        read = follower.read
        follower.read = lambda register, motor, _read=read, _l=limits, **kw: (
            _l.get(motor, 330) if register == 'PWM_Limit' else _read(register, motor, **kw))
        motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
        if admitted:
            motion.send(action(leader))
            assert motion.pwm_limits['shoulder_lift'] == 600
        else:
            with pytest.raises(ValueError, match='PWM_Limit'):
                motion.send(action(leader))
            assert ('on',) not in follower.events


def test_initial_alignment_deadline_is_fixed_by_admitted_gap_not_later_targets(guard):
    motion, follower, leader, clock, step = phased_pair(guard)
    for _ in range(95):
        leader.raw['shoulder_lift'] = motion.command['shoulder_lift'] + 40
        step()
    assert not motion.tracking
    with pytest.raises(ValueError, match='alignment deadline'):
        for _ in range(10):
            step()
    assert not any(follower.torque.values())


def test_large_admitted_gap_gets_slow_alignment_time_budget(guard):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    leader.raw['wrist_roll'] += 900
    motion = guard.NativeJointMotion(follower, leader, body_only=True, clock=lambda: clock[0])
    motion.send(action(leader))
    assert motion.alignment_deadline == pytest.approx(15 + 900 / guard.TICKS_PER_DEGREE)


@pytest.mark.parametrize('body_only', [False, True])
@pytest.mark.parametrize('error_ticks,pwm,stop', [(23, 297, True), (22, 330, False), (25, 296, False)])
def test_effort_boundaries_apply_to_all_commanded_body_modes(guard, body_only, error_ticks, pwm, stop):
    follower, leader, clock = Bus(), Bus(leader=True), [10.0]
    motion = guard.NativeJointMotion(follower, leader, body_only=body_only, clock=lambda: clock[0])
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
