"""A dropped arm is freed by the strong joints in small steps, and the rule switches action when one strains."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import cell_unwedge as u  # noqa: E402

HOME = [0.8, -62.2, 53.1, 51.6, 45.2]


class Cell:
    """Joints follow a jog at once, except `stuck` joints, which lag `stuck_lag` behind their target."""

    def __init__(self, state, stuck=(), stuck_lag=2.0):
        self.state, self.target, self.stuck, self.stuck_lag, self.sent = list(state), list(state), stuck, stuck_lag, []

    def act(self, command):
        self.sent.append(command)
        words = command.split()
        if words[0] == "jog":
            i = u.BODY.index(words[1].removesuffix(".pos"))
            self.target[i] += float(words[2])
            self.state[i] = self.target[i] - (self.stuck_lag if words[1].startswith(self.stuck) else 0.0)
        return {"ok": True, "state": list(self.state), "target": list(self.target)}


def test_a_free_arm_lifts_first_then_pulls_and_parks():
    cell = Cell([-5.4, 13.5, -1.9, 59.4, 41.3, 48.8])
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert out["result"] == "recovered" and cell.sent[-1] == "park"
    jogs = [c for c in cell.sent if c.startswith("jog")]
    assert jogs[:3] == ["jog shoulder_lift.pos -1.0"] * 3  # lift off what it lies on before pulling back
    assert "jog elbow_flex.pos 1.0" in jogs and not any("wrist" in c for c in cell.sent)  # the weak wrist is never asked


def test_a_strained_action_backs_off_and_both_strained_stops_for_a_person():
    cell = Cell([-5.4, 13.5, -1.9, 59.4, 41.3, 48.8], stuck=("shoulder_lift", "elbow_flex"))
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert out["result"] == "stuck" and [r["action"] for r in out["rows"]] == ["lift", "pull"]
    assert "jog shoulder_lift.pos 0.5" in cell.sent and "jog elbow_flex.pos -0.5" in cell.sent  # half a step back
    assert "park" not in cell.sent


def test_the_rule_never_repeats_the_action_that_just_strained():
    assert u.decide(None, None, 0.0) == "lift"
    assert u.decide(None, "lift", 0.0) == "pull"
    assert u.decide("lift", None, 5.0) == "pull" and u.decide("pull", None, 5.0) == "lift"
