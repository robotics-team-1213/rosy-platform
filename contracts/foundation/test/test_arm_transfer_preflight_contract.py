"""D-856 read-only physical arm request/result wire contract."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core_common.protocol import schemas


def model(name):
    value = getattr(schemas, name, None)
    assert value is not None, f"neutral arm preflight contract {name} is missing"
    return value


def request(**changes):
    return {**dict(workcell_id="arm-cell", instance_id="arm-a", catalog_digest="c" * 64,
                   source="p1", target="p2", geometry="g1"), **changes}


def result(**changes):
    return {**dict(request=request(), journal_id="owner-journal-1", profile_revision="a" * 64,
                   kinematics_revision="b" * 64, calibration_revision="cal-1", transform_revision="tf-1",
                   planning_scene_revision="kin:" + "b" * 64, source_state_sequence=7, state_age_s=0.01,
                   simulation=True, collision_checked=False), **changes}


def test_preflight_wire_round_trips_only_physical_references_and_snapshot_facts():
    body = model("ArmTransferCheckRequest").model_validate(request())
    assert body.model_dump() == request()
    response = model("ArmTransferCheckResponse").model_validate({
        "check": result(), "received_at": datetime.now(timezone.utc)})
    assert response.check.request == body
    assert set(response.check.model_dump()) == set(result())


@pytest.mark.parametrize("change", [
    {"source": True}, {"target": 7}, {"geometry": " g1"}, {"source": "p1\n"},
    {"target": "x" * 193}, {"catalog_digest": "C" * 64}, {"instance_id": "../arm-a"},
    {"pallet": "pallet-1"}, {"pose": {"x": 0.1}},
])
def test_untrusted_request_values_are_not_coerced_or_accepted(change):
    with pytest.raises(ValidationError):
        model("ArmTransferCheckRequest").model_validate(request(**change))


@pytest.mark.parametrize("change", [
    {"simulation": 1}, {"simulation": False}, {"collision_checked": 0}, {"collision_checked": True},
    {"source_state_sequence": True}, {"source_state_sequence": -1},
    {"state_age_s": float("nan")}, {"state_age_s": -0.1}, {"state_age_s": True},
    {"profile_revision": "unreviewed"}, {"grant": {}},
])
def test_result_requires_explicit_supported_scope_and_finite_facts(change):
    with pytest.raises(ValidationError):
        model("ArmTransferCheckResult").model_validate(result(**change))


def test_result_cannot_omit_simulation_limits_or_claim_a_naive_receipt_time():
    data = result()
    data.pop("simulation")
    with pytest.raises(ValidationError):
        model("ArmTransferCheckResult").model_validate(data)
    with pytest.raises(ValidationError):
        model("ArmTransferCheckResponse").model_validate({"check": result(), "received_at": datetime(2026, 1, 1)})
