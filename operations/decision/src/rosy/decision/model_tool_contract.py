"""Provider-neutral, Fleet-internal model tool call and result messages."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core_common.protocol.schemas import (
    ER2_MAX_FUNCTION_CALLS_PER_TURN,
    ER2_TOOL_ARGUMENT_MAX_BYTES,
    ER2_TOOL_RESULT_MAX_BYTES,
)


_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_REASON_CODE = re.compile(r"^[A-Z0-9_]{1,64}$")


def _is_json_value(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(type(key) is str and _is_json_value(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    return False


def _canonical_json_object(value: Any, *, limit: int, field_name: str) -> str:
    if not isinstance(value, Mapping) or not _is_json_value(value):
        raise ValueError(f"{field_name} must be a finite JSON object with string keys")
    try:
        encoded = json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite JSON") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError(f"{field_name} exceeds its {limit}-byte limit")
    return encoded


def _decode_canonical_object(encoded: str, *, limit: int, field_name: str) -> str:
    if not isinstance(encoded, str):
        raise ValueError(f"{field_name} must be JSON text")
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be valid JSON") from exc
    return _canonical_json_object(value, limit=limit, field_name=field_name)


def _validate_identifier(value: str, *, field_name: str, limit: int) -> str:
    if (not value.strip() or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{field_name} must be non-empty, trimmed, and contain no controls")
    if len(value) > limit:
        raise ValueError(f"{field_name} exceeds its {limit}-character limit")
    return value


class ModelToolCall(BaseModel):
    """Immutable snapshot of one provider call bound to a trusted Fleet turn.

    Arguments are kept as canonical JSON text internally. The ``arguments``
    property returns a fresh object so callers cannot mutate the recorded call.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_call_id: str = Field(strict=True, min_length=1, max_length=128)
    tool_name: str = Field(strict=True, min_length=1, max_length=64)
    arguments_json: str = Field(exclude=True, repr=False)
    turn_id: str = Field(strict=True, min_length=1, max_length=96)
    ordinal: int = Field(strict=True, ge=0, lt=ER2_MAX_FUNCTION_CALLS_PER_TURN)

    @model_validator(mode="before")
    @classmethod
    def _capture_arguments(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        fields = dict(value)
        has_arguments = "arguments" in fields
        has_encoded_arguments = "arguments_json" in fields
        if has_arguments == has_encoded_arguments:
            raise ValueError("provide exactly one arguments object")
        if has_arguments:
            fields["arguments_json"] = _canonical_json_object(
                fields.pop("arguments"), limit=ER2_TOOL_ARGUMENT_MAX_BYTES,
                field_name="arguments",
            )
        return fields

    @field_validator("arguments_json")
    @classmethod
    def _validate_arguments_json(cls, value: str) -> str:
        return _decode_canonical_object(
            value, limit=ER2_TOOL_ARGUMENT_MAX_BYTES, field_name="arguments",
        )

    @field_validator("provider_call_id")
    @classmethod
    def _validate_provider_call_id(cls, value: str) -> str:
        return _validate_identifier(value, field_name="provider_call_id", limit=128)

    @field_validator("turn_id")
    @classmethod
    def _validate_turn_id(cls, value: str) -> str:
        return _validate_identifier(value, field_name="turn_id", limit=96)

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        if not _TOOL_NAME.fullmatch(value):
            raise ValueError("tool_name must be a bounded lower snake-case identifier")
        return value

    @property
    def arguments(self) -> dict[str, Any]:
        return json.loads(self.arguments_json)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "provider_call_id": self.provider_call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "turn_id": self.turn_id,
            "ordinal": self.ordinal,
        }


