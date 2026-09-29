"""Policy task admission binding tests (D-268 ladder step 1, T4).

These pin the fail-closed invariants: every policy submission requires an
`evidence_id` reference, every admission failure lands in HOLD with an audit
reason, and even a fully admissible record cannot dispatch while the valve
`POLICY_DISPATCH_ENABLED` stays False.
"""

from __future__ import annotations

import pytest

from fakes import run
from fleet.server.policy_evidence import PolicyEvidenceStore
from fleet.server.policy_evidence_config import PolicyEvidenceSource
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

_TOKEN = "site-secret-1"
_NOW = 1_760_000_000.0


def _source() -> PolicyEvidenceSource:
    return PolicyEvidenceSource(
        source_id="ceiling-vision-1",
        token=_TOKEN,
        asset_kinds=("robot",),
        task_kinds=("navigate",),
        map_id="site-map-a",
        calibration_revision="cal-2026-09-26",
        model_revisions=("aruco-v3",),
    )


class _RegisteredStore(PolicyEvidenceStore):
    """Test-only store with one registered observation kind (the T-later shape)."""

    OBSERVATION_KINDS = frozenset({"robot_zone"})


def _evidence_payload(evidence_id="ev-1", asset_id="rosy_01", captured_at=_NOW - 0.1) -> dict:
    return {
        "evidence_id": evidence_id,
        "asset_kind": "robot",
        "asset_id": asset_id,
        "task_kind": "navigate",
        "captured_at": captured_at,
        "map_id": "site-map-a",
        "calibration_revision": "cal-2026-09-26",
        "model_revision": "aruco-v3",
        "observation": {"kind": "robot_zone"},
    }


def _service(tmp_path, *, policy_evidence=None, max_evidence_age_s=None, clock=None):
    service = FleetTaskService(
        FleetTaskStore(tmp_path / "fleet.sqlite3"),
        robot_ids={"rosy_01"},
        policy_evidence=policy_evidence,
        max_evidence_age_s=max_evidence_age_s,
        clock=clock if clock is not None else (lambda: _NOW),
    )
    state = service.store.dispatch_control()
    service.store.rearm_dispatch(expected_generation=state["generation"],
                                 actor_id="test-operator")
    return service


def _submit(service, evidence=None, request_key="p-1"):
    return run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, yaw=0.0,
        source="policy", actor_id="policy:test", request_key=request_key,
        evidence=evidence if evidence is not None else {"evidence_id": "ev-1"},
    ))


def test_the_dispatch_valve_is_closed():
    assert FleetTaskService.POLICY_DISPATCH_ENABLED is False


def test_policy_submission_requires_an_evidence_id_reference(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="INVALID_EVIDENCE_REFERENCE"):
        run(service.submit_navigation(
            robot_id="rosy_01", x=1.0, y=2.0, yaw=0.0,
            source="policy", actor_id="policy:test", request_key="p-none",
            evidence=None,
        ))
    for bad in ({}, {"event_id": "ev-1"}, {"evidence_id": "  "}, {"evidence_id": 7}):
        with pytest.raises(ValueError, match="INVALID_EVIDENCE_REFERENCE"):
            _submit(service, evidence=bad)


def test_unwired_service_holds_with_evidence_not_configured(tmp_path):
    service = _service(tmp_path)
    task = _submit(service)
    assert task["status"] == "HOLD"
    assert task["reason"] == "EVIDENCE_NOT_CONFIGURED"
    assert [row["status"] for row in service.store.history(task["task_id"])] == [
        "REQUESTED", "HOLD",
    ]


def test_unknown_evidence_id_holds_with_not_found(tmp_path):
    store = PolicyEvidenceStore([_source()], tmp_path / "pe.sqlite3",
                                clock=lambda: _NOW)
    service = _service(tmp_path, policy_evidence=store)
    task = _submit(service, evidence={"evidence_id": "missing"})
    assert task["reason"] == "EVIDENCE_NOT_FOUND"


def test_rejected_evidence_record_carries_its_reason_into_the_task(tmp_path):
    store = PolicyEvidenceStore([_source()], tmp_path / "pe.sqlite3",
                                clock=lambda: _NOW)
    record = store.submit(_evidence_payload(), token=_TOKEN, now=_NOW)
    assert record["outcome"] == "rejected"  # v1 empty registry

    service = _service(tmp_path, policy_evidence=store)
    task = _submit(service)
    assert task["status"] == "HOLD"
    assert task["reason"] == record["reason"] == "EVIDENCE_OBSERVATION_KIND_UNKNOWN"


def test_accepted_record_without_age_budget_is_stale(tmp_path):
    store = _RegisteredStore([_source()], tmp_path / "pe.sqlite3", clock=lambda: _NOW)
    record = store.submit(_evidence_payload(), token=_TOKEN, now=_NOW)
    assert record["outcome"] == "accepted"

    service = _service(tmp_path, policy_evidence=store, max_evidence_age_s=None)
    task = _submit(service)
    assert task["reason"] == "EVIDENCE_STALE"


def test_accepted_record_for_another_robot_is_an_asset_mismatch(tmp_path):
    store = _RegisteredStore([_source()], tmp_path / "pe.sqlite3", clock=lambda: _NOW)
    store.submit(_evidence_payload(asset_id="rosy_02"), token=_TOKEN, now=_NOW)

    service = _service(tmp_path, policy_evidence=store, max_evidence_age_s=30.0)
    task = _submit(service)
    assert task["reason"] == "EVIDENCE_ASSET_MISMATCH"


def test_admissible_evidence_still_holds_under_the_closed_valve(tmp_path):
    """The key invariant: valid evidence admits, but only the valve dispatches."""
    store = _RegisteredStore([_source()], tmp_path / "pe.sqlite3", clock=lambda: _NOW)
    store.submit(_evidence_payload(), token=_TOKEN, now=_NOW)

    service = _service(tmp_path, policy_evidence=store, max_evidence_age_s=30.0)
    task = _submit(service)
    assert task["status"] == "HOLD"
    assert task["reason"] == "POLICY_NOT_ACCEPTED"


def test_operator_path_is_unchanged_by_the_binding_contract(tmp_path):
    service = _service(tmp_path)
    task = run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="manual-1",
        evidence={"note": "operators may attach arbitrary mapping evidence"},
    ))
    assert task["status"] == "QUEUED"
    assert task["source"] == "operator"
