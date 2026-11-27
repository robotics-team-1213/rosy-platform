"""2026-11-27: a recovery park that settles folded but off home rehomes in the same session before declaring folded."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_auto_fold as af  # noqa: E402

HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 46.6]
OFF = [0.0, -58.0, 54.9, 50.0, -5.0, 46.6]  # arm_s 11-27: elbow 4.9 off, inside REST_TOL 8, outside SETTLE_TOL 3
FAR = [0.0, -58.0, 62.0, 50.0, -5.0, 46.6]  # 12 off: not a coarse fold, never rehomed


class Cell:
    def __init__(self, park_to):
        self.state, self.park_to, self.commands = [20.0, -20.0, 20.0, 45.0, -5.0, 46.6], list(park_to), []

    def act(self, command):
        self.commands.append(command)
        if command.split()[0] == "park":
            self.state = list(self.park_to)
            return {"ok": True, "settled": True, "state": self.state, "target": self.state}
        return {"ok": True, "state": self.state, "target": self.state}


def run(cell, rehome):
    return af.recover(cell, HOME, 46.6, plan=lambda s: [s, HOME], reserve=lambda f: {"ok": True}, release=lambda: None,
                      look=lambda f: {"clear": True, "low": [], "high": [], "off_map": 0, "off_surface": 0},
                      release_and_rise=lambda c: {"result": "risen"}, low=lambda s: True, rehome=rehome)


def test_folded_off_home_rehomes_then_folds():
    cell, calls = Cell(OFF), []

    def rehome(c):
        calls.append(c)
        c.state = list(HOME)
        return {"result": "home"}

    result = run(cell, rehome)
    assert result["result"] == "folded" and result["state"][:5] == HOME[:5]
    assert calls == [cell] and any(s.get("step") == "rehome" for s in result["steps"])
    assert "human-hold" not in cell.commands


def test_rehome_that_does_not_reach_home_still_holds():
    cell = Cell(OFF)
    result = run(cell, lambda c: {"result": "stopped", "error": "blocked"})
    assert result["result"] == "held" and result["reason"] == "PARK_NOT_HOME"


def test_failed_rehome_keeps_its_stop_ack_as_evidence():
    stop = {"command": "human-hold", "ack": {"ok": True}}
    result = run(Cell(OFF), lambda c: {"result": "stopped", "error": "contact", "stop": stop})
    assert result["reason"] == "PARK_NOT_HOME"
    assert [s for s in result["steps"] if s.get("step") == "rehome"][0]["stop"] == stop


def test_rehome_reporting_home_but_measured_off_still_holds():
    cell = Cell(OFF)
    result = run(cell, lambda c: {"result": "home"})  # state unchanged: the measurement decides, not the receipt
    assert result["result"] == "held" and result["reason"] == "PARK_NOT_HOME"


def test_not_a_coarse_fold_is_never_rehomed():
    cell, calls = Cell(FAR), []
    result = run(cell, lambda c: calls.append(c) or {"result": "home"})
    assert result["result"] == "held" and calls == []


def test_without_rehome_the_old_hold_stays():
    result = run(Cell(OFF), None)
    assert result["result"] == "held" and result["reason"] == "PARK_NOT_HOME"
