"""Authenticated recovery intent and independent observations in the existing journal."""
from contextlib import closing
import json
import re
from uuid import uuid4

from pydantic import TypeAdapter

from core_common.protocol.arm_transfer_jobs import ArmTransferRequestKey
from core_common.protocol.arm_transfer_observations import ArmTransferObservation
from .mission_store import MissionConflict
from .physical_transfer_evidence import PhysicalEvidenceRejected, validate_transfer_observations
from .physical_transfer_io import physical_io
from .physical_transfer_observations import evidence_document, world_observations
from .physical_transfer_recovery import (
    _digest, _job, _lineage_record, _newer_observations, _parent,
)
from .physical_transfer_store import _principal
from .site_auth import SitePrincipal

REQUESTED = "PHYSICAL_TRANSFER_RECOVERY_REQUESTED"
OBSERVED = "PHYSICAL_TRANSFER_RECOVERY_OBSERVED"


def _events(connection, parent_id, kind):
    rows = connection.execute("SELECT actor_id,detail_json FROM fleet_cell_events "
        "WHERE mission_id=? AND event_type=? ORDER BY event_id", (parent_id, kind)).fetchall()
    return [(row["actor_id"], json.loads(row["detail_json"])) for row in rows]


def _intent(connection, parent_id, request_id=None, *, latest=False):
    rows = _events(connection, parent_id, REQUESTED)
    selected = [(actor, item) for actor, item in rows if request_id is None or item["request_id"] == request_id]
    if not selected:
        raise KeyError(request_id or parent_id)
    actor, item = selected[-1]
    if (item["schema"] != "rosy.transfer-recovery-request/1"
            or len(selected) != 1 and request_id is not None or actor != item["proposed_by"]
            or item["parent_mission_id"] != parent_id
            or _digest({k: v for k, v in item.items() if k != "proposal_digest"}) != item["proposal_digest"]
            or _digest(item["source"]) != item["context_digest"]
            or item["authority"]["principal_id"] != actor):
        raise MissionConflict("recovery request integrity changed")
    if latest and item["request_id"] != rows[-1][1]["request_id"]:
        raise MissionConflict("recovery request was superseded")
    return item


def _proof(connection, parent_id, intent, digest=None):
    rows = [(actor, item) for actor, item in _events(connection, parent_id, OBSERVED)
            if item["request_id"] == intent["request_id"]]
    if digest is not None:
        rows = [(actor, item) for actor, item in rows if item["evidence_digest"] == digest]
    if not rows:
        return None
    actor, item = rows[-1]
    if (actor != item["producer_id"] or item["proposal_digest"] != intent["proposal_digest"]
            or _digest(item["evidence"]) != item["evidence_digest"]):
        raise MissionConflict("recovery observations changed")
    return item


def _source(execution, connection, parent_id):
    job, grant, receipt, assessment, context = _parent(execution, connection, parent_id)
    source = dict(expected_request_digest=grant.request_digest,
        expected_receipt_event_id=receipt["receipt"]["journal_event_id"],
        expected_assessment_digest=None if assessment is None else _digest(assessment),
        expected_generation=job["dispatch_generation"], context=context.model_dump(mode="json"),
        execution_authorized=False)
    return source, job, grant, context


def _samples(proof):
    return world_observations(tuple(ArmTransferObservation.model_validate(item)
                                    for item in proof["evidence"]["samples"]))


def _authority(principal):
    return {name: getattr(principal, name) for name in
        ("principal_id", "role", "password_change_required", "account_id", "grants", "site_resource")}


def _proposer(intent):
    data = dict(intent["authority"])
    data["grants"] = tuple((scope, tuple(caps)) for scope, caps in data["grants"])
    return SitePrincipal(**data)


def _request_view(intent):
    return {key: intent[key] for key in
        ("request_id", "request_key", "proposal_digest", "context_digest", "proposed_by", "requested_at_ns")}


def _validate(execution, connection, parent_id, intent, observations, producer):
    source, job, grant, context = _source(execution, connection, parent_id)
    if _digest(source) != intent["context_digest"]:
        raise MissionConflict("original effect or dispatch binding changed")
    control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
    if (control is None or not control["dispatch_enabled"]
            or control["generation"] != source["expected_generation"]
            or control["authority_epoch"] != job["authority_epoch"]):
        raise MissionConflict("recovery requires the current active dispatch fence")
    validate_transfer_observations(execution.store.installation.policy, context, observations,
        now_ns=execution.store._now_ns(), authenticated_producer_id=producer)
    if min(observations[0].sample_times_ns) <= intent["requested_at_ns"]:
        raise MissionConflict("recovery observations must follow their authenticated request")
    _newer_observations(connection, parent_id, observations, grant, execution.store.installation.policy)
    return json.loads(evidence_document(context, observations))


