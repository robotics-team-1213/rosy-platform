"""ROS-free pallet.transfer policy over injected planning and owner ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import Protocol

from rosy.skills.api import SkillContract, SkillInvocation

SKILL_ID = "pallet.transfer"
SKILL_VERSION = "1.0.0"
COMPLETION_CONDITIONS = frozenset({
    "transfer_phases_succeeded",
    "gripper_release_verified",
    "destination_pose_verified",
})

TRANSFER_SKILL_CONTRACT = SkillContract(
    skill_id=SKILL_ID,
    version=SKILL_VERSION,
    input_schema_id="rosy.skill.pallet-transfer/1",
    preconditions=(
        "fleet_grant_validated_by_execution_owner",
        "workcell_and_cell_revision_current",
        "required_resources_owned",
        "fresh_start_state_within_plan_tolerance",
    ),
    completion_conditions=tuple(sorted(COMPLETION_CONDITIONS)),
    resources=("arm", "gripper"),
    cancellation_contract=(
        "cancel_exact_active_phase_goal; unresolved_outcome_is_HOLD"
    ),
    result_evidence=tuple(sorted(COMPLETION_CONDITIONS)),
)

_INPUTS = frozenset({
    "item", "pallet_id", "layer_index", "home_pose_base", "source_pose_base",
    "destination_pose_base", "source_approach_z_base_m",
    "destination_approach_z_base_m", "carry_z_base_m",
})
_POSE_FIELDS = frozenset({"x_m", "y_m", "z_m", "yaw_rad"})


def _finite(value: object, field: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _identifier(value: object, field: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > 192 or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{field} must be a non-empty trimmed identifier")
    return value


def _pose(value: object, field: str) -> None:
    if not isinstance(value, Mapping) or set(value) != _POSE_FIELDS:
        raise ValueError(f"{field} must contain x_m, y_m, z_m and yaw_rad")
    for name in _POSE_FIELDS:
        _finite(value[name], f"{field}.{name}")


def _validate_inputs(inputs: Mapping[str, object]) -> None:
    if set(inputs) != _INPUTS:
        raise ValueError(
            "pallet.transfer inputs do not match the versioned Skill contract",
        )
    if inputs["item"] not in {"box", "slip_sheet"}:
        raise ValueError("item must be box or slip_sheet")
    _identifier(inputs["pallet_id"], "pallet_id")
    layer = inputs["layer_index"]
    if isinstance(layer, bool) or not isinstance(layer, int) or layer < 0:
        raise ValueError("layer_index must be a non-negative integer")
    _pose(inputs["home_pose_base"], "home_pose_base")
    source = inputs["source_pose_base"]
    destination = inputs["destination_pose_base"]
    _pose(source, "source_pose_base")
    _pose(destination, "destination_pose_base")
    source_approach = _finite(
        inputs["source_approach_z_base_m"], "source_approach_z_base_m",
    )
    destination_approach = _finite(
        inputs["destination_approach_z_base_m"],
        "destination_approach_z_base_m",
    )
    carry = _finite(inputs["carry_z_base_m"], "carry_z_base_m")
    if (source_approach < source["z_m"]
            or destination_approach < destination["z_m"]
            or carry < max(source_approach, destination_approach)):
        raise ValueError("carry height must cover both target approaches")


class TransferPlanner(Protocol):
    """A product integration plans from a validated, immutable invocation."""

    def plan(self, invocation: SkillInvocation) -> object: ...


class TransferPhaseExecutor(Protocol):
    """Start the validated plan under its existing local Action."""

    def start(self, planned: PlannedTransfer) -> object: ...


class TransferEvidencePort(Protocol):
    """Independent evidence source; a journal receipt alone is insufficient."""

    def verify(self, invocation: SkillInvocation, planned: PlannedTransfer,
               receipt: object) -> EvidenceVerdict: ...


@dataclass(frozen=True)
class PlannedTransfer:
    invocation: SkillInvocation
    plan: object

    def __post_init__(self) -> None:
        if not isinstance(self.invocation, SkillInvocation):
            raise ValueError("invocation must be a SkillInvocation")
        if self.plan is None:
            raise ValueError("planner must return a plan")


@dataclass(frozen=True)
class EvidenceVerdict:
    state: str
    conditions: frozenset[str]
    references: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.state not in {"VERIFIED", "HOLD", "UNKNOWN"}:
            raise ValueError(
                "evidence state must be VERIFIED, HOLD or UNKNOWN",
            )
        if not isinstance(self.conditions, frozenset):
            raise ValueError("conditions must be a frozenset")
        if any(not isinstance(value, str) or not value.strip()
               for value in self.conditions):
            raise ValueError("evidence conditions must be non-empty strings")
        if not isinstance(self.references, tuple):
            raise ValueError("references must be a tuple")
        if any(not isinstance(value, str) or not value
               or value != value.strip() for value in self.references):
            raise ValueError(
                "evidence references must be non-empty trimmed strings",
            )
        if len(self.references) != len(set(self.references)):
            raise ValueError("evidence references must be unique")


@dataclass(frozen=True)
class TransferCompletion:
    state: str
    evidence_references: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in {"SUCCEEDED", "HOLD", "UNKNOWN"}:
            raise ValueError("transfer completion state is invalid")
        if not isinstance(self.evidence_references, tuple):
            raise ValueError("evidence_references must be a tuple")
        if self.state == "SUCCEEDED" and not self.evidence_references:
            raise ValueError(
                "success requires independent evidence references",
            )
        if (self.reason is not None
                and (not self.reason or self.reason != self.reason.strip())):
            raise ValueError("reason must be non-empty trimmed text")


class TransferSkill:
    """Validate inputs, delegate motion, and gate completion on evidence.

    The Skill does not authenticate grants, write journals, call ROS, or choose
    a device owner. The injected phase executor is constructed only after the
    local execution boundary has accepted the existing Action and attempt.
    """

    contract = TRANSFER_SKILL_CONTRACT

    def plan(self, invocation: SkillInvocation,
             planner: TransferPlanner) -> PlannedTransfer:
        self.contract.validate_invocation(invocation)
        _validate_inputs(invocation.inputs)
        plan = getattr(planner, "plan", None)
        if not callable(plan):
            raise ValueError("a transfer planner port is required")
        planned = plan(invocation)
        return PlannedTransfer(invocation, planned)

    def start(self, planned: PlannedTransfer,
              executor: TransferPhaseExecutor) -> object:
        if not isinstance(planned, PlannedTransfer):
            raise ValueError("a PlannedTransfer is required")
        start = getattr(executor, "start", None)
        if not callable(start):
            raise ValueError("a phase execution port is required")
        return start(planned)

    def verify_completion(self, invocation: SkillInvocation,
                          planned: PlannedTransfer,
                          receipt: object, evidence: TransferEvidencePort, *,
                          action_state: str) -> TransferCompletion:
        self.contract.validate_invocation(invocation)
        if planned.invocation != invocation:
            raise ValueError("planned transfer does not match the invocation")
        if action_state == "UNKNOWN":
            return TransferCompletion(
                "UNKNOWN", reason="ACTION_OUTCOME_UNKNOWN",
            )
        if action_state != "SUCCEEDED":
            return TransferCompletion("HOLD", reason="ACTION_NOT_SUCCEEDED")
        verify = getattr(evidence, "verify", None)
        if not callable(verify):
            raise ValueError(
                "an independent transfer evidence port is required",
            )
        verdict = verify(invocation, planned, receipt)
        if not isinstance(verdict, EvidenceVerdict):
            raise ValueError("evidence port returned an unsupported verdict")
        if verdict.state == "UNKNOWN":
            return TransferCompletion(
                "UNKNOWN", reason="COMPLETION_EVIDENCE_UNKNOWN",
            )
        if verdict.state != "VERIFIED":
            return TransferCompletion(
                "HOLD", reason="COMPLETION_EVIDENCE_HOLD",
            )
        if (not COMPLETION_CONDITIONS <= verdict.conditions
                or not verdict.references):
            return TransferCompletion(
                "HOLD", reason="COMPLETION_EVIDENCE_INCOMPLETE",
            )
        return TransferCompletion("SUCCEEDED", verdict.references)
