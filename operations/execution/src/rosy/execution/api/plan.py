"""Immutable plan shape and structural views over the existing D-18 records."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from rosy.contracts.skill import AttemptIdentity, ReceiptBinding, SkillInvocation

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _GrantLike(Protocol):
    mission_id: str
    step_id: str
    action_id: str
    attempt_id: str
    workcell_id: str
    instance_id: str
    request_digest: str
    authority_epoch: int
    dispatch_generation: int
    action_kind: str
    capability_revision: str
    config_revision: str
    observation_revision: str


class _CompiledJobLike(Protocol):
    recipe_hash: str
    cell_hash: str


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")


def _revision(value: str, field: str) -> None:
    _identifier(value, field)


@dataclass(frozen=True)
class PlanStep:
    ordinal: int
    invocation: SkillInvocation

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        if not isinstance(self.invocation, SkillInvocation):
            raise ValueError("invocation must be a SkillInvocation")


@dataclass(frozen=True)
class PlanBundle:
    process_artifact_digest: str
    recipe_digest: str
    cell_digest: str
    steps: tuple[PlanStep, ...]
    verification_refs: tuple[str, ...] = ()
    schema_version: str = "rosy.plan.v1"

    @classmethod
    def from_job(cls, job: _CompiledJobLike, *, process_artifact_digest: str, recipe_digest: str,
                 cell_digest: str, steps: tuple[PlanStep, ...],
                 verification_refs: tuple[str, ...] = ()) -> PlanBundle:
        """Bind a compiled Job to its source revisions; this does not grant execution."""
        if job.recipe_hash != recipe_digest or job.cell_hash != cell_digest:
            raise ValueError("Job recipe/cell digest does not match the supplied source revisions")
        return cls(
            process_artifact_digest=process_artifact_digest,
            recipe_digest=recipe_digest,
            cell_digest=cell_digest,
            steps=steps,
            verification_refs=verification_refs,
        )

    def __post_init__(self) -> None:
        if self.schema_version != "rosy.plan.v1":
            raise ValueError("unsupported PlanBundle schema_version")
        for name in ("process_artifact_digest", "recipe_digest", "cell_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("steps must be a non-empty tuple")
        if any(not isinstance(step, PlanStep) for step in self.steps):
            raise ValueError("steps must contain PlanStep values")
        if tuple(step.ordinal for step in self.steps) != tuple(range(len(self.steps))):
            raise ValueError("PlanStep ordinals must be contiguous and ordered")
        if not isinstance(self.verification_refs, tuple):
            raise ValueError("verification_refs must be a tuple")
        for reference in self.verification_refs:
            _identifier(reference, "verification reference")


@dataclass(frozen=True)
class GrantBinding:
    identity: AttemptIdentity
    action_kind: str
    capability_revision: str
    config_revision: str
    observation_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, AttemptIdentity):
            raise ValueError("identity must be an AttemptIdentity")
        if self.action_kind != "PICK_PLACE":
            raise ValueError("this mapping supports only the existing PICK_PLACE wire kind")
        for name in ("capability_revision", "config_revision", "observation_revision"):
            _revision(getattr(self, name), name)

    @classmethod
    def from_wire(cls, grant: _GrantLike) -> GrantBinding:
        """Copy identity and revisions only; does not authenticate or authorize a grant."""
        identity = AttemptIdentity(
            mission_id=grant.mission_id,
            step_id=grant.step_id,
            action_id=grant.action_id,
            attempt_id=grant.attempt_id,
            workcell_id=grant.workcell_id,
            instance_id=grant.instance_id,
            request_digest=grant.request_digest,
            authority_epoch=grant.authority_epoch,
            dispatch_generation=grant.dispatch_generation,
        )
        return cls(
            identity=identity,
            action_kind=grant.action_kind,
            capability_revision=grant.capability_revision,
            config_revision=grant.config_revision,
            observation_revision=grant.observation_revision,
        )
