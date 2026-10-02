"""D-402 §3: CELL_TRANSFER runs only through its phase runner; gripper start state after grasp."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core_common.protocol.schemas import FleetActionGrant
from omx_adapter.action_runner import ActionRunner, action_grant_digest
from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import TrajectoryCommand
from omx_adapter.gripper_contract import GripperObservation
from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics
from omx_adapter.manipulation_plan import ExecutionStateSnapshot
from omx_adapter.phase_recorder import ActionPhaseRecorder
from omx_adapter.pick_place_runner import PickPlaceRunner
from omx_adapter.pose_plan import CellPlanningProfile

from test_omx_action_api import FakePhaseExecution, _grant, _runner
from test_omx_pick_place_runner import _event, _Fence, _GoalPort
from test_omx_pose_plan import PROFILE_PATH, _plan


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


def _action_runner(store, driver, base, **factories):
    return ActionRunner(
        store, driver, workcell_id="omx-1", instance_id="omx-1-control",
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={1001},
        current_fence=lambda epoch, generation: (epoch, generation) == (2, 8),
        capability_current=lambda grant: grant.config_revision == "cfg-1",
        submission_fence=base.submission_fence, enabled=True, **factories,
    )


def test_cell_transfer_runs_through_its_own_phase_runner(tmp_path):
    store, driver, base = _runner(tmp_path)
    started = []
    runner = _action_runner(store, driver, base, phase_runner_factories={
        "CELL_TRANSFER": lambda grant, recorder: started.append(grant.action_kind)
        or FakePhaseExecution(recorder),
    })
    receipt = runner.submit(_kind("CELL_TRANSFER"), peer_uid=1001)
    assert receipt["state"] == "ACCEPTED"
    assert started == ["CELL_TRANSFER"]
    assert driver.submissions == []
    with pytest.raises(PermissionError, match="no admitted executor"):
        runner.submit(_kind("UNKNOWN_KIND").model_copy(update={"action_id": "action-2"}), peer_uid=1001)


def test_pick_place_factory_never_executes_cell_transfer(tmp_path):
    store, driver, base = _runner(tmp_path)
    started = []
    runner = _action_runner(store, driver, base, phase_runner_factory=lambda grant, recorder: (
        started.append(grant.action_kind) or FakePhaseExecution(recorder)))
    with pytest.raises(PermissionError, match="no admitted executor"):
        runner.submit(_kind("CELL_TRANSFER"), peer_uid=1001)
    assert started == [] and store.get_action("action-1") is None


def test_factory_map_rejects_unknown_kind_and_double_pick_place(tmp_path):
    store, driver, base = _runner(tmp_path)
    with pytest.raises(ValueError, match="phase runner kinds"):
        _action_runner(store, driver, base, phase_runner_factories={"PICK": lambda g, r: None})
    with pytest.raises(ValueError, match="PICK_PLACE"):
        _action_runner(store, driver, base, phase_runner_factory=lambda g, r: None,
                       phase_runner_factories={"PICK_PLACE": lambda g, r: None})


@pytest.fixture(scope="module")
def kin():
    return OmxKinematics.load()


@pytest.fixture(scope="module")
def profile():
    return CellPlanningProfile.load(PROFILE_PATH)


def _held(present=True, *, received_at=100.6, object_id="box"):
    return GripperObservation("omx-1", "omx-1-control", "test-sensor", 7, received_at,
                              "CLOSED", present, object_id if present else None, 8)


def _phase_runner(tmp_path, kin, profile, *, plan=None, grippers=None, arm_delta=0.0,
                  cell_profile="default", readback="default"):
    """Runner whose state provider returns each phase's planned start, with overrides."""
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
    plan = plan or _plan(kin, profile)
    calls = {"n": 0}

    def state():
        index = min(calls["n"], 3)
        calls["n"] += 1
        phase = plan.phases[index]
        positions = dict(zip(phase.joint_names, phase.start_state_positions))
        positions["joint2"] += arm_delta
        if grippers and phase.phase_id in grippers:
            positions["gripper_joint_1"] = grippers[phase.phase_id]
        return ExecutionStateSnapshot(
            sequence=plan.source_state_sequence + 1 + index, joint_positions=positions,
            calibration_revision=phase.calibration_revision, transform_revision=phase.transform_revision,
            planning_scene_revision=phase.planning_scene_revision, observed_at_monotonic_s=100.6,
        )

    port = _GoalPort()

    def succeed(command, goal, callback):
        callback(_event("GOAL_ACCEPTED", command, command.phase_id, goal, 1))
        callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))

    port.on_submit = succeed
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
        current_execution_state=state,
        start_state_tolerances=profile.start_state_tolerances(),
        max_joint_state_age_s=0.5, monotonic=lambda: 100.7,
        cell_profile=profile if cell_profile == "default" else cell_profile,
        gripper_readback=_held if readback == "default" else readback, held_object_id="box",
    )
    return recorder, port, runner


def _run_all(runner):
    runner.start()
    for _ in range(3):
        runner.advance()


def test_gripper_is_checked_before_grasp_and_ignored_after(tmp_path, kin, profile):
    # transfer/release: gripper stops at the object width, not the planned closed value.
    recorder, port, runner = _phase_runner(
        tmp_path / "after", kin, profile, grippers={"transfer": 0.3, "release": 0.3})
    _run_all(runner)
    assert [row["state"] for row in recorder.phases()] == ["SUCCEEDED"] * 4
    # approach and grasp check the gripper like any joint.
    for phase_id, name in (("approach", "a"), ("grasp", "g")):
        recorder, port, runner = _phase_runner(tmp_path / name, kin, profile, grippers={phase_id: 0.3})
        with pytest.raises(RuntimeError, match="start state is invalid"):
            _run_all(runner)
        assert [row["phase_id"] for row in recorder.phases()] == (
            [] if phase_id == "approach" else ["approach"])


