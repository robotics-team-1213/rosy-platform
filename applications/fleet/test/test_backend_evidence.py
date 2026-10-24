"""The opt-in probe preserves HTTPX's keyword send contract for streamed peers."""

import asyncio

import httpx
from fastapi import FastAPI

from backend_evidence import OBSERVED, fleet_contract_probe  # noqa: F401 (autouse fixture)


def test_async_probe_preserves_keyword_stream_send_and_records_response():
    app = FastAPI()

    # This harness-only status cannot become a successful product-route receipt.
    @app.get("/api/fleet/control-unit/overview", status_code=207)
    def overview():
        return {"probe": True}

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            request = client.build_request("GET", "http://probe.invalid/api/fleet/control-unit/overview")
            response = await client.send(request=request, stream=True)
            await response.aread()
            assert response.status_code == 207 and response.json() == {"probe": True}
            await response.aclose()

    asyncio.run(exercise())
    nodes = OBSERVED["GET:/api/fleet/control-unit/overview"][207]
    assert any(node.endswith("::test_async_probe_preserves_keyword_stream_send_and_records_response") for node in nodes)
