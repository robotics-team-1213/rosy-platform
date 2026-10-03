"""Policy-evidence HTTP surface tests (D-268 ladder step 1, T5).

Source-scoped bearer tokens, durable rejection records with audit reasons,
idempotent resubmission, replay rejection, and operator readback. The v1
empty observation registry makes every well-formed submission a recorded
rejection — asserted here at the HTTP layer too.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.policy_evidence import PolicyEvidenceStore
from fleet.server.policy_evidence_config import PolicyEvidenceSource
from fleet.swarm.robots import RobotEndpoint

_TOKEN = "source-secret-1"
_CONSOLE_TOKEN = "console-secret"
_NOW = 1_760_000_000.0


def _source(*, token: str = _TOKEN) -> PolicyEvidenceSource:
    return PolicyEvidenceSource(
        source_id="ceiling-vision-1",
        token=token,
        asset_kinds=("robot",),
        task_kinds=("navigate",),
        map_id="site-map-a",
        calibration_revision="cal-2026-09-26",
        model_revisions=("aruco-v3",),
    )


def _console_and_store(tmp_path, *, sources=None, clock=lambda: _NOW):
    robot = FakeRobot("rosy_01")
    console = FleetConsole(
        [RobotEndpoint(robot_id="rosy_01", base_url="http://127.0.0.1:8080", token="t")],
        [robot])
    store = PolicyEvidenceStore(
        sources if sources is not None else [_source()],
        tmp_path / "pe.sqlite3", clock=clock)
    return console, store


def _payload(evidence_id="ev-1", *, asset_id="rosy_01") -> dict:
    return {
        "evidence_id": evidence_id,
        "asset_kind": "robot",
        "asset_id": asset_id,
        "task_kind": "navigate",
        "captured_at": _NOW - 0.1,
        "map_id": "site-map-a",
        "calibration_revision": "cal-2026-09-26",
        "model_revision": "aruco-v3",
        "observation": {"kind": "robot_zone"},
    }


def test_missing_or_unknown_token_is_unauthorized(tmp_path):
    console, store = _console_and_store(tmp_path)
    client = TestClient(create_app(console, console_token=_CONSOLE_TOKEN,
                                   policy_evidence=store))

    for headers in ({}, {"Authorization": "Bearer wrong-token"},
                    {"Authorization": f"Bearer {_CONSOLE_TOKEN}"}):
        response = client.post("/api/fleet/policy-evidence", json=_payload(), headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "EVIDENCE_SOURCE_UNKNOWN"


def test_well_formed_submission_is_a_recorded_rejection_in_v1(tmp_path):
    console, store = _console_and_store(tmp_path)
    client = TestClient(create_app(console, console_token=_CONSOLE_TOKEN,
                                   policy_evidence=store))

    response = client.post("/api/fleet/policy-evidence", json=_payload(),
                           headers={"Authorization": f"Bearer {_TOKEN}"})
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "rejected"
    assert body["reason"] == "EVIDENCE_OBSERVATION_KIND_UNKNOWN"
    assert body["source_id"] == "ceiling-vision-1"

    again = client.post("/api/fleet/policy-evidence", json=_payload(),
                        headers={"Authorization": f"Bearer {_TOKEN}"})
    assert again.status_code == 200
    assert again.json() == body  # idempotent


def test_same_id_different_content_is_replay_conflict(tmp_path):
    console, store = _console_and_store(tmp_path)
    client = TestClient(create_app(console, console_token=_CONSOLE_TOKEN,
                                   policy_evidence=store))
    headers = {"Authorization": f"Bearer {_TOKEN}"}

    client.post("/api/fleet/policy-evidence", json=_payload(), headers=headers)
    response = client.post("/api/fleet/policy-evidence",
                           json=_payload(asset_id="rosy_02"), headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVIDENCE_REPLAY"


def test_forbidden_client_fields_are_rejected_as_validation_errors(tmp_path):
    console, store = _console_and_store(tmp_path)
    client = TestClient(create_app(console, console_token=_CONSOLE_TOKEN,
                                   policy_evidence=store))

    raw = _payload()
    raw["source_id"] = "spoofed"
    response = client.post("/api/fleet/policy-evidence", json=raw,
                           headers={"Authorization": f"Bearer {_TOKEN}"})
    assert response.status_code == 422


def test_operator_readback_lists_records_and_requires_a_credential(tmp_path):
    console, store = _console_and_store(tmp_path)
    client = TestClient(create_app(console, console_token=_CONSOLE_TOKEN,
                                   policy_evidence=store))
    client.post("/api/fleet/policy-evidence", json=_payload(),
                headers={"Authorization": f"Bearer {_TOKEN}"})

    unauthenticated = client.get("/api/fleet/policy-evidence/latest")
    assert unauthenticated.status_code == 401

    readback = client.get("/api/fleet/policy-evidence/latest",
                          headers={"Authorization": f"Bearer {_CONSOLE_TOKEN}"})
    assert readback.status_code == 200
    rows = readback.json()["evidence"]
    assert len(rows) == 1
    assert rows[0]["payload"]["observation"] == {"kind": "robot_zone"}


def test_source_token_must_differ_from_the_console_token(tmp_path):
    console, store = _console_and_store(
        tmp_path, sources=[_source(token=_CONSOLE_TOKEN)])
    with pytest.raises(ValueError, match="must differ from the console token"):
        create_app(console, console_token=_CONSOLE_TOKEN, policy_evidence=store)
