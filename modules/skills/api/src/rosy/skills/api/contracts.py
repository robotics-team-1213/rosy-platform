"""Versioned Skill metadata; ``SkillInvocation`` lives in ``rosy.contracts.skill`` (D-427 2a)."""

from __future__ import annotations

from dataclasses import dataclass

from rosy.contracts.skill import SkillInvocation


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")


def _unique_identifiers(values: tuple[str, ...], field: str, *, allow_empty: bool = False) -> None:
    if not isinstance(values, tuple) or (not values and not allow_empty):
        raise ValueError(f"{field} must be a tuple with at least one value")
    for value in values:
        _identifier(value, field)
    if len(values) != len(set(values)):
        raise ValueError(f"{field} values must be unique")


@dataclass(frozen=True)
class SkillContract:
    skill_id: str
    version: str
    input_schema_id: str
    preconditions: tuple[str, ...]
    completion_conditions: tuple[str, ...]
    resources: tuple[str, ...]
    cancellation_contract: str
    result_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("skill_id", "version", "input_schema_id", "cancellation_contract"):
            _identifier(getattr(self, name), name)
        _unique_identifiers(self.preconditions, "preconditions")
        _unique_identifiers(self.completion_conditions, "completion_conditions")
        _unique_identifiers(self.resources, "resources", allow_empty=True)
        _unique_identifiers(self.result_evidence, "result_evidence", allow_empty=True)

    def validate_invocation(self, invocation: SkillInvocation) -> None:
        if (invocation.skill_id, invocation.version) != (self.skill_id, self.version):
            raise ValueError("SkillInvocation ID/version does not match the SkillContract")
