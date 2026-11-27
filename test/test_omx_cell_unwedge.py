"""A dropped arm is freed by the strong joints in small steps, and the rule switches action when one strains."""
from pathlib import Path
import sys

import pytest


class HomeCell:
    def __init__(self, measured, *, lag_axis=4, lag=0.0, held=False, jaw_moves=True):
        self.measured = list(measured)
        self.target = list(measured)
        self.lag_axis, self.lag, self.held, self.jaw_moves = lag_axis, lag, held, jaw_moves
        self.commands = []

    def act(self, command):
        self.commands.append(command)
        if command.startswith("jog "):
            _, name, delta = command.split()
            axis = u.BODY.index(name.removesuffix(".pos"))
            self.target[axis] += float(delta)
            self.measured[axis] = self.target[axis]
            self.measured[self.lag_axis] = self.target[self.lag_axis] - self.lag
        elif command.startswith("grip ") and self.jaw_moves:
            self.measured[5] = self.target[5] = float(command.split()[1])
        return {"ok": True, "state": list(self.measured), "target": list(self.target), "holding": False,
                "health": {"current_ma": [0, 0, 0, 0, 0, 10]}, "human_hold_latched": self.held or command == "human-hold"}


RETURN_HOME = [0.8, -62.2, 53.1, 51.6, 45.2, 50.0]


@pytest.mark.parametrize(("measured", "flex_max", "roll_min", "roll_out"), [
    ([1.73, -63.76, 53.41, 55.56, -50.48, -1.0], 55.3, -55.5, False),
    ([-0.22, -62.59, 54.43, 57.07, -49.30, -1.0], 56.0, -31.0, True),
])
def test_return_home_plans_from_measured_ab_poses(measured, flex_max, roll_min, roll_out):
    limits = {"joint_min": {"wrist_roll.pos": roll_min}, "joint_max": {"wrist_flex.pos": flex_max}}
    cell = HomeCell(measured)
    result = u.return_home(cell, RETURN_HOME, limits, sleep=lambda _: None, log=None)
    assert result["result"] == "home"
    prefix = ["wrist_flex", "wrist_roll"] if roll_out else ["wrist_flex"]
    assert [step["joint"] for step in result["plan"][:len(prefix) + 2]] == [*prefix, "elbow_flex", "wrist_roll"]
    assert all(step["outside_limits"] for step in result["plan"][:len(prefix)])
    if roll_out:
        assert roll_min <= result["plan"][1]["goal"] < RETURN_HOME[4]
    assert result["plan"][-1]["joint"] == "elbow_flex"
    assert cell.target == pytest.approx(RETURN_HOME, abs=u.HOME_TOL)
    assert all(row["delta"] < 0 for row in result["jogs"] if row["joint"] == "wrist_flex")
    assert all(row["delta"] > 0 for row in result["jogs"] if row["joint"] == "wrist_roll")
    assert "stop" not in cell.commands


@pytest.mark.parametrize(("lag_axis", "lag", "held", "jaw_moves", "result", "last"), [
    (1, 2.1, False, True, "bind_suspected", "stop now"),
    (4, 0.0, True, True, "stopped", "state"),
    (4, 0.0, False, False, "stopped", "stop now"),
])
def test_return_home_failure_commands(lag_axis, lag, held, jaw_moves, result, last):
    state = list(RETURN_HOME)
    state[4:] = [41.0, 20.0]
    cell = HomeCell(state, lag_axis=lag_axis, lag=lag, held=held, jaw_moves=jaw_moves)
    limits = {"joint_min": {"wrist_roll.pos": -31}, "joint_max": {"wrist_flex.pos": 56}}
    out = u.return_home(cell, RETURN_HOME, limits, sleep=lambda _: None, log=None)
    assert out["result"] == result
    assert cell.commands[-1] == last and "stop" not in cell.commands
    if held or lag:
        assert not any(command.startswith("grip ") for command in cell.commands)


