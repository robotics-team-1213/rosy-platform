import pytest

from omx_adapter.gripper_contract import GripperObservation
from omx_adapter.pick_place_transaction import (
    ArmActionResult,
    PickPlaceState,
    PickPlaceTransaction,
    PlacementEvidence,
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


def setup_transaction():
    source = evidence("block-1", "red block", (40, 40, 100, 100))
    destination = evidence("tray-1", "green tray", (200, 200, 400, 400))
    return PickPlaceTransaction(
        action_id="action-1", attempt_id="attempt-1", workcell_id="omx_01",
        instance_id="omx_01_control", gripper_sensor_revision="fake-gripper-v1",
        owner_generation=3, source=source, destination=destination,
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
    with pytest.raises(TransactionError, match="final"):
        tx.record_arm_result(arm_result("approach", terminal=False))
    assert tx.state is PickPlaceState.HOLD

    tx = setup_transaction()
    tx.record_arm_result(arm_result("approach"))
    assert tx.state is PickPlaceState.GRASP
    tx.record_arm_result(arm_result("grasp"))
    assert tx.state is PickPlaceState.VERIFY_HOLD
    tx.verify_gripper_held(gripper(), now=30.1, max_age_s=0.5)
    tx.record_arm_result(arm_result("transfer"))
    tx.record_arm_result(arm_result("release"))
    assert tx.state is PickPlaceState.VERIFY_RELEASE

    tx.verify_gripper_released(
        gripper(state="OPEN", object_present=False, object_id=None, sequence=8),
        now=30.1, max_age_s=0.5)
    tx.verify_placement(PlacementEvidence(
        action_id="action-1", attempt_id="attempt-1", object_id="block-1",
        destination_id="tray-1", observation_id="obs-placement-9",
        evaluator_id="test-placement-oracle", evaluator_revision="fixture-v1",
        predicate="inside_destination", satisfied=True, observed_at=30.0,
    ), now=30.1, max_age_s=0.5)
    assert tx.state is PickPlaceState.COMPLETED


def test_cancel_while_holding_latches_hold_without_implicit_release():
    tx = setup_transaction()
    tx.record_arm_result(arm_result("approach"))
    tx.record_arm_result(arm_result("grasp"))
    tx.verify_gripper_held(gripper(), now=30.1, max_age_s=0.5)

    tx.cancel(reason="operator_cancel")

    assert tx.state is PickPlaceState.HOLD
    assert tx.hold_reason == "cancel_while_object_held"


def test_placement_or_late_attempt_evidence_cannot_complete_another_action():
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
