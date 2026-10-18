"""The gripper tuning tool always ends with torque OFF and its raised limits and gains restored."""
import importlib.util
from pathlib import Path
import sys

import pytest


def module():
    directory = Path(__file__).parents[1] / "deploy/robot/omx"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("gripper_tune", directory / "gripper_tune.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(directory))


m = module()
CLOSED, OPEN = 1982, 3300


class Gripper:
    """A gripper between two mechanical ends, moving 30 ticks per 0.1 s toward its goal."""

    def __init__(self, position=2028, torque=0, mode=5, fail_at=None):
        self.reg = {"mode": mode, "torque": torque, "hw_error": 0, "moving": 0, "present_current": 0,
                    "present_pos": position, "pwm_limit": 20, "current_limit": 50, "p_gain": 250, "i_gain": 0,
                    "goal_current": 0, "goal_pos": position, "profile_acc": 0, "profile_vel": 0}
        self.t, self.writes, self.fail_at = 0.0, [], fail_at

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
        step = max(-30, min(30, goal - pos))
        new = max(CLOSED, min(OPEN, pos + step))
        blocked = new == pos and goal != pos
        self.reg["present_pos"] = new
        self.reg["present_current"] = (self.reg["goal_current"] * (1 if goal > pos else -1)) if blocked else 0


def run(bus, argv):
    rows, frames = [], []
    args = m.parse(["--device", "x", *argv])
    result = m.Run(bus, log=lambda **row: rows.append(row), grab=frames.append,
                   clock=lambda: bus.t, sleep=bus.sleep).execute(args)
    return result, rows, frames


def assert_restored(bus):
    assert bus.reg["torque"] == 0
    assert (bus.reg["pwm_limit"], bus.reg["current_limit"], bus.reg["p_gain"], bus.reg["i_gain"]) == (20, 50, 250, 0)


def test_a_move_reaches_its_target_and_restores_everything():
    bus = Gripper()
    result, _, frames = run(bus, ["move", "--to", "3200", "--p-gain", "600", "--i-gain", "200"])
    assert result["reached"] == 3200 and result["error_ticks"] == 0
    assert_restored(bus)
    assert frames[0] == "before" and frames[-1] == "after" and "move" in frames


def test_a_sweep_finds_both_ends_only_where_the_motor_stalled():
    bus = Gripper()
    result, _, _ = run(bus, ["sweep", "--reach", "1700"])
    assert (result["closed_raw"], result["open_raw"]) == (CLOSED, OPEN)
    assert result["end_found"] == {"open": True, "closed": True}
    assert_restored(bus)
    short, _, _ = run(Gripper(position=2600), ["sweep", "--reach", "300"])  # stops at its goals, not at ends
    assert short["end_found"] == {"open": False, "closed": False}


def test_a_hardware_error_stops_the_run_with_torque_off_and_limits_restored():
    bus = Gripper(fail_at=0.5)
    with pytest.raises(RuntimeError, match="hardware error"):
        run(bus, ["move", "--to", "3200"])
    assert_restored(bus)


@pytest.mark.parametrize("state", [{"torque": 1}, {"mode": 4}])
def test_nothing_is_written_unless_the_gripper_starts_idle_in_mode_5(state):
    bus = Gripper(**state)
    with pytest.raises(SystemExit):
        run(bus, ["move", "--delta", "100"])
    assert bus.writes == []


def test_eeprom_limits_are_never_written_with_torque_on():
    bus = Gripper()
    runner = m.Run(bus, log=lambda **row: None, grab=lambda label: None)
    bus.reg["torque"] = 1
    with pytest.raises(RuntimeError, match="torque must be OFF"):
        runner.set("pwm_limit", 300)
    assert bus.writes == []


@pytest.mark.parametrize("argv", [
    ["move"], ["move", "--to", "1", "--delta", "1"], ["move", "--to", "5000"],
    ["move", "--to", "2000", "--pwm", "500"], ["move", "--to", "2000", "--goal-current", "300"],
    ["move", "--to", "2000", "--i-gain", "5000"],
])
def test_out_of_bounds_arguments_are_refused(argv):
    with pytest.raises(SystemExit):
        m.parse(["--device", "x", *argv])
