"""Exact persisted closure proof for a scoped read; no new execution authority."""
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from .arm_transfer import ArmActionId, ArmJournalId
from .arm_transfer_preflight import ArmPhysicalRef
from .arm_transfer_observations import (
    ArmTransferObservation, ArmTransferPhysicalReceipt, _Closed, _Counter, _sequence,
)


class ArmTransferEvidenceOwner(_Closed):
    workcell_id: ArmPhysicalRef
    instance_id: ArmPhysicalRef
    journal_id: ArmJournalId
    owner_session_id: ArmPhysicalRef


class ArmTransferEvidenceContext(_Closed):
    action_id: ArmActionId
    attempt_id: ArmActionId
    phase: Literal["POST_ACTION"]
    not_before_ns: _Counter
    owners: Annotated[tuple[ArmTransferEvidenceOwner, ...], BeforeValidator(_sequence), Field(min_length=1, max_length=32)]


class ArmTransferEvidenceDocument(_Closed):
    context: ArmTransferEvidenceContext
    samples: Annotated[tuple[ArmTransferObservation, ArmTransferObservation], BeforeValidator(_sequence)]


class ArmTransferPhysicalEvidenceResponse(_Closed):
    receipt: ArmTransferPhysicalReceipt
    evidence_document: Annotated[str, Field(min_length=1, max_length=8_388_608)]
    released_zone_ids: Annotated[tuple[ArmPhysicalRef, ...], BeforeValidator(_sequence), Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _proof_binding(self):
        receipt = self.receipt
        if sha256(self.evidence_document.encode()).hexdigest() != receipt.evidence_digest:
            raise ValueError("physical evidence bytes must match the original receipt digest")
        proof = ArmTransferEvidenceDocument.model_validate_json(self.evidence_document)
        context = proof.context
        targets = {(p.workcell_id, p.instance_id): (p.journal_id, p.owner_session_id) for p in context.owners}
        if (len(targets) != len(context.owners) or len(set(self.released_zone_ids)) != len(self.released_zone_ids)
                or (context.action_id, context.attempt_id) != (receipt.action_id, receipt.attempt_id)):
            raise ValueError("physical evidence requires the original attempt and unique scopes")
        for sample in proof.samples:
            if ((sample.action_id, sample.attempt_id, sample.policy_digest, sample.object_ref)
                    != (receipt.action_id, receipt.attempt_id, receipt.policy_digest, receipt.object_ref)
                    or {(p.workcell_id, p.instance_id) for p in sample.owners} != set(targets)
                    or any(p.joints is None or (p.journal_id, p.owner_session_id)
                           != targets[p.workcell_id, p.instance_id] for p in sample.owners)):
                raise ValueError("physical evidence requires complete original measured joint samples")
        return self
