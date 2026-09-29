import asyncio
import base64
import hashlib
import json

import httpx
import pytest

from fleet.ai.er2_standard import (
    ER2ProposalError,
    ER2RequestError,
    GeminiER2StandardAdapter,
    ImageObservation,
)
from fleet.ai.candidate import ImageTransform, SpatialSelector
from core_common.protocol.schemas import ER2ToolResult, MissionFeedbackTurnScope


def _tool_response(*, arguments=None, name="propose_pick_place", call_id="call-1"):
    return {
        "id": "interaction-1",
        "outputs": [{
            "type": "function_call",
            "id": call_id,
            "name": name,
            "arguments": arguments or {
                "target": {"label": "red block", "point_yx_1000": [575, 664]},
                "destination": {"label": "green tray", "box_yxyx_1000": [300, 100, 600, 400]},
            },
        }],
    }


def _observation():
    return ImageObservation(
        observation_id="obs-2026-09-29-001",
        camera_id="omx-overhead-1",
        frame_id="camera_optical_frame",
        observed_at="2026-09-29T12:00:00Z",
        image_bytes=b"test-image-bytes",
        mime_type="image/jpeg",
        image_transform=ImageTransform.identity(source_width=640, source_height=480),
        calibration_revision="cal-4",
        transform_revision="tf-9",
    )


def _feedback_scope_and_context(outcome_policy="STATUS_ONLY"):
    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "event_watermark": 19,
        "model_policy_revision": "policy-v1", "outcome_policy": outcome_policy,
    })
    context = {
        "mission_id": "mission-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "stop_generation": 4, "authority_epoch": 2,
        "snapshot_event_id": 19, "snapshot_at": "2026-09-30T12:00:00Z",
        "policy_revision": "policy-v1", "outcome_policy": outcome_policy,
        "task_summary": "Place the red block in the tray.",
        "mission_source": "fleet_missions", "step_source": "fleet_missions",
        "action_source": "fleet_mission_events", "action_freshness": "FRESH",
        "action_observed_at": "2026-09-30T12:00:00Z",
        "goal_evidence_source": "trusted-test", "goal_evidence_freshness": "FRESH",
        "goal_evidence_observed_at": "2026-09-30T12:00:01Z",
        "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
        "stop_observed_at": "2026-09-30T12:00:00Z",
        "mission_state": "HOLD" if outcome_policy == "STATUS_AND_REPLAN" else "ACTION_SUCCEEDED",
        "step_state": "HOLD" if outcome_policy == "STATUS_AND_REPLAN" else "AWAITING_GOAL_EVIDENCE",
        "action_state": "SUCCEEDED", "action_reason": None,
        "goal_evidence_state": "UNSATISFIED" if outcome_policy == "STATUS_AND_REPLAN" else "PENDING",
        "goal_evidence_reason": "GOAL_NOT_SATISFIED" if outcome_policy == "STATUS_AND_REPLAN" else None,
        "stop_state": "DISPATCH_ENABLED", "stop_reason": None,
    }
    policy = __import__("fleet.ai.er2_standard", fromlist=["ER2FeedbackEgressPolicy"])
    egress = policy.ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress", "mission_instruction"}),
        approved_workcell_ids=frozenset({"omx_01"}),
        approved_task_classes=frozenset({"PICK_PLACE"}), estimated_cost_usd=0.02,
    )
    return scope, context, egress


def test_er2_standard_sends_stateless_multimodal_proposal_request_and_never_executes_tool():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=_tool_response())

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            candidate = await adapter.propose_pick_place(
                request_id="proposal-job-001",
                instruction="Put the red block in the green tray.",
                observation=_observation(),
            )
        return candidate

    candidate = asyncio.run(scenario())

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert request.headers["x-goog-api-key"] == "test-secret"
    body = json.loads(request.content)
    assert body["model"] == "gemini-robotics-er-2-preview"
    assert body["store"] is False
    assert body["input"]["parts"][0]["inlineData"] == {
        "mimeType": "image/jpeg",
        "data": base64.b64encode(b"test-image-bytes").decode("ascii"),
    }
    assert body["tools"][0]["name"] == "propose_pick_place"
    assert "move" not in {tool["name"] for tool in body["tools"]}
    assert candidate.target.point_yx_1000 == (575, 664)
    assert candidate.destination.box_yxyx_1000 == (300, 100, 600, 400)
    assert candidate.source_observation_id == "obs-2026-09-29-001"
    assert candidate.source_image_sha256 == hashlib.sha256(b"test-image-bytes").hexdigest()
    assert candidate.provider_interaction_id == "interaction-1"
    assert candidate.provider_call_id == "call-1"
    assert candidate.request_key == "gemini-er2:proposal-job-001"


