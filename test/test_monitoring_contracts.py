"""D-876: passive Fleet connection evidence, never a command or a fresh gather."""

import json

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import FleetLinkObservation, FleetMonitoringRead


def snapshot(**changes):
    return {
        "schema_version": 1,
        "sampled_at": "2026-10-25T00:00:00Z",
        "cache_age_s": 8.5,
        "robots": [{"robot_id": "robot-a", "link": "tls-refused", "reachable": True,
                    "reason_code": "PAIRING_REQUIRED", "state_age_s": None}],
    } | changes


def test_canonical_read_shape_preserves_failed_authentication_and_old_cache():
    value = FleetMonitoringRead.model_validate_json(json.dumps(snapshot()))
    assert value.cache_age_s == 8.5
    row = value.robots[0]
    assert isinstance(row, FleetLinkObservation)
    assert row.link == "tls-refused" and row.reachable is True
    assert row.reason_code == "PAIRING_REQUIRED" and row.state_age_s is None
    assert set(value.model_dump()) == {"schema_version", "sampled_at", "cache_age_s", "robots"}


def test_no_cache_is_explicit_and_empty():
    value = FleetMonitoringRead.model_validate(snapshot(sampled_at=None, cache_age_s=None, robots=[]))
    assert value.sampled_at is None and value.cache_age_s is None and value.robots == []


@pytest.mark.parametrize("changes", [
    {"sampled_at": None}, {"cache_age_s": None},
    {"sampled_at": "2026-10-25T00:00:00"},
    {"sampled_at": True}, {"sampled_at": 1},
    {"schema_version": 2}, {"schema_version": True},
    {"cache_age_s": -1.0}, {"cache_age_s": float("nan")},
    {"cache_age_s": float("inf")}, {"cache_age_s": True}, {"cache_age_s": "1"},
    {"command": "restart"},
])
def test_invalid_cache_metadata_and_extra_authority_are_rejected(changes):
    with pytest.raises(ValidationError):
        FleetMonitoringRead.model_validate(snapshot(**changes))


@pytest.mark.parametrize("changes", [
    {"robot_id": ""}, {"robot_id": "x" * 97}, {"robot_id": "robot/a"},
    {"link": "ready_to_move"}, {"reachable": "true"},
    {"reason_code": "UNREGISTERED_REASON"}, {"state_age_s": -0.1},
    {"state_age_s": float("inf")}, {"state_age_s": True},
    {"access_token": "must-not-cross-the-wire"}, {"error": "raw exception body"},
])
def test_robot_evidence_is_closed_and_contains_no_raw_body(changes):
    row = snapshot()["robots"][0] | changes
    with pytest.raises(ValidationError):
        FleetMonitoringRead.model_validate(snapshot(robots=[row]))


def test_duplicate_and_excess_robot_rows_are_rejected():
    row = snapshot()["robots"][0]
    with pytest.raises(ValidationError):
        FleetMonitoringRead.model_validate(snapshot(robots=[row, row]))
    with pytest.raises(ValidationError):
        FleetMonitoringRead.model_validate(snapshot(robots=[row | {"robot_id": f"r-{i}"} for i in range(257)]))


def test_missing_cache_cannot_carry_robot_evidence():
    with pytest.raises(ValidationError):
        FleetMonitoringRead.model_validate(snapshot(sampled_at=None, cache_age_s=None))


def test_observation_is_frozen():
    value = FleetMonitoringRead.model_validate(snapshot())
    with pytest.raises(ValidationError):
        value.robots[0].reachable = False