def test_arm_joint_outside_tolerance_still_holds(tmp_path, kin, profile):
    recorder, port, runner = _phase_runner(tmp_path, kin, profile, arm_delta=0.05)
    with pytest.raises(RuntimeError, match="start state is invalid"):
        runner.start()
    assert port.submissions == []


def test_runner_rejects_a_plan_whose_unchecked_joints_are_not_the_profile_gripper(tmp_path, kin, profile):
    plan = _plan(kin, profile)
    object.__setattr__(plan, "gripper_joint_names", ARM_JOINTS)  # forged after validation
    with pytest.raises(ValueError, match="gripper"):
        _phase_runner(tmp_path / "forged", kin, profile, plan=plan)
    with pytest.raises(ValueError, match="cell_profile"):
        _phase_runner(tmp_path / "noprofile", kin, profile, cell_profile=None)


def test_cell_transfer_tolerances_cover_every_planned_joint(profile):
    assert set(profile.start_state_tolerances()) == set(profile.joint_names)


def test_runner_hands_the_owner_its_start_check_as_a_window(tmp_path, kin, profile):
    # A1 (C3b): the owner re-runs this exact check on its newest state under its lock, so a
    # joint state that lands while the runner journals no longer rejects the phase.
    recorder, port, runner = _phase_runner(tmp_path, kin, profile, grippers={"transfer": 0.3})
    _run_all(runner)
    tolerances = profile.start_state_tolerances()
    for (command, _goal), phase in zip(port.submissions, runner.plan.phases):
        window = command.start_state_window
        expected = dict(zip(phase.joint_names, phase.start_state_positions))
        skipped = {"gripper_joint_1"} if phase.phase_id in ("transfer", "release") else set()
        assert set(window) == set(phase.joint_names) - skipped
        for name, (value, tolerance) in window.items():
            assert value == expected[name] and tolerance == tolerances[name]


# A4 (C3b): C3 run8 passed every gate while the block fell in transit. The runner re-reads
# the gripper immediately before submitting release and HOLDs if it no longer holds the item.
def test_release_is_not_submitted_when_the_item_was_lost_in_transit(tmp_path, kin, profile):
    recorder, port, runner = _phase_runner(tmp_path, kin, profile,
                                           readback=lambda: _held(present=False))
    runner.start()
    runner.advance()
    runner.advance()
    with pytest.raises(RuntimeError, match="item_lost_in_transit"):
        runner.advance()
    assert [command.phase_id for command, _ in port.submissions] == ["approach", "grasp", "transfer"]
    parent = recorder.parent()
    assert parent["state"] == "HOLD" and parent["reason"] == "ITEM_LOST_IN_TRANSIT"


@pytest.mark.parametrize("readback", [
    lambda: _held(received_at=99.0),            # stale (max age 0.5 s at t=100.7)
    lambda: _held(object_id="slip_sheet"),      # another item
    lambda: (_ for _ in ()).throw(OSError("no readback")),
])
def test_release_holds_on_a_stale_wrong_or_missing_readback(tmp_path, kin, profile, readback):
    recorder, port, runner = _phase_runner(tmp_path, kin, profile, readback=readback)
    runner.start()
    runner.advance()
    runner.advance()
    with pytest.raises(RuntimeError, match="item_lost_in_transit"):
        runner.advance()
    assert recorder.parent()["reason"] == "ITEM_LOST_IN_TRANSIT"
    assert len(port.submissions) == 3


def test_release_proceeds_after_a_fresh_hold_readback(tmp_path, kin, profile):
    recorder, port, runner = _phase_runner(tmp_path, kin, profile)
    _run_all(runner)
    assert [row["state"] for row in recorder.phases()] == ["SUCCEEDED"] * 4


def test_cell_transfer_runner_requires_a_gripper_readback(tmp_path, kin, profile):
    with pytest.raises(ValueError, match="gripper_readback"):
        _phase_runner(tmp_path, kin, profile, readback=None)


def _widened(profile):
    import copy

    import yaml

    from test_omx_pose_plan import PROFILE_PATH as path
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["phase_start_state_tolerance_rad"] = {"transfer": {"joint5": 0.06}}
    return CellPlanningProfile.from_mapping(copy.deepcopy(document), revision=profile.revision)


def test_wrist_deflection_after_grasp_uses_the_profile_phase_tolerance(tmp_path, kin, profile):
    # A5 (C3b): joint5 sags under the held item; only transfer's joint5 window is widened.
    widened = _widened(profile)
    plan = _plan(kin, profile)

    def deflected(phase_id, joint, delta):
        recorder, port, runner = _phase_runner(tmp_path / f"{phase_id}{joint}{delta}", kin, profile,
                                               plan=plan, cell_profile=widened)
        original = runner.current_execution_state

        def state():
            snapshot = original()
            index = len(port.submissions)
            if plan.phases[index].phase_id == phase_id:
                positions = dict(snapshot.joint_positions)
                positions[joint] += delta
                snapshot = replace(snapshot, joint_positions=positions)
            return snapshot

        runner.current_execution_state = state
        return recorder, port, runner

    recorder, port, runner = deflected("transfer", "joint5", 0.05)
    _run_all(runner)
    window = port.submissions[2][0].start_state_window
    assert window["joint5"][1] == 0.06 and window["joint4"][1] == 0.02
    for phase_id, joint in (("transfer", "joint4"), ("grasp", "joint5"), ("release", "joint5")):
        recorder, port, runner = deflected(phase_id, joint, 0.05)
        with pytest.raises(RuntimeError, match="start state is invalid"):
            _run_all(runner)
