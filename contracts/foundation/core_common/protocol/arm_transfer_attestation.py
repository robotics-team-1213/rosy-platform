"""D-977 5: a named field operator's statement about an ARM_TRANSFER job; Fleet record only, never a goal proof."""
from typing import Literal

from pydantic import Field

from .arm_transfer import ArmActionId
from .arm_transfer_observations import _Closed, _Counter
from .arm_transfer_preflight import ArmDigest, ArmPhysicalRef

#: SOURCE_CLEAR: the object is at `source` and the arm zone is empty (before dispatch).
#: TARGET_PLACED: the object is at `target` (after dispatch). Neither makes GOAL_CONFIRMED.
OperatorAttestationKind = Literal["SOURCE_CLEAR", "TARGET_PLACED"]
OPERATOR_ATTESTATION_VALIDITY_NS = 45_000_000_000  # D-977 5: a human-speed window that stays below 60 s


class ArmTransferOperatorAttestationCreate(_Closed):
    kind: OperatorAttestationKind
    expected_request_digest: ArmDigest
    expected_proposal_digest: ArmDigest


class ArmTransferOperatorAttestation(_Closed):
    mission_id: ArmActionId
    kind: OperatorAttestationKind
    evidence_source: Literal["operator_attested"]
    attested_by: ArmPhysicalRef = Field(max_length=96)
    proposed_by: ArmPhysicalRef = Field(max_length=96)
    approved_by: ArmPhysicalRef = Field(max_length=96)
    request_digest: ArmDigest
    proposal_digest: ArmDigest
    job_status: Literal["READY", "ACTION_SUCCEEDED"]
    attested_at_ns: _Counter
    expires_at_ns: _Counter
    goal_confirmed: Literal[False]


class ArmTransferOperatorAttestationResponse(_Closed):
    attestation: ArmTransferOperatorAttestation
