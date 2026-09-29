import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from core_common.protocol.schemas import MissionFeedbackTurnScope
from core_common.protocol.vision_preview import VisionLeaseSigner
from fleet.ai.vision_observation_source import (
    VisionObservationSourceSpec,
    VisionPostActionObservationSource,
)


def _scope():
    return MissionFeedbackTurnScope.model_validate({
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1",
        "attempt_id": "attempt-1", "dispatch_generation": 4,
        "event_watermark": 19, "model_policy_revision": "policy-v1",
        "outcome_policy": "STATUS_AND_REPLAN",
    })


def _spec():
    return VisionObservationSourceSpec(
        workcell_id="omx_01", source_id="ceiling-north",
        camera_id="top-camera", frame_id="camera_top_optical",
        calibration_revision="cal-4", transform_revision="tf-9",
    )


def _response(*, captured_at="2026-09-30T12:00:02+00:00", seq="52",
              body=b"\xff\xd8bounded-jpeg", updates=None):
    headers = {
        "content-type": "image/jpeg", "cache-control": "no-store",
        "x-frame-seq": seq, "x-frame-age-ms": "20",
        "x-frame-captured-at": str(datetime.fromisoformat(captured_at).timestamp()),
        "x-frame-width": "640", "x-frame-height": "480",
        "x-frame-rotation-deg": "0", "x-frame-rectified": "false",
    }
    headers.update(updates or {})
    return httpx.Response(200, headers=headers, content=body)


def test_reader_uses_scoped_lease_and_returns_fresh_correlated_frame():
    secret = "v" * 32
    signer = VisionLeaseSigner(secret)
    requests = []

    async def handler(request):
        requests.append(request)
        return _response()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = VisionPostActionObservationSource(
                base_url="https://vision.example", lease_signer=signer,
                sources={"omx_01": _spec()}, client=client,
                clock=lambda: datetime(2026, 9, 30, 12, 0, 3, tzinfo=timezone.utc),
            )
            result = await source.capture_after(
                scope=_scope(), based_on_event_id=19,
                after_action_at="2026-09-30T12:00:01+00:00",
            )
        return result

    captured = asyncio.run(run())

    assert len(requests) == 1
    assert requests[0].url.path == "/api/vision/sources/ceiling-north/frame"
    assert requests[0].headers["cache-control"] == "no-cache"
    lease = requests[0].headers["authorization"].removeprefix("Bearer ")
    assert signer.verify(lease, source_id="ceiling-north")["sub"] == "operator-1"
    observation = captured["observation"]
    assert observation.camera_id == "top-camera"
    assert observation.frame_id == "camera_top_optical"
    assert observation.image_bytes == b"\xff\xd8bounded-jpeg"
    assert observation.image_transform.source_width == 640
    assert observation.image_transform.source_height == 480
    assert captured["scope"] == {
        "mission_id": "mission-1", "workcell_id": "omx_01",
        "action_id": "action-1", "attempt_id": "attempt-1",
        "dispatch_generation": 4, "based_on_event_id": 19,
        "observation_id": observation.observation_id,
        "observed_at": observation.observed_at,
        "image_sha256": observation.sha256,
    }


def test_reader_waits_for_a_frame_newer_than_the_terminal_action():
    responses = iter([
        _response(captured_at="2026-09-30T12:00:00+00:00", seq="51"),
        _response(captured_at="2026-09-30T12:00:02+00:00", seq="52"),
    ])
    sleeps = []

    async def handler(_request):
        return next(responses)

    async def no_wait(seconds):
        sleeps.append(seconds)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = VisionPostActionObservationSource(
                base_url="https://vision.example",
                lease_signer=VisionLeaseSigner("v" * 32),
                sources={"omx_01": _spec()}, client=client,
                clock=lambda: datetime(2026, 9, 30, 12, 0, 3, tzinfo=timezone.utc),
                sleep=no_wait,
            )
            return await source.capture_after(
                scope=_scope(), based_on_event_id=19,
                after_action_at="2026-09-30T12:00:01+00:00",
            )

    result = asyncio.run(run())

    assert ":52:" in result["observation"].observation_id
    assert sleeps == [1.05]


@pytest.mark.parametrize("updates", [
    {"cache-control": "public, max-age=60"},
    {"content-type": "application/json"},
    {"x-frame-rectified": "true"},
    {"x-frame-age-ms": "40000"},
    {"x-frame-width": "0"},
    {"x-frame-rotation-deg": "45"},
])
def test_reader_rejects_untrusted_or_unbounded_frame_metadata(updates):
    async def handler(_request):
        return _response(updates=updates)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = VisionPostActionObservationSource(
                base_url="https://vision.example",
                lease_signer=VisionLeaseSigner("v" * 32),
                sources={"omx_01": _spec()}, client=client,
                clock=lambda: datetime(2026, 9, 30, 12, 0, 3, tzinfo=timezone.utc),
            )
            await source.capture_after(
                scope=_scope(), based_on_event_id=19,
                after_action_at="2026-09-30T12:00:01+00:00",
            )

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_reader_fails_closed_for_unknown_workcell_or_insecure_remote_url():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _request: _response())) as client:
            source = VisionPostActionObservationSource(
                base_url="https://vision.example",
                lease_signer=VisionLeaseSigner("v" * 32),
                sources={"other-cell": _spec()}, client=client,
            )
            await source.capture_after(
                scope=_scope(), based_on_event_id=19,
                after_action_at="2026-09-30T12:00:01+00:00",
            )

    with pytest.raises(ValueError):
        asyncio.run(run())
    with pytest.raises(ValueError):
        VisionPostActionObservationSource(
            base_url="http://vision.example",
            lease_signer=VisionLeaseSigner("v" * 32), sources={"omx_01": _spec()},
        )


def test_reader_rejects_a_provider_selected_event_watermark_before_network_access():
    requests = []

    async def handler(request):
        requests.append(request)
        return _response()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = VisionPostActionObservationSource(
                base_url="https://vision.example",
                lease_signer=VisionLeaseSigner("v" * 32),
                sources={"omx_01": _spec()}, client=client,
            )
            await source.capture_after(
                scope=_scope(), based_on_event_id=18,
                after_action_at="2026-09-30T12:00:01+00:00",
            )

    with pytest.raises(ValueError, match="trusted turn watermark"):
        asyncio.run(run())
    assert requests == []


def test_reader_rejects_non_jpeg_payload():
    async def handler(_request):
        return _response(body=b"not-jpeg")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = VisionPostActionObservationSource(
                base_url="https://vision.example",
                lease_signer=VisionLeaseSigner("v" * 32),
                sources={"omx_01": _spec()}, client=client,
                clock=lambda: datetime(2026, 9, 30, 12, 0, 3, tzinfo=timezone.utc),
            )
            await source.capture_after(
                scope=_scope(), based_on_event_id=19,
                after_action_at="2026-09-30T12:00:01+00:00",
            )

    with pytest.raises(ValueError, match="JPEG"):
        asyncio.run(run())
