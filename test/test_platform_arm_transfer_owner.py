"""Neutral owner: real planner/journal, injected simulation goal and gripper ports."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in ("contracts/foundation", "middleware/devices/omx/adapter",
                 "integrations/robots/omx/src", "middleware/devices/omx/adapter/test"):
    sys.path.insert(0, str(ROOT / relative))

from core_common.protocol.schemas import FleetArmTransferGrant  # noqa: E402
from omx_adapter.action_api import ActionApi  # noqa: E402
from omx_adapter.action_runner import action_grant_digest  # noqa: E402
from omx_adapter.command_owner import TrajectoryCommand  # noqa: E402
from omx_adapter.gripper_contract import GripperObservation  # noqa: E402
from omx_adapter.transfer_object_bindings import TransferObjectBindings  # noqa: E402
from test_omx_action_api import _runner  # noqa: E402
from test_omx_pick_place_runner import _event, _GoalPort  # noqa: E402
from test_omx_pose_plan import kin, profile, _state  # noqa: E402,F401
from test_transfer_preflight import _catalog  # noqa: E402


def api():
    try:
        return import_module("rosy.integrations.robots.omx.arm_transfer")
    except ModuleNotFoundError:
        pytest.fail("installed neutral arm phase factory is missing")


def setup(tmp_path, kin, profile, *, install=True, fault=None):
    catalog = _catalog(kin, profile, workcell_id="omx-1", instance_id="omx-1-control")
    installation = api().ArmTransferInstallation(
        TransferObjectBindings(catalog, {"object-1": "g1"}), "arm-cap-1", "cfg-1", "d" * 64)
    now = datetime.now(timezone.utc)
    body = dict(mission_id="m-1", step_id="s-1", action_id="a-1", attempt_id="t-1",
                workcell_id=catalog.workcell_id, instance_id=catalog.instance_id, action_kind="ARM_TRANSFER",
                request_digest="0" * 64, capability_revision="arm-cap-1", config_revision="cfg-1",
                authority_epoch=2, dispatch_generation=8, issued_at=now, expires_at=now + timedelta(minutes=1),
                arm_transfer=dict(object_ref="object-1", catalog_digest=catalog.digest,
                                  bindings_digest=installation.bindings.revision, source="p1", target="p2",
                                  resource_policy_digest="d" * 64))
    body["request_digest"] = action_grant_digest(body)
    grant = FleetArmTransferGrant.model_validate(body)
    store, driver, runner = _runner(tmp_path, capability_current=installation.capability_current)
    states = [_state(kin, profile)]
    port = _GoalPort()

    def succeed(command, goal, callback):
        callback(_event("GOAL_ACCEPTED", command, command.phase_id, goal, 1))
        states[0] = replace(states[0], sequence=states[0].sequence + 1,
                            joint_positions=dict(command.positions), observed_at_monotonic_s=100.1)
        callback(_event("TERMINAL_RESULT", command, command.phase_id, goal, 2, status=4, result_code=0))

    port.on_submit = succeed

    def readback():
        phase = port.submissions[-1][0].phase_id
        if fault == "readback":
            raise TimeoutError("sensor unavailable")
        return GripperObservation(catalog.workcell_id, catalog.instance_id, "sensor-1",
                                  8 if phase == "release" else 7, 100.1,
                                  "OPEN" if phase == "release" else "CLOSED", phase != "release",
                                  None if phase == "release" else ("other" if fault == "object" else "object-1"), 8)

    factory = api().create_arm_transfer_phase_factory(
        installation=installation, profile=profile, kinematics=kin, execution_state=lambda: states[0],
        command_for_phase=lambda accepted, phase: TrajectoryCommand(
            workcell_id=accepted.workcell_id, instance_id=accepted.instance_id,
            command_id=f"{accepted.action_id}-{phase.phase_id}", session_id="session-1", owner="rule_based",
            positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
            duration_s=phase.points[-1].time_from_start_s, source_state_sequence=phase.source_state_sequence,
            calibration_revision=phase.calibration_revision, joint_names=phase.joint_names,
            trajectory_points=phase.points, phase_id=phase.phase_id),
        goal_port=port, submission_fence=runner.submission_fence, phase_gate=lambda *_: True,
        current_fence=runner.current_fence, gripper_readback=readback, gripper_sensor_revision="sensor-1",
        monotonic=lambda: 100.1)
    if install:
        runner.phase_runner_factories["ARM_TRANSFER"] = factory
    return grant, store, driver, runner, port, states, installation


def test_neutral_grant_runs_four_physical_phases_without_cell_recipe_or_direct_driver(tmp_path, kin, profile):
    grant, store, driver, runner, port, _, _ = setup(tmp_path, kin, profile)
    reply = ActionApi(runner).dispatch(dict(version=2, operation="SubmitAction", grant=grant.model_dump(mode="json")),
                                      peer_uid=1001)
    assert reply["status"] == 200 and reply["receipt"]["state"] == "ACCEPTED", reply
    execution = runner._phase_runners[(grant.action_id, grant.attempt_id)]
    for _ in range(5):
        execution.advance()
    row = store.get_action(grant.action_id)
    assert row["state"] == "SUCCEEDED"
    assert row["result_source"] == "arm-transfer-workflow"
    assert len(port.submissions) == 4 and driver.submissions == []
    assert row["request"]["observation_id"] == ""
    assert not any(e["event_type"] == "GOAL_CONFIRMED" for e in store.history(grant.action_id))
    replay = runner.submit(grant, peer_uid=1001)
    assert replay["created"] is False and len(port.submissions) == 4
    _, reopened_driver, reopened = _runner(tmp_path)
    read = ActionApi(reopened).dispatch(dict(version=2, operation="GetAction", action_id=grant.action_id),
                                       peer_uid=1001)
    assert read["status"] == 200 and read["receipt"]["state"] == "SUCCEEDED"
    assert not reopened._phase_runners and not reopened_driver.submissions


@pytest.mark.parametrize("fault", ["object", "readback"])
def test_gripper_fault_holds_before_transfer(tmp_path, kin, profile, fault):
    grant, store, driver, runner, port, _, _ = setup(tmp_path, kin, profile, fault=fault)
    runner.submit(grant, peer_uid=1001)
    execution = runner._phase_runners[(grant.action_id, grant.attempt_id)]
    execution.advance()
    with pytest.raises(RuntimeError):
        execution.advance()
    assert store.get_action(grant.action_id)["state"] == "HOLD"
    assert len(port.submissions) == 2 and driver.submissions == []


@pytest.mark.parametrize("condition", ["uninstalled", "v1", "no-control", "catalog", "object", "policy"])
def test_owner_rejects_before_journal_or_actuator(tmp_path, kin, profile, condition):
    grant, store, driver, runner, port, _, _ = setup(tmp_path, kin, profile, install=condition != "uninstalled")
    if condition == "no-control":
        runner.control_admission = None
    changes = {"catalog": {"catalog_digest": "0" * 64}, "object": {"object_ref": "other"},
               "policy": {"resource_policy_digest": "0" * 64}}.get(condition)
    if changes:
        raw = grant.model_dump(mode="json")
        raw["arm_transfer"].update(changes)
        raw["request_digest"] = action_grant_digest(raw)
        grant = FleetArmTransferGrant.model_validate(raw)
    reply = ActionApi(runner).dispatch(dict(version=1 if condition == "v1" else 2, operation="SubmitAction",
                                           grant=grant.model_dump(mode="json")), peer_uid=1001)
    assert reply["status"] in {400, 403, 409}, reply
    assert store.get_action(grant.action_id) is None
    assert not port.submissions and not driver.submissions


@pytest.mark.parametrize("fault", ["stale", "calibration", "transform"])
def test_changed_measured_state_cannot_start_a_physical_phase(tmp_path, kin, profile, fault):
    grant, store, driver, runner, port, states, _ = setup(tmp_path, kin, profile)
    changes = {"stale": dict(observed_at_monotonic_s=90.0),
               "calibration": dict(calibration_revision="other"),
               "transform": dict(transform_revision="other")}[fault]
    states[0] = replace(states[0], **changes)
    receipt = runner.submit(grant, peer_uid=1001)
    assert receipt["state"] in {"HOLD", "UNKNOWN"}
    assert not port.submissions and not driver.submissions


@pytest.mark.parametrize("fault", ["revision", "stop"])
def test_final_completion_requires_current_state_and_serialized_stop_fence(tmp_path, kin, profile, fault):
    from core_common.protocol.schemas import LocalStopRequest, StopRequestSource

    grant, store, driver, runner, port, states, _ = setup(tmp_path, kin, profile)
    runner.submit(grant, peer_uid=1001)
    execution = runner._phase_runners[(grant.action_id, grant.attempt_id)]
    for _ in range(3):
        execution.advance()
    assert len(port.submissions) == 4
    if fault == "revision":
        states[0] = replace(states[0], calibration_revision="changed")
    else:
        runner.local_stop.trip(LocalStopRequest(
            workcell_id=grant.workcell_id, instance_id=grant.instance_id,
            authority_epoch=2, dispatch_generation=8, requested_at=datetime.now(timezone.utc), reason="test"),
            source=StopRequestSource.FLEET)
    with pytest.raises((PermissionError, ValueError)):
        execution.advance()
    assert store.get_action(grant.action_id)["state"] == "HOLD"
    assert len(port.submissions) == 4 and not driver.submissions
