from types import SimpleNamespace
import asyncio
import time

import httpx

from core_common.protocol.vision_preview import VisionLeaseSigner
from overhead.ingest import IngestServer, LatestFrame
from overhead.protocol import FrameHeader


def _server_with_frame(captured_at):
    server = IngestServer({"ceiling-north": "phone-token"},
                          preview_signer=VisionLeaseSigner("p" * 32))
    server._sources["ceiling-north"] = SimpleNamespace(latest=LatestFrame(
        header=FrameHeader(seq=42, age_ms=0, width=640, height=480, rotation_deg=0),
        jpeg=b"jpeg-frame", captured_at=captured_at, received_at=captured_at,
    ))
    return server


def test_preview_requires_scoped_lease_and_returns_latest_jpeg_without_caching():
    import time

    server = _server_with_frame(time.time())
    token = server.preview_signer.issue(principal_id="viewer", source_id="ceiling-north")

    denied = server._preview_response("/api/vision/sources/ceiling-north/frame", None)
    allowed = server._preview_response(
        "/api/vision/sources/ceiling-north/frame", f"Bearer {token}")

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.body == b"jpeg-frame"
    assert allowed.headers["Content-Type"] == "image/jpeg"
    assert allowed.headers["Cache-Control"] == "no-store"
    assert allowed.headers["X-Frame-Seq"] == "42"
    assert server._preview_response(
        "/api/vision/sources/ceiling-north/frame", f"Bearer {token}").status_code == 429


def test_preview_rejects_wrong_source_and_stale_latest_frame():
    import time

    server = _server_with_frame(time.time() - 2.0)
    token = server.preview_signer.issue(principal_id="viewer", source_id="ceiling-north")

    stale = server._preview_response(
        "/api/vision/sources/ceiling-north/frame", f"Bearer {token}")
    wrong = server._preview_response(
        "/api/vision/sources/other/frame", f"Bearer {token}")

    assert stale.status_code == 404
    assert stale.headers["X-Frame-State"] == "stale"
    assert wrong.status_code == 401


def test_preview_http_route_serves_frame_from_running_vision_server():
    server = _server_with_frame(time.time())
    token = server.preview_signer.issue(principal_id="viewer", source_id="ceiling-north")

    async def request_frame():
        websocket_server = await server.start("127.0.0.1", 0)
        port = websocket_server.sockets[0].getsockname()[1]
        try:
            async with httpx.AsyncClient() as client:
                return await client.get(
                    f"http://127.0.0.1:{port}/api/vision/sources/ceiling-north/frame",
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            websocket_server.close()
            await websocket_server.wait_closed()

    response = asyncio.run(request_frame())

    assert response.status_code == 200
    assert response.content == b"jpeg-frame"
    assert response.headers["x-frame-seq"] == "42"
