import pytest

from omx_adapter.action_store import ActionStore
from omx_adapter.gripper_contract import GripperObservation
from omx_adapter.phase_recorder import ActionPhaseRecorder
from omx_adapter.pick_place_transaction import (
    ArmActionResult,
    PickPlaceState,
    PickPlaceTransaction,
    PickPlaceWorkflowJournal,
    TransactionError,
)
from omx_adapter.target_evidence import TargetEvidence


def evidence(object_id, label, bbox):
    return TargetEvidence(
        object_id=object_id, observation_id="obs-4", frame_sha256="a" * 64,
        camera_identity="camera-serial-1", optical_frame_id="workcell_camera_optical",
        calibration_revision="cal-v3", transform_revision="tf-v7",
        capture_time_ns=12_000_000_000, selector_kind="object_id", image_bbox_xyxy=bbox,
    )


def setup_transaction(action_id="action-1", attempt_id="attempt-1", owner_generation=3):
    source = evidence("block-1", "red block", (40, 40, 100, 100))
    destination = evidence("tray-1", "green tray", (200, 200, 400, 400))
    return PickPlaceTransaction(
        action_id=action_id, attempt_id=attempt_id, workcell_id="omx_01",
        instance_id="omx_01_control", gripper_sensor_revision="fake-gripper-v1",
        owner_generation=owner_generation, source=source, destination=destination,
    )


def arm_result(stage, *, terminal=True, success=True, **changes):
    values = dict(action_id="action-1", attempt_id="attempt-1", workcell_id="omx_01",
                  owner_generation=3, stage=stage, accepted=True, terminal=terminal,
                  success=success, result_id=f"result-{stage}", observed_at=30.0)
    values.update(changes)
    return ArmActionResult(**values)


def gripper(**changes):
    values = dict(workcell_id="omx_01", instance_id="omx_01_control",
                  sensor_revision="fake-gripper-v1", sequence=7, received_at=30.0,
                  state="CLOSED", object_present=True, object_id="block-1", owner_generation=3)
    values.update(changes)
    return GripperObservation(**values)


def test_transaction_waits_for_final_driver_result_and_gripper_readback_each_stage():
    tx = setup_transaction()
    assert tx.may_submit_phase("approach")
    assert not tx.may_submit_phase("grasp")
    with pytest.raises(TransactionError, match="final"):
        tx.record_arm_result(arm_result("approach", terminal=False))
    assert tx.state is PickPlaceState.HOLD

    tx = setup_transaction()
    tx.record_arm_result(arm_result("approach"))
    assert tx.state is PickPlaceState.GRASP
    assert tx.may_submit_phase("grasp")
    tx.record_arm_result(arm_result("grasp"))
    assert tx.state is PickPlaceState.VERIFY_HOLD
    assert not tx.may_submit_phase("transfer")
    tx.verify_gripper_held(gripper(), now=30.1, max_age_s=0.5)
    assert tx.may_submit_phase("transfer")
    tx.record_arm_result(arm_result("transfer"))
    assert tx.may_submit_phase("release")
    tx.record_arm_result(arm_result("release"))
    assert tx.state is PickPlaceState.VERIFY_RELEASE
    assert not tx.may_submit_phase("release")

    tx.verify_gripper_released(
        gripper(state="OPEN", object_present=False, object_id=None, sequence=8),
        now=30.1, max_age_s=0.5)
    assert tx.state is PickPlaceState.ACTION_SUCCEEDED


def test_cancel_while_holding_latches_hold_without_implicit_release():
    tx = setup_transaction()
    tx.record_arm_result(arm_result("approach"))
    tx.record_arm_result(arm_result("grasp"))
    tx.verify_gripper_held(gripper(), now=30.1, max_age_s=0.5)

    tx.cancel(reason="operator_cancel")

    assert tx.state is PickPlaceState.HOLD
    assert tx.hold_reason == "cancel_while_object_held"


def test_late_attempt_arm_result_cannot_complete_another_action():
    tx = setup_transaction()
    tx.record_arm_result(arm_result("approach"))
    tx.record_arm_result(arm_result("grasp"))
    tx.verify_gripper_held(gripper(), now=30.1, max_age_s=0.5)
    tx.record_arm_result(arm_result("transfer"))
    with pytest.raises(TransactionError, match="attempt"):
        tx.record_arm_result(arm_result("release", attempt_id="old-attempt"))
    assert tx.state is PickPlaceState.HOLD


def test_replayed_gripper_sequence_cannot_prove_a_later_release():
    tx = setup_transaction()
    tx.record_arm_result(arm_result("approach"))
    tx.record_arm_result(arm_result("grasp"))
    tx.verify_gripper_held(gripper(sequence=7), now=30.1, max_age_s=0.5)
    tx.record_arm_result(arm_result("transfer"))
    tx.record_arm_result(arm_result("release"))

    with pytest.raises(TransactionError, match="sequence"):
        tx.verify_gripper_released(
            gripper(state="OPEN", object_present=False, object_id=None, sequence=7),
            now=30.1, max_age_s=0.5)
    assert tx.state is PickPlaceState.HOLD


