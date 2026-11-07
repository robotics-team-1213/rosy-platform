"""A dropped arm is freed by the strong joints in small steps, and the rule switches action when one strains."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import cell_unwedge as u  # noqa: E402
from chunk_runner import SETTLE_TOL  # noqa: E402

HOME = [0.8, -62.2, 53.1, 51.6, 45.2]


class Cell:
    """Joints follow a jog at once, except `stuck` joints, which lag `stuck_lag` behind their target."""

    def __init__(self, state, stuck=(), stuck_lag=2.0, park_settled=True, park_offset=0.0):
        self.state, self.target, self.stuck, self.stuck_lag, self.sent = list(state), list(state), stuck, stuck_lag, []
        self.park_settled, self.park_offset = park_settled, park_offset

    def act(self, command):
        self.sent.append(command)
        words = command.split()
        if words[0] == "jog":
            i = u.BODY.index(words[1].removesuffix(".pos"))
            self.target[i] += float(words[2])
            self.state[i] = self.target[i] - (self.stuck_lag if words[1].startswith(self.stuck) else 0.0)
        if words[0] == "park":
            self.target[:5], self.state[:5] = HOME, HOME
            self.state[0] += self.park_offset
            result = {"ok": True, "state": list(self.state), "target": list(self.target)}
            if self.park_settled is not None:
                result["settled"] = self.park_settled
            return result
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


class Holding:
    """An arm stopped low on a box: the jaws stay at the box until their target passes it; the runner's target is the park's."""

    def __init__(self, rise_lag=0.3, opens=True):
        self.state = [-35.0, 1.1, 16.1, 34.3, 11.6, 53.8]
        self.target = [-35.0, 1.1, 16.1, 34.3, 11.6, 48.8]
        self.rise_lag, self.opens, self.sent = rise_lag, opens, []

    def act(self, command):
        self.sent.append(command)
        words = command.split()
        if words[0] == "jog" and words[1] == "gripper.pos":
            self.target[5] += float(words[2])
            self.state[5] = max(self.state[5], self.target[5] - 0.5) if self.opens else self.state[5]
        elif words[0] == "jog":
            self.target[1] += float(words[2])
            self.state[1] = self.target[1] + self.rise_lag
        return {"ok": True, "state": list(self.state), "target": list(self.target)}


def test_a_held_box_is_let_go_before_the_rise_and_the_arm_only_rises():
    cell = Holding()
    out = u.release_and_rise(cell, sleep=lambda s: None)
    assert out["result"] == "risen" and "park" not in cell.sent  # the caller folds, through the gate
    jogs = [c for c in cell.sent if c.startswith("jog")]
    assert all(c.startswith("jog gripper") for c in jogs[:2]) and all(c == "jog shoulder_lift.pos -1.0" for c in jogs[2:])
    assert len(jogs) == 2 + int(u.CLEAR / u.STEP) and cell.target[5] == pytest.approx(53.8 + u.RELEASE_OPEN)


def test_wide_jaws_far_from_the_parks_target_can_still_open():
    cell = Holding()
    cell.state[5] = 60.0  # a wider box: the runner refuses a jog that leaves the target more than 8 from the joint
    assert u.release_and_rise(cell, sleep=lambda s: None)["result"] == "risen"
    first = float(next(c for c in cell.sent if c.startswith("jog gripper")).split()[2])
    assert abs(48.8 + first - 60.0) <= 8.0  # JOG_MAX + SETTLE_TOL as the runner has them


def test_jaws_that_do_not_open_never_rise():
    cell = Holding(opens=False)
    out = u.release_and_rise(cell, sleep=lambda s: None)
    assert out["result"] == "stuck" and out["at"] == "open" and not any("shoulder" in c for c in cell.sent)


def test_a_blocked_rise_backs_off_and_stops_without_pulling():
    cell = Holding(rise_lag=2.0)
    out = u.release_and_rise(cell, sleep=lambda s: None)
    assert out["result"] == "stuck" and cell.sent[-1] == "jog shoulder_lift.pos 0.5"
    assert not any("elbow" in c or c == "park" for c in cell.sent)


def test_the_rule_never_repeats_the_action_that_just_strained():
    assert u.decide(None, None, 0.0) == "lift"
    assert u.decide(None, "lift", 0.0) == "pull"
    assert u.decide("lift", None, 5.0) == "pull" and u.decide("pull", None, 5.0) == "lift"


def test_near_home_shoulder_cannot_oscillate_into_clearance():
    cell = Cell([-5.4, HOME[1] + 0.25, -1.9, 59.4, 41.3, 48.8])
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert out["result"] != "recovered" and "park" not in cell.sent
    assert all(row["state"][1] >= HOME[1] for row in out["rows"])


def test_a_held_target_at_home_cannot_be_jogged_past_it_while_measurement_lags():
    cell = Cell([-5.4, HOME[1] + 0.25, -1.9, 59.4, 41.3, 48.8])
    cell.target[1] = HOME[1]
    assert u.unwedge(cell, HOME, sleep=lambda s: None)["result"] == "stopped"
    assert cell.sent == ["state"]


@pytest.mark.parametrize("settled", [False, None])
def test_park_without_positive_settled_evidence_is_not_recovered(settled):
    cell = Cell([-5.4, 13.5, -1.9, 59.4, 41.3, 48.8], park_settled=settled)
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert cell.sent[-1] == "park" and out["result"] == "stopped"


def test_park_settled_flag_cannot_replace_measured_home_evidence():
    cell = Cell([-5.4, 13.5, -1.9, 59.4, 41.3, 48.8], park_offset=SETTLE_TOL + 0.1)
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert cell.sent[-1] == "park" and out["result"] == "stopped"


@pytest.mark.parametrize("field,value", [("state", None), ("target", []), ("state", [float("nan")] * 6)])
def test_missing_or_nonfinite_body_evidence_stops_before_motion(field, value):
    class MissingEvidence(Cell):
        def act(self, command):
            return {**super().act(command), field: value}

    cell = MissingEvidence([-5.4, 13.5, -1.9, 59.4, 41.3, 48.8])
    assert u.unwedge(cell, HOME, sleep=lambda s: None)["result"] == "stopped"
    assert cell.sent == ["state"]


def test_a_failed_backoff_does_not_try_another_motion():
    class FailedBackoff(Cell):
        def act(self, command):
            if command == "jog shoulder_lift.pos 0.5":
                self.sent.append(command)
                return {"ok": False, "error": "backoff refused"}
            return super().act(command)

    cell = FailedBackoff([-5.4, 13.5, -1.9, 59.4, 41.3, 48.8], stuck=("shoulder_lift",))
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert out["result"] == "stopped" and out["error"] == "backoff refused"
    assert cell.sent[-1] == "jog shoulder_lift.pos 0.5"
