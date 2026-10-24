"""Closed raw physical facts and physical receipts carry no application verdict."""
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path

import pytest

NAMES = ("ArmObservationPose", "ArmObservationBounds", "ArmLinkObservation", "ArmOwnerObservation",
    "ArmTransferObservation", "ArmTransferObservationRequest", "ArmTransferOwnerContext",
    "ArmTransferObservationContext", "ArmTransferObservationContextResponse", "ArmTransferPhysicalReceipt",
    "ArmTransferPhysicalReceiptResponse", "ArmTransferObservationReply", "ArmTransferCancelRequest")


def api():
    try:
        return import_module("core_common.protocol.arm_transfer_observations")
    except ModuleNotFoundError:
        pytest.fail("physical observation/receipt wire contract is missing")


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/arm_transfer_observation_v1.json").read_text())


def test_canonical_exports_and_json_round_trip_preserve_unknown_velocity():
    module = api()
    facade = import_module("core_common.protocol.schemas")
    assert all(getattr(facade, name) is getattr(module, name) for name in NAMES)
    raw = fixture()
    request = module.ArmTransferObservationRequest.model_validate(raw["request"])
    assert request.model_dump(mode="json") == raw["request"]
    assert request.observations[0].owners[0].links["link1"].angular_velocity_rad_s is None
    with pytest.raises(ValueError):
        request.phase = "POST_ACTION"
    assert module.ArmTransferObservationContextResponse(context=raw["context"]).context.phase == "PRE_DISPATCH"
    assert module.ArmTransferObservationContextResponse(context=None).model_dump() == {"context": None}
    assert module.ArmTransferPhysicalReceiptResponse(receipt=raw["receipt"]).receipt.physical_status == "AT_TARGET_AND_CLEAR"


@pytest.mark.parametrize("path,value", [
    (("satisfied",), True), (("resources",), []), (("phase",), "UNLOAD"),
    (("observations", 0, "clear"), True), (("observations", 0, "sequence"), True),
    (("observations", 0, "object_observed_at_ns"), 1.5),
    (("observations", 0, "object_pose", "orientation_xyzw"), [0, 0, 0, .8]),
    (("observations", 0, "owners", 0, "held_state"), "CLEARED"),
    (("observations", 0, "owners", 0, "links", "link1", "cleared"), True),
    (("observations", 0, "owners", 0, "links", "link1", "linear_velocity_m_s"), [False, 0, 0]),
    (("observations", 0, "owners", 0, "links", "link1", "bounds", "min_m"), [2, 2, 2]),
])
def test_request_rejects_verdicts_authority_unknown_fields_and_invalid_measured_shapes(path, value):
    raw = deepcopy(fixture()["request"])
    cursor = raw
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(ValueError):
        api().ArmTransferObservationRequest.model_validate(raw)


def test_request_requires_exactly_two_samples_and_unique_owner_scopes():
    raw = fixture()["request"]
    with pytest.raises(ValueError):
        api().ArmTransferObservationRequest.model_validate({**raw, "observations": raw["observations"][:1]})
    raw["observations"][0]["owners"] *= 2
    with pytest.raises(ValueError):
        api().ArmTransferObservationRequest.model_validate(raw)


def test_wire_preserves_missing_coverage_as_unknown_raw_facts():
    raw = fixture()["request"]
    raw["observations"][0]["owners"] = []
    raw["observations"][1]["owners"][0]["links"] = {}
    parsed = api().ArmTransferObservationRequest.model_validate(raw)
    assert parsed.observations[0].owners == ()
    assert parsed.observations[1].owners[0].links == {}


def test_reply_binds_the_physical_receipt_to_the_job_without_equating_request_hash_domains():
    raw = fixture()
    job = json.loads((Path(__file__).parent / "fixtures/arm_transfer_job_v1.json").read_text())["proposed"]
    job.update(status="GOAL_CONFIRMED", approved_by="operator", authority_epoch=2, dispatch_generation=3)
    model = api().ArmTransferObservationReply
    assert model(job=job, receipt=raw["receipt"]).job.request_digest != raw["receipt"]["request_digest"]
    with pytest.raises(ValueError):
        model(job=job, receipt=None)
    for changes in ({"mission_id": "other"}, {"target": "other"}, {"object_ref": "other"},
                    {"policy_digest": "a" * 64}, {"dispatch_generation": 4}, {"physical_status": "BUSINESS_COMPLETED"}):
        with pytest.raises(ValueError):
            model(job=job, receipt={**raw["receipt"], **changes})
    with pytest.raises(ValueError):
        model(job={**job, "status": "ACTION_SUCCEEDED"}, receipt=raw["receipt"])


def test_cancel_body_cannot_select_an_action_or_discard_claims():
    model = api().ArmTransferCancelRequest
    assert model(reason="operator cancel").reason == "operator cancel"
    for changes in ({"reason": ""}, {"reason": " cancel "}, {"action_id": "caller"}, {"release_claims": True}):
        with pytest.raises(ValueError):
            model(**{**dict(reason="cancel"), **changes})


def test_existing_status_enum_exports_keep_one_owner():
    try:
        enums = import_module("core_common.protocol.wire_status")
    except ModuleNotFoundError:
        pytest.fail("budgeted wire facade status enums have not been separated")
    facade = import_module("core_common.protocol.schemas")
    for name in ("RobotMode", "NavigationState", "HealthState", "Severity", "AckStatus"):
        assert getattr(facade, name) is getattr(enums, name)