def validate_approval(store, connection, parent_id, binding, *, proposed_by, evidence,
                      producer, resolve_proposer=None, historical=False):
    required = {"request_id", "expected_proposal_digest", "expected_evidence_digest", "expected_generation"}
    if not isinstance(binding, dict) or set(binding) != required:
        raise MissionConflict("exact recovery request approval is required")
    if (type(binding["expected_generation"]) is not int
            or not 0 <= binding["expected_generation"] < 2**63
            or any(not isinstance(binding[k], str) or not re.fullmatch(r"[0-9a-f]{64}", binding[k])
                   for k in ("expected_proposal_digest", "expected_evidence_digest"))):
        raise MissionConflict("invalid recovery request approval binding")
    intent = _intent(connection, parent_id, binding["request_id"], latest=not historical)
    proof = _proof(connection, parent_id, intent,
                   binding["expected_evidence_digest"] if historical else None)
    if (intent["proposed_by"] != proposed_by or intent["proposal_digest"] != binding["expected_proposal_digest"]
            or intent["source"]["expected_generation"] != binding["expected_generation"]
            or proof is None or proof["evidence_digest"] != binding["expected_evidence_digest"]
            or proof["producer_id"] != producer or proof["evidence"] != evidence):
        raise MissionConflict("recovery approval targets a different request or evidence")
    if not historical:
        current = resolve_proposer(connection, proposed_by) if callable(resolve_proposer) else None
        if _principal(current, propose=True) != proposed_by:
            raise PermissionError("the original proposer is no longer authorized")


