import asyncio
import json

import httpx

from fleet.ai.er2_standard import (
    GeminiER2StandardAdapter,
    ImageObservation,
)
from fleet.ai.candidate import ImageTransform
from test_mission_api import _candidate, _client


_OPERATOR = {"Authorization": "Bearer operator-secret"}


def _provider_response():
    return {
        "id": "interaction-fixture-1",
        "outputs": [{
            "type": "function_call",
            "id": "provider-call-fixture-1",
            "name": "propose_pick_place",
            "arguments": {
                "target": {
                    "label": "red block", "point_yx_1000": [575, 664],
                },
                "destination": {
                    "label": "green tray", "point_yx_1000": [475, 305],
                },
            },
        }],
    }


def test_er2_and_operator_candidates_share_proposal_api_without_dispatch(
    tmp_path,
):
    requests = []

    async def provider_handler(request):
        requests.append(request)
        return httpx.Response(200, json=_provider_response())

    async def generate_candidate():
        async with GeminiER2StandardAdapter(
            api_key="test-secret",
            transport=httpx.MockTransport(provider_handler),
        ) as adapter:
            return await adapter.propose_pick_place(
                request_id="task-9-fixture",
                instruction="Move the red block to the green tray.",
                observation=ImageObservation(
                    observation_id="observation-fixture-1",
                    camera_id="camera-overhead-1",
                    frame_id="camera_optical_frame",
                    observed_at="2026-09-29T12:00:00Z",
                    image_bytes=b"fixture-image",
                    image_transform=ImageTransform.identity(
                        source_width=640, source_height=480,
                    ),
                    calibration_revision="cal-4",
                    transform_revision="tf-9",
                ),
            )

    client, _, _ = _client(tmp_path)
    model_candidate = asyncio.run(generate_candidate())
    model_proposal = client.post(
        "/api/fleet/proposals",
        headers=_OPERATOR,
        json={
            "request_key": model_candidate.request_key,
            "workcell_id": "omx_01",
            "instance_id": "omx_01_control",
            "candidate": model_candidate.to_candidate_record(),
        },
    )
    operator_proposal = client.post(
        "/api/fleet/proposals",
        headers=_OPERATOR,
        json={
            "request_key": "operator-fixture-request",
            "workcell_id": "omx_01",
            "instance_id": "omx_01_control",
            "candidate": _candidate(),
        },
    )

    assert len(requests) == 1
    assert requests[0].headers["x-goog-api-key"] == "test-secret"
    assert (
        model_proposal.status_code == operator_proposal.status_code == 200
    ), (
        model_proposal.text, operator_proposal.text,
    )
    assert model_proposal.json()["proposal"]["state"] == "PROPOSED"
    assert operator_proposal.json()["proposal"]["state"] == "PROPOSED"
    assert model_proposal.json()["physical_submission"] == "NOT_CONNECTED"
    saved = model_proposal.json()["proposal"]["candidate"]
    assert saved["provider_call_id"] == "provider-call-fixture-1"
    assert (saved["source_observation"]["image_sha256"]
            == model_candidate.source_image_sha256)
    assert "action_id" not in saved
    proposal_id = model_proposal.json()["proposal"]["proposal_id"]
    assert client.app.state.mission_service.get(proposal_id) is None
    assert client.app.state.mission_dispatcher is None


def test_provider_tool_declaration_is_proposal_only_and_not_a_public_route(
    tmp_path,
):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=_provider_response())

    async def scenario():
        async with GeminiER2StandardAdapter(
            api_key="test-secret", transport=httpx.MockTransport(handler),
        ) as adapter:
            return await adapter.propose_pick_place(
                request_id="proposal-only-fixture",
                instruction="Move the red block.",
                observation=ImageObservation(
                    observation_id="observation-2", camera_id="camera-1",
                    frame_id="camera_optical_frame",
                    observed_at="2026-09-29T12:00:00Z", image_bytes=b"image",
                    image_transform=ImageTransform.identity(
                        source_width=640, source_height=480,
                    ),
                    calibration_revision="cal-4", transform_revision="tf-9",
                ),
            )

    candidate = asyncio.run(scenario())
    client, _, _ = _client(tmp_path)
    spec = client.app.openapi()
    provider_request = json.loads(requests[0].read())
    tool_names = [tool["name"] for tool in provider_request["tools"]]

    assert candidate.provider_call_id == "provider-call-fixture-1"
    assert tool_names == ["propose_pick_place"]
    assert provider_request["store"] is False
    assert not any("/er2" in path for path in spec["paths"])
    assert "/api/fleet/proposals" in spec["paths"]