@pytest.mark.parametrize("arguments", [
    {"target": {"label": "red block", "point_yx_1000": [1001, 2]},
     "destination": {"label": "green tray", "point_yx_1000": [1, 2]}},
    {"target": {"label": "red block", "point_yx_1000": [True, 2]},
     "destination": {"label": "green tray", "point_yx_1000": [1, 2]}},
    {"target": {"label": "red block", "point_yx_1000": [1, 2], "box_yxyx_1000": [1, 2, 3, 4]},
     "destination": {"label": "green tray", "point_yx_1000": [1, 2]}},
    {"target": {"label": "red block", "box_yxyx_1000": [4, 2, 3, 5]},
     "destination": {"label": "green tray", "point_yx_1000": [1, 2]}},
])
def test_er2_standard_rejects_invalid_spatial_arguments(arguments):
    async def handler(_request):
        return httpx.Response(200, json=_tool_response(arguments=arguments))

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.propose_pick_place(
                request_id="invalid-spatial-case",
                instruction="Move the block.", observation=_observation()
            )

    with pytest.raises(ER2ProposalError):
        asyncio.run(scenario())


def test_er2_standard_rejects_text_only_unknown_and_multiple_tool_calls():
    responses = [
        {"id": "i1", "outputs": [{"type": "text", "text": "Done."}]},
        {
            "id": "i2",
            "outputs": [{"type": "function_call", "id": "c1",
                         "name": "move", "arguments": {}}],
        },
        {"id": "i3", "outputs": _tool_response()["outputs"] * 2},
        {"id": "i4", "outputs": [
            {"type": "text", "text": "I found both objects."},
            *_tool_response()["outputs"],
        ]},
    ]

    async def scenario(payload):
        async def handler(_request):
            return httpx.Response(200, json=payload)
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.propose_pick_place(
                request_id="invalid-output-case",
                instruction="Move the block.", observation=_observation()
            )

    for response in responses:
        with pytest.raises(ER2ProposalError):
            asyncio.run(scenario(response))


def test_er2_standard_rejects_oversized_provider_response():
    payload = _tool_response()
    payload["unrelated_output"] = "x" * (65 * 1024)

    async def handler(_request):
        return httpx.Response(200, json=payload)

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.propose_pick_place(
                request_id="bounded-response", instruction="Pick and place.",
                observation=_observation(),
            )

    with pytest.raises(ER2ProposalError, match="64 KiB"):
        asyncio.run(scenario())


def test_er2_standard_http_error_is_fail_closed_and_does_not_retry():
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.propose_pick_place(
                request_id="rate-limit-case",
                instruction="Move the block.", observation=_observation()
            )

    with pytest.raises(ER2RequestError):
        asyncio.run(scenario())
    assert calls == 1


def test_image_observation_rejects_empty_or_unsupported_media():
    with pytest.raises(ER2ProposalError):
        ImageObservation("obs", "camera", "frame", "now", b"", "image/jpeg")
    with pytest.raises(ER2ProposalError):
        ImageObservation("obs", "camera", "frame", "now", b"frame", "image/gif")
    with pytest.raises(ER2ProposalError, match="14 MiB"):
        ImageObservation("obs", "camera", "frame", "now", b"x" * (14 * 1024 * 1024 + 1))


def test_image_observation_accepts_exact_inline_budget_and_rejects_one_over():
    from core_common.protocol.schemas import ER2_IMAGE_MAX_BYTES

    arguments = {
        "observation_id": "obs-large", "camera_id": "cam-1", "frame_id": "frame-1",
        "observed_at": "2026-09-30T12:00:00Z", "mime_type": "image/jpeg",
        "image_transform": ImageTransform.identity(source_width=1, source_height=1),
        "calibration_revision": "cal-v1", "transform_revision": "transform-v1",
    }
    image = ImageObservation(**arguments, image_bytes=b"x" * ER2_IMAGE_MAX_BYTES)
    assert len(image.image_bytes) == ER2_IMAGE_MAX_BYTES
    with pytest.raises(ER2ProposalError, match="14 MiB"):
        ImageObservation(**arguments, image_bytes=b"x" * (ER2_IMAGE_MAX_BYTES + 1))


