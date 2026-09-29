"""PolicyEvidencePayload contract tests (D-268 ladder step 1, T1).

Producer-side rules only: the empty server-side observation registry that
rejects every submission and the dispatch valve are asserted in the fleet
execute-plan tasks (T3/T4), not here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core_common.protocol.policy_evidence import PolicyEvidencePayload, PolicyObservation


def _base() -> dict:
    return {
        "evidence_id": "ev-20260929-0001",
        "asset_kind": "robot",
        "asset_id": "rosy_01",
        "task_kind": "navigate",
        "captured_at": 1760000000.25,
        "map_id": "site-map-a",
        "calibration_revision": "cal-2026-09-26",
        "model_revision": "aruco-v3",
        "observation": {"kind": "robot_zone"},
    }


def test_minimal_payload_is_accepted_and_frozen():
    model = PolicyEvidencePayload.model_validate(_base())
    assert model.asset_kind == "robot"
    assert model.observation.kind == "robot_zone"
    with pytest.raises(ValidationError):
        model.captured_at = 0.0


def test_extra_fields_are_forbidden():
    raw = _base()
    raw["quality"] = 0.9
    with pytest.raises(ValidationError):
        PolicyEvidencePayload.model_validate(raw)


@pytest.mark.parametrize("field", ["source", "source_id", "token", "policy", "satisfied"])
def test_client_identity_and_goal_vocabulary_are_rejected(field):
    raw = _base()
    raw[field] = "whatever"
    with pytest.raises(ValidationError, match="client may not set"):
        PolicyEvidencePayload.model_validate(raw)


@pytest.mark.parametrize(
    "evidence_id",
    [
        "has spaces",
        "-leading-dash",
        "",
        "e" * 161,
    ],
)
def test_evidence_id_format(evidence_id):
    raw = _base()
    raw["evidence_id"] = evidence_id
    with pytest.raises(ValidationError):
        PolicyEvidencePayload.model_validate(raw)


def test_asset_id_format():
    raw = _base()
    raw["asset_id"] = "a" * 129
    with pytest.raises(ValidationError):
        PolicyEvidencePayload.model_validate(raw)


@pytest.mark.parametrize("asset_kind", ["robot", "workcell", "object"])
def test_asset_kind_accepts_dispatch_resource_vocabulary(asset_kind):
    raw = _base()
    raw["asset_kind"] = asset_kind
    assert PolicyEvidencePayload.model_validate(raw).asset_kind == asset_kind


def test_asset_kind_rejects_unknown_kind():
    raw = _base()
    raw["asset_kind"] = "zone"
    with pytest.raises(ValidationError, match="asset_kind must be one of"):
        PolicyEvidencePayload.model_validate(raw)


def test_task_kind_is_closed_to_v1_navigate():
    raw = _base()
    raw["task_kind"] = "pick_place"
    with pytest.raises(ValidationError, match="task_kind must be one of"):
        PolicyEvidencePayload.model_validate(raw)


def test_revisions_must_not_be_blank():
    raw = _base()
    raw["model_revision"] = "   "
    with pytest.raises(ValidationError, match="must not be blank"):
        PolicyEvidencePayload.model_validate(raw)


@pytest.mark.parametrize("bad", [True, float("inf"), float("nan")])
def test_captured_timestamp_rejects_bool_and_nonfinite(bad):
    raw = _base()
    raw["captured_at"] = bad
    with pytest.raises(ValidationError):
        PolicyEvidencePayload.model_validate(raw)


def test_observation_kind_must_be_snake_case():
    with pytest.raises(ValidationError):
        PolicyObservation.model_validate({"kind": "RobotZone"})
    with pytest.raises(ValidationError):
        PolicyObservation.model_validate({"kind": "robot-zone"})


def test_observation_is_closed():
    with pytest.raises(ValidationError):
        PolicyObservation.model_validate({"kind": "robot_zone", "zone_id": "a"})
