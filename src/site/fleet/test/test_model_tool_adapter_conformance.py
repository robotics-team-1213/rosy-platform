from __future__ import annotations

import asyncio

import pytest

from core_common.protocol.schemas import ER2_TOOL_ARGUMENT_MAX_BYTES
from fleet.ai.model_tool_catalog import MODEL_TOOL_CATALOG, ToolEffectClass, provider_tool_schemas
from fleet.ai.model_tool_contract import ModelToolCall, ModelToolResult
from test_er2_tool_dispatch import _dispatcher, _running_mission, _scope


class InteractionsFixtureAdapter:
    """Test-only projection of Interactions function_call/function_result steps."""

    def decode(self, envelope, *, turn_id, ordinal):
        assert envelope["type"] == "function_call"
        return ModelToolCall(
            provider_call_id=envelope["id"], tool_name=envelope["name"],
            arguments=envelope["arguments"], turn_id=turn_id, ordinal=ordinal,
        )

    def encode(self, call, result):
        return {
            "type": "function_result", "call_id": call.provider_call_id,
            "name": call.tool_name, "result": result.to_provider_payload(),
        }


class LiveApiFixtureAdapter:
    """Test-only projection of a Live API functionCalls/functionResponses frame."""

    def decode(self, envelope, *, turn_id, ordinal):
        calls = envelope["toolCall"]["functionCalls"]
        assert len(calls) == 1
        native = calls[0]
        return ModelToolCall(
            provider_call_id=native["id"], tool_name=native["name"],
            arguments=native["args"], turn_id=turn_id, ordinal=ordinal,
        )

    def encode(self, call, result):
        return {
            "toolResponse": {"functionResponses": [{
                "id": call.provider_call_id, "name": call.tool_name,
                "response": result.to_provider_payload(),
            }]},
        }


def _native_call(profile, *, call_id, name, arguments):
    if profile == "interactions":
        return {"type": "function_call", "id": call_id,
                "name": name, "arguments": arguments}
    return {"toolCall": {"functionCalls": [{
        "id": call_id, "name": name, "args": arguments,
    }]}}


def _fixture_adapter(profile):
    return InteractionsFixtureAdapter() if profile == "interactions" else LiveApiFixtureAdapter()


def _live_schema(schema):
    """Project JSON Schema primitive names to Live API declaration spelling."""
    if isinstance(schema, dict):
        return {
            key: (value.upper() if key == "type" and isinstance(value, str)
                  else _live_schema(value))
            for key, value in schema.items() if key != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_live_schema(value) for value in schema]
    return schema


def _native_tool_declarations(profile):
    declarations = provider_tool_schemas()
    if profile == "interactions":
        return declarations
    return [{"function_declarations": [{
        "name": schema["name"], "description": schema["description"],
        "parameters": _live_schema(schema["parameters"]),
    } for schema in declarations]}]


def _turn(client, scope):
    mission = client.app.state.mission_service.get(scope.mission_id)
    client.app.state.mission_service.record_action_result(
        scope.mission_id, event_id="adapter-conformance-terminal",
        action_id=mission["action_id"], attempt_id=mission["attempt_id"],
        outcome="SUCCEEDED", result={"fixture": True},
    )
    scope = _scope(client, scope.mission_id)
    store = client.app.state.mission_model_turn_store
    turn = store.enqueue(scope=scope, trigger_event_id=scope.event_watermark)["turn"]
    assert store.claim(turn["turn_id"], worker_id="adapter-conformance")
    assert store.begin_submission_fenced(
        turn["turn_id"], worker_id="adapter-conformance",
    )["state"] == "SUBMITTING"
    return scope, turn


