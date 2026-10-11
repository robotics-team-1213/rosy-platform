import pytest

from omx_adapter.gripper_contract import (
    GripperObservation,
    GripperReadbackError,
    verify_held_object,
    verify_released_object,
)


def reading(**changes):
    values = dict(
        workcell_id="omx_01", instance_id="omx_01_control", sensor_revision="fake-gripper-v1",
        sequence=7, received_at=10.0, state="CLOSED", object_present=True,
        object_id="block-1", owner_generation=3,
    )
    values.update(changes)
    return GripperObservation(**values)


def test_hold_receipt_requires_fresh_closed_readback_for_the_requested_object():
    receipt = verify_held_object(reading(), object_id="block-1", now=10.1, max_age_s=0.5)

    assert receipt.object_id == "block-1"
    assert receipt.sequence == 7
    assert receipt.owner_generation == 3


@pytest.mark.parametrize("changes", [
    {"state": "OPEN"}, {"object_present": False}, {"object_present": None},
    {"object_id": "other"}, {"received_at": 9.0},
])
def test_invalid_or_stale_gripper_readback_does_not_prove_object_hold(changes):
    with pytest.raises(GripperReadbackError):
        verify_held_object(reading(**changes), object_id="block-1", now=10.1, max_age_s=0.5)


def test_release_receipt_requires_fresh_open_readback_and_no_object():
    released = verify_released_object(
        reading(state="OPEN", object_present=False, object_id=None),
        object_id="block-1", now=10.1, max_age_s=0.5,
    )

    assert released.object_id == "block-1"
    assert released.sequence == 7
