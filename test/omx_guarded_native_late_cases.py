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

