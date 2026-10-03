"""Immutable Skill invocation with JSON-only inputs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty trimmed string")


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