def test_image_observation_requires_transform_provenance():
    with pytest.raises(ER2ProposalError, match="image_transform"):
        ImageObservation(
            "obs", "camera", "frame", "now", b"frame",
            calibration_revision="cal-4", transform_revision="tf-9",
        )


def test_image_observation_requires_calibration_and_transform_provenance():
    with pytest.raises(ER2ProposalError, match="calibration_revision"):
        ImageObservation(
            "obs", "camera", "frame", "now", b"frame",
            image_transform=ImageTransform.identity(source_width=640, source_height=480),
            transform_revision="tf-9",
        )
    with pytest.raises(ER2ProposalError, match="transform_revision"):
        ImageObservation(
            "obs", "camera", "frame", "now", b"frame",
            image_transform=ImageTransform.identity(source_width=640, source_height=480),
            calibration_revision="cal-4",
        )


def test_selector_requires_image_space_evidence_and_stable_request_identity():
    with pytest.raises(ER2ProposalError):
        SpatialSelector.from_mapping("target", {"label": "red block"})

    candidate_response = _tool_response()

    async def handler(_request):
        return httpx.Response(200, json=candidate_response)

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.propose_pick_place(
                request_id="stable-job-id",
                instruction="Put the red block in the green tray.",
                observation=_observation(),
            )

    first = asyncio.run(scenario())
    second = asyncio.run(scenario())
    assert first.request_key == second.request_key == "gemini-er2:stable-job-id"
    coordinate_space = first.to_candidate_record()["source_observation"]["coordinate_space"]
    assert coordinate_space == "image_normalized_yx_0_1000"


def test_long_instruction_is_rejected_before_network_request():
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_tool_response())

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.propose_pick_place(
                request_id="too-long-prompt",
                instruction="x" * 2001, observation=_observation()
            )

    with pytest.raises(ValueError, match="2000"):
        asyncio.run(scenario())
    assert calls == 0


def test_feedback_turn_replays_stateless_function_result_and_checks_egress_preflight(tmp_path):
    from fleet.ai.er2_standard import ER2FeedbackEgressPolicy

    requests = []
    returned = [
        {"steps": [{"type": "function_call", "id": "call-1",
                    "name": "get_mission_status", "arguments": {}}]},
        {"steps": [{"type": "text", "text": "The action is still running."}]},
    ]

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=returned.pop(0))

    class Dispatcher:
        def __init__(self):
            self.calls = []

        def dispatch(self, **kwargs):
            self.calls.append(kwargs)
            return ER2ToolResult(tool_name="get_mission_status", status="accepted",
                                 reason_code="STATUS_CURRENT", event_id=19,
                                 payload={"mission_state": "ACTION_SUCCEEDED"})

    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "event_watermark": 19,
        "model_policy_revision": "policy-v1", "outcome_policy": "STATUS_ONLY",
    })
    dispatcher = Dispatcher()
    policy = ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress", "mission_instruction"}),
        approved_workcell_ids=frozenset({"omx_01"}),
        approved_task_classes=frozenset({"PICK_PLACE"}),
        estimated_cost_usd=0.02,
    )

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.reason_about_mission(
                scope=scope,
                context={
                    "mission_id": "mission-1", "workcell_id": "omx_01",
                    "action_id": "action-1", "attempt_id": "attempt-1",
                    "dispatch_generation": 4, "stop_generation": 4,
                    "authority_epoch": 2, "snapshot_event_id": 19,
                    "snapshot_at": "2026-09-30T12:00:00Z",
                    "policy_revision": "policy-v1", "outcome_policy": "STATUS_ONLY",
                    "task_summary": "Place the red block in the tray.",
                    "mission_source": "fleet_missions", "step_source": "fleet_missions",
                    "action_source": "fleet_mission_events", "action_freshness": "FRESH",
                    "action_observed_at": "2026-09-30T12:00:00Z",
                    "goal_evidence_source": "none", "goal_evidence_freshness": "UNKNOWN",
                    "goal_evidence_observed_at": None,
                    "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
                    "stop_observed_at": "2026-09-30T12:00:00Z",
                    "mission_state": "ACTION_SUCCEEDED", "step_state": "AWAITING_GOAL_EVIDENCE",
                    "action_state": "SUCCEEDED", "action_reason": None,
                    "goal_evidence_state": "PENDING", "goal_evidence_reason": None,
                    "stop_state": "DISPATCH_ENABLED", "stop_reason": None,
                },
                dispatcher=dispatcher, egress_policy=policy,
            )

    result = asyncio.run(scenario())
    assert result == "The action is still running."
    assert len(dispatcher.calls) == 1
    assert [request["store"] for request in requests] == [False, False]
    first_input = requests[0]["input"]
    second_input = requests[1]["input"]
    assert first_input[0]["type"] == "user_input"
    assert second_input[0] == first_input[0]
    assert second_input[1]["type"] == "function_call"
    assert second_input[2]["type"] == "function_result"
    assert "previous_interaction_id" not in requests[1]