@pytest.mark.parametrize("profile", ["interactions", "live"])
def test_native_provider_calls_converge_on_fleet_read_and_candidate_contract(profile, tmp_path):
    client, mission_id = _running_mission(tmp_path)
    scope, turn = _turn(client, _scope(client, mission_id))
    adapter = _fixture_adapter(profile)
    dispatcher = _dispatcher(client)
    native_calls = [
        ("get_mission_status", {}, "read-call"),
        ("propose_replan", {
            "based_on_event_id": scope.event_watermark,
            "rationale": "The goal still needs review.",
        }, "candidate-call"),
    ]
    encoded_results = []

    for ordinal, (name, arguments, call_id) in enumerate(native_calls):
        call = adapter.decode(
            _native_call(profile, call_id=call_id, name=name, arguments=arguments),
            turn_id=turn["turn_id"], ordinal=ordinal,
        )
        assert call.turn_id == turn["turn_id"]
        assert call.ordinal == ordinal
        if name == "propose_replan":
            result = asyncio.run(dispatcher.dispatch_replan(
                scope=scope, turn_id=call.turn_id, call_id=call.provider_call_id,
                arguments=call.arguments, candidate_adapter=None, egress_policy=None,
                model_tool_call=call,
            ))
        else:
            result = dispatcher.dispatch(
                scope=scope, call_id=call.provider_call_id,
                tool_name=call.tool_name, arguments=call.arguments,
                model_tool_call=call,
            )
        canonical_result = ModelToolResult.from_effect_result(call, result)
        encoded_results.append(adapter.encode(call, canonical_result))

    assert [entry["result"]["status"] if profile == "interactions"
            else entry["toolResponse"]["functionResponses"][0]["response"]["status"]
            for entry in encoded_results] == ["accepted", "rejected"]
    candidate_response = (encoded_results[1]["result"] if profile == "interactions"
                          else encoded_results[1]["toolResponse"]["functionResponses"][0]["response"])
    assert candidate_response["reason_code"] == "REPLAN_NOT_ALLOWED"
    assert client.app.state.mission_service.get(mission_id)["status"] == "ACTION_SUCCEEDED"
    assert MODEL_TOOL_CATALOG["propose_replan"].effect_class.value == "candidate_writing"
    assert MODEL_TOOL_CATALOG["propose_replan"].device_action_api is False


#: D-429 §3 / D-392 §4: direct site-device actuation names (signal, door, conveyor,
#: PLC, generic). Examples of a regression boundary; the closed catalog rejects any
#: other name too.
SITE_DEVICE_ACTUATION_NAMES = [
    "set_signal", "set_signal_mode", "set_signal_phase", "signal_command", "signal_all_red",
    "post_signal_command",
    "open_door", "close_door", "set_door_state",
    "start_conveyor", "stop_conveyor", "set_conveyor_speed",
    "write_plc_output", "write_coil", "write_register",
    "set_site_device_state", "site_device_command",
]


@pytest.mark.parametrize("profile", ["interactions", "live"])
@pytest.mark.parametrize("name", [
    "move", "set_gripper_state", "execute_action", "cancel_action", "stop",
    "emergency_stop", "rearm", "post_actions_execute",
    *SITE_DEVICE_ACTUATION_NAMES,
])
def test_sample_actuation_and_openapi_operations_stay_outside_catalog(profile, name, tmp_path):
    client, mission_id = _running_mission(tmp_path)
    scope, turn = _turn(client, _scope(client, mission_id))
    adapter = _fixture_adapter(profile)
    arguments = {"x": 1, "y": 2, "high": True}
    call = adapter.decode(
        _native_call(profile, call_id="untrusted-tool-call", name=name,
                     arguments=arguments),
        turn_id=turn["turn_id"], ordinal=0,
    )

    result = _dispatcher(client).dispatch(
        scope=scope, call_id=call.provider_call_id, tool_name=call.tool_name,
        arguments=call.arguments, model_tool_call=call,
    )

    assert result.status == "rejected"
    assert result.reason_code == "TOOL_NOT_ALLOWED"
    assert name not in MODEL_TOOL_CATALOG
    assert all(not definition.device_action_api
               for definition in MODEL_TOOL_CATALOG.values())


_ACTUATION_VERBS = ("set_", "start_", "stop_", "open_", "close_", "write_", "post_", "toggle_")
_SITE_DEVICE_WORDS = ("signal", "door", "conveyor", "plc", "coil", "register", "site_device")


def _actuates_site_device(name: str) -> bool:
    """A verb-led or ``*_command`` name about a site device; read-only names pass."""
    about_device = any(word in name for word in _SITE_DEVICE_WORDS)
    return about_device and (name.startswith(_ACTUATION_VERBS) or name.endswith(("_command", "_all_red")))


def test_catalog_has_no_site_device_tool_or_effect_class():
    """D-429 §3: until the follow-up candidate ADR lands, no catalog tool and no
    effect class may actuate a site device; candidates are the only future path.
    Read-only names such as ``get_signal_state`` stay possible."""
    assert {member.value for member in ToolEffectClass} == {"read_only", "candidate_writing"}
    assert all(_actuates_site_device(name) for name in SITE_DEVICE_ACTUATION_NAMES)
    assert not any(map(_actuates_site_device, ("get_signal_state", "registered_robots", "list_doors")))
    assert [name for name in MODEL_TOOL_CATALOG if _actuates_site_device(name)] == []
    assert not set(SITE_DEVICE_ACTUATION_NAMES) & set(MODEL_TOOL_CATALOG)
    assert all(definition.effect_class in (ToolEffectClass.READ_ONLY, ToolEffectClass.CANDIDATE_WRITING)
               for definition in MODEL_TOOL_CATALOG.values())


