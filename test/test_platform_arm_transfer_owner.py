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
from omx_adapter.pick_place.pick_place_transaction import TransactionError  # noqa: E402
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


def _setup(tmp_path, kin, profile, *, install=True, fault=None, managed=False, wall_clock=None):
    catalog = _catalog(kin, profile, workcell_id="omx-1", instance_id="omx-1-control")
    installation = api().ArmTransferInstallation(
        TransferObjectBindings(catalog, {"object-1": "g1"}), "arm-cap-1", "cfg-1", "d" * 64)
    from omx_adapter.journal_identity import journal_identity

    store, driver, runner = _runner(tmp_path, capability_current=installation.capability_current)
    now = datetime.now(timezone.utc)
    body = dict(mission_id="m-1", step_id="s-1", action_id="a-1", attempt_id="t-1",
                owner_journal_id=journal_identity(store.path),
                owner_session_id="session-1" if managed else runner.control_admission.owner.session_id,
                workcell_id=catalog.workcell_id, instance_id=catalog.instance_id, action_kind="ARM_TRANSFER",
                request_digest="0" * 64, capability_revision="arm-cap-1", config_revision="cfg-1",
                authority_epoch=2, dispatch_generation=8, issued_at=now, expires_at=now + timedelta(minutes=1),
                arm_transfer=dict(object_ref="object-1", catalog_digest=catalog.digest,
                                  bindings_digest=installation.bindings.revision, source="p1", target="p2",
                                  resource_policy_digest="d" * 64))
    body["request_digest"] = action_grant_digest(body)
    grant = FleetArmTransferGrant.model_validate(body)
    states = [_state(kin, profile)]
    port = _GoalPort()
    if managed:
        from omx_adapter.command_owner import ArmCommandOwner, JointStateSnapshot
        from omx_adapter.control_seat_admission import ControlSeatAdmission
        from test_omx_command_owner import FakeActionClient

        config = profile.arm_command_config(workcell_id=grant.workcell_id, instance_id=grant.instance_id,
                                            calibration_revision=catalog.calibration_revision)
        owner = ArmCommandOwner(config, FakeActionClient(), session_id="session-1", monotonic=lambda: 100.1)
        owner.observe_joint_state(JointStateSnapshot(states[0].joint_positions, states[0].sequence,
                                                     100.1, catalog.calibration_revision))
        runner.control_admission = ControlSeatAdmission(owner, store, monotonic=lambda: 100.1)
        owner.bind_control_admission(runner.control_admission)
        runner.control_admission.enable_managed_transfers(installation.resource_policy_digest)
        port.command_owner = owner

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
            command_id=f"{accepted.action_id}-{phase.phase_id}",
            session_id=accepted.owner_session_id, owner="rule_based",
            positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
            duration_s=phase.points[-1].time_from_start_s, source_state_sequence=phase.source_state_sequence,
            calibration_revision=phase.calibration_revision, joint_names=phase.joint_names,
            trajectory_points=phase.points, phase_id=phase.phase_id),
        goal_port=port, submission_fence=runner.submission_fence, phase_gate=lambda *_: True,
        current_fence=runner.current_fence, gripper_readback=readback, gripper_sensor_revision="sensor-1",
        monotonic=lambda: 100.1,
        now=wall_clock,
        control_admission=runner.control_admission if managed else None)
    if install:
        runner.phase_runner_factories["ARM_TRANSFER"] = factory
    return grant, store, driver, runner, port, states, installation


def test_managed_phase_reaches_final_owner_only_during_exact_synchronous_submission(tmp_path, kin, profile):
    from concurrent.futures import ThreadPoolExecutor

    grant, store, _, runner, port, _, _ = _setup(tmp_path, kin, profile, managed=True)
    admission = runner.control_admission
    decisions = []

    def submit(command, goal, callback):
        assert admission.check_command(command)
        assert not admission.check_command(replace(command))
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(admission.check_command, command).result(timeout=1) is False
        decisions.append(admission.owner.submit(command))
        callback(_event("GOAL_ACCEPTED", command, command.phase_id, goal, 1))

    port.on_submit = submit
    receipt = runner.submit(grant, peer_uid=1001)
    assert receipt["state"] == "ACCEPTED", receipt
    assert len(decisions) == 1 and decisions[0].accepted, decisions
    assert store.get_action(grant.action_id)["state"] == "ACCEPTED"
    assert not admission.check_command(port.submissions[0][0])
    with pytest.raises(PermissionError):
        admission.acquire("token", "seat", ttl_s=1)


