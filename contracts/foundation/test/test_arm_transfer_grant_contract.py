"""D-856 neutral execution references; model construction grants no authority."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from core_common.protocol import schemas


def grant(**changes):
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    return {**dict(mission_id="m-1", step_id="s-1", action_id="a-1", attempt_id="t-1",
                   owner_journal_id="journal-1", owner_session_id="session-1",
                   request_digest="0" * 64, workcell_id="workcell-1", instance_id="arm-1",
                   action_kind="ARM_TRANSFER", arm_transfer=payload(), capability_revision="cap-1",
                   config_revision="config-1", authority_epoch=1, dispatch_generation=2,
                   issued_at=now, expires_at=now + timedelta(seconds=30)), **changes}


def payload(**changes):
    return {**dict(object_ref="object-1", catalog_digest="a" * 64, bindings_digest="b" * 64,
                   source="pose-1", target="pose-2", resource_policy_digest="c" * 64), **changes}


def model():
    value = getattr(schemas, "FleetArmTransferGrant", None)
    assert value is not None, "neutral arm transfer grant contract is missing"
    return value


def test_neutral_grant_round_trip_is_physical_only_and_frozen():
    body = model().model_validate(grant())
    assert body.model_dump() == grant()
    assert type(body.arm_transfer) is schemas.ArmTransferPayload
    assert set(body.arm_transfer.model_dump()) == set(payload())
    assert model().model_validate_json(body.model_dump_json()) == body
    with pytest.raises(ValidationError):
        body.authority_epoch = 2
    with pytest.raises(ValidationError):
        body.arm_transfer.object_ref = "other"


@pytest.mark.parametrize("change", [
    {"object_ref": True}, {"object_ref": " x"}, {"source": "x\n"}, {"target": "\x7f"},
    {"catalog_digest": "A" * 64}, {"bindings_digest": 7}, {"resource_policy_digest": ""},
    {"source": "pose-2"}, {"geometry": "requester-override"}, {"cargo_id": "cargo-1"},
    {"pick": {"x": 0.1}}, {"recipe_sha256": "d" * 64},
])
def test_untrusted_physical_payload_is_strict_and_closed(change):
    with pytest.raises(ValidationError):
        model().model_validate(grant(arm_transfer=payload(**change)))


@pytest.mark.parametrize("change", [
    {"step_id": "m-1"}, {"action_id": " s"}, {"attempt_id": "../t"}, {"mission_id": True},
    {"instance_id": "../arm"}, {"workcell_id": "work cell"},
    {"request_digest": "G" * 64}, {"authority_epoch": True}, {"dispatch_generation": "2"},
    {"authority_epoch": -1}, {"capability_revision": " "}, {"config_revision": "bad\x00"},
    {"issued_at": datetime(2026, 10, 24)}, {"expires_at": datetime(2026, 10, 23, tzinfo=timezone.utc)},
    {"expires_at": datetime(2026, 10, 24, tzinfo=timezone.utc)}, {"action_kind": "CELL_TRANSFER"},
    {"pair_id": "p-1"}, {"cell_transfer": {}},
])
def test_untrusted_grant_envelope_is_strict_distinct_aware_and_closed(change):
    with pytest.raises(ValidationError):
        model().model_validate(grant(**change))
