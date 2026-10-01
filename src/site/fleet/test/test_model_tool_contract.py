import math

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import (
    ER2_TOOL_ARGUMENT_MAX_BYTES,
    ER2_TOOL_RESULT_MAX_BYTES,
)
from fleet.ai.model_tool_contract import ModelToolCall, ModelToolResult


def _call(**overrides):
    fields = {
        "provider_call_id": "opaque/provider-call-1",
        "tool_name": "get_mission_status",
        "arguments": {},
        "turn_id": "durable-turn-1",
        "ordinal": 0,
    }
    fields.update(overrides)
    return ModelToolCall(**fields)


def test_model_tool_call_is_frozen_and_returns_an_isolated_json_snapshot():
    arguments = {"filters": {"states": ["RUNNING"]}}
    call = _call(arguments=arguments)

    arguments["filters"]["states"].append("FAILED")
    returned = call.arguments
    returned["filters"]["states"].append("UNKNOWN")

    assert call.arguments == {"filters": {"states": ["RUNNING"]}}
    with pytest.raises(ValidationError):
        call.turn_id = "other-turn"


@pytest.mark.parametrize("overrides", [
    {"provider_call_id": ""},
    {"provider_call_id": "call\n1"},
    {"tool_name": "Move"},
    {"tool_name": "move/arm"},
    {"turn_id": " "},
    {"ordinal": -1},
    {"ordinal": True},
    {"arguments": []},
    {"arguments": {1: "non-string-key"}},
    {"arguments": {"value": math.nan}},
    {"arguments": {"value": object()}},
    {"unexpected": "field"},
])
def test_model_tool_call_rejects_invalid_envelopes(overrides):
    with pytest.raises((ValidationError, ValueError)):
        _call(**overrides)


def test_model_tool_call_rejects_arguments_over_the_shared_byte_limit():
    oversized = {"value": "x" * ER2_TOOL_ARGUMENT_MAX_BYTES}

    with pytest.raises((ValidationError, ValueError)):
        _call(arguments=oversized)


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "unavailable", "unknown"])
def test_model_tool_result_correlates_to_call_and_bounds_outcome(outcome):
    call = _call()

    result = ModelToolResult.for_call(
        call, outcome=outcome, reason_code="STATUS_CURRENT",
        payload={"mission_state": "RUNNING"},
    )

    assert (result.turn_id, result.provider_call_id, result.ordinal) == (
        "durable-turn-1", "opaque/provider-call-1", 0,
    )
    assert result.tool_name == "get_mission_status"
    assert result.outcome == outcome
    assert result.payload == {"mission_state": "RUNNING"}
    assert "Fleet tool effect" in ModelToolResult.__doc__
    with pytest.raises(ValidationError):
        result.outcome = "succeeded"


@pytest.mark.parametrize("fields", [
    {"reason_code": "lowercase"},
    {"reason_code": "HAS SPACE"},
    {"reason_code": "X" * 65},
    {"outcome": "succeeded"},
    {"payload": {"bad": math.inf}},
    {"payload": "not-an-object"},
    {"unexpected": "field"},
])
def test_model_tool_result_rejects_invalid_result_fields(fields):
    values = {
        "turn_id": "durable-turn-1",
        "provider_call_id": "opaque/provider-call-1",
        "tool_name": "get_mission_status",
        "ordinal": 0,
        "outcome": "accepted",
        "reason_code": "STATUS_CURRENT",
        "payload": {},
    }
    values.update(fields)

    with pytest.raises((ValidationError, ValueError)):
        ModelToolResult(**values)


def test_model_tool_result_rejects_oversized_payload():
    values = {
        "turn_id": "durable-turn-1",
        "provider_call_id": "opaque/provider-call-1",
        "tool_name": "get_mission_status",
        "ordinal": 0,
        "outcome": "accepted",
        "reason_code": "STATUS_CURRENT",
        "payload": {"value": "x" * ER2_TOOL_RESULT_MAX_BYTES},
    }

    with pytest.raises((ValidationError, ValueError)):
        ModelToolResult(**values)


def test_model_tool_result_provider_projection_preserves_existing_wire_shape():
    call = _call()
    result = ModelToolResult.for_call(
        call, outcome="accepted", reason_code="STATUS_CURRENT",
        event_id=19, payload={"mission_state": "RUNNING"},
    )

    assert result.to_provider_payload() == {
        "tool_name": "get_mission_status",
        "status": "accepted",
        "reason_code": "STATUS_CURRENT",
        "event_id": 19,
        "proposal_id": None,
        "payload": {"mission_state": "RUNNING"},
    }


def test_unknown_result_is_internal_only_and_has_no_provider_success_projection():
    result = ModelToolResult(
        turn_id="durable-turn-1", provider_call_id="call-1",
        tool_name="get_mission_status", ordinal=0,
        outcome="unknown", reason_code="EFFECT_OUTCOME_UNKNOWN", payload={},
    )

    with pytest.raises(ValueError, match="unknown"):
        result.to_provider_payload()
