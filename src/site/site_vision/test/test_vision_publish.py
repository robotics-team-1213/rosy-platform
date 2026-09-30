import asyncio
import json

import httpx
import pytest

from core_common.protocol.sightings import SiteSightingPayload
from overhead.publish import SightingPublisher, SightingPublishError


def _sighting():
    return SiteSightingPayload(
        robot_id="rosy_01", x=1.0, y=2.0, yaw=0.3, captured_at=1_790_000_000.0,
        seq=17, map_id="site-v1", calibration_revision="cal-v3",
        processor_revision="aruco-v1", quality=None, corner_marker_ids=(30, 31, 32, 33),
    )


def test_publisher_sends_only_derived_sighting_with_source_token_header():
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"source_id": "ceiling_north", "seq": 17})

    async def run():
        async with SightingPublisher(
            "http://127.0.0.1:8090", "source-secret",
            transport=httpx.MockTransport(handler),
        ) as publisher:
            return await publisher.publish(_sighting())

    assert asyncio.run(run()) == {"source_id": "ceiling_north", "seq": 17}
    request = observed[0]
    assert request.method == "POST"
    assert request.url.path == "/api/fleet/sightings"
    assert request.url.query == b""
    assert request.headers["authorization"] == "Bearer source-secret"
    assert json.loads(request.content)["seq"] == 17
    assert b"source-secret" not in request.content


@pytest.mark.parametrize("status,code", [(401, "SIGHTING_UNAUTHORIZED"), (409, "SIGHTING_STALE")])
def test_publisher_surfaces_contract_error_code(status, code):
    def handler(_request):
        return httpx.Response(status, json={"detail": {"code": code, "message": "rejected"}})

    async def run():
        async with SightingPublisher(
            "http://127.0.0.1:8090", "source-secret",
            transport=httpx.MockTransport(handler),
        ) as publisher:
            await publisher.publish(_sighting())

    with pytest.raises(SightingPublishError) as exc:
        asyncio.run(run())
    assert (exc.value.status_code, exc.value.code) == (status, code)