def test_feedback_adapter_uses_async_candidate_dispatch_with_the_durable_turn_id():
    from fleet.ai.er2_standard import ER2FeedbackEgressPolicy

    requests = []
    returned = [
        {"steps": [{"type": "function_call", "id": "replan-call",
                    "name": "propose_replan", "arguments": {
                        "based_on_event_id": 19,
                        "rationale": "Goal evidence says the object is not in the tray.",
                    }}]},
        {"steps": [{"type": "text", "text": "A successor proposal is ready for review."}]},
    ]

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=returned.pop(0))

    class Dispatcher:
        def __init__(self):
            self.calls = []

        def dispatch(self, **kwargs):
            raise AssertionError(f"replan bypassed async dispatcher: {kwargs}")

        async def dispatch_replan(self, **kwargs):
            self.calls.append(kwargs)
            return ER2ToolResult(
                tool_name="propose_replan", status="accepted",
                reason_code="CANDIDATE_RECORDED", event_id=19,
                proposal_id="proposal-1", payload={"executable": False},
            )

    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "event_watermark": 19,
        "model_policy_revision": "policy-v1", "outcome_policy": "STATUS_AND_REPLAN",
    })
    context = {
        "mission_id": "mission-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "stop_generation": 4, "authority_epoch": 2,
        "snapshot_event_id": 19, "snapshot_at": "2026-09-30T12:00:00Z",
        "policy_revision": "policy-v1", "outcome_policy": "STATUS_AND_REPLAN",
        "task_summary": "Place the red block in the tray.",
        "mission_source": "fleet_missions", "step_source": "fleet_missions",
        "action_source": "fleet_mission_events", "action_freshness": "FRESH",
        "action_observed_at": "2026-09-30T12:00:00Z",
        "goal_evidence_source": "trusted-test", "goal_evidence_freshness": "FRESH",
        "goal_evidence_observed_at": "2026-09-30T12:00:01Z",
        "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
        "stop_observed_at": "2026-09-30T12:00:00Z",
        "mission_state": "HOLD", "step_state": "HOLD", "action_state": "SUCCEEDED",
        "action_reason": None, "goal_evidence_state": "UNSATISFIED",
        "goal_evidence_reason": "GOAL_NOT_SATISFIED",
        "stop_state": "DISPATCH_ENABLED", "stop_reason": None,
    }
    dispatcher = Dispatcher()
    policy = ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress", "mission_instruction"}),
        approved_workcell_ids=frozenset({"omx_01"}),
        approved_task_classes=frozenset({"PICK_PLACE"}), estimated_cost_usd=0.05,
    )

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.reason_about_mission(
                scope=scope, context=context, dispatcher=dispatcher,
                egress_policy=policy, turn_id="turn-abc",
            )

    assert asyncio.run(scenario()) == "A successor proposal is ready for review."
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0]["turn_id"] == "turn-abc"
    assert dispatcher.calls[0]["call_id"] == "replan-call"
    assert dispatcher.calls[0]["candidate_adapter"].__class__ is GeminiER2StandardAdapter
    assert [request["store"] for request in requests] == [False, False]
    replan_tool = next(tool for tool in requests[0]["tools"]
                       if tool.get("name") == "propose_replan")
    assert replan_tool["parameters"]["required"] == ["based_on_event_id", "rationale"]


