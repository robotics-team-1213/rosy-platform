"""cell_transfer: a grasp check that finds the jaws empty stops the carry (2026-11-17 arm_s floor->belt)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import cell_transfer  # noqa: E402


class Scripted:
    """A runner that answers each command from a script; anything unscripted succeeds."""

    def __init__(self, answers=None):
        self.answers, self.commands = dict(answers or {}), []

    def act(self, command):
        self.commands.append(command)
        return {"command": command, "ok": True, **self.answers.get(command, {})}


def test_a_grasp_check_that_finds_the_jaws_empty_stops_the_carry_before_transit():
    """The runner said holding (48.91 > target+2), the debate said empty, and the carry went on to the belt."""
    cell = Scripted({"run grasp_pick": {"holding": True, "gripper_current_ma": 73}})
    checks = []

    def grasp_check(command, status, run):
        checks.append(command)
        return {"verdict": "empty", "reason": "empty_air_grasp"}

    moved = cell_transfer.transfer_folded(cell, "lib.json", closed=48.8, grasp_check=grasp_check)
    assert moved["result"] == "empty" and moved["at"] == "run grasp_pick" and checks == ["run grasp_pick"]
    assert "goto above_place" not in cell.commands and "run release_place" not in cell.commands
    assert cell.commands[-2:] == ["run lift_pick", "park"]


def test_a_held_verdict_still_carries():
    cell = Scripted({"run grasp_pick": {"holding": True, "gripper_current_ma": 215}})
    moved = cell_transfer.transfer_folded(cell, "lib.json", closed=48.8,
                                          grasp_check=lambda command, status, run: {"verdict": "held"})
    assert moved["result"] == "placed" and "run release_place" in cell.commands