class ModelToolResult(BaseModel):
    """Immutable Fleet result correlated to one model call.

    ``accepted`` means only that the Fleet tool effect was accepted. It is not
    Mission admission, ROS Action acceptance, physical completion, or stop.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(strict=True, min_length=1, max_length=96)
    provider_call_id: str = Field(strict=True, min_length=1, max_length=128)
    tool_name: str = Field(strict=True, min_length=1, max_length=64)
    ordinal: int = Field(strict=True, ge=0, lt=ER2_MAX_FUNCTION_CALLS_PER_TURN)
    outcome: Literal["accepted", "rejected", "unavailable", "unknown"]
    reason_code: str = Field(strict=True, min_length=1, max_length=64)
    event_id: int | None = Field(default=None, strict=True, ge=0)
    proposal_id: str | None = Field(default=None, strict=True, min_length=1, max_length=128)
    payload_json: str = Field(exclude=True, repr=False)

    @model_validator(mode="before")
    @classmethod
    def _capture_payload(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        fields = dict(value)
        has_payload = "payload" in fields
        has_encoded_payload = "payload_json" in fields
        if has_payload == has_encoded_payload:
            raise ValueError("provide exactly one payload object")
        if has_payload:
            fields["payload_json"] = _canonical_json_object(
                fields.pop("payload"), limit=ER2_TOOL_RESULT_MAX_BYTES,
                field_name="payload",
            )
        return fields

    @field_validator("payload_json")
    @classmethod
    def _validate_payload_json(cls, value: str) -> str:
        return _decode_canonical_object(
            value, limit=ER2_TOOL_RESULT_MAX_BYTES, field_name="payload",
        )

    @field_validator("turn_id")
    @classmethod
    def _validate_turn_id(cls, value: str) -> str:
        return _validate_identifier(value, field_name="turn_id", limit=96)

    @field_validator("provider_call_id")
    @classmethod
    def _validate_provider_call_id(cls, value: str) -> str:
        return _validate_identifier(value, field_name="provider_call_id", limit=128)

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        if not _TOOL_NAME.fullmatch(value):
            raise ValueError("tool_name must be a bounded lower snake-case identifier")
        return value

    @field_validator("reason_code")
    @classmethod
    def _validate_reason_code(cls, value: str) -> str:
        if not _REASON_CODE.fullmatch(value):
            raise ValueError("reason_code must contain uppercase letters, digits, or underscores")
        return value

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    @classmethod
    def for_call(cls, call: ModelToolCall, *, outcome: str, reason_code: str,
                 payload: Mapping[str, Any], event_id: int | None = None,
                 proposal_id: str | None = None) -> "ModelToolResult":
        return cls(
            turn_id=call.turn_id,
            provider_call_id=call.provider_call_id,
            tool_name=call.tool_name,
            ordinal=call.ordinal,
            outcome=outcome,
            reason_code=reason_code,
            event_id=event_id,
            proposal_id=proposal_id,
            payload=payload,
        )

    @classmethod
    def from_effect_result(cls, call: ModelToolCall, effect_result: Any) -> "ModelToolResult":
        result_tool_name = getattr(effect_result, "tool_name", None)
        if not isinstance(result_tool_name, str):
            raise ValueError("effect result has no bounded tool name")
        outcome = getattr(effect_result, "status", None)
        if outcome not in {"accepted", "rejected", "unavailable"}:
            raise ValueError("effect result has no bounded provider outcome")
        return cls(
            turn_id=call.turn_id,
            provider_call_id=call.provider_call_id,
            tool_name=result_tool_name,
            ordinal=call.ordinal,
            outcome=outcome,
            reason_code=effect_result.reason_code,
            event_id=effect_result.event_id,
            proposal_id=effect_result.proposal_id,
            payload=effect_result.payload,
        )

    def to_provider_payload(self) -> dict[str, Any]:
        if self.outcome == "unknown":
            raise ValueError("unknown outcomes cannot be reported as provider completion")
        return {
            "tool_name": self.tool_name,
            "status": self.outcome,
            "reason_code": self.reason_code,
            "event_id": self.event_id,
            "proposal_id": self.proposal_id,
            "payload": self.payload,
        }

    def to_mapping(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "provider_call_id": self.provider_call_id,
            "tool_name": self.tool_name,
            "ordinal": self.ordinal,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "event_id": self.event_id,
            "proposal_id": self.proposal_id,
            "payload": self.payload,
        }


__all__ = ["ModelToolCall", "ModelToolResult"]