def test_rehome_before_work_turns_a_hand_turned_wrist_back_and_leaves_others():
    """11-19: wrists turned by hand with torque OFF; the next task now lifts and turns home before it starts."""
    library = {"chunks": {"home": [RETURN_HOME]}}
    limits = {"joint_min": {"wrist_roll.pos": -55.5}}
    assert u.rehome_before_work(HomeCell(RETURN_HOME), library, limits, sleep=lambda _: None) is None
    cell = HomeCell([*RETURN_HOME[:4], -50.5, 50.0])
    out = u.rehome_before_work(cell, library, limits, sleep=lambda _: None)
    assert out["result"] == "home" and out["plan"][0]["joint"] == "elbow_flex"
    extended = HomeCell([0.8, -30.0, 20.0, 51.6, 45.2, 50.0])  # not folded: nothing moves
    assert u.rehome_before_work(extended, library, limits, sleep=lambda _: None)["result"] == "refused"
    assert not any(c.startswith("jog ") for c in extended.commands)
    arm_s = HomeCell([0.0, -58.0, 50.0, 50.0, 57.5, 46.5])  # arm_s config has no joint window; home roll -5
    s_home = {"chunks": {"home": [[0.0, -58.0, 50.0, 50.0, -5.0, 46.5]]}}
    assert u.rehome_before_work(arm_s, s_home, {}, sleep=lambda _: None)["result"] == "refused"  # no window, no opt-in
    out = u.rehome_before_work(arm_s, s_home, {"joint_window_full_range": True}, sleep=lambda _: None)
    assert out["result"] == "home" and arm_s.target[4] == pytest.approx(-5.0, abs=u.HOME_TOL)
    assert not any(c.startswith("grip ") for c in arm_s.commands)  # the jaws are never commanded


@pytest.mark.parametrize("drop", ["holding", "health"])
def test_return_home_refuses_a_state_that_does_not_say_the_jaws_are_empty(drop):
    """The runner's state did not carry holding before 11-20 and a missing current read as 0 mA (robot-17 review)."""
    cell = HomeCell([*RETURN_HOME[:4], -50.5, 50.0])
    act = cell.act
    cell.act = lambda command: {k: v for k, v in act(command).items() if k != drop}
    out = u.return_home(cell, RETURN_HOME, {"joint_min": {"wrist_roll.pos": -55.5}}, sleep=lambda _: None)
    assert out["result"] == "refused" and not any(c.startswith("jog ") for c in cell.commands)


def test_return_home_accepts_static_friction_plateau():
    state = [*RETURN_HOME[:4], 41.0, 20.0]
    cell = HomeCell(state, lag=1.75)
    out = u.return_home(cell, RETURN_HOME, {"joint_min": {"wrist_roll.pos": -32}}, sleep=lambda _: None)
    assert out["result"] == "home"
    assert out["jogs"][-1]["lags"][4] == 1.75


@pytest.mark.parametrize(("moving", "result"), [(True, "bind_suspected"), (False, "stopped")])
def test_return_home_only_labels_unsettled_motion_as_binding(moving, result):
    class UnsettledCell(HomeCell):
        def act(self, command):
            before = self.measured[4]
            if command == "state" and any(c.startswith("jog") for c in self.commands):
                if moving:
                    self.lag = 1.65 if self.lag > 1.7 else 1.8
                    self.measured[4] = self.target[4] - self.lag
                else:
                    # A changing target alone is not measured joint movement.
                    self.target[4] = self.measured[4] + (1.65 if self.lag > 1.7 else 1.8)
                    self.lag = self.target[4] - self.measured[4]
            status = super().act(command)
            if command.startswith("jog") and not moving:
                self.measured[4] = before
            return status

    cell = UnsettledCell([*RETURN_HOME[:4], -31.0, 20.0], lag=1.7)
    limits = {"joint_min": {"wrist_roll.pos": -32}, "joint_max": {"wrist_flex.pos": 56}}
    out = u.return_home(cell, RETURN_HOME, limits, lift=False, sleep=lambda _: None)
    assert out["result"] == result
    assert cell.commands[-1] == "human-hold"


@pytest.mark.parametrize("lift", [None, ("shoulder_lift", -6.0), False])
def test_return_home_lifts_from_held_target_then_restores_home(lift):
    cell = HomeCell([*RETURN_HOME[:4], 20.0, 20.0])
    cell.measured[0] += 9.0
    cell.target[0] += 9.0
    if lift is not False:
        cell.target[u.BODY.index(lift[0] if lift else "elbow_flex")] += 0.75
    out = u.return_home(cell, RETURN_HOME, {"joint_min": {"wrist_roll.pos": -32}},
                        lift=lift, sleep=lambda _: None)
    assert out["result"] == "home"
    plan = out["plan"]
    if lift is False:
        assert plan[0]["joint"] == "wrist_roll"
    else:
        joint, delta = lift or ("elbow_flex", -10.0)
        axis = u.BODY.index(joint)
        assert [step["joint"] for step in (plan[0], plan[1], plan[-1])] == [joint, "wrist_roll", joint]
        assert plan[0]["goal"] == pytest.approx(out["start"]["target"][axis] + delta)
        assert plan[-1]["goal"] == RETURN_HOME[axis]
    assert cell.target == pytest.approx(RETURN_HOME, abs=0.01)


