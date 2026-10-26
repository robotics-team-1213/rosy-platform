"""Installed capability describes an owner; grants must target its exact journal/session."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from core_common.protocol import schemas
from test_arm_transfer_grant_contract import grant


def facts():
    return json.loads((Path(__file__).parent / "fixtures/arm_transfer_capability_v1.json").read_text())


def capability_model():
    model = getattr(schemas, "ArmTransferCapability", None)
    assert model is not None, "installed transfer capability contract is missing"
    return model


def test_capability_fixture_is_closed_frozen_and_round_trips():
    model = capability_model()
    value = model.model_validate(facts())
    assert value.model_dump() == facts()
    assert model.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        value.owner_session_id = "other"


@pytest.mark.parametrize("change", [
    {"control_mode": "manual"}, {"journal_id": ""}, {"owner_session_id": " session"},
    {"catalog_digest": "A" * 64}, {"bindings_digest": True}, {"config_revision": "x\n"},
    {"mission_id": "requester-claim"},
])
def test_capability_rejects_wrong_mode_identity_and_undeclared_fields(change):
    with pytest.raises(ValidationError):
        capability_model().model_validate({**facts(), **change})


@pytest.mark.parametrize("missing", ["owner_journal_id", "owner_session_id"])
def test_arm_grant_requires_both_target_owner_identities(missing):
    body = {**grant(), "owner_journal_id": "journal-1", "owner_session_id": "session-1"}
    del body[missing]
    with pytest.raises(ValidationError):
        schemas.FleetArmTransferGrant.model_validate(body)


def test_bound_grant_preserves_target_owner_in_canonical_payload():
    body = {**grant(), "owner_journal_id": "journal-1", "owner_session_id": "session-1"}
    assert schemas.FleetArmTransferGrant.model_validate(body).model_dump() == body