def test_feedback_turn_without_egress_approval_never_calls_transport():
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"steps": []})

    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "event_watermark": 19,
        "model_policy_revision": "policy-v1", "outcome_policy": "STATUS_ONLY",
    })

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.reason_about_mission(
                scope=scope, context={"mission_id": "mission-1"},
                dispatcher=object(), egress_policy=None,
            )

    with pytest.raises(ER2RequestError, match="egress policy"):
        asyncio.run(scenario())
    assert calls == 0


def test_feedback_turn_cost_above_ceiling_is_rejected_before_transport():
    from fleet.ai.er2_standard import ER2FeedbackEgressPolicy

    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"steps": [{"type": "text", "text": "done"}]})

    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "event_watermark": 19,
        "model_policy_revision": "policy-v1", "outcome_policy": "STATUS_ONLY",
    })
    policy = ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress", "mission_instruction"}),
        approved_workcell_ids=frozenset({"omx_01"}),
        approved_task_classes=frozenset({"PICK_PLACE"}),
        estimated_cost_usd=0.100001,
    )

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.reason_about_mission(
                scope=scope, context={"mission_id": "mission-1"},
                dispatcher=object(), egress_policy=policy,
            )

    with pytest.raises(ER2RequestError, match="cost preflight"):
        asyncio.run(scenario())
    assert calls == 0


def test_feedback_turn_rejects_duplicate_provider_call_ids_without_second_dispatch():
    from fleet.ai.er2_standard import ER2FeedbackEgressPolicy

    requests = 0
    dispatched = []

    async def handler(_request):
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"steps": [{
            "type": "function_call", "id": "same-call", "name": "get_mission_status",
            "arguments": {},
        }]})

    class Dispatcher:
        def dispatch(self, **_kwargs):
            dispatched.append(True)
            return ER2ToolResult(tool_name="get_mission_status", status="accepted",
                                 reason_code="STATUS_CURRENT", event_id=19)

    scope = MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "event_watermark": 19,
        "model_policy_revision": "policy-v1", "outcome_policy": "STATUS_ONLY",
    })
    policy = ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress", "mission_instruction"}),
        approved_workcell_ids=frozenset({"omx_01"}),
        approved_task_classes=frozenset({"PICK_PLACE"}), estimated_cost_usd=0.05,
    )

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.reason_about_mission(
                scope=scope, context={
                    "mission_id": "mission-1", "workcell_id": "omx_01",
                    "action_id": "action-1", "attempt_id": "attempt-1",
                    "dispatch_generation": 4, "stop_generation": 4,
                    "authority_epoch": 2, "snapshot_event_id": 19,
                    "snapshot_at": "2026-09-30T12:00:00Z",
                    "policy_revision": "policy-v1", "outcome_policy": "STATUS_ONLY",
                    "task_summary": "Place the red block in the tray.",
                    "mission_source": "fleet_missions", "step_source": "fleet_missions",
                    "action_source": "fleet_mission_events", "action_freshness": "FRESH",
                    "action_observed_at": "2026-09-30T12:00:00Z",
                    "goal_evidence_source": "none", "goal_evidence_freshness": "UNKNOWN",
                    "goal_evidence_observed_at": None,
                    "stop_source": "fleet_dispatch_control", "stop_freshness": "CURRENT",
                    "stop_observed_at": "2026-09-30T12:00:00Z",
                    "mission_state": "ACTION_SUCCEEDED", "step_state": "AWAITING_GOAL_EVIDENCE",
                    "action_state": "SUCCEEDED", "action_reason": None,
                    "goal_evidence_state": "PENDING", "goal_evidence_reason": None,
                    "stop_state": "DISPATCH_ENABLED", "stop_reason": None,
                },
                dispatcher=Dispatcher(), egress_policy=policy,
            )

    with pytest.raises(ER2ProposalError, match="repeated a function call ID"):
        asyncio.run(scenario())
    assert requests == 2
    assert dispatched == [True]