@pytest.mark.parametrize(("fault", "error"), [
    (None, "elbow_flex: strain"),
    ("contact in jog", "elbow_flex: live state refused after jog"),
    ("profile_mismatch", "elbow_flex: live state refused after jog"),
])
def test_return_home_stops_during_lift_before_turning(fault, error):
    class LiftCell(HomeCell):
        def act(self, command):
            status = super().act(command)
            if fault and command == "state" and any(c.startswith("jog") for c in self.commands):
                status["fault"] = fault
            return status

    cell = LiftCell([*RETURN_HOME[:4], 20.0, 20.0], lag_axis=1, lag=2.1)
    out = u.return_home(cell, RETURN_HOME, {"joint_min": {"wrist_roll.pos": -32}}, sleep=lambda _: None)
    assert out["result"] == ("stopped" if fault == "profile_mismatch" else "bind_suspected")
    assert out["error"] == error
    assert [row["joint"] for row in out["jogs"]] == ["elbow_flex"]
    assert cell.commands[-1] == "human-hold"


def test_return_home_refuses_a_lift_outside_joint_limits_before_motion():
    cell = HomeCell([*RETURN_HOME[:4], 20.0, 20.0])
    limits = {"joint_min": {"elbow_flex.pos": RETURN_HOME[2] - 5}}
    out = u.return_home(cell, RETURN_HOME, limits, sleep=lambda _: None)
    assert out["result"] == "refused" and "elbow_flex" in out["error"]
    assert cell.commands == ["state"]

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import cell_unwedge as u  # noqa: E402
from chunk_runner import SETTLE_TOL  # noqa: E402

HOME = [0.8, -62.2, 53.1, 51.6, 45.2]


class Cell:
    """Joints follow a jog at once, except `stuck` joints, which lag `stuck_lag` behind their target; `droop` is the
    shoulder_lift's lag just holding the pose (a far reach), which it keeps while it moves."""

    def __init__(self, state, stuck=(), stuck_lag=2.0, park_settled=True, park_offset=0.0, droop=0.0):
        self.state, self.target, self.stuck, self.stuck_lag, self.sent = list(state), list(state), stuck, stuck_lag, []
        self.park_settled, self.park_offset, self.droop = park_settled, park_offset, droop
        self.target[1] -= droop

    def act(self, command):
        self.sent.append(command)
        words = command.split()
        if words[0] == "jog":
            i = u.BODY.index(words[1].removesuffix(".pos"))
            self.target[i] += float(words[2])
            self.state[i] = self.target[i] - (self.stuck_lag if words[1].startswith(self.stuck) else 0.0)
            if i == 1 and not words[1].startswith(self.stuck):
                self.state[i] += self.droop
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


def test_a_lift_that_droops_holding_its_pose_is_not_read_as_blocked():
    """2026-11-14 arm_s: the lift lagged 1.3-1.6 just holding a far reach; every 1.0 step read blocked and unwedge stopped."""
    cell = Cell([-5.4, 1.9, -1.0, 48.4, -11.5, 53.2], droop=1.5)
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert out["result"] == "recovered" and all(r["outcome"] == "moved" for r in out["rows"])
    assert {c for c in cell.sent if c.startswith("jog")} <= {"jog shoulder_lift.pos -0.3", "jog elbow_flex.pos 0.3"}


