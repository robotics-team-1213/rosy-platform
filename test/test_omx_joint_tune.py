"""The joint tuning tool touches one motor, bounds its motion, and always ends torque OFF and restored."""
import importlib.util
from pathlib import Path
import sys

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
        default_model, default_mode = m.FOLLOWER[motor]
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
