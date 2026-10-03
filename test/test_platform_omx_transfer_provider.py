"""ROS-free contract tests for the OMX transfer integration provider."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for package_root in (
    ROOT / "contracts/skill/src",
    ROOT / "middleware/skills/api/src",
    ROOT / "middleware/skills/manipulation/src",
    ROOT / "contracts/foundation",
    ROOT / "middleware/apps/device/omx/adapter",
    ROOT / "integrations/robots/omx/src",
    ROOT / "middleware/apps/device/omx/adapter/test",
):
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from core_common.protocol.schemas import FleetCellTransferGrant  # noqa: E402
from omx_adapter.pose_plan import CellPlanningProfile  # noqa: E402
from rosy.integrations.robots.omx.transfer_provider import (  # noqa: E402
    OMXAnalyticTransferPlanner,
    cell_transfer_invocation,
    create_cell_transfer_phase_factory,
)
from rosy.skills.api import SkillInvocation  # noqa: E402
from rosy.skills.manipulation.transfer import PlannedTransfer, TransferSkill  # noqa: E402


NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _grant():
    return FleetCellTransferGrant.model_validate({
        "mission_id": "mission-1", "step_id": "step-1", "action_id": "action-1",
        "attempt_id": "attempt-1", "request_digest": "a" * 64,
        "workcell_id": "cell-1", "instance_id": "cell-1-a", "action_kind": "CELL_TRANSFER",
        "cell_transfer": {
            "job_id": "job-1", "recipe_sha256": "b" * 64, "cell_sha256": "c" * 64,
            "step_index": 2, "item": "box", "pallet": "pallet-1", "layer": 1,
            "frame": "robot_base",
            "home": {"x": 0.1, "y": 0.0, "z": 0.2, "yaw": 0.0},
            "pick": {"x": 0.2, "y": 0.0, "z": 0.04, "yaw": 0.0},
            "place": {"x": 0.3, "y": 0.0, "z": 0.04, "yaw": 0.0},
            "pick_approach_z": 0.12, "place_approach_z": 0.12, "carry_z": 0.18,
        },
        "capability_revision": "cap-1", "config_revision": "cfg-1",
        "authority_epoch": 4, "dispatch_generation": 9,
        "issued_at": NOW, "expires_at": NOW + timedelta(minutes=5),
    })


class _Planner:
    def __init__(self):
        self.calls = []

    def plan(self, invocation):
        self.calls.append(invocation)
        return "opaque-plan"


class _Runner:
    def __init__(self, plan):
        self.plan = plan
        self.started = 0
        self.cancelled = 0
        self.active_phase_id = None

    def start(self):
        self.started += 1
        self.active_phase_id = "approach"
        return {"state": "SUBMITTING"}

    def cancel_current(self):
        self.cancelled += 1
        return {"state": "CANCEL_REQUESTED"}


def test_grant_maps_to_skill_invocation_and_existing_runner_ports():
    grant = _grant()
    invocation = cell_transfer_invocation(grant)
    planner = _Planner()
    runners = []

    def runner_for_grant(received, recorder, planned):
        runner = _Runner(planned.plan)
        runners.append((received, recorder, planned, runner))
        return runner

    factory = create_cell_transfer_phase_factory(
        skill=TransferSkill(), planner_for_grant=lambda received: planner,
        executor_for_grant=runner_for_grant,
    )
    phase = factory(grant, "recorder")
    assert phase.active_phase_id is None
    receipt = phase.start()
    assert phase.active_phase_id == "approach"
    runners[0][3].active_phase_id = "carry"
    assert phase.active_phase_id == "carry"
    cancelled = phase.cancel_current()

    assert invocation.inputs["item"] == "box"
    assert invocation.inputs["source_pose_base"]["x_m"] == pytest.approx(0.2)
    assert invocation.inputs["destination_pose_base"]["x_m"] == pytest.approx(0.3)
    assert planner.calls == [invocation]
    received, recorder, planned, runner = runners[0]
    assert received is grant and recorder == "recorder"
    assert isinstance(planned, PlannedTransfer) and planned.plan == "opaque-plan"
    assert (runner.started, runner.cancelled) == (1, 1)
    assert receipt == {"state": "SUBMITTING"}
    assert cancelled == {"state": "CANCEL_REQUESTED"}


def test_omx_planner_uses_grant_hashes_and_accepted_recipe_geometry():
    grant = _grant()
    calls = []
    marker = object()
    planner = SimpleNamespace(plan_transfer=lambda request, profile, state: (
        calls.append((request, profile, state)) or marker
    ))
    profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    state = object()
    geometry_calls = []
    adapter = OMXAnalyticTransferPlanner(
        grant, profile=profile, planner=planner, execution_state=lambda: state,
        accepted_item_geometry=lambda recipe, item: (
            geometry_calls.append((recipe, item)) or {
                "grasp_width_m": 0.06, "grasp_depth_m": 0.02, "height_m": 0.1,
            }
        ),
    )

    result = adapter.plan(cell_transfer_invocation(grant))

    request, used_profile, used_state = calls[0]
    assert result is marker
    assert (request.job_id, request.recipe_sha256, request.cell_sha256) == (
        "job-1", "b" * 64, "c" * 64,
    )
    assert (request.step_index, request.item, request.grasp_width_m, request.grasp_depth_m) == (
        2, "box", 0.06, 0.02,
    )
    assert (request.home.x, request.pick.x, request.place.x) == (0.1, 0.2, 0.3)
    assert (used_profile, used_state) == (profile, state)
    assert geometry_calls == [("b" * 64, "box")]


def test_provider_rejects_invocation_or_invalid_accepted_geometry_before_planning():
    grant = _grant()
    profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    calls = []
    adapter = OMXAnalyticTransferPlanner(
        grant, profile=profile,
        planner=SimpleNamespace(plan_transfer=lambda *args: calls.append(args)),
        execution_state=lambda: object(),
        accepted_item_geometry=lambda *_args: {
            "grasp_width_m": 0.06, "grasp_depth_m": 0.02, "height_m": float("nan"),
        },
    )
    altered = SkillInvocation("pallet.transfer", "1.0.0", {
        **dict(cell_transfer_invocation(grant).inputs), "pallet_id": "another-pallet",
    })
    with pytest.raises(ValueError, match="does not match"):
        adapter.plan(altered)
    with pytest.raises(ValueError, match="height"):
        adapter.plan(cell_transfer_invocation(grant))
    assert calls == []


def test_skill_wrapped_cell_action_cancels_only_its_live_phase(tmp_path):
    from omx_adapter.action_api import ActionApi
    from omx_adapter.action_store import InvalidActionTransition
    from test_omx_action_api import FakePhaseExecution, _cell_transfer_grant, _runner

    executions = []

    def executor_for_grant(grant, recorder, planned):
        execution = FakePhaseExecution(recorder)
        execution.plan = planned.plan
        executions.append(execution)
        return execution

    factory = create_cell_transfer_phase_factory(
        skill=TransferSkill(), planner_for_grant=lambda _: _Planner(),
        executor_for_grant=executor_for_grant,
    )
    store, driver, runner = _runner(
        tmp_path, phase_runner_factories={"CELL_TRANSFER": factory},
    )
    api = ActionApi(runner)
    submitted = api.dispatch({
        "version": 2, "operation": "SubmitAction", "grant": FleetCellTransferGrant.model_validate(
            _cell_transfer_grant(),
        ).model_dump(mode="json"),
    }, peer_uid=1001)
    assert submitted["status"] == 200, submitted
    assert submitted["receipt"]["state"] == "ACCEPTED"
    with pytest.raises(InvalidActionTransition, match="active ROS goal"):
        runner.cancel_phase("cell-action-1", "cell-attempt-1",
                            phase_id="release", peer_uid=1001)
    assert store.action_phases("cell-action-1")[0]["state"] == "ACCEPTED"

    cancelled = api.dispatch({
        "version": 2, "operation": "CancelAction", "action_id": "cell-action-1",
        "attempt_id": "cell-attempt-1", "reason": "SITE_STOP",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }, peer_uid=1001)
    assert cancelled["status"] == 200
    # A phase cancel request does not establish a terminal parent Action result.
    assert cancelled["receipt"]["state"] == "ACCEPTED"
    phase = store.action_phases("cell-action-1")[0]
    assert (phase["phase_id"], phase["driver_goal_id"], phase["state"]) == (
        "approach", "ros-goal-approach", "CANCEL_REQUESTED",
    )
    assert len(executions) == 1
    assert driver.submissions == driver.cancellations == driver.phase_cancellations == []


@pytest.mark.parametrize("deny_phase", [None, "transfer"])
@pytest.mark.parametrize("workflow_revision,release_fault", [
    (None, None), ("readback", None), ("readback", "wrong-instance"), ("readback", "old-sequence"),
    ("readback", "grasp-timeout"), ("readback", "release-timeout"),
    ("readback", "clock-failure"),
])
def test_composed_cell_skill_runs_real_analytic_plan_and_phase_journal(
        tmp_path, deny_phase, workflow_revision, release_fault):
    from dataclasses import asdict, replace
    from omx_adapter.action_api import ActionApi
    from omx_adapter.action_runner import ActionRunner
    from omx_adapter.action_store import ActionStore
    from omx_adapter.command_owner import TrajectoryCommand
    from omx_adapter.gripper_contract import GripperObservation
    from omx_adapter.kinematics import OmxKinematics
    from rosy.integrations.robots.omx.transfer_provider import create_omx_cell_transfer_phase_factory
    from test_omx_action_api import _cell_transfer_grant, _runner
    from test_omx_pick_place_runner import _event, _GoalPort
    from test_omx_pose_plan import _request, _planner, _state

    kin = OmxKinematics.load()
    profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    request = _request()
    transfer = dict(_cell_transfer_grant()["cell_transfer"])
    for name in ("job_id", "recipe_sha256", "cell_sha256", "step_index", "item",
                 "pick_approach_z", "place_approach_z", "carry_z"):
        transfer[name] = getattr(request, name)
    for name in ("home", "pick", "place"):
        transfer[name] = asdict(getattr(request, name))
    grant = FleetCellTransferGrant.model_validate(
        _cell_transfer_grant(cell_transfer=transfer),
    )
    states = [_state(kin, profile)]
    port = _GoalPort()

    def succeed(command, goal, callback):
        callback(_event("GOAL_ACCEPTED", command, command.phase_id, goal, 1))
        states[0] = replace(states[0], sequence=states[0].sequence + 1,
                            joint_positions=dict(command.positions), observed_at_monotonic_s=100.5)
        callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))

    port.on_submit = succeed
    store, driver, action_runner = _runner(tmp_path)
    executions = []

    def readback():
        phase_id = port.submissions[-1][0].phase_id
        if release_fault == f"{phase_id}-timeout":
            raise TimeoutError("sensor unavailable")
        return GripperObservation(
            grant.workcell_id, "elsewhere" if release_fault == "wrong-instance"
            and phase_id == "release" else grant.instance_id, "readback",
            8 if phase_id == "release" and release_fault != "old-sequence" else 7, 100.5,
            "OPEN" if phase_id == "release" else "CLOSED", phase_id != "release",
            None if phase_id == "release" else request.item, grant.dispatch_generation,
        )

    def now():
        return datetime.now(timezone.utc)

    factory = create_omx_cell_transfer_phase_factory(
        profile=profile, planner=_planner(kin), execution_state=lambda: states[0],
        accepted_item_geometry=lambda recipe, item: {
            "grasp_width_m": request.grasp_width_m, "grasp_depth_m": request.grasp_depth_m,
            "height_m": 0.03,
        } if (recipe, item) == (request.recipe_sha256, request.item) else None,
        command_for_phase=lambda accepted, phase: TrajectoryCommand(
            workcell_id=accepted.workcell_id, instance_id=accepted.instance_id,
            command_id=f"{accepted.action_id}-{phase.phase_id}", session_id="session-1",
            owner="rule_based", positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
            duration_s=phase.points[-1].time_from_start_s,
            source_state_sequence=phase.source_state_sequence,
            calibration_revision=phase.calibration_revision, joint_names=phase.joint_names,
            trajectory_points=phase.points, phase_id=phase.phase_id,
        ),
        goal_port=port, submission_fence=action_runner.submission_fence,
        phase_gate=lambda accepted, phase: accepted is grant and phase != deny_phase,
        current_fence=action_runner.current_fence,
        gripper_readback=readback,
        monotonic=lambda: 100.5,
        now=now,
        **({"gripper_sensor_revision": workflow_revision} if workflow_revision else {}),
    )

    def capture(accepted, recorder):
        # Keep the deserialized grant used by the local semantic gate.
        nonlocal grant
        grant = accepted
        execution = factory(accepted, recorder)
        executions.append(execution)
        return execution

    action_runner.phase_runner_factories["CELL_TRANSFER"] = capture
    response = ActionApi(action_runner).dispatch({
        "version": 2, "operation": "SubmitAction", "grant": grant.model_dump(mode="json"),
    }, peer_uid=1001)
    assert response["status"] == 200, response
    assert response["receipt"]["state"] == "ACCEPTED", response
    execution = executions[0]
    execution.advance()
    if release_fault == "grasp-timeout":
        from omx_adapter.pick_place_transaction import TransactionError
        with pytest.raises(TransactionError):
            execution.advance()
        assert store.get_action(grant.action_id)["state"] == "HOLD"
        execution.advance()
        assert len(port.submissions) == 2
    elif deny_phase:
        with pytest.raises(RuntimeError, match="semantic workflow gate"):
            execution.advance()
        assert [row["phase_id"] for row in store.action_phases(grant.action_id)] == ["approach", "grasp"]
    else:
        execution.advance()
        execution.advance()
        assert [row["state"] for row in store.action_phases(grant.action_id)] == ["SUCCEEDED"] * 4
        if workflow_revision:
            if release_fault:
                from omx_adapter.pick_place_transaction import TransactionError
                if release_fault == "clock-failure":
                    def unavailable_clock():
                        raise RuntimeError("clock unavailable")
                    execution.now = unavailable_clock
                with pytest.raises(RuntimeError if release_fault == "clock-failure" else TransactionError):
                    execution.advance()
                assert store.get_action(grant.action_id)["state"] == "HOLD"
            else:
                execution.advance()
                assert store.get_action(grant.action_id)["state"] == "SUCCEEDED"
                assert store.latest_workflow_state(grant.action_id, grant.attempt_id) == "ACTION_SUCCEEDED"
            execution.advance()
        else:
            with pytest.raises(RuntimeError, match="already been submitted"):
                execution.advance()
        assert len(port.submissions) == 4
    assert driver.submissions == []
    from omx_adapter.local_stop import LocalStopBlocked, LocalStopController
    from test_omx_action_api import FakeDriver

    reopened_store = ActionStore(tmp_path / "actions.sqlite3")
    reopened_driver = FakeDriver()
    reopened_stop = LocalStopController(
        tmp_path / "actions.sqlite3", workcell_id=grant.workcell_id, instance_id=grant.instance_id,
    )
    if not (workflow_revision and not deny_phase and not release_fault):
        with pytest.raises(LocalStopBlocked, match="unresolved local Actions"):
            reopened_stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
                                fleet_fence_current=action_runner.current_fence)
    reopened_runner = ActionRunner(
        reopened_store, reopened_driver, workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        principal_for_peer=action_runner.principal_for_peer, allowed_peer_uids={1001},
        current_fence=action_runner.current_fence, capability_current=action_runner.capability_current,
        submission_fence=reopened_stop, phase_runner_factories={"CELL_TRANSFER": capture}, enabled=True,
    )
    replay = ActionApi(reopened_runner).dispatch({
        "version": 2, "operation": "SubmitAction", "grant": grant.model_dump(mode="json"),
    }, peer_uid=1001)
    assert replay["status"] == 200, replay
    assert replay["receipt"]["attempt_id"] == grant.attempt_id
    assert replay["receipt"]["created"] is False
    assert len(executions) == 1
    assert len(port.submissions) == (2 if deny_phase or release_fault == "grasp-timeout" else 4)
    assert reopened_store.action_phases(grant.action_id) == store.action_phases(grant.action_id)
    assert reopened_driver.submissions == []


def test_cell_transaction_has_recipe_provenance_and_reuses_gripper_checks():
    from omx_adapter.gripper_contract import GripperObservation
    from omx_adapter.pick_place_transaction import ArmActionResult, PickPlaceTransaction, TransactionError

    grant = _grant()
    tx = PickPlaceTransaction.for_cell_transfer(grant, gripper_sensor_revision="sensor-1")
    snapshot = tx.snapshot()
    assert snapshot["cell_grant"] == grant.model_dump(mode="json")
    assert snapshot["source_observation_id"] is None

    def result(stage):
        return ArmActionResult(grant.action_id, grant.attempt_id, grant.workcell_id,
                              grant.dispatch_generation, stage, True, True, True, f"ros-{stage}", 10.0)

    tx.record_arm_result(result("approach"))
    tx.record_arm_result(result("grasp"))
    held = GripperObservation(grant.workcell_id, grant.instance_id, "sensor-1", 1,
                              10.0, "CLOSED", True, "box", grant.dispatch_generation)
    tx.verify_gripper_held(held, now=10.1, max_age_s=0.5)
    tx.record_arm_result(result("transfer"))
    tx.record_arm_result(result("release"))
    released = GripperObservation(grant.workcell_id, grant.instance_id, "sensor-1", 2,
                                  10.2, "OPEN", False, None, grant.dispatch_generation)
    tx.verify_gripper_released(released, now=10.3, max_age_s=0.5)
    assert tx.workflow_evidence()["workflow_state"] == "ACTION_SUCCEEDED"
    assert tx.workflow_evidence()["evidence_refs"]["gripper_release_sequence"] == 2
    recovered = PickPlaceTransaction.recover(snapshot)
    assert recovered.state.value == "HOLD"
    assert recovered.snapshot()["cell_grant"] == snapshot["cell_grant"]
    with pytest.raises(ValueError, match="identity does not match"):
        PickPlaceTransaction.recover({**snapshot, "attempt_id": "another-attempt"})
    with pytest.raises(TransactionError, match="HOLD"):
        recovered.record_arm_result(result("approach"))


@pytest.mark.parametrize("field,value", [("instance_id", "elsewhere"), ("owner_generation", 123),
                                       ("sensor_revision", "other"), ("object_id", "other")])
def test_cell_transaction_rejects_gripper_identity_mismatch(field, value):
    from dataclasses import replace
    from omx_adapter.gripper_contract import GripperObservation
    from omx_adapter.pick_place_transaction import ArmActionResult, PickPlaceTransaction, TransactionError

    grant = _grant()
    tx = PickPlaceTransaction.for_cell_transfer(grant, gripper_sensor_revision="sensor-1")
    for stage in ("approach", "grasp"):
        tx.record_arm_result(ArmActionResult(grant.action_id, grant.attempt_id, grant.workcell_id,
                             grant.dispatch_generation, stage, True, True, True, f"ros-{stage}", 10.0))
    held = GripperObservation(grant.workcell_id, grant.instance_id, "sensor-1", 1,
                              10.0, "CLOSED", True, "box", grant.dispatch_generation)
    with pytest.raises(TransactionError):
        tx.verify_gripper_held(replace(held, **{field: value}), now=10.1, max_age_s=0.5)
    assert tx.state.value == "HOLD"


def test_cell_cancel_timeout_records_workflow_hold_and_blocks_late_success(tmp_path):
    from omx_adapter.action_api import ActionApi
    from omx_adapter.pick_place_transaction import PickPlaceTransaction, PickPlaceWorkflowJournal
    from rosy.integrations.robots.omx.cell_workflow import CellTransferWorkflowExecution
    from test_omx_action_api import FakePhaseExecution, _cell_transfer_grant, _runner

    executions = []

    def create(grant, recorder):
        workflow = PickPlaceWorkflowJournal(PickPlaceTransaction.for_cell_transfer(
            grant, gripper_sensor_revision="sensor-1"), recorder)
        underlying = FakePhaseExecution(recorder)

        def timeout():
            recorder.request_cancel(phase_id="approach")
            raise TimeoutError("cancel ACK unavailable")

        underlying.cancel_current = timeout
        execution = CellTransferWorkflowExecution(
            underlying, workflow, recorder, gripper_readback=lambda: None,
            max_age_s=0.5, monotonic=lambda: 10.0, complete_if_current=lambda operation: operation(),
        )
        executions.append(execution)
        return execution

    store, driver, runner = _runner(tmp_path, phase_runner_factories={"CELL_TRANSFER": create})
    api = ActionApi(runner)
    grant = FleetCellTransferGrant.model_validate(_cell_transfer_grant()).model_dump(mode="json")
    assert api.dispatch({"version": 2, "operation": "SubmitAction", "grant": grant}, peer_uid=1001)["status"] == 200
    with pytest.raises(TimeoutError):
        runner.cancel("cell-action-1", "cell-attempt-1", peer_uid=1001)
    assert store.get_action("cell-action-1")["state"] == "HOLD"
    assert store.latest_workflow_state("cell-action-1", "cell-attempt-1") == "HOLD"
    executions[0].recorder.record_terminal(
        phase_id="approach", driver_goal_id="ros-goal-approach", outcome="SUCCEEDED",
        result_source="ros-action-result", result_observed_at=datetime.now(timezone.utc).isoformat(), result={},
    )
    assert executions[0].advance()["state"] == "HOLD"
    assert len(store.action_phases("cell-action-1")) == 1
    assert driver.submissions == driver.cancellations == []