def test_a_drooping_lift_that_stalls_still_stops_below_the_guard():
    """The room over the droop ends at LAG_CEIL: a lift stalled at 2.04 (the guard trips near 2.2) is blocked, not pushed."""
    cell = Cell([-5.4, 1.9, -1.0, 48.4, -11.5, 53.2], stuck=("shoulder_lift", "elbow_flex"), stuck_lag=2.04, droop=1.9)
    out = u.unwedge(cell, HOME, sleep=lambda s: None)
    assert out["result"] == "stuck" and "park" not in cell.sent
    assert all(max(r["lags"]) <= u.LAG_CEIL or r["outcome"] == "blocked" for r in out["rows"])


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
    rose = [c for c in cell.sent if c == f"jog shoulder_lift.pos {-u.STEP}"]
    back = [c for c in cell.sent if c == f"jog shoulder_lift.pos {u.STEP}"]
    assert out["result"] == "stuck" and out["returned"] and len(back) == len(rose)  # back down onto the support it rose from (2026-11-27)
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


def test_home_jogs_uses_checked_prefix_when_session_active():
    class CheckedCell(HomeCell):
        def act(self, command):
            self.commands.append(command)
            if command.startswith("checked sid-42 deadbeef "):
                command = command.removeprefix("checked sid-42 deadbeef ")
            if command.startswith("jog "):
                _, name, delta = command.split()
                axis = u.BODY.index(name.removesuffix(".pos"))
                self.target[axis] += float(delta)
                self.measured[axis] = self.target[axis]
            elif command.startswith("grip "):
                self.measured[5] = self.target[5] = float(command.split()[1])
            return {
                "ok": True, "state": list(self.measured), "target": list(self.target), "holding": False,
                "health": {"current_ma": [0, 0, 0, 0, 0, 10]}, "human_hold_latched": False,
                "operating_context": {"session_id": "sid-42"}, "library_sha256": "deadbeef",
            }

    measured = [1.73, -63.76, 53.41, 55.56, -50.48, 50.0]
    limits = {"joint_min": {"wrist_roll.pos": -55.5}, "joint_max": {"wrist_flex.pos": 55.3}}
    cell = CheckedCell(measured)
    result = u.return_home(cell, RETURN_HOME, limits, sleep=lambda _: None, log=None)
    assert result["result"] == "home"
    jogs = [c for c in cell.commands if "jog " in c]
    grips = [c for c in cell.commands if "grip " in c]
    assert jogs and all(c.startswith("checked sid-42 deadbeef jog ") for c in jogs)
    assert grips and all(c.startswith("checked sid-42 deadbeef grip ") for c in grips)


class SlowJaw(HomeCell):
    """The jaws travel `rate` units per state poll toward the grip target, stopping at `stop` when set."""
    def __init__(self, measured, rate, stop=None):
        super().__init__(measured)
        self.rate, self.stop, self.goal = rate, stop, None

    def act(self, command):
        if command == "state" and self.goal is not None:
            step = max(-self.rate, min(self.rate, self.goal - self.measured[5]))
            if self.stop is not None:
                step = min(step, max(0.0, self.stop - self.measured[5]))
            self.measured[5] += step
        out = super().act(command)
        if command.startswith("grip "):
            self.goal = float(command.split()[1])
            self.measured[5] = self.target[5] = 40.0
            out["state"] = list(self.measured)
        return out


@pytest.mark.parametrize(("rate", "stop", "result"), [(2.8, None, "home"), (60.0, None, "home"), (2.8, 44.0, "stopped")])
def test_home_waits_for_a_slow_gripper_but_a_jaw_stuck_short_still_stops(rate, stop, result):
    cell = SlowJaw([0.8, -62.2, 53.1, 51.6, 45.2, 40.0], rate, stop)
    out = u.return_home(cell, RETURN_HOME, {"joint_min": {"wrist_roll.pos": -32}}, sleep=lambda _: None, log=None)
    assert out["result"] == result


def test_home_grip_wait_stops_when_the_live_state_is_refused():
    class FaultAfterGrip(SlowJaw):
        def act(self, command):
            out = super().act(command)
            if command == "state" and self.goal is not None:
                out["fault"] = "overload"
            return out

    cell = FaultAfterGrip([0.8, -62.2, 53.1, 51.6, 45.2, 40.0], 2.8)
    out = u.return_home(cell, RETURN_HOME, {"joint_min": {"wrist_roll.pos": -32}}, sleep=lambda _: None, log=None)
    assert out["result"] == "stopped" and out["error"] == "live state refused while the grip settled"
    last_grip = max(i for i, c in enumerate(cell.commands) if c.startswith("grip "))
    assert not [c for c in cell.commands[last_grip + 1:] if c.startswith(("grip ", "jog "))]