class RecoveryRequestService:
    def __init__(self, dispatcher, *, resolve_proposer):
        self.dispatcher, self.execution = dispatcher, dispatcher.execution
        self.store, self.resolve_proposer = self.execution.store, resolve_proposer

    def _visible(self, parent_id, principal):
        if self.store.get(parent_id, principal=principal) is None:
            raise KeyError(parent_id)

    def preview(self, parent_id, principal):
        self._visible(parent_id, principal)
        actor = _principal(principal)
        with closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN")
            view = dict(parent_mission_id=parent_id, recovery_limit=1, child_mission_id=None,
                status="UNAVAILABLE", context_digest=None, request_id=None, proposal_digest=None,
                evidence_digest=None, proposed_by=None, expected_generation=None,
                can_request=False, can_approve=False, reason=None, execution_authorized=False)
            lineage = _lineage_record(self.store, connection, parent_id)
            if lineage is not None:
                return {**view, "status": "RECOVERED", "child_mission_id": lineage["child_mission_id"]}
            try:
                source, job, _, _ = _source(self.execution, connection, parent_id)
            except MissionConflict:
                return {**view, "reason": "RECOVERY_NOT_ADMISSIBLE"}
            view.update(status="AVAILABLE", context_digest=_digest(source),
                expected_generation=source["expected_generation"],
                can_request=actor == job["proposal_principal_id"] and principal.role in {"operator", "service"})
            try:
                intent = _intent(connection, parent_id)
            except KeyError:
                return view
            view.update(request_id=intent["request_id"], proposal_digest=intent["proposal_digest"],
                        proposed_by=intent["proposed_by"], status="WAITING_OBSERVATIONS")
            proof = _proof(connection, parent_id, intent)
            if proof is None:
                return view
            view["evidence_digest"] = proof["evidence_digest"]
            try:
                _validate(self.execution, connection, parent_id, intent, _samples(proof), proof["producer_id"])
                current = self.resolve_proposer(connection, intent["proposed_by"])
                _principal(current, propose=True)
            except (MissionConflict, PhysicalEvidenceRejected, PermissionError):
                return {**view, "status": "EXPIRED", "reason": "RECOVERY_EVIDENCE_OR_AUTHORITY_CHANGED"}
            view.update(status="READY_FOR_APPROVAL", can_approve=actor != intent["proposed_by"]
                        and principal.role == "operator" and principal.permits_site("fleet.operate", {"operator"}))
            return view

    def request(self, parent_id, *, principal, request_key, expected_context_digest):
        actor = _principal(principal, propose=True)
        request_key = TypeAdapter(ArmTransferRequestKey).validate_python(request_key, strict=True)
        with physical_io(self.store._journal.path), closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            parent = _job(self.store, connection, parent_id)
            if parent["proposal_principal_id"] != actor:
                raise PermissionError("only the original proposer may request recovery")
            for _, item in _events(connection, parent_id, REQUESTED):
                if item["request_key"] == request_key:
                    intent = _intent(connection, parent_id, item["request_id"])
                    if intent["context_digest"] != expected_context_digest:
                        raise MissionConflict("recovery request key changed")
                    return _request_view(intent)
            source, _, _, _ = _source(self.execution, connection, parent_id)
            if _digest(source) != expected_context_digest:
                raise MissionConflict("recovery context changed")
            request_id = "recovery-request-" + uuid4().hex
            intent = dict(schema="rosy.transfer-recovery-request/1", event_id=request_id,
                request_id=request_id, request_key=request_key, parent_mission_id=parent_id,
                proposed_by=actor, authority=_authority(principal), source=source,
                context_digest=expected_context_digest, requested_at_ns=self.store._now_ns())
            intent["proposal_digest"] = _digest(intent)
            self.store._journal._event(connection, parent_id, None, REQUESTED, actor, intent)
            connection.commit()
            return _request_view(intent)

    def context(self, parent_id, request_id):
        with closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN")
            intent = _intent(connection, parent_id, request_id, latest=True)
            source, _, _, _ = _source(self.execution, connection, parent_id)
            if _digest(source) != intent["context_digest"]:
                raise MissionConflict("recovery context changed")
            policy = self.store.installation.policy
            return dict(mission_id=parent_id, request_id=request_id, proposal_digest=intent["proposal_digest"],
                purpose="RECOVERY_RESET", execution_authorized=False,
                context={**source["context"], "not_before_ns": max(source["context"]["not_before_ns"],
                                                                          intent["requested_at_ns"])},
                producer_id=policy.producer_id, evaluator_revision=policy.evaluator_revision,
                frame_id=policy.frame_id, policy_digest=policy.digest, catalog_digest=policy.catalog_digest,
                bindings_digest=policy.bindings_digest, object_ref=policy.object_ref,
                object_origin_id=policy.object_origin_id, min_separation_ns=policy.min_separation_ns,
                max_age_ns=policy.max_age_ns)

    def observe(self, parent_id, request_id, *, expected_proposal_digest, observations, authenticated_producer_id):
        with physical_io(self.store._journal.path), closing(self.store._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            intent = _intent(connection, parent_id, request_id, latest=True)
            if intent["proposal_digest"] != expected_proposal_digest:
                raise MissionConflict("observer targets another recovery request")
            if authenticated_producer_id != self.store.installation.policy.producer_id:
                raise PermissionError("only the configured independent producer may attest recovery")
            evidence = json.loads(evidence_document(self._context_model(intent), observations))
            previous = _proof(connection, parent_id, intent)
            if previous is not None and previous["evidence_digest"] == _digest(evidence):
                return dict(evidence_digest=previous["evidence_digest"])
            evidence = _validate(self.execution, connection, parent_id, intent, observations, authenticated_producer_id)
            if previous is not None:
                old = _samples(previous)
                if (observations[0].sequence <= old[-1].sequence
                        or {s.evidence_id for s in observations} & {s.evidence_id for s in old}):
                    raise MissionConflict("replacement recovery evidence must be new")
            proof = dict(event_id=request_id + ":" + _digest(evidence), request_id=request_id,
                proposal_digest=intent["proposal_digest"], producer_id=authenticated_producer_id,
                evidence=evidence, evidence_digest=_digest(evidence), validated_at_ns=self.store._now_ns())
            self.store._journal._event(connection, parent_id, None, OBSERVED, authenticated_producer_id, proof)
            connection.commit()
            return dict(evidence_digest=proof["evidence_digest"])

    @staticmethod
    def _context_model(intent):
        from .physical_transfer_evidence import TransferEvidenceContext
        return TransferEvidenceContext.model_validate_json(json.dumps(intent["source"]["context"]))

    def approve(self, parent_id, request_id, *, principal, expected_proposal_digest,
                expected_evidence_digest, expected_generation):
        actor = _principal(principal, operator=True)
        self._visible(parent_id, principal)
        with physical_io(self.store._journal.path):
            with closing(self.store._journal._connect()) as connection:
                connection.execute("BEGIN")
                intent = _intent(connection, parent_id, request_id)
                if actor == intent["proposed_by"]:
                    raise PermissionError("the proposer cannot approve its recovery")
                proof = _proof(connection, parent_id, intent, expected_evidence_digest)
                if (proof is None or intent["proposal_digest"] != expected_proposal_digest
                        or intent["source"]["expected_generation"] != expected_generation):
                    raise MissionConflict("approval targets different recovery evidence")
            source = intent["source"]
            binding = dict(request_id=request_id, expected_proposal_digest=expected_proposal_digest,
                expected_evidence_digest=expected_evidence_digest, expected_generation=expected_generation)
            try:
                return self.dispatcher.recover(parent_id, proposer=_proposer(intent), principal=principal,
                    **{k: source[k] for k in ("expected_request_digest", "expected_receipt_event_id",
                        "expected_assessment_digest", "expected_generation")}, observations=_samples(proof),
                    authenticated_producer_id=proof["producer_id"], recovery_approval=binding,
                    resolve_proposer=self.resolve_proposer)
            except PhysicalEvidenceRejected as exc:
                raise MissionConflict(str(exc)) from exc
