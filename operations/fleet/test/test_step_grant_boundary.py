"""D-856 step identity is common; typed payload provenance belongs to its registered kind."""
from datetime import datetime, timedelta, timezone
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict
import pytest

from fleet.server import step_action_kinds as kinds
from fleet.server.cell_job_store import CellJobStore
from test_cell_job_store import _stores, _create, _grant


class PhysicalProbeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    opaque_id: str


class PhysicalProbeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action_kind: Literal["TEST_PHYSICAL"]
    mission_id: str
    step_id: str
    action_id: str
    attempt_id: str
    workcell_id: str
    instance_id: str
    authority_epoch: int
    dispatch_generation: int
    request_digest: str
    issued_at: datetime
    expires_at: datetime
    physical: PhysicalProbeBody


def _api(name):
    value = getattr(kinds, name, None)
    assert value is not None, f"kind-neutral step grant boundary {name} is missing"
    return value


def _physical_case(monkeypatch):
    # This inactive test kind is never registered in product code or admitted to a device.
    monkeypatch.setitem(kinds._KINDS, "TEST_PHYSICAL", kinds.StepActionKind(
        action_kind="TEST_PHYSICAL", open_profiles=frozenset(), grant_model=PhysicalProbeGrant,
        body_field="physical", body=lambda job, index, inputs: {"opaque_id": inputs["opaque_id"]},
        phase_ids=(), rejection_reasons={}, approval="two_person"))
    job = dict(mission_id="m1", workcell_id="w1", instance_id="i1", authority_epoch=3, dispatch_generation=4)
    step = dict(step_id="s1", step_index=0, action_kind="TEST_PHYSICAL",
                step_json=json.dumps({"inputs": {"opaque_id": "object-1"}}))
    now = datetime.now(timezone.utc)
    grant = PhysicalProbeGrant(**job, step_id="s1", action_id="a1", attempt_id="t1",
        action_kind="TEST_PHYSICAL", request_digest="0" * 64, issued_at=now,
        expires_at=now + timedelta(seconds=30), physical={"opaque_id": "object-1"})
    grant = grant.model_copy(update={"request_digest": kinds.step_grant_digest(grant)})
    return job, step, grant


def test_registry_parses_and_matches_a_physical_grant_without_cell_fields(monkeypatch):
    job, step, grant = _physical_case(monkeypatch)
    parsed = _api("parse_step_grant")(grant.model_dump(mode="json"))
    assert type(parsed) is PhysicalProbeGrant
    _api("validate_step_grant")(parsed, job, step, step_index=0, action_id="a1", attempt_id="t1")
    assert not kinds.dispatch_open("simulation", "TEST_PHYSICAL")
    assert not {"recipe_digest", "cell_digest", "job_id", "pallet", "layer"} & set(job)


@pytest.mark.parametrize("field,value", [
    ("mission_id", "m2"), ("step_id", "s2"), ("action_id", "a2"), ("attempt_id", "t2"),
    ("workcell_id", "w2"), ("instance_id", "i2"), ("authority_epoch", 4), ("dispatch_generation", 5),
])
def test_common_identity_cannot_change_for_another_kind(monkeypatch, field, value):
    job, step, grant = _physical_case(monkeypatch)
    with pytest.raises(ValueError):
        _api("validate_step_grant")(grant.model_copy(update={field: value}), job, step,
                                     step_index=0, action_id="a1", attempt_id="t1")


def test_stored_kind_and_full_physical_body_are_both_bound(monkeypatch):
    job, step, grant = _physical_case(monkeypatch)
    validate = _api("validate_step_grant")
    with pytest.raises(ValueError):
        validate(grant, job, {**step, "action_kind": "CELL_TRANSFER"},
                 step_index=0, action_id="a1", attempt_id="t1")
    with pytest.raises(ValueError):
        validate(grant.model_copy(update={"physical": PhysicalProbeBody(opaque_id="object-2")}), job, step,
                 step_index=0, action_id="a1", attempt_id="t1")


@pytest.mark.parametrize("kind", ["TRIP", "NOT_REGISTERED"])
def test_only_registered_device_grants_can_be_parsed(kind):
    with pytest.raises(ValueError):
        _api("parse_step_grant")({"action_kind": kind})


@pytest.mark.parametrize("field,value", [
    ("recipe_sha256", "f" * 64), ("cell_sha256", "f" * 64), ("job_id", "f" * 64),
    ("step_index", 1), ("item", "slip_sheet"), ("pallet", "another-pallet"),
    ("pick", {"x": 0.9, "y": 0.2, "z": 0.3, "yaw": 0.0}),
])
def test_resigned_cell_payload_changes_still_leave_ledger_and_claims_unchanged(tmp_path, field, value):
    path, tasks, _, control = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1", expected_generation=control["generation"])
    grant = _grant(ready, 0)
    grant["cell_transfer"][field] = value
    grant["request_digest"] = kinds.step_grant_digest(grant)
    claims = tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    with pytest.raises(ValueError):
        store.start_step("cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0", grant=grant)
    assert store.get("cell-mission-1") == ready
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01") == claims


def test_uninstalled_arm_transfer_dto_is_not_a_fleet_execution_kind():
    from fleet.server.step_action_kinds import parse_step_grant

    with pytest.raises(ValueError):
        parse_step_grant({"action_kind": "ARM_TRANSFER"})
