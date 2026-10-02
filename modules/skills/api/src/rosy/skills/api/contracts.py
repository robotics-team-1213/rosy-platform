"""Versioned Skill metadata and immutable JSON inputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any


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


def _freeze_json(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} must contain only finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            _identifier(key, f"{field} key")
            frozen[key] = _freeze_json(item, field)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, field) for item in value)
    raise ValueError(f"{field} must contain JSON-compatible values")


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


@dataclass(frozen=True)
class SkillInvocation:
    skill_id: str
    version: str
    inputs: Mapping[str, Any]

    def __post_init__(self) -> None:
        _identifier(self.skill_id, "skill_id")
        _identifier(self.version, "version")
        if not isinstance(self.inputs, Mapping):
            raise ValueError("inputs must be a JSON object")
        frozen = _freeze_json(self.inputs, "inputs")
        object.__setattr__(self, "inputs", frozen)
