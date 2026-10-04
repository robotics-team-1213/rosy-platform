"""Manual sheet readback describes a barrier and never grants execution authority."""

import copy

import pytest
from pydantic import ValidationError

from core_common.protocol.cell_app import CellOperatorCheckpoint


def snapshot():
    return {"checkpoint_id": "a" * 64, "kind": "operator_sheet",
            "before_transfer_ordinal": 5, "pallet_id": "A", "layer_index": 1,
            "sheet_pose_base": {"x_m": 0.15, "y_m": 0.02, "z_m": 0.042, "yaw_rad": 0.0},
            "thickness_m": 0.002, "status": "WAITING_ACCESS",
            "updated_at": "2026-10-04T08:00:00+00:00"}


def test_barrier_readback_has_no_confirmation_or_grant_fields():
    value = snapshot()
    assert CellOperatorCheckpoint.model_validate(value).model_dump(mode="json") == value
    value["operator_confirmed"] = True
    with pytest.raises(ValidationError):
        CellOperatorCheckpoint.model_validate(value)


@pytest.mark.parametrize("key,value", [
    ("status", "CONFIRMED"), ("kind", "CELL_TRANSFER"),
    ("before_transfer_ordinal", True), ("before_transfer_ordinal", 0),
    ("before_transfer_ordinal", "5"), ("layer_index", -1), ("layer_index", True),
    ("thickness_m", True), ("thickness_m", float("nan")),
    ("thickness_m", float("inf")), ("thickness_m", 0),
    ("pallet_id", " A"), ("pallet_id", "A\nB"), ("checkpoint_id", "B" * 64),
])
def test_invalid_barrier_cannot_be_coerced_into_readback(key, value):
    data = snapshot()
    data[key] = value
    with pytest.raises(ValidationError):
        CellOperatorCheckpoint.model_validate(data)


@pytest.mark.parametrize("value", [True, "0.15", float("nan"), float("inf")])
def test_authored_pose_requires_finite_numbers(value):
    data = copy.deepcopy(snapshot())
    data["sheet_pose_base"]["x_m"] = value
    with pytest.raises(ValidationError):
        CellOperatorCheckpoint.model_validate(data)
