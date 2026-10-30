"""D-930 recheck of a confirmed attempt: fresh measured facts only; no execution, claim or completion authority."""
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from .arm_transfer import ArmActionId
from .arm_transfer_evidence import ArmTransferEvidenceOwner
from .arm_transfer_jobs import ArmTransferRequestKey
from .arm_transfer_observations import ArmTransferObservation, _Closed, _Counter, _sequence
from .arm_transfer_preflight import ArmDigest, ArmPhysicalRef


class ArmTransferRecheckCreate(_Closed):
    recheck_key: ArmTransferRequestKey


class ArmTransferRecheckContext(_Closed):
    action_id: ArmActionId
    attempt_id: ArmActionId
    phase: Literal["RECHECK"]
    not_before_ns: _Counter
    owners: Annotated[tuple[ArmTransferEvidenceOwner, ...], BeforeValidator(_sequence), Field(min_length=1, max_length=32)]


class ArmTransferRecheckDocument(_Closed):
    context: ArmTransferRecheckContext
    samples: Annotated[tuple[ArmTransferObservation, ArmTransferObservation], BeforeValidator(_sequence)]


class ArmTransferRecheck(_Closed):
    mission_id: ArmActionId
    recheck_key: ArmTransferRequestKey
    action_id: ArmActionId
    attempt_id: ArmActionId
    requested_at_ns: _Counter
    status: Literal["WAITING_OBSERVATIONS", "CONFIRMED"]
    evidence_document: Annotated[str, Field(min_length=1, max_length=8_388_608)] | None
    evidence_digest: ArmDigest | None
    validated_at_ns: _Counter | None
    zone_ids: Annotated[tuple[ArmPhysicalRef, ...], BeforeValidator(_sequence), Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _proof(self):
        proof = (self.evidence_document, self.evidence_digest, self.validated_at_ns)
        if self.status == "WAITING_OBSERVATIONS":
            if proof != (None, None, None):
                raise ValueError("a waiting recheck carries no proof")
            return self
        if None in proof or sha256(self.evidence_document.encode()).hexdigest() != self.evidence_digest:
            raise ValueError("a confirmed recheck carries its exact proof bytes")
        document = ArmTransferRecheckDocument.model_validate_json(self.evidence_document)
        context = document.context
        if ((context.action_id, context.attempt_id) != (self.action_id, self.attempt_id)
                or context.not_before_ns < self.requested_at_ns
                or any(owner.joints is None for sample in document.samples for owner in sample.owners)):
            raise ValueError("a recheck proof binds the original attempt with measured joints after the request")
        return self


class ArmTransferRecheckResponse(_Closed):
    recheck: ArmTransferRecheck