def test_managed_submission_context_is_cleared_after_port_error(tmp_path, kin, profile):
    grant, store, _, runner, port, _, _ = _setup(tmp_path, kin, profile, managed=True)

    def fail(command, *_):
        assert runner.control_admission.check_command(command)
        raise TimeoutError("unknown dispatch")

    port.on_submit = fail
    runner.submit(grant, peer_uid=1001)
    assert store.get_action(grant.action_id)["state"] == "HOLD"
    assert not runner.control_admission.check_command(port.submissions[0][0])


def test_managed_factory_rejects_a_port_bound_to_another_final_owner(tmp_path, kin, profile):
    grant, store, _, runner, port, _, _ = _setup(tmp_path, kin, profile, managed=True)
    port.command_owner = object()
    receipt = runner.submit(grant, peer_uid=1001)
    assert receipt["state"] in {"HOLD", "UNKNOWN"}
    assert store.get_action(grant.action_id)["state"] in {"HOLD", "UNKNOWN"}
    assert not port.submissions


def test_managed_expiry_is_checked_again_at_the_final_writer(tmp_path, kin, profile):
    clock = [datetime.now(timezone.utc)]
    grant, _, _, runner, port, _, _ = _setup(tmp_path, kin, profile, managed=True,
                                            wall_clock=lambda: clock[0])
    clock[0] = grant.issued_at + timedelta(seconds=1)
    decisions = []

    def expire_before_writer(command, *_):
        admission = runner.control_admission
        assert admission.check_command(command)
        clock[0] = grant.expires_at
        decisions.append(admission.owner.submit(command))
        raise PermissionError("grant expired before the final writer")

    port.on_submit = expire_before_writer
    runner.submit(grant, peer_uid=1001)
    assert len(decisions) == 1
    assert not decisions[0].accepted and decisions[0].reason == "control_seat_fenced"


def test_neutral_grant_runs_four_physical_phases_without_cell_recipe_or_direct_driver(tmp_path, kin, profile):
    grant, store, driver, runner, port, _, _ = _setup(tmp_path, kin, profile)
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
    from omx_adapter.action_runner import ActionRunner
    from omx_adapter.action_store import ActionStore
    from test_omx_action_api import FakeDriver

    reopened_driver = FakeDriver()
    reopened = ActionRunner(
        ActionStore(tmp_path / "actions.sqlite3"), reopened_driver,
        workcell_id=grant.workcell_id, instance_id=grant.instance_id,
        principal_for_peer=runner.principal_for_peer, allowed_peer_uids={1001},
        current_fence=runner.current_fence, capability_current=runner.capability_current)
    read = ActionApi(reopened).dispatch(dict(version=2, operation="GetAction", action_id=grant.action_id),
                                       peer_uid=1001)
    assert read["status"] == 200 and read["receipt"]["state"] == "SUCCEEDED"
    assert read["receipt"]["journal_id"] == grant.owner_journal_id
    assert not reopened._phase_runners and not reopened_driver.submissions


@pytest.mark.parametrize("fault", ["object", "readback"])
def test_gripper_fault_holds_before_transfer(tmp_path, kin, profile, fault):
    grant, store, driver, runner, port, _, _ = _setup(tmp_path, kin, profile, fault=fault)
    runner.submit(grant, peer_uid=1001)
    execution = runner._phase_runners[(grant.action_id, grant.attempt_id)]
    execution.advance()
    with pytest.raises(TransactionError):
        execution.advance()
    assert store.get_action(grant.action_id)["state"] == "HOLD"
    assert len(port.submissions) == 2 and driver.submissions == []


@pytest.mark.parametrize("condition", ["uninstalled", "v1", "no-control", "catalog", "object", "policy"])
def test_owner_rejects_before_journal_or_actuator(tmp_path, kin, profile, condition):
    grant, store, driver, runner, port, _, _ = _setup(tmp_path, kin, profile, install=condition != "uninstalled")
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
    grant, store, driver, runner, port, states, _ = _setup(tmp_path, kin, profile)
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

    grant, store, driver, runner, port, states, _ = _setup(tmp_path, kin, profile)
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