@pytest.mark.parametrize("profile", ["interactions", "live"])
def test_idempotency_and_stopped_generation_fences_are_provider_independent(profile, tmp_path):
    client, mission_id = _running_mission(tmp_path)
    scope, turn = _turn(client, _scope(client, mission_id))
    adapter = _fixture_adapter(profile)
    dispatcher = _dispatcher(client)
    arguments = {"based_on_event_id": scope.event_watermark,
                 "rationale": "The goal still needs review."}
    native = _native_call(profile, call_id="replay-call", name="propose_replan",
                          arguments=arguments)
    call = adapter.decode(native, turn_id=turn["turn_id"], ordinal=0)

    first = asyncio.run(dispatcher.dispatch_replan(
        scope=scope, turn_id=call.turn_id, call_id=call.provider_call_id,
        arguments=call.arguments, candidate_adapter=None, egress_policy=None,
        model_tool_call=call,
    ))
    replay = asyncio.run(dispatcher.dispatch_replan(
        scope=scope, turn_id=call.turn_id, call_id=call.provider_call_id,
        arguments=call.arguments, candidate_adapter=None, egress_policy=None,
        model_tool_call=call,
    ))
    assert replay.model_dump(mode="json") == first.model_dump(mode="json")

    changed = adapter.decode(
        _native_call(profile, call_id="replay-call", name="propose_replan",
                     arguments={**arguments, "rationale": "changed"}),
        turn_id=turn["turn_id"], ordinal=0,
    )
    collision = asyncio.run(dispatcher.dispatch_replan(
        scope=scope, turn_id=changed.turn_id, call_id=changed.provider_call_id,
        arguments=changed.arguments, candidate_adapter=None, egress_policy=None,
        model_tool_call=changed,
    ))
    assert collision.reason_code == "PROVIDER_CALL_ID_REUSE"

    client.app.state.task_service.store.trip_stop_latch(
        actor_id="operator-1", reason="CONFORMANCE_STOP_FENCE",
    )
    stopped = dispatcher.dispatch(
        scope=scope, call_id="stopped-status", tool_name="get_mission_status",
        arguments={},
    )
    assert stopped.status == "accepted"  # Read remains available; no Action is issued.
    assert client.app.state.task_service.store.dispatch_control()["dispatch_enabled"] is False
    replan_scope = scope.model_copy(update={"outcome_policy": "STATUS_AND_REPLAN"})
    stop_fenced_candidate = dispatcher.dispatch(
        scope=replan_scope, call_id="stopped-candidate", tool_name="propose_replan",
        arguments={"based_on_event_id": scope.event_watermark,
                   "rationale": "Check the candidate against the stop fence."},
    )
    # The stop generation invalidates this turn before candidate admission.
    assert stop_fenced_candidate.reason_code == "TURN_SCOPE_FORBIDDEN"


@pytest.mark.parametrize(("profile", "structured_output", "code_execution"), [
    ("interactions", True, True),
    ("live", False, False),
])
def test_endpoint_capability_profiles_keep_same_closed_function_catalog(
        profile, structured_output, code_execution):
    # Mirrors the audited ER 2 endpoint split: Interactions supports these
    # extras; Live supports streaming function calls without those features.
    endpoint_capabilities = {
        "function_calling": True,
        "structured_output": structured_output,
        "code_execution": code_execution,
    }
    assert endpoint_capabilities["function_calling"] is True
    if profile == "interactions":
        declarations = _native_tool_declarations(profile)
        names = {schema["name"] for schema in declarations}
    else:
        wrappers = _native_tool_declarations(profile)
        assert len(wrappers) == 1
        declarations = wrappers[0]["function_declarations"]
        names = {schema["name"] for schema in declarations}
        assert declarations[1]["parameters"]["type"] == "OBJECT"
    assert names == {"get_mission_status", "propose_replan"}
    assert endpoint_capabilities["structured_output"] is structured_output
    assert endpoint_capabilities["code_execution"] is code_execution
    assert profile in {"interactions", "live"}


def test_provider_text_or_sample_success_payload_is_not_physical_completion():
    assert "success" not in ModelToolResult.model_fields
    assert "physical_completion" not in ModelToolResult.model_fields
    assert "stop" not in MODEL_TOOL_CATALOG
    assert "move" not in MODEL_TOOL_CATALOG


@pytest.mark.parametrize("profile", ["interactions", "live"])
def test_provider_formats_share_canonical_argument_byte_limit(profile):
    adapter = _fixture_adapter(profile)
    arguments = {"rationale": "x" * ER2_TOOL_ARGUMENT_MAX_BYTES,
                 "based_on_event_id": 1}
    with pytest.raises(ValueError, match="arguments exceeds"):
        adapter.decode(
            _native_call(profile, call_id="oversized-call", name="propose_replan",
                         arguments=arguments),
            turn_id="turn-size-limit", ordinal=0,
        )