def _accepted_four_phase_action(tmp_path):
    store = ActionStore(tmp_path / "workflow.sqlite3")
    created = store.create_action(
        workcell_id="omx_01", instance_id="omx_01_control",
        principal_id="fleet-1", request_key="workflow-action",
        action_id="workflow-action", action_kind="PICK_PLACE",
        configuration_revision="cfg-v1", observation_id="obs-4",
        owner_generation=8, payload={"mission_id": "mission-1"},
    )
    attempt = store.begin_submission(
        "workflow-action", expected_generation=8, attempt_id="workflow-attempt",
    )
    phase_ids = ("approach", "grasp", "transfer", "release")
    for ordinal, phase_id in enumerate(phase_ids):
        store.begin_phase(
            "workflow-action", "workflow-attempt", phase_id=phase_id,
            ordinal=ordinal, command_digest=str(ordinal) * 64,
        )
        if ordinal == 0:
            store.record_first_phase_submission(
                "workflow-action", "workflow-attempt", phase_id=phase_id,
                accepted=True, driver_goal_id=f"ros-goal-{phase_id}",
            )
        else:
            store.record_phase_submission(
                "workflow-action", "workflow-attempt", phase_id=phase_id,
                accepted=True, driver_goal_id=f"ros-goal-{phase_id}",
            )
        store.record_phase_terminal(
            "workflow-action", "workflow-attempt", phase_id=phase_id,
            driver_goal_id=f"ros-goal-{phase_id}", outcome="SUCCEEDED",
            result_source="ros-action", result_observed_at="2026-10-01T00:00:01Z",
            result={"phase": phase_id},
        )
    return store, ActionPhaseRecorder(
        store, action_id=created["action"]["action_id"], attempt_id=attempt["attempt_id"],
    )


def test_durable_workflow_gates_each_phase_and_completes_local_action_after_release_only(tmp_path):
    store, recorder = _accepted_four_phase_action(tmp_path)
    transaction = setup_transaction("workflow-action", "workflow-attempt", 8)
    workflow = PickPlaceWorkflowJournal(transaction, recorder)

    assert workflow.phase_gate("approach")
    assert not workflow.phase_gate("grasp")
    workflow.record_arm_result(arm_result("approach", action_id="workflow-action",
                                          attempt_id="workflow-attempt", owner_generation=8))
    assert workflow.phase_gate("grasp")
    workflow.record_arm_result(arm_result("grasp", action_id="workflow-action",
                                          attempt_id="workflow-attempt", owner_generation=8))
    assert not workflow.phase_gate("transfer")
    workflow.verify_gripper_held(
        gripper(workcell_id="omx_01", instance_id="omx_01_control",
                sensor_revision="fake-gripper-v1", sequence=11, owner_generation=8),
        now=30.1, max_age_s=0.5,
    )
    assert workflow.phase_gate("transfer")
    workflow.record_arm_result(arm_result("transfer", action_id="workflow-action",
                                          attempt_id="workflow-attempt", owner_generation=8))
    assert workflow.phase_gate("release")
    workflow.record_arm_result(arm_result("release", action_id="workflow-action",
                                          attempt_id="workflow-attempt", owner_generation=8))
    released = workflow.verify_gripper_released(
        gripper(workcell_id="omx_01", instance_id="omx_01_control",
                sensor_revision="fake-gripper-v1", sequence=12, owner_generation=8,
                state="OPEN", object_present=False, object_id=None),
        now=30.1, max_age_s=0.5,
        result_observed_at="2026-10-01T00:00:03Z",
    )

    assert released.sequence == 12
    action = store.get_action("workflow-action")
    assert action["state"] == "SUCCEEDED"
    assert action["result_source"] == "pick-place-workflow"
    workflow_events = [event for event in store.history("workflow-action")
                       if event["event_type"] == "ACTION_WORKFLOW_STATE"]
    assert [event["detail"]["workflow_state"] for event in workflow_events] == [
        "APPROACH", "GRASP", "VERIFY_HOLD", "TRANSFER", "RELEASE",
        "VERIFY_RELEASE", "ACTION_SUCCEEDED",
    ]
    assert workflow_events[-1]["detail"]["object_may_be_held"] is False
    assert set(workflow_events[-1]["detail"]["evidence_refs"]) == {
        "phase_result_id", "gripper_hold_sequence", "gripper_release_sequence",
    }
    assert all(event["event_type"] != "GOAL_CONFIRMED" for event in store.history("workflow-action"))


def test_invalid_gripper_readback_holds_action_and_does_not_complete_it(tmp_path):
    store, recorder = _accepted_four_phase_action(tmp_path)
    workflow = PickPlaceWorkflowJournal(
        setup_transaction("workflow-action", "workflow-attempt", 8), recorder,
    )
    workflow.record_arm_result(arm_result("approach", action_id="workflow-action",
                                          attempt_id="workflow-attempt", owner_generation=8))
    workflow.record_arm_result(arm_result("grasp", action_id="workflow-action",
                                          attempt_id="workflow-attempt", owner_generation=8))

    with pytest.raises(TransactionError, match="held"):
        workflow.verify_gripper_held(
            gripper(workcell_id="omx_01", instance_id="omx_01_control",
                    sensor_revision="fake-gripper-v1", sequence=11, owner_generation=8,
                    object_present=False),
            now=30.1, max_age_s=0.5,
        )

    assert store.get_action("workflow-action")["state"] == "HOLD"
    assert recorder.latest_workflow_state() == "HOLD"
    assert not workflow.phase_gate("transfer")


def test_restart_recovery_never_resubmits_an_ambiguous_stage():
    tx = setup_transaction()
    tx.record_arm_result(arm_result("approach"))
    tx.record_arm_result(arm_result("grasp"))
    tx.verify_gripper_held(gripper(), now=30.1, max_age_s=0.5)

    recovered = PickPlaceTransaction.recover(tx.snapshot())

    assert recovered.state is PickPlaceState.HOLD
    assert recovered.hold_reason == "restart_reconciliation_required"
    assert recovered.object_held
    with pytest.raises(TransactionError, match="HOLD"):
        recovered.record_arm_result(arm_result("transfer"))
