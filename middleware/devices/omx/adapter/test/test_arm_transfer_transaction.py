"""D-856 owner workflow binds physical objects, without inventing Cell/camera evidence."""
from copy import deepcopy

import pytest

from omx_adapter.pick_place_transaction import PickPlaceState, PickPlaceTransaction, TransactionError
from test_arm_transfer_registration_gate import grant
from test_omx_pick_place_transaction import arm_result, gripper


def transaction():
    create = getattr(PickPlaceTransaction, "for_arm_transfer", None)
    assert create is not None, "neutral grant transaction consumer is missing"
    return create(grant(), gripper_sensor_revision="sensor-1")


def result(stage):
    body = grant()
    return arm_result(stage, action_id=body.action_id, attempt_id=body.attempt_id,
                      workcell_id=body.workcell_id, owner_generation=body.dispatch_generation)


def observation(**changes):
    body = grant()
    return gripper(**{**dict(workcell_id=body.workcell_id, instance_id=body.instance_id,
                            sensor_revision="sensor-1", owner_generation=body.dispatch_generation,
                            object_id=body.arm_transfer.object_ref), **changes})


def held():
    tx = transaction()
    tx.record_arm_result(result("approach"))
    tx.record_arm_result(result("grasp"))
    tx.verify_gripper_held(observation(), now=30.1, max_age_s=0.5)
    return tx


def test_snapshot_contains_neutral_grant_and_no_fake_cell_or_camera_destination():
    tx = transaction()
    snapshot = tx.snapshot()
    assert snapshot["action_kind"] == "ARM_TRANSFER"
    assert snapshot["arm_grant"]["arm_transfer"]["object_ref"] == "o-1"
    assert snapshot["source_object_id"] == "o-1"
    assert not set(snapshot) & {"cell_grant", "destination_object_id",
                                "source_observation_id", "destination_observation_id"}
    assert tx.source is None and tx.destination is None


def test_physical_gripper_sequence_uses_the_bound_object_and_requires_release_readback():
    tx = held()
    tx.record_arm_result(result("transfer"))
    tx.record_arm_result(result("release"))
    assert tx.state is PickPlaceState.VERIFY_RELEASE
    tx.verify_gripper_released(observation(state="OPEN", object_present=False, object_id=None, sequence=8),
                               now=30.1, max_age_s=0.5)
    assert tx.state is PickPlaceState.ACTION_SUCCEEDED
    assert tx.object_held is False


def test_another_object_cannot_satisfy_the_physical_grasp():
    tx = transaction()
    tx.record_arm_result(result("approach"))
    tx.record_arm_result(result("grasp"))
    with pytest.raises(TransactionError):
        tx.verify_gripper_held(observation(object_id="other"), now=30.1, max_age_s=0.5)
    assert tx.state is PickPlaceState.HOLD


def test_restart_keeps_hold_and_bound_grant_without_replaying_motion():
    snapshot = held().snapshot()
    recovered = PickPlaceTransaction.recover(snapshot)
    assert recovered.state is PickPlaceState.HOLD
    assert recovered.object_held
    assert recovered.snapshot()["arm_grant"] == snapshot["arm_grant"]
    assert not recovered.may_submit_phase("transfer")
    with pytest.raises(TransactionError):
        recovered.record_arm_result(result("transfer"))


@pytest.mark.parametrize("change", [
    {"action_kind": None}, {"arm_grant": None}, {"cell_grant": {}},
    {"action_id": "other"}, {"attempt_id": "other"}, {"workcell_id": "other"},
    {"instance_id": "other"}, {"owner_generation": True}, {"owner_generation": "1"},
    {"source_object_id": "other"}, {"gripper_sensor_revision": True},
])
def test_new_snapshot_refuses_missing_tags_mixed_formats_and_coerced_identity(change):
    snapshot = deepcopy(held().snapshot())
    snapshot.update(change)
    with pytest.raises(ValueError):
        PickPlaceTransaction.recover(snapshot)


def test_snapshot_alone_does_not_prove_a_completed_neutral_action_after_restart():
    snapshot = transaction().snapshot()
    snapshot.update(state="ACTION_SUCCEEDED", object_held=False)
    recovered = PickPlaceTransaction.recover(snapshot)
    assert recovered.state is PickPlaceState.HOLD
