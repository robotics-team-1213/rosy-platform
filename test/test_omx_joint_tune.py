"""The joint tuning tool touches one motor, bounds its motion, and always ends torque OFF and restored."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def module():
    directory = Path(__file__).parents[1] / "deploy/robot/omx"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("joint_tune", directory / "joint_tune.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(directory))


m = module()
CLOSED, OPEN = 1982, 3300


class Motor:
    """One follower motor moving 30 ticks per 0.1 s toward its goal. The gripper stops at its ends;
    `sag` ticks per 0.1 s pull a loaded joint down while its PWM Limit is below `holds_at`."""

    def __init__(self, motor=16, position=2028, torque=0, mode=None, model=None, fail_at=None, sag=0, holds_at=0):
        default_model, default_mode = m.FOLLOWER.get(motor, (1200, 4))
        self.motor = motor
        self.reg = {"model": model or default_model, "mode": mode or default_mode, "torque": torque, "hw_error": 0,
                    "moving": 0, "present_load": 0, "present_pos": position, "pwm_limit": 20,
                    "current_limit": 50 if default_model == 1200 else None, "p_gain": 250, "i_gain": 0,
                    "goal_current": 0, "goal_pos": position, "profile_acc": 0, "profile_vel": 0}
        self.t, self.writes, self.fail_at, self.sag, self.holds_at = 0.0, [], fail_at, sag, holds_at

    def read(self, name):
        return self.reg[name]

    def write(self, name, value):
        assert name in m.WRITES
        self.writes.append((name, value))
        self.reg[name] = value

    def sleep(self, seconds):
        self.t += seconds
        if not self.reg["torque"]:
            return
        if self.fail_at is not None and self.t >= self.fail_at:
            self.reg["hw_error"] = 32
        goal, pos = self.reg["goal_pos"], self.reg["present_pos"]
        new = pos + max(-30, min(30, goal - pos))
        if self.motor == m.GRIPPER:
            new = max(CLOSED, min(OPEN, new))
        if self.reg["pwm_limit"] < self.holds_at:
            new -= self.sag
        blocked = new == pos and goal != pos
        self.reg["present_pos"] = new
        self.reg["present_load"] = (self.reg["goal_current"] * (1 if goal > pos else -1)) if blocked else 0


def run(bus, argv):
    rows, frames = [], []
    args = m.parse(["--device", "x", "--id", str(bus.motor), *argv])
    result = m.Run(bus, bus.motor, log=lambda **row: rows.append(row), grab=frames.append,
                   clock=lambda: bus.t, sleep=bus.sleep).execute(args)
    return result, rows, frames


def assert_restored(bus):
    assert bus.reg["torque"] == 0
    assert (bus.reg["pwm_limit"], bus.reg["p_gain"], bus.reg["i_gain"]) == (20, 250, 0)
    assert bus.reg["current_limit"] == (50 if bus.reg["model"] == 1200 else None)


def test_a_gripper_move_reaches_its_target_and_restores_everything():
    bus = Motor()
    result, _, frames = run(bus, ["move", "--to", "3200", "--p-gain", "600", "--i-gain", "200"])
    assert result["reached"] == 3200 and result["error_ticks"] == 0
    assert_restored(bus)
    assert frames[0] == "before" and frames[-1] == "after" and "move" in frames


def test_a_gripper_sweep_finds_both_ends_only_where_the_motor_stalled():
    bus = Motor()
    result, _, _ = run(bus, ["sweep", "--reach", "1700"])
    assert (result["closed_raw"], result["open_raw"]) == (CLOSED, OPEN)
    assert result["end_found"] == {"open": True, "closed": True}
    assert_restored(bus)
    short, _, _ = run(Motor(position=2600), ["sweep", "--reach", "300"])  # stops at its goals, not at ends
    assert short["end_found"] == {"open": False, "closed": False}


@pytest.mark.parametrize("motor", [15, 12])
def test_a_joint_move_touches_only_pwm_and_never_goal_current(motor):
    bus = Motor(motor=motor, position=2000)
    result, _, _ = run(bus, ["move", "--delta", "60", "--pwm", "150"])
    assert result["reached"] == 2060
    written = {name for name, _ in bus.writes}
    assert "goal_current" not in written
    assert ("current_limit" in written) == (motor == 15)  # XL430 has no Current Limit
    assert_restored(bus)


def test_a_loaded_joint_that_sags_at_torque_on_stops_before_any_motion():
    bus = Motor(motor=12, position=2000, sag=40, holds_at=100)
    with pytest.raises(RuntimeError, match="sagged"):
        run(bus, ["move", "--delta", "60", "--pwm", "50"])
    assert ("goal_pos", 2060) not in bus.writes
    assert_restored(bus)


def test_a_joint_move_beyond_max_delta_never_turns_torque_on():
    bus = Motor(motor=14, position=2000)
    with pytest.raises(SystemExit):
        run(bus, ["move", "--to", "2500"])
    assert ("torque", 1) not in bus.writes
    assert_restored(bus)


def test_a_hardware_error_stops_the_run_with_torque_off_and_limits_restored():
    bus = Motor(fail_at=0.5)
    with pytest.raises(RuntimeError, match="hardware error"):
        run(bus, ["move", "--to", "3200"])
    assert_restored(bus)


@pytest.mark.parametrize("state", [{"torque": 1}, {"mode": 4}, {"model": 1060}])
def test_nothing_is_written_unless_the_motor_is_the_expected_idle_one(state):
    bus = Motor(**state)
    with pytest.raises(SystemExit):
        run(bus, ["move", "--delta", "100"])
    assert bus.writes == []


def test_eeprom_limits_are_never_written_with_torque_on():
    bus = Motor()
    runner = m.Run(bus, 16, log=lambda **row: None, grab=lambda label: None)
    bus.reg["torque"] = 1
    with pytest.raises(RuntimeError, match="torque must be OFF"):
        runner.set("pwm_limit", 300)
    assert bus.writes == []


@pytest.mark.parametrize("argv", [
    ["move"], ["move", "--to", "1", "--delta", "1"], ["move", "--to", "5000"],
    ["move", "--to", "2000", "--pwm", "500"], ["move", "--to", "2000", "--goal-current", "300"],
    ["move", "--to", "2000", "--i-gain", "5000"], ["--id", "12", "sweep"], ["--id", "9", "move", "--delta", "1"],
    ["move", "--delta", "1", "--sag", "500"],
])
def test_out_of_bounds_arguments_are_refused(argv):
    with pytest.raises(SystemExit):
        m.parse(["--device", "x", *argv])


def test_a_motor_whose_caps_are_not_the_baseline_is_refused_untouched():
    bus = Motor()
    bus.reg["pwm_limit"] = 300  # an earlier run that never restored
    with pytest.raises(SystemExit, match="baseline"):
        run(bus, ["move", "--to", "2100"])
    assert bus.writes == []


def test_one_failed_restore_never_skips_the_others():
    bus = Motor()
    original = bus.write

    def write(name, value):
        if name == "pwm_limit" and value == 20:
            raise RuntimeError("bus dropped")
        original(name, value)

    bus.write = write
    with pytest.raises(RuntimeError, match="did not end safely"):
        run(bus, ["move", "--to", "2100", "--p-gain", "600", "--i-gain", "200"])
    assert bus.reg["torque"] == 0
    assert (bus.reg["current_limit"], bus.reg["p_gain"], bus.reg["i_gain"]) == (50, 250, 0)


def test_only_confirmed_leader_wrist_is_added_and_uses_slow_profiles():
    args = m.parse(["--device", "x", "--id", "5", "move", "--delta", "20"])
    assert (args.velocity, args.acceleration) == (1, 1)
    assert set(m.FOLLOWER) == {11, 12, 13, 14, 15, 16}
    for motor in (1, 2, 3, 4, 6):
        with pytest.raises(SystemExit):
            m.parse(["--device", "x", "--id", str(motor), "move", "--delta", "20"])
        with pytest.raises((SystemExit, ValueError)):
            m.Run(Motor(motor=motor), motor, log=lambda **row: None, grab=lambda label: None)


def leader(high_caps=True):
    bus = Motor(motor=5)
    if high_caps:
        bus.reg.update(pwm_limit=885, current_limit=1750)
    return bus


def test_leader_high_caps_are_lowered_before_trial_and_seed_precedes_torque():
    bus = leader()
    write = bus.write
    def checked_write(name, value):
        if name in m.EEPROM:
            assert bus.reg["torque"] == 0
        write(name, value)
    bus.write = checked_write
    result, _, _ = run(bus, ["move", "--delta", "40"])
    assert result["reached"] == 2068
    assert bus.writes[:2] == [("pwm_limit", 20), ("current_limit", 50)]
    assert bus.writes.index(("goal_pos", 2028)) < bus.writes.index(("torque", 1))
    assert ("profile_acc", 1) in bus.writes and ("profile_vel", 1) in bus.writes
    assert_restored(bus)


@pytest.mark.parametrize("state", [{"model": 1060}, {"mode": 5}, {"torque": 1}, {"hw_error": 4},
                                   {"pwm_limit": 19}, {"current_limit": 49}])
def test_bad_leader_validation_never_writes(state):
    bus = leader()
    bus.reg.update(state)
    with pytest.raises(SystemExit):
        run(bus, ["move", "--delta", "40"])
    assert bus.writes == []


def test_leader_unbounded_target_refused_without_changing_caps():
    bus = leader()
    with pytest.raises(SystemExit):
        run(bus, ["move", "--delta", "500"])
    assert bus.writes == []


@pytest.mark.parametrize("failure", ["interrupt", "hardware", "readback"])
def test_leader_failure_restores_only_safe_caps_and_torque_off(failure):
    bus = leader()
    if failure == "interrupt":
        def interrupted_sleep(seconds):
            raise KeyboardInterrupt
        bus.sleep = interrupted_sleep
    elif failure == "hardware":
        bus.fail_at = 0.5
    else:
        original = bus.read
        failed = [False]
        def wrong_readback(name):
            value = original(name)
            if name == "pwm_limit" and value == 20 and not failed[0]:
                failed[0] = True
                return 21
            return value
        bus.read = wrong_readback
    with pytest.raises((KeyboardInterrupt, RuntimeError)):
        run(bus, ["move", "--delta", "40"])
    assert_restored(bus)


def test_disconnected_persistent_serial_identity_is_recoverable_transport_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'dynamixel_sdk', SimpleNamespace(PacketHandler=None, PortHandler=None))
    with pytest.raises(RuntimeError, match='physically confirmed'):
        m.SerialBus('/dev/serial/by-id/rosy-unit-test-device-disconnected-7c1a', 0)


@pytest.mark.parametrize('name,value', [('torque', 1), ('goal_pos', 0), ('goal_current', 0),
                                        ('pwm_limit', 21), ('current_limit', 51), ('p_gain', 640),
                                        ('mode', 4), ('reboot', 0)])
def test_cleanup_write_rejects_every_operation_except_off_and_baseline_caps(name, value):
    bus = object.__new__(m.SerialBus)
    bus.motor = 12
    bus.packet = SimpleNamespace()
    with pytest.raises(ValueError):
        bus.cleanup_write(name, value)


@pytest.mark.parametrize('name', ['present_pos', 'p_gain', 'i_gain', 'goal_pos'])
def test_cleanup_read_is_limited_to_stop_and_caps_evidence(name):
    bus = object.__new__(m.SerialBus)
    bus.motor = 12
    bus.packet = SimpleNamespace()
    with pytest.raises(ValueError):
        bus.cleanup_read(name)
