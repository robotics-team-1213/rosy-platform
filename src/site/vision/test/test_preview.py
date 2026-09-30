import asyncio
import time
from types import SimpleNamespace

import cv2
import httpx
import numpy as np

from core_common.protocol.vision_preview import VisionLeaseSigner
from site_vision.ingest import IngestServer, LatestFrame
from site_vision.protocol import FrameHeader


def _get(server, path, authorization):
    return asyncio.run(server._preview_response(path, authorization))


def _server_with_frame(captured_at, *, preview_max_age_s=1.0):
    server = IngestServer({"ceiling-north": "phone-token"},
                          preview_signer=VisionLeaseSigner("p" * 32),
                          preview_max_age_s=preview_max_age_s)
    server._sources["ceiling-north"] = SimpleNamespace(latest=LatestFrame(
        header=FrameHeader(seq=42, age_ms=0, width=640, height=480, rotation_deg=0),
        jpeg=b"jpeg-frame", captured_at=captured_at, received_at=captured_at,
    ))
    return server


def test_preview_requires_scoped_lease_and_returns_latest_jpeg_without_caching():
    import time

    server = _server_with_frame(time.time())
    token = server.preview_signer.issue(principal_id="viewer", source_id="ceiling-north")

    denied = _get(server, "/api/vision/sources/ceiling-north/frame", None)
    allowed = _get(server, "/api/vision/sources/ceiling-north/frame", f"Bearer {token}")

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.body == b"jpeg-frame"
    assert allowed.headers["Content-Type"] == "image/jpeg"
    assert allowed.headers["Cache-Control"] == "no-store"
    assert allowed.headers["X-Frame-Seq"] == "42"
    assert allowed.headers["X-Frame-Width"] == "640"
    assert allowed.headers["X-Frame-Height"] == "480"
    assert allowed.headers["X-Frame-Rotation-Deg"] == "0"
    assert _get(server, "/api/vision/sources/ceiling-north/frame", f"Bearer {token}").status_code == 429


def test_preview_rejects_wrong_source_and_stale_latest_frame():
    import time

    server = _server_with_frame(time.time() - 2.0)
    token = server.preview_signer.issue(principal_id="viewer", source_id="ceiling-north")

    stale = _get(server, "/api/vision/sources/ceiling-north/frame", f"Bearer {token}")
    wrong = _get(server, "/api/vision/sources/other/frame", f"Bearer {token}")

    assert stale.status_code == 404
    assert stale.headers["X-Frame-State"] == "stale"
    assert wrong.status_code == 401


def test_preview_http_route_serves_frame_from_running_vision_server():
    server = _server_with_frame(time.time(), preview_max_age_s=30.0)
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


def test_rectified_preview_warps_only_the_served_copy_of_latest_frame():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    image[:, :80] = (10, 20, 230)
    image[:, 80:] = (230, 20, 10)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    raw = encoded.tobytes()
    server = _server_with_frame(time.time())
    server._sources["ceiling-north"].latest.jpeg = raw
    profile = {
        "fx": 1, "fy": 1, "cx": 0.5, "cy": 0.5,
        "k1": 0, "k2": 0, "p1": 0, "p2": 0, "k3": 0,
        "corners": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        "output_aspect": 1,
    }
    token = server.preview_signer.issue(principal_id="viewer", source_id="ceiling-north",
                                        rectification=profile)

    response = _get(server, "/api/vision/sources/ceiling-north/frame", f"Bearer {token}")
    corrected = cv2.imdecode(np.frombuffer(response.body, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert response.status_code == 200
    assert response.headers["X-Frame-Rectified"] == "true"
    assert corrected.shape[:2] == (128, 128)
    assert server.latest_frame("ceiling-north").jpeg == raw
