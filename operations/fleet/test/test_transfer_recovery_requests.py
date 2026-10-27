"""Authenticated recovery intent and independent evidence bind one durable child."""
from importlib import import_module

import pytest

from fleet.server.mission_store import MissionConflict
from fleet.server.site_auth import SitePrincipal
from test_transfer_recovery_flow import failed_driver, driver, geometry, policy, installation, rig
from test_physical_transfer_store import PROPOSER, OPERATOR, claims
from test_physical_transfer_recovery import measured


def service(case, *, resolver=None):
    d, _ = case
    try:
        module = import_module("fleet.server.physical_transfer_recovery_requests")
    except ModuleNotFoundError:
        pytest.fail("authenticated recovery request service is missing")
    return module.RecoveryRequestService(d.dispatcher,
        resolve_proposer=resolver or (lambda connection, name: PROPOSER if name == PROPOSER.principal_id else None))


def request(s, case, key="request-one"):
    d, _ = case
    parent = d.job["mission_id"]
    preview = s.preview(parent, PROPOSER)
    return s.request(parent, principal=PROPOSER, request_key=key,
                     expected_context_digest=preview["context_digest"])


def capture(s, case, intent, *, sequence=20):
    d, _ = case
    parent = d.job["mission_id"]
    context = s.context(parent, intent["request_id"])
    assert context["purpose"] == "RECOVERY_RESET"
    assert context["execution_authorized"] is False
    data = measured(d.store, d.execution.snapshot(parent), offset=1_200_000_000, sequence=sequence)
    d.clock[0] += 500_000_000
    return s.observe(parent, intent["request_id"], expected_proposal_digest=intent["proposal_digest"],
                     observations=data, authenticated_producer_id=d.store.installation.policy.producer_id)


def approve(s, case, intent, evidence, *, actor=OPERATOR):
    d, _ = case
    return s.approve(d.job["mission_id"], intent["request_id"], principal=actor,
        expected_proposal_digest=intent["proposal_digest"], expected_evidence_digest=evidence["evidence_digest"],
        expected_generation=d.tasks.dispatch_control()["generation"])


def test_original_proposer_intent_and_independent_facts_are_required(failed_driver):
    d, _ = failed_driver
    s, parent = service(failed_driver), d.job["mission_id"]
    before = claims(d.path)
    preview = s.preview(parent, PROPOSER)
    assert preview["can_request"] and not preview["can_approve"]
    with pytest.raises(PermissionError):
        s.request(parent, principal=OPERATOR, request_key="operator-forgery",
                  expected_context_digest=preview["context_digest"])
    intent = request(s, failed_driver)
    waiting = s.preview(parent, OPERATOR)
    assert waiting["status"] == "WAITING_OBSERVATIONS" and not waiting["can_approve"]
    with pytest.raises(MissionConflict):
        approve(s, failed_driver, intent, {"evidence_digest": "a" * 64})
    assert claims(d.path) == before and not s.preview(parent, OPERATOR)["child_mission_id"]
    proof = capture(s, failed_driver, intent)
    with pytest.raises(PermissionError):
        approve(s, failed_driver, intent, proof, actor=PROPOSER)
    assert s.preview(parent, OPERATOR)["can_approve"]
    result = approve(s, failed_driver, intent, proof)
    assert result["job"]["mission_id"] != parent and result["execution"]["status"] == "PREPARED"
    assert d.store.get(parent, principal=OPERATOR)["status"] == "HOLD"
    assert {row["owner_id"] for row in claims(d.path)} == {result["job"]["mission_id"]}


def test_replaced_request_cannot_approve_older_observations(failed_driver):
    s = service(failed_driver)
    intent = request(s, failed_driver)
    proof = capture(s, failed_driver, intent)
    replacement = request(s, failed_driver, key="request-two")
    assert replacement["request_id"] != intent["request_id"]
    with pytest.raises(MissionConflict):
        approve(s, failed_driver, intent, proof)
    assert s.preview(failed_driver[0].job["mission_id"], OPERATOR)["child_mission_id"] is None


def test_observation_must_follow_its_authenticated_capture_request(failed_driver):
    d, _ = failed_driver
    s = service(failed_driver)
    intent = request(s, failed_driver)
    old = measured(d.store, d.execution.snapshot(d.job["mission_id"]), offset=600_000_000, sequence=20)
    with pytest.raises(MissionConflict):
        s.observe(d.job["mission_id"], intent["request_id"], expected_proposal_digest=intent["proposal_digest"],
                  observations=old, authenticated_producer_id=d.store.installation.policy.producer_id)


def test_revoked_original_proposer_cannot_be_approved(failed_driver):
    current = [PROPOSER]
    s = service(failed_driver, resolver=lambda connection, name: current[0])
    intent = request(s, failed_driver)
    proof = capture(s, failed_driver, intent)
    current[0] = SitePrincipal(PROPOSER.principal_id, "viewer")
    before = claims(failed_driver[0].path)
    with pytest.raises(PermissionError):
        approve(s, failed_driver, intent, proof)
    assert claims(failed_driver[0].path) == before


def test_expired_evidence_cannot_be_approved(failed_driver):
    d, _ = failed_driver
    s = service(failed_driver)
    intent = request(s, failed_driver)
    proof = capture(s, failed_driver, intent)
    d.clock[0] += 60_000_000_000
    assert not s.preview(d.job["mission_id"], OPERATOR)["can_approve"]
    with pytest.raises(MissionConflict):
        approve(s, failed_driver, intent, proof)


def test_exact_approved_replay_needs_no_owner_or_fresh_evidence(failed_driver):
    d, _ = failed_driver
    s = service(failed_driver)
    intent = request(s, failed_driver)
    proof = capture(s, failed_driver, intent)
    first = approve(s, failed_driver, intent, proof)
    d.clock[0] += 60_000_000_000
    def unavailable(*args, **kwargs):
        raise AssertionError("a retained exact replay cannot call the owner")
    d.port.transfer_capability = unavailable
    again = approve(service(failed_driver), failed_driver, intent, proof)
    assert again == first


def test_request_key_replay_is_exact_and_changed_context_is_rejected(failed_driver):
    d, _ = failed_driver
    s = service(failed_driver)
    first = request(s, failed_driver)
    assert request(s, failed_driver) == first
    with pytest.raises(MissionConflict):
        s.request(d.job["mission_id"], principal=PROPOSER, request_key="request-one",
                  expected_context_digest="f" * 64)
