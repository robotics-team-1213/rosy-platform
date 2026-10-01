"""D-402 §3: CELL_TRANSFER runs only through the phase runner; gripper excluded from start state."""

from __future__ import annotations

import pytest

from core_common.protocol.schemas import FleetActionGrant
from omx_adapter.action_runner import ActionRunner, action_grant_digest
from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import TrajectoryCommand
from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics
from omx_adapter.phase_recorder import ActionPhaseRecorder
from omx_adapter.pick_place_runner import PickPlaceRunner

from test_omx_action_api import FakePhaseExecution, _grant, _runner
from test_omx_pick_place_runner import _Fence, _GoalPort
from test_omx_pose_plan import PROFILE_PATH, _plan, _state
from omx_adapter.pose_plan import CellPlanningProfile


def _kind(kind):
    # The Fleet grant schema still admits only PICK_PLACE (C4 adds CELL_TRANSFER);
    # model_copy builds the device-side view without widening that schema here.
    grant = FleetActionGrant.model_validate(_grant()).model_copy(update={"action_kind": kind})
    return grant.model_copy(update={"request_digest": action_grant_digest(grant)})


@pytest.mark.parametrize("kind", ["CELL_TRANSFER", "PICK", "UNKNOWN_KIND"])
def test_direct_driver_path_rejects_every_kind_but_pick_place_before_journal(tmp_path, kind):
    store, driver, runner = _runner(tmp_path)
    with pytest.raises(PermissionError, match="no admitted executor"):
        runner.submit(_kind(kind), peer_uid=1001)
    assert driver.submissions == []
    assert store.get_action("action-1") is None


def test_cell_transfer_runs_through_the_phase_runner(tmp_path):
    store, driver, base = _runner(tmp_path)
    started = []
    runner = ActionRunner(
        store, driver, workcell_id="omx-1", instance_id="omx-1-control",
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={1001},
        current_fence=lambda epoch, generation: (epoch, generation) == (2, 8),
        capability_current=lambda grant: grant.config_revision == "cfg-1",
        submission_fence=base.submission_fence, enabled=True,
        phase_runner_factory=lambda grant, recorder: started.append(grant.action_kind)
        or FakePhaseExecution(recorder),
    )
    receipt = runner.submit(_kind("CELL_TRANSFER"), peer_uid=1001)
    assert receipt["state"] == "ACCEPTED"
    assert started == ["CELL_TRANSFER"]
    assert driver.submissions == []
    # Unknown kinds stay closed even with a phase runner configured.
    with pytest.raises(PermissionError, match="no admitted executor"):
        runner.submit(_kind("UNKNOWN_KIND").model_copy(update={"action_id": "action-2"}), peer_uid=1001)


@pytest.fixture(scope="module")
def kin():
    return OmxKinematics.load()


@pytest.fixture(scope="module")
def profile():
    return CellPlanningProfile.load(PROFILE_PATH)


def _phase_runner(tmp_path, kin, profile, *, tolerances=None, gripper=None, arm_delta=0.0):
    grant = FleetActionGrant.model_validate(_grant())
    store = ActionStore(tmp_path / "cell.sqlite3")
    store.create_action(
        workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        principal_id="fleet-uid-1001", request_key=grant.action_id, action_id=grant.action_id,
        action_kind=grant.action_kind, configuration_revision=grant.config_revision,
        observation_id=grant.observation_revision, owner_generation=grant.dispatch_generation,
        payload=grant.model_dump(mode="json"),
    )
    store.begin_submission(grant.action_id, expected_generation=grant.dispatch_generation,
                           attempt_id=grant.attempt_id)
    recorder = ActionPhaseRecorder(store, action_id=grant.action_id, attempt_id=grant.attempt_id)
    plan = _plan(kin, profile)
    planned = _state(kin, profile, sequence=plan.source_state_sequence + 1)
    positions = dict(planned.joint_positions)
    positions["joint2"] += arm_delta
    if gripper is not None:
        positions["gripper_joint_1"] = gripper
    state = type(planned)(
        sequence=planned.sequence, joint_positions=positions,
        calibration_revision=planned.calibration_revision, transform_revision=planned.transform_revision,
        planning_scene_revision=planned.planning_scene_revision, observed_at_monotonic_s=100.6,
    )
    port = _GoalPort()
    runner = PickPlaceRunner(
        recorder, grant, plan, command_for_phase=lambda phase: TrajectoryCommand(
            workcell_id=grant.workcell_id, instance_id=grant.instance_id,
            command_id=f"cmd-{phase.phase_id}", session_id="session-1", owner="rule_based",
            positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
            duration_s=phase.points[-1].time_from_start_s,
            source_state_sequence=phase.source_state_sequence,
            calibration_revision=phase.calibration_revision, joint_names=phase.joint_names,
            trajectory_points=phase.points, phase_id=phase.phase_id,
        ),
        goal_port=port, submission_fence=_Fence(), phase_gate=lambda _phase: True,
        current_fence=lambda epoch, generation: (epoch, generation) == (2, 8),
        current_execution_state=lambda: state,
        start_state_tolerances=tolerances or profile.start_state_tolerances(),
        max_joint_state_age_s=0.5, monotonic=lambda: 100.7,
    )
    return recorder, port, runner


def test_cell_transfer_start_state_ignores_gripper_but_checks_arm(tmp_path, kin, profile):
    # Gripper far from the planned open value: not a start-state failure.
    recorder, port, runner = _phase_runner(tmp_path / "a", kin, profile, gripper=0.2)
    runner.start()
    assert len(port.submissions) == 1
    assert recorder.phases()[0]["state"] == "ACCEPTED"
    # Arm joint outside tolerance still holds before any goal.
    recorder, port, runner = _phase_runner(tmp_path / "b", kin, profile, arm_delta=0.05)
    with pytest.raises(RuntimeError, match="start state is invalid"):
        runner.start()
    assert port.submissions == []


def test_cell_transfer_tolerances_must_cover_arm_joints_only(tmp_path, kin, profile):
    with_gripper = {**profile.start_state_tolerances(), "gripper_joint_1": 0.02}
    with pytest.raises(ValueError, match="checked planned joints"):
        _phase_runner(tmp_path, kin, profile, tolerances=with_gripper)
    assert set(profile.start_state_tolerances()) == set(ARM_JOINTS)