def test_feedback_deadline_also_bounds_async_tool_dispatch(monkeypatch):
    from fleet.ai import er2_standard

    monkeypatch.setattr(er2_standard, "ER2_PROVIDER_DEADLINE_SECONDS", 0.01, raising=False)
    scope, context, egress = _feedback_scope_and_context("STATUS_AND_REPLAN")
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) > 1:
            return httpx.Response(200, json={"steps": [{"type": "text", "text": "Done."}]})
        return httpx.Response(200, json={"steps": [{
            "type": "function_call", "id": "call-slow", "name": "propose_replan",
            "arguments": {"based_on_event_id": 19, "rationale": "Recheck the tray."},
        }]})

    class SlowDispatcher:
        def dispatch(self, **_kwargs):
            raise AssertionError("replan must use async dispatch")

        async def dispatch_replan(self, **_kwargs):
            await asyncio.sleep(1)
            return ER2ToolResult(
                tool_name="propose_replan", status="unavailable",
                reason_code="REPLAN_OBSERVATION_UNAVAILABLE",
            )

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.reason_about_mission(
                scope=scope, context=context, dispatcher=SlowDispatcher(),
                egress_policy=egress, turn_id="turn-1",
            )

    with pytest.raises(ER2RequestError, match="deadline"):
        asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0]["store"] is False


@pytest.mark.parametrize("call_count,expected_dispatches", [(4, 4), (5, 0)])
def test_feedback_function_call_budget_boundary(call_count, expected_dispatches):
    scope, context, egress = _feedback_scope_and_context()
    dispatches = []
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(dispatches):
            return httpx.Response(200, json={"steps": [{"type": "text", "text": "Done."}]})
        return httpx.Response(200, json={"steps": [
            {"type": "function_call", "id": f"call-{index}",
             "name": "get_mission_status", "arguments": {}}
            for index in range(call_count)
        ]})

    class Dispatcher:
        def dispatch(self, **kwargs):
            dispatches.append(kwargs["call_id"])
            return ER2ToolResult(
                tool_name="get_mission_status", status="accepted",
                reason_code="STATUS_CURRENT", event_id=19,
            )

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.reason_about_mission(
                scope=scope, context=context, dispatcher=Dispatcher(),
                egress_policy=egress,
            )

    if call_count == 4:
        assert asyncio.run(scenario()) == "Done."
    else:
        with pytest.raises(ER2ProposalError, match="tool-call budget"):
            asyncio.run(scenario())
    assert len(dispatches) == expected_dispatches
    if call_count == 4:
        replay = requests[1]["input"]
        assert [step["type"] for step in replay[1:]] == [
            "function_call", "function_call", "function_call", "function_call",
            "function_result", "function_result", "function_result", "function_result",
        ]
        assert [step["call_id"] for step in replay if step["type"] == "function_result"] == [
            "call-0", "call-1", "call-2", "call-3",
        ]


@pytest.mark.parametrize("step,match", [
    ({"type": "function_response", "id": "call-1"}, "unsupported step"),
    ({"type": "function_call", "id": "call-1", "name": "get_mission_status",
      "arguments": []}, "function call is invalid"),
])
def test_feedback_rejects_invalid_provider_steps_before_tool_dispatch(step, match):
    scope, context, egress = _feedback_scope_and_context()
    calls = []

    async def handler(_request):
        return httpx.Response(200, json={"steps": [step]})

    class Dispatcher:
        def dispatch(self, **_kwargs):
            calls.append(True)
            return ER2ToolResult(tool_name="get_mission_status", status="accepted",
                                 reason_code="STATUS_CURRENT", event_id=19)

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            await adapter.reason_about_mission(
                scope=scope, context=context, dispatcher=Dispatcher(),
                egress_policy=egress,
            )

    with pytest.raises(ER2ProposalError, match=match):
        asyncio.run(scenario())
    assert calls == []


