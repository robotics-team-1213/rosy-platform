"""Source-only scope fetch does not expose or need a robot credential."""
import asyncio
import secrets

import httpx

from rosy_vision.publish import SightingPublisher
from test_station_observation import template


def test_station_publisher_reads_metadata_scope_with_its_source_credential():
    async def run():
        token = secrets.token_urlsafe(32)
        def handler(request):
            assert request.method == 'GET'
            assert request.url.path == '/api/fleet/station-observation-scope/robot-1'
            assert request.headers['Authorization'] == 'Bearer '+token
            return httpx.Response(200, json={'scope': template(sequence=0).model_dump()})
        async with SightingPublisher('http://fleet', token, transport=httpx.MockTransport(handler)) as publisher:
            assert hasattr(publisher, 'station_scope'), 'source-only scope fetch is missing'
            result = await publisher.station_scope('robot-1')
            assert result.pose is None and not result.visible and result.session_id == 'charge-1'
    asyncio.run(run())
