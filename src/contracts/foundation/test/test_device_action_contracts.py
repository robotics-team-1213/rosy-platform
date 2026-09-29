"""Versioned Fleet-to-workcell action grant contracts (D-333/D-336)."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import (
    DeviceActionReceipt,
    DeviceActionState,
    DeviceActionCancelRequest,
    DeviceActionLookup,
    FleetActionGrant,
    LocalStopRequest,
    LocalStopQuery,
    LocalStopSnapshot,
    LocalStopState,
)


def _grant(**overrides):
    now = datetime.now(timezone.utc)
    source = {
        "object_id": "red-block-01",
        "observation_id": "camera-frame-44",
        "frame_sha256": "b" * 64,
        "camera_identity": "overhead-cam-01",
        "optical_frame_id": "overhead_optical",
        "calibration_revision": "overhead-cal-03",
        "transform_revision": "base-tf-12",
        "capture_time_ns": 1760000000000000000,
        "selector_kind": "point",
        "image_bbox_xyxy": [20.0, 30.0, 60.0, 70.0],
    }
    destination = dict(source, object_id="green-tray-01", selector_kind="label")
    value = {
        "mission_id": "mission-01",
        "step_id": "step-01",
        "action_id": "action-01",
        "attempt_id": "attempt-01",
        "request_digest": "a" * 64,
        "workcell_id": "omx-cell-01",
        "instance_id": "omx-cell-01-control",
        "action_kind": "PICK_PLACE",
        "source_evidence": source,
        "destination_evidence": destination,
        "capability_revision": "omx-pick-place-01",
        "config_revision": "workcell-config-08",
        "observation_revision": "camera-frame-44",
        "authority_epoch": 3,
        "dispatch_generation": 19,
        "issued_at": now,
        "expires_at": now + timedelta(seconds=5),
    }
    value.update(overrides)
    return value


def test_fleet_action_grant_roundtrips_with_all_execution_fences():
    grant = FleetActionGrant.model_validate(_grant())
    restored = FleetActionGrant.model_validate(grant.model_dump())
    assert restored == grant
    assert restored.action_kind == "PICK_PLACE"
    assert restored.dispatch_generation == 19
    assert restored.request_digest == "a" * 64


@pytest.mark.parametrize("field", ["principal_id", "provider_call_id", "api_key", "stop_clearance"])
def test_action_grant_rejects_untrusted_identity_or_unapproved_authority(field):
    raw = _grant()
    raw[field] = "untrusted"
    with pytest.raises(ValidationError):
        FleetActionGrant.model_validate(raw)


@pytest.mark.parametrize("field", ["mission_id", "step_id", "action_id", "attempt_id"])
def test_action_grant_requires_distinct_correlation_ids(field):
    raw = _grant()
    raw[field] = raw["step_id"] if field == "mission_id" else raw["mission_id"]
    with pytest.raises(ValidationError, match="distinct"):
        FleetActionGrant.model_validate(raw)


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_digest": "not-a-sha256"},
        {"authority_epoch": True},
        {"dispatch_generation": -1},
        {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
        {"workcell_id": "   "},
    ],
)
def test_action_grant_rejects_invalid_digest_generation_expiry_and_identity(overrides):
    with pytest.raises(ValidationError):
        FleetActionGrant.model_validate(_grant(**overrides))


@pytest.mark.parametrize(
    "evidence_field,value",
    [
        ("observation_id", "different-frame"),
        ("frame_sha256", "c" * 64),
        ("calibration_revision", "different-calibration"),
        ("transform_revision", "different-transform"),
    ],
)
def test_source_and_destination_must_share_one_observation(evidence_field, value):
    raw = _grant()
    raw["destination_evidence"][evidence_field] = value
    with pytest.raises(ValidationError, match="same observation"):
        FleetActionGrant.model_validate(raw)


def test_source_and_destination_must_be_distinct_objects():
    raw = _grant()
    raw["destination_evidence"]["object_id"] = raw["source_evidence"]["object_id"]
    with pytest.raises(ValidationError, match="distinct objects"):
        FleetActionGrant.model_validate(raw)


def test_durable_action_receipt_is_not_goal_or_physical_stop_evidence():
    receipt = DeviceActionReceipt(
        mission_id="mission-01",
        step_id="step-01",
        action_id="action-01",
        attempt_id="attempt-01",
        workcell_id="omx-cell-01",
        instance_id="omx-cell-01-control",
        state=DeviceActionState.PREPARED,
        journal_event_id=1,
        observed_at=datetime.now(timezone.utc),
    )
    assert receipt.state is DeviceActionState.PREPARED
    assert receipt.model_dump()["state"] == "PREPARED"
    assert "goal_confirmed" not in receipt.model_dump()
    assert "physical_stop" not in receipt.model_dump()


def test_local_stop_snapshot_cannot_claim_driver_or_physical_completion():
    snapshot = LocalStopSnapshot(
        workcell_id="omx-cell-01",
        instance_id="omx-cell-01-control",
        authority_epoch=3,
        dispatch_generation=20,
        state=LocalStopState.LOCAL_LATCHED,
        source="operator_local",
        observed_at=datetime.now(timezone.utc),
        reason="operator_stop",
    )
    dumped = snapshot.model_dump()
    assert dumped["state"] == "LOCAL_LATCHED"
    assert "physical_stopped" not in dumped
    assert "driver_goal_canceled" not in dumped


def test_local_stop_request_cannot_claim_its_own_principal():
    with pytest.raises(ValidationError):
        LocalStopRequest.model_validate({
            "workcell_id": "omx-cell-01",
            "instance_id": "omx-cell-01-control",
            "authority_epoch": 3,
            "dispatch_generation": 20,
            "requested_at": datetime.now(timezone.utc),
            "reason": "stop requested",
            "source": "fleet",
        })


def test_local_stop_request_requires_trimmed_identity_and_aware_time():
    base = {
        "workcell_id": "omx-cell-01",
        "instance_id": "omx-cell-01-control",
        "authority_epoch": 3,
        "dispatch_generation": 20,
        "requested_at": datetime.now(timezone.utc),
        "reason": "operator stop",
    }
    for field, invalid in (("workcell_id", "omx cell"),
                           ("instance_id", "omx-cell-01 control"),
                           ("requested_at", datetime(2026, 9, 29))):
        with pytest.raises(ValidationError):
            LocalStopRequest.model_validate({**base, field: invalid})


def test_action_read_and_cancel_are_bound_to_the_same_fleet_attempt():
    lookup = DeviceActionLookup(action_id="action-01", attempt_id="attempt-01")
    cancel = DeviceActionCancelRequest(
        action_id=lookup.action_id,
        attempt_id=lookup.attempt_id,
        reason="operator_cancel",
        requested_at=datetime.now(timezone.utc),
    )
    assert cancel.action_id == lookup.action_id
    assert cancel.attempt_id == lookup.attempt_id


def test_cancel_request_requires_timezone_and_rejects_principal_claim():
    with pytest.raises(ValidationError, match="timezone"):
        DeviceActionCancelRequest(
            action_id="action-01",
            attempt_id="attempt-01",
            reason="cancel",
            requested_at=datetime(2026, 9, 29),
        )
    with pytest.raises(ValidationError):
        DeviceActionCancelRequest.model_validate({
            "action_id": "action-01",
            "attempt_id": "attempt-01",
            "reason": "cancel",
            "requested_at": datetime.now(timezone.utc),
            "principal_id": "operator-1",
        })


def test_local_stop_query_requires_workcell_and_runtime_instance():
    query = LocalStopQuery(workcell_id="omx-cell-01", instance_id="omx-cell-01-control")
    assert query.workcell_id == "omx-cell-01"
    with pytest.raises(ValidationError):
        LocalStopQuery(workcell_id="omx-cell-01", instance_id="")