@pytest.mark.parametrize("over_by", [0, 1])
def test_feedback_replay_byte_limit_accepts_exact_boundary(over_by):
    from core_common.protocol.schemas import ER2_REPLAY_MAX_BYTES
    from core_common.protocol.schemas import MissionFeedbackContext

    scope, context, egress = _feedback_scope_and_context()
    feedback = MissionFeedbackContext.model_validate(context)
    encoded = json.dumps(
        feedback.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    prompt = (
        "Review the Fleet evidence below. Report only the Fleet-backed "
        "Mission, Action, goal-evidence, and stop states. A provider "
        "response is not proof of physical completion or stop. Use only "
        "the declared Fleet tools.\n\n" + encoded
    )
    first_step = {"type": "user_input", "text": prompt}
    empty_replay = [first_step, {"type": "text", "text": ""}]
    empty_size = len(json.dumps(
        empty_replay, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8"))
    final_text = "x" * (ER2_REPLAY_MAX_BYTES + over_by - empty_size)
    replay_size = len(json.dumps(
        [first_step, {"type": "text", "text": final_text}],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8"))
    assert replay_size == ER2_REPLAY_MAX_BYTES + over_by
    response_body = json.dumps(
        {"steps": [{"type": "text", "text": final_text}]},
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    assert len(response_body) < 64 * 1024

    class Dispatcher:
        def dispatch(self, **_kwargs):
            raise AssertionError("text response must not dispatch a tool")

    async def handler(_request):
        return httpx.Response(200, content=response_body,
                              headers={"Content-Type": "application/json"})

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.reason_about_mission(
                scope=scope, context=context, dispatcher=Dispatcher(),
                egress_policy=egress,
            )

    if over_by == 0:
        assert asyncio.run(scenario()) == "x" * 4000
    else:
        with pytest.raises(ER2ProposalError, match="replay exceeds 64 KiB"):
            asyncio.run(scenario())


@pytest.mark.parametrize("over_by", [0, 1])
def test_feedback_response_byte_limit_accepts_exact_boundary(over_by):
    from core_common.protocol.schemas import ER2_RESPONSE_MAX_BYTES

    response = {"padding": ""}
    empty_size = len(json.dumps(response, separators=(",", ":")).encode("utf-8"))
    response["padding"] = "x" * (ER2_RESPONSE_MAX_BYTES + over_by - empty_size)
    body = json.dumps(response, separators=(",", ":")).encode("utf-8")
    assert len(body) == ER2_RESPONSE_MAX_BYTES + over_by

    async def handler(_request):
        return httpx.Response(200, content=body,
                              headers={"Content-Type": "application/json"})

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter._feedback_post({"store": False})

    if over_by == 0:
        assert len(asyncio.run(scenario())["padding"]) > 60_000
    else:
        with pytest.raises(ER2ProposalError, match="response exceeds the 64 KiB limit"):
            asyncio.run(scenario())


@pytest.mark.parametrize("step_count", [8, 9])
def test_feedback_provider_step_count_boundary(step_count):
    from core_common.protocol.schemas import ER2_REPLAY_MAX_STEPS

    assert step_count in {ER2_REPLAY_MAX_STEPS, ER2_REPLAY_MAX_STEPS + 1}
    scope, context, egress = _feedback_scope_and_context()
    steps = ([{"type": "thought", "text": "considering"}
              for _ in range(step_count - 1)]
             + [{"type": "text", "text": "Reviewed."}])

    async def handler(_request):
        return httpx.Response(200, json={"steps": steps})

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler)
        ) as adapter:
            return await adapter.reason_about_mission(
                scope=scope, context=context,
                dispatcher=type("Dispatcher", (), {"dispatch": lambda self, **_: None})(),
                egress_policy=egress,
            )

    if step_count == ER2_REPLAY_MAX_STEPS:
        assert asyncio.run(scenario()) == "Reviewed."
    else:
        with pytest.raises(ER2ProposalError, match="too many steps"):
            asyncio.run(scenario())


def test_feedback_cost_policy_accepts_exact_ceiling():
    from core_common.protocol.schemas import ER2_MAX_ESTIMATED_TURN_COST_USD
    from fleet.ai.er2_standard import ER2FeedbackEgressPolicy

    scope, _context, _egress = _feedback_scope_and_context()
    policy = ER2FeedbackEgressPolicy(
        approved=True, project_id="approved-project", service_tier="standard",
        approved_data_classes=frozenset({"mission_progress", "mission_instruction"}),
        approved_workcell_ids=frozenset({scope.workcell_id}),
        approved_task_classes=frozenset({"PICK_PLACE"}),
        estimated_cost_usd=ER2_MAX_ESTIMATED_TURN_COST_USD,
    )

    policy.validate_for(scope=scope, task_class="PICK_PLACE")
