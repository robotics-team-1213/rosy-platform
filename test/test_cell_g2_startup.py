"""Startup is a reserved Pilot goal, never a shortcut past Cell admission."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
sys.path.insert(0, str(Path(__file__).parents[1] / "middleware/apps/device/omx/adapter"))
from g2_startup import prepare_home


class Fixture:
    def __init__(self, outcome="success", settle=True):
        self.t = 0.0
        self.calls = []
        self.sink = None
        self.outcome, self.settle = outcome, settle
        self.owner = NS(session_id="session", state="ready", config=NS(
            workcell_id="cell", instance_id="instance", calibration_revision="sim",
            joint_names=("joint1", "gripper")))
        self.latest_joint_state = NS(sequence=1, received_at=0., positions={"joint1": 0., "gripper": 0.})
        self.control_admission = NS(
            acquire=lambda *a, **k: self.calls.append("acquire"),
            reserve_pilot=lambda *a: self.calls.append("reserve"),
            note_goal=lambda *a: self.calls.append(("event", *a)),
            note_rejected=lambda *a: self.calls.append("rejected"),
            release=lambda *a: self.calls.append("release"),
            run_action_admission=lambda op: self.calls.append("reconcile") or op())
        self.profile = NS(velocity_limits={"joint1": .5, "gripper": .5}, planning_limit_fraction=.8,
                          home_joint_tolerance_rad=.02, start_state_tolerance_rad=.02,
                          gripper_joint="gripper", max_joint_state_age_s=.5,
                          action_timeout_s=1., wall_clock_bound_factor=4.)

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.settle:
            self.latest_joint_state = NS(sequence=self.latest_joint_state.sequence+1,
                                        received_at=self.t, positions={"joint1": .2, "gripper": 1.})

    def register_phase_event_sink(self, command_id, sink):
        self.calls.append("bind")
        self.sink = sink

    def submit(self, command):
        if hasattr(self.control_admission, "check_command"):
            assert self.control_admission.check_command(command)
        else:
            assert self.calls[:3] == ["acquire", "reserve", "bind"]
        self.calls.append("submit")
        assert command.owner == "pilot_sim" and command.session_id == "session"
        assert command.expected_start_state_positions == {"joint1": 0., "gripper": 0.}
        if self.outcome == "lost":
            raise RuntimeError("submission unknown")
        self.sink(NS(command_id=command.command_id, kind="GOAL_ACCEPTED", goal_id="uuid", sequence=1))
        self.sink(NS(command_id=command.command_id, kind="TERMINAL_RESULT", sequence=2,
                     goal_id="wrong" if self.outcome == "wrong_uuid" else "uuid",
                     status=4, result_code=1 if self.outcome == "failed" else 0))
        return NS(accepted=True, reason="submitted")

    def run(self):
        return prepare_home(self, self.profile, {"joint1": .2, "gripper": 1.},
                            wall_clock=self.monotonic, sleep=self.sleep)


def test_startup_waits_for_fresh_settled_readback_then_retires_seat():
    f = Fixture()
    result = f.run()
    assert result["result"] == "READY" and result["ros_goal_id"] == "uuid"
    assert f.t >= .5 and result["final_sequence"] > result["initial_sequence"]
    assert f.calls[-2:] == ["release", "reconcile"]


@pytest.mark.parametrize("outcome", ["wrong_uuid", "failed", "lost"])
def test_unknown_or_unsuccessful_goal_does_not_clear_admission(outcome):
    f = Fixture(outcome=outcome)
    with pytest.raises(RuntimeError):
        f.run()
    assert "release" not in f.calls and "reconcile" not in f.calls


def test_terminal_success_without_new_readback_is_not_ready():
    f = Fixture(settle=False)
    with pytest.raises(RuntimeError, match="home readiness timed out"):
        f.run()
    assert "release" not in f.calls


def test_stale_initial_readback_refuses_goal():
    f = Fixture()
    f.t = 2.
    with pytest.raises(RuntimeError, match="initial joint state"):
        f.run()
    assert f.calls == []


def test_real_durable_seat_reconciles_only_after_matching_goal(tmp_path):
    from omx_adapter.action_store import ActionStore
    from omx_adapter.control_seat_admission import ControlSeatAdmission
    f = Fixture()
    f.owner.run_admission_policy = lambda op: op(f.owner.state)
    store = ActionStore(tmp_path / "actions.sqlite3")
    f.control_admission = ControlSeatAdmission(f.owner, store, monotonic=f.monotonic)
    assert f.run()["seat_reconciled"] is True
    assert not f.control_admission._durable.has_pending()


def test_real_durable_seat_preserves_unknown_submission(tmp_path):
    from omx_adapter.action_store import ActionStore
    from omx_adapter.control_seat_admission import ControlSeatAdmission
    f = Fixture(outcome="lost")
    f.owner.run_admission_policy = lambda op: op(f.owner.state)
    f.control_admission = ControlSeatAdmission(f.owner, ActionStore(tmp_path / "actions.sqlite3"),
                                              monotonic=f.monotonic)
    with pytest.raises(RuntimeError, match="submission unknown"):
        f.run()
    assert f.control_admission._durable.has_pending()
    with pytest.raises(PermissionError, match="seat"):
        f.control_admission.run_action_admission(lambda: pytest.fail("must stay fenced"))


def test_frozen_post_terminal_sample_cannot_satisfy_stability():
    f = Fixture()
    original_sleep = f.sleep
    def freeze_after_one(seconds):
        if f.t == 0:
            original_sleep(seconds)
        else:
            f.t += seconds
    f.sleep = freeze_after_one
    with pytest.raises(RuntimeError, match="home readiness timed out"):
        f.run()
    assert "release" not in f.calls


def test_slower_publisher_can_settle_with_duplicate_fresh_polls():
    f = Fixture()
    ticks = [0]
    def slower(seconds):
        f.t += seconds
        ticks[0] += 1
        if ticks[0] % 2 == 0:
            f.latest_joint_state = NS(sequence=f.latest_joint_state.sequence+1,
                                     received_at=f.t, positions={"joint1": .2, "gripper": 1.})
    f.sleep = slower
    assert f.run()["result"] == "READY"
    assert .5 <= f.t < 1.
