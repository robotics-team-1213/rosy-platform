"""Immutable plan shape shared by process compilers and site execution (ROS-free, no Fleet import)."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from .invocation import SkillInvocation, _identifier

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class _CompiledJobLike(Protocol):
    recipe_hash: str
    cell_hash: str


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
