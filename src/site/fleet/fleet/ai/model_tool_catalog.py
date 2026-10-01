"""Closed Fleet tool catalog and provider-schema projection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any


class ToolEffectClass(str, Enum):
    READ_ONLY = "read_only"
    CANDIDATE_WRITING = "candidate_writing"


@dataclass(frozen=True)
class ModelToolDefinition:
    name: str
    description: str
    effect_class: ToolEffectClass
    feedback_enabled: bool
    _parameters_json: str
    device_action_api: bool = False

    @property
    def parameters(self) -> dict[str, Any]:
        """Return a fresh provider-neutral JSON schema projection."""
        return json.loads(self._parameters_json)

    def provider_schema(self) -> dict[str, Any]:
        return {
            "type": "function", "name": self.name,
            "description": self.description, "parameters": self.parameters,
        }


_EMPTY_OBJECT = json.dumps({
    "type": "object", "properties": {}, "additionalProperties": False,
}, separators=(",", ":"))
_REPLAN_ARGUMENTS = json.dumps({
    "type": "object",
    "properties": {
        "based_on_event_id": {"type": "integer", "minimum": 0},
        "rationale": {"type": "string", "maxLength": 512},
    },
    "required": ["based_on_event_id", "rationale"],
    "additionalProperties": False,
}, separators=(",", ":"))
_PICK_PLACE_ARGUMENTS = json.dumps({
    "type": "object",
    "properties": {
        "target": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "point_yx_1000": {"type": "array", "items": {"type": "integer"},
                                  "minItems": 2, "maxItems": 2},
                "box_yxyx_1000": {"type": "array", "items": {"type": "integer"},
                                  "minItems": 4, "maxItems": 4},
            },
            "required": ["label"], "additionalProperties": False,
        },
        "destination": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "point_yx_1000": {"type": "array", "items": {"type": "integer"},
                                  "minItems": 2, "maxItems": 2},
                "box_yxyx_1000": {"type": "array", "items": {"type": "integer"},
                                  "minItems": 4, "maxItems": 4},
            },
            "required": ["label"], "additionalProperties": False,
        },
    },
    "required": ["target", "destination"], "additionalProperties": False,
}, separators=(",", ":"))

MODEL_TOOL_CATALOG = MappingProxyType({
    "get_mission_status": ModelToolDefinition(
        name="get_mission_status",
        description=("Read current Fleet evidence and bounded manipulation phase progress "
                     "for the already scoped Mission. This tool cannot issue device commands."),
        effect_class=ToolEffectClass.READ_ONLY, feedback_enabled=True,
        _parameters_json=_EMPTY_OBJECT,
    ),
    "propose_replan": ModelToolDefinition(
        name="propose_replan",
        description="Submit a non-executable replan candidate for Fleet review.",
        effect_class=ToolEffectClass.CANDIDATE_WRITING, feedback_enabled=True,
        _parameters_json=_REPLAN_ARGUMENTS,
    ),
    "propose_pick_place": ModelToolDefinition(
        name="propose_pick_place",
        description=("Propose one pick-and-place target selection for Fleet review. This "
                     "function does not move a robot. Select one point or box in the supplied "
                     "image for each item."),
        effect_class=ToolEffectClass.CANDIDATE_WRITING, feedback_enabled=False,
        _parameters_json=_PICK_PLACE_ARGUMENTS,
    ),
})


def provider_tool_schemas(*, feedback_only: bool = True) -> list[dict[str, Any]]:
    """Project only the selected turn's catalog entries as fresh JSON objects."""
    return [
        definition.provider_schema()
        for definition in MODEL_TOOL_CATALOG.values()
        if not feedback_only or definition.feedback_enabled
    ]


__all__ = [
    "MODEL_TOOL_CATALOG", "ModelToolDefinition", "ToolEffectClass",
    "provider_tool_schemas",
]
