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
