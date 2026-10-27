"""One explicitly approved recovery child; original attempts and evidence stay intact."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from uuid import uuid4

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from rosy.world.state.projections.physical_transfer import TransferObservation
from .action_receipts import verify_phase_receipt
from .dispatch_admission import release
from .mission_store import MissionConflict, _json
from .physical_transfer_evidence import TransferEvidenceContext, validate_transfer_observations
from .physical_transfer_execution import PhysicalTransferExecution
from .physical_transfer_observations import evidence_document, validate_post_action_order
from .physical_transfer_outcomes import EVENT as ASSESSED
from .physical_transfer_store import PhysicalTransferRequest, _principal

CREATED = "PHYSICAL_TRANSFER_RECOVERY_CREATED"
ORIGIN = "PHYSICAL_TRANSFER_RECOVERY_ORIGIN"


def _digest(value):
    return sha256(_json(value).encode()).hexdigest()


def _event(connection, mission_id, kind):
    rows = connection.execute("SELECT detail_json FROM fleet_cell_events WHERE mission_id=? AND event_type=?",
                              (mission_id, kind)).fetchall()
    if len(rows) > 1:
        raise MissionConflict("recovery journal has conflicting lineage")
    return None if not rows else json.loads(rows[0][0])


def _job(store, connection, mission_id):
    job = store._read(connection, mission_id)
    if job is None:
        raise KeyError(mission_id)
    if store._document(PhysicalTransferRequest.model_validate(job["request"])) != _json(
            {"request": job["request"], "installation": job["installation"]}):
        raise PermissionError("recovery is outside the installed physical profile")
    return job


def _assessment(detail, grant, policy):
    evidence = detail["evidence"]
    if (detail["schema"] != "rosy.transfer-outcome/1" or detail["mission_id"] != grant.mission_id
            or detail["action_id"] != grant.action_id or detail["attempt_id"] != grant.attempt_id
            or detail["request_digest"] != grant.request_digest or detail["policy_digest"] != policy.digest
            or _digest(evidence) != detail["evidence_digest"]
            or evidence["context"]["action_id"] != grant.action_id
            or evidence["context"]["attempt_id"] != grant.attempt_id
            or evidence["context"]["phase"] != "POST_ACTION"):
        raise MissionConflict("recovery assessment evidence changed")
    return detail


def _retained_execution(store, connection, mission_id):
    row = connection.execute("SELECT grant_json FROM fleet_physical_transfer_attempts WHERE mission_id=?",
                             (mission_id,)).fetchone()
    if row is None:
        raise KeyError(mission_id)
    grant = FleetArmTransferGrant.model_validate_json(row[0])
    return PhysicalTransferExecution(store, grant_ttl_s=(grant.expires_at - grant.issued_at).total_seconds())


def retained_snapshot(execution, mission_id):
    with closing(execution.store._journal._connect()) as connection:
        connection.execute("BEGIN")
        try:
            retained = _retained_execution(execution.store, connection, mission_id)
        except KeyError:
            return None
        return retained._state(connection, mission_id)


def _parent(execution, connection, mission_id):
    store = execution.store
    job = _job(store, connection, mission_id)
    if _event(connection, mission_id, ORIGIN) or _event(connection, mission_id, CREATED):
        raise MissionConflict("one recovery child is the complete retry budget")
    try:
        retained = _retained_execution(store, connection, mission_id)
    except KeyError as exc:
        raise MissionConflict("recovery requires a retained original attempt") from exc
    state = retained._state(connection, mission_id)
    grant = FleetArmTransferGrant.model_validate(state["grant"])
    latest = retained._last_receipt(connection, mission_id)
    if latest is None or not state["first_send_committed"]:
        raise MissionConflict("recovery requires the original submitted Action receipt")
    receipt = verify_phase_receipt(grant, latest["receipt"], phase_ids=("approach", "grasp", "transfer", "release"))
    assessment = None
    if receipt.state.value == "FAILED" and job["status"] == "HOLD" and state["status"] in {"UNKNOWN", "HOLD"}:
        pass
    elif receipt.state.value == "SUCCEEDED" and job["status"] == state["status"] == "ACTION_SUCCEEDED":
        row = connection.execute("SELECT detail_json FROM fleet_cell_events WHERE mission_id=? AND event_type=? "
            "ORDER BY event_id DESC LIMIT 1", (mission_id, ASSESSED)).fetchone()
        if row is not None:
            assessment = _assessment(json.loads(row[0]), grant, store.installation.policy)
        if assessment is None or assessment["task_outcome"] != "failed":
            raise MissionConflict("recovery requires the latest task assessment to be failed")
    else:
        raise MissionConflict("uncertain, active, held or completed effects cannot be retried")
    boundary = latest["received_at_ns"]
    if type(boundary) is not int or not state["prepared_at_ns"] <= boundary <= store._now_ns():
        raise MissionConflict("recovery receipt clock changed")
    context = TransferEvidenceContext.model_validate_json(_json(
        {**state["context"], "phase": "PRE_DISPATCH", "not_before_ns": boundary}))
    return job, grant, latest, assessment, context


def recovery_context(execution, parent_id):
    """Trusted host producer context, not a public observer route or execution permit."""
    with closing(execution.store._journal._connect()) as connection:
        connection.execute("BEGIN")
        job, grant, latest, assessment, context = _parent(execution, connection, parent_id)
        return dict(expected_request_digest=grant.request_digest,
            expected_receipt_event_id=latest["receipt"]["journal_event_id"],
            expected_assessment_digest=None if assessment is None else _digest(assessment),
            expected_generation=job["dispatch_generation"], context=context.model_dump(mode="json"),
            execution_authorized=False)


def _newer_observations(connection, mission_id, observations, grant, policy):
    validate_post_action_order(connection, mission_id, observations)
    for row in connection.execute("SELECT detail_json FROM fleet_cell_events WHERE mission_id=? AND event_type=?",
                                  (mission_id, ASSESSED)):
        detail = _assessment(json.loads(row[0]), grant, policy)
        old = detail["evidence"]["samples"]
        times = [sample["object_observed_at_ns"] for sample in old]
        times.extend(t for sample in old for owner in sample["owners"]
                     for t in (owner["links_observed_at_ns"], owner["gripper_observed_at_ns"]))
        if ({sample.evidence_id for sample in observations} & {sample["evidence_id"] for sample in old}
                or observations[0].sequence <= max(sample["sequence"] for sample in old)
                or min(observations[0].sample_times_ns) <= max(times)):
            raise MissionConflict("recovery requires new observations after the retained assessments")


def _request(parent_id, proposer, actor, expected_request_digest, expected_receipt_event_id,
             expected_assessment_digest, expected_generation, producer, evidence, recovery_approval=None):
    request = dict(parent_mission_id=parent_id, proposed_by=proposer, approved_by=actor,
        parent_request_digest=expected_request_digest, source_receipt_event_id=expected_receipt_event_id,
        source_assessment_digest=expected_assessment_digest, dispatch_generation=expected_generation,
        producer_id=producer, evidence=evidence)
    if recovery_approval is not None:
        request["recovery_approval"] = recovery_approval
    return request


def _lineage_record(store, connection, mission_id):
    created, origin = _event(connection, mission_id, CREATED), _event(connection, mission_id, ORIGIN)
    if created is None and origin is None:
        return None
    if created is not None and origin is not None:
        raise MissionConflict("a recovery child cannot create another child")
    detail = created if created is not None else origin
    parent_id, child_id = detail["parent_mission_id"], detail["child_mission_id"]
    parent, child = _job(store, connection, parent_id), _job(store, connection, child_id)
    left, right = _event(connection, parent_id, CREATED), _event(connection, child_id, ORIGIN)
    evidence = detail["evidence"]
    request = _request(parent_id, detail["proposed_by"], detail["approved_by"], detail["parent_request_digest"],
        detail["source_receipt_event_id"], detail["source_assessment_digest"], detail["dispatch_generation"],
        detail["producer_id"], evidence, detail.get("recovery_approval"))
    if (detail["schema"] != "rosy.transfer-recovery/1" or detail["root_mission_id"] != parent_id
            or parent_id == child_id or mission_id not in {parent_id, child_id}
            or left is None or right is None or left["event_id"] != "physical-transfer-recovery"
            or right["event_id"] != "physical-transfer-recovery-origin"
            or {k: v for k, v in left.items() if k != "event_id"}
                != {k: v for k, v in right.items() if k != "event_id"}
            or _digest(request) != detail["recovery_request_digest"]
            or _digest(evidence) != detail["evidence_digest"]
            or detail["producer_id"] != store.installation.policy.producer_id
            or child["proposal_principal_id"] != detail["proposed_by"] or child["approved_by"] != detail["approved_by"]
            or child["request"] != parent["request"] or child["installation"] != parent["installation"]
            or _event(connection, parent_id, ORIGIN) is not None or _event(connection, child_id, CREATED) is not None):
        raise MissionConflict("retained recovery lineage changed")
    row = connection.execute("SELECT grant_json FROM fleet_physical_transfer_attempts WHERE mission_id=?",
                             (parent_id,)).fetchone()
    if row is None:
        raise MissionConflict("recovery lost its original attempt")
    grant = FleetArmTransferGrant.model_validate_json(row[0])
    context = TransferEvidenceContext.model_validate_json(_json(evidence["context"]))
    if (detail["parent_request_digest"] != grant.request_digest or context.action_id != grant.action_id
            or context.attempt_id != grant.attempt_id or context.phase != "PRE_DISPATCH"):
        raise MissionConflict("recovery evidence targets another original attempt")
    receipts = [json.loads(row[0])["receipt"] for row in connection.execute(
        "SELECT detail_json FROM fleet_cell_events WHERE mission_id=? AND event_type='PHYSICAL_TRANSFER_RECEIPT'",
        (parent_id,))]
    receipts = [receipt for receipt in receipts if receipt["journal_event_id"] == detail["source_receipt_event_id"]]
    if len(receipts) != 1 or _digest(receipts[0]) != detail["source_receipt_digest"]:
        raise MissionConflict("recovery lost its original receipt")
    receipt = verify_phase_receipt(grant, receipts[0], phase_ids=("approach", "grasp", "transfer", "release"))
    source_digest = detail["source_assessment_digest"]
    if source_digest is None:
        if receipt.state.value != "FAILED":
            raise MissionConflict("successful Action recovery requires its retained failed assessment")
    else:
        assessments = [json.loads(row[0]) for row in connection.execute(
            "SELECT detail_json FROM fleet_cell_events WHERE mission_id=? AND event_type=?", (parent_id, ASSESSED))]
        assessments = [item for item in assessments if _digest(item) == source_digest]
        if (receipt.state.value != "SUCCEEDED" or len(assessments) != 1
                or _assessment(assessments[0], grant, store.installation.policy)["task_outcome"] != "failed"):
            raise MissionConflict("recovery lost its original failed task assessment")
    if detail.get("recovery_approval") is not None:
        from .physical_transfer_recovery_requests import validate_approval
        validate_approval(store, connection, parent_id, detail["recovery_approval"],
            proposed_by=detail["proposed_by"], evidence=evidence, producer=detail["producer_id"], historical=True)
    return detail


def recovery_lineage(store, connection, mission_id):
    detail = _lineage_record(store, connection, mission_id)
    return dict(root_mission_id=mission_id if detail is None else detail["root_mission_id"],
        parent_mission_id=None if detail is None else detail["parent_mission_id"],
        child_mission_id=None if detail is None else detail["child_mission_id"],
        attempt_index=int(detail is not None and mission_id == detail["child_mission_id"]), recovery_limit=1)


def validate_recovery_preconditions(store, connection, mission_id, observations):
    detail = _lineage_record(store, connection, mission_id)
    if detail is None or mission_id != detail["child_mission_id"]:
        return
    prior = detail["evidence"]["samples"]
    if ({sample.evidence_id for sample in observations} & {sample["evidence_id"] for sample in prior}
            or observations[0].sequence <= max(sample["sequence"] for sample in prior)):
        raise MissionConflict("child submission requires new observations after recovery approval")


def _check_request(store, proposer, principal, expected_request_digest, expected_receipt_event_id,
                   expected_assessment_digest, expected_generation, observations):
    policy = store.installation.policy
    proposed_by, actor = _principal(proposer, propose=True), _principal(principal, operator=True)
    if proposed_by == actor or policy.producer_id in {proposed_by, actor}:
        raise PermissionError("recovery requires independent proposer, operator and observer")
    if (not isinstance(expected_request_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_request_digest)
            or type(expected_receipt_event_id) is not int or expected_receipt_event_id < 0
            or type(expected_generation) is not int or expected_generation < 0
            or (expected_assessment_digest is not None and (not isinstance(expected_assessment_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_assessment_digest)))):
        raise ValueError("exact recovery receipt, assessment and dispatch bindings are required")
    if (not isinstance(observations, (tuple, list)) or len(observations) != 2
            or any(not isinstance(sample, TransferObservation) for sample in observations)):
        raise ValueError("recovery requires two immutable World observations")
    return proposed_by, actor, tuple(observations)


def _replay(store, connection, parent_id, proposed_by, actor, expected_request_digest,
            expected_receipt_event_id, expected_assessment_digest, expected_generation,
            observations, authenticated_producer_id, recovery_approval=None):
    parent = _job(store, connection, parent_id)
    if parent["proposal_principal_id"] != proposed_by:
        raise PermissionError("only the original proposer may propose its recovery")
    prior = _event(connection, parent_id, CREATED)
    if prior is None:
        return None
    prior = _lineage_record(store, connection, parent_id)
    context = TransferEvidenceContext.model_validate_json(_json(prior["evidence"]["context"]))
    evidence = json.loads(evidence_document(context, observations))
    request = _request(parent_id, proposed_by, actor, expected_request_digest, expected_receipt_event_id,
        expected_assessment_digest, expected_generation, authenticated_producer_id, evidence, recovery_approval)
    if prior["recovery_request_digest"] != _digest(request):
        raise MissionConflict("recovery request changed")
    return _job(store, connection, prior["child_mission_id"])


def find_recovery(execution, parent_id, *, proposer, principal, expected_request_digest,
                  expected_receipt_event_id, expected_assessment_digest, expected_generation,
                  observations, authenticated_producer_id, recovery_approval=None):
    proposed_by, actor, observations = _check_request(execution.store, proposer, principal,
        expected_request_digest, expected_receipt_event_id, expected_assessment_digest, expected_generation, observations)
    with closing(execution.store._journal._connect()) as connection:
        connection.execute("BEGIN")
        return _replay(execution.store, connection, parent_id, proposed_by, actor, expected_request_digest,
            expected_receipt_event_id, expected_assessment_digest, expected_generation, observations,
            authenticated_producer_id, recovery_approval)


def recover_transfer(execution, parent_id, *, proposer, principal, expected_request_digest,
                     expected_receipt_event_id, expected_assessment_digest, expected_generation,
                     observations, authenticated_producer_id, capabilities, capabilities_observed_at_ns,
                     recovery_approval=None, resolve_proposer=None):
    store, policy = execution.store, execution.store.installation.policy
    proposed_by, actor, observations = _check_request(store, proposer, principal, expected_request_digest,
        expected_receipt_event_id, expected_assessment_digest, expected_generation, observations)
    with closing(store._journal._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        child = _replay(store, connection, parent_id, proposed_by, actor, expected_request_digest,
            expected_receipt_event_id, expected_assessment_digest, expected_generation, observations,
            authenticated_producer_id, recovery_approval)
        if child is not None:
            return child
        parent, grant, latest, assessment, context = _parent(execution, connection, parent_id)
        evidence = json.loads(evidence_document(context, observations))
        request = _request(parent_id, proposed_by, actor, expected_request_digest, expected_receipt_event_id,
            expected_assessment_digest, expected_generation, authenticated_producer_id, evidence, recovery_approval)
        request_digest = _digest(request)
        if (grant.request_digest != expected_request_digest
                or latest["receipt"]["journal_event_id"] != expected_receipt_event_id
                or (None if assessment is None else _digest(assessment)) != expected_assessment_digest):
            raise MissionConflict("recovery targets a different original effect or assessment")
        control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
        if (control is None or not control["dispatch_enabled"] or control["generation"] != expected_generation
                or parent["dispatch_generation"] != expected_generation
                or parent["authority_epoch"] != control["authority_epoch"]
                or not execution._owns_claims(connection, parent, phases={"HELD", "UNKNOWN"})):
            raise MissionConflict("recovery requires the current fence and every original claim")
        now_ns = store._now_ns()
        store._check_capabilities(capabilities, capabilities_observed_at_ns, now_ns)
        validate_transfer_observations(policy, context, observations, now_ns=now_ns,
                                       authenticated_producer_id=authenticated_producer_id)
        _newer_observations(connection, parent_id, observations, grant, policy)
        if recovery_approval is not None:
            from .physical_transfer_recovery_requests import validate_approval
            validate_approval(store, connection, parent_id, recovery_approval, proposed_by=proposed_by,
                evidence=evidence, producer=authenticated_producer_id, resolve_proposer=resolve_proposer)
        child = store._create(connection, principal=proposer, request_key="recovery-" + uuid4().hex,
                              request=PhysicalTransferRequest.model_validate(parent["request"]))
        connection.execute("UPDATE fleet_cell_jobs SET status='HOLD',reason=COALESCE(reason,?),updated_at=? "
            "WHERE mission_id=?", ("PHYSICAL_RECOVERY_CHILD_CREATED",
                datetime.fromtimestamp(now_ns / 1e9, timezone.utc).isoformat(), parent_id))
        if release(connection, owner_kind="mission", owner_id=parent_id,
                   generation=expected_generation) != len(policy.resources):
            raise MissionConflict("recovery did not release exactly the original claim set")
        child = store._admit(connection, child["mission_id"], principal=principal,
            expected_proposal_digest=child["proposal_digest"], expected_generation=expected_generation,
            capabilities=capabilities, capabilities_observed_at_ns=capabilities_observed_at_ns)
        final_ns = store._now_ns()
        if final_ns < now_ns:
            raise MissionConflict("recovery clock moved backwards")
        store._check_capabilities(capabilities, capabilities_observed_at_ns, final_ns)
        validate_transfer_observations(policy, context, observations, now_ns=final_ns,
                                       authenticated_producer_id=authenticated_producer_id)
        detail = dict(schema="rosy.transfer-recovery/1", root_mission_id=parent_id,
            child_mission_id=child["mission_id"], **request, recovery_request_digest=request_digest,
            evidence_digest=_digest(evidence), source_receipt_digest=_digest(latest["receipt"]),
            validated_at_ns=final_ns)
        store._journal._event(connection, parent_id, None, CREATED, actor,
                             {**detail, "event_id": "physical-transfer-recovery"})
        store._journal._event(connection, child["mission_id"], None, ORIGIN, actor,
                             {**detail, "event_id": "physical-transfer-recovery-origin"})
        connection.commit()
        return child
