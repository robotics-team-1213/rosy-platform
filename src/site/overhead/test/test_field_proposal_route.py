"""D-354 field-proposal route: same lease, headers and freshness rules as the frame route."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import cv2
import httpx
import numpy as np

from core_common.protocol.vision_preview import VisionLeaseSigner
from overhead.ingest import IngestServer, LatestFrame
from overhead.protocol import FrameHeader

PATH = "/api/vision/sources/ceiling-north/field-proposal"


def _get(server, path, authorization):
    return asyncio.run(server._preview_response(path, authorization))


def _field_jpeg(field=True):
    image = np.full((360, 640, 3), 108, dtype=np.uint8)
    if field:
        quad = np.array([(170, 60), (480, 70), (560, 300), (90, 290)], dtype=np.int32)
        cv2.polylines(image, [quad.reshape(-1, 1, 2)], True, (240, 240, 240), 8, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def _server(jpeg, captured_at=None, *, seq=7, max_age=30.0):
    captured_at = time.time() if captured_at is None else captured_at
    server = IngestServer({"ceiling-north": "phone-token"},
                          preview_signer=VisionLeaseSigner("p" * 32),
                          preview_max_age_s=max_age)
    server._sources["ceiling-north"] = SimpleNamespace(latest=LatestFrame(
        header=FrameHeader(seq=seq, age_ms=0, width=640, height=360, rotation_deg=0),
        jpeg=jpeg, captured_at=captured_at, received_at=captured_at,
    ))
    return server


def _lease(server, source="ceiling-north", principal="viewer"):
    return f"Bearer {server.preview_signer.issue(principal_id=principal, source_id=source)}"


def test_proposal_requires_a_source_scoped_lease():
    server = _server(_field_jpeg())
    assert _get(server, PATH, None).status_code == 401
    assert _get(server, PATH, "Bearer nope").status_code == 401
    other = _lease(server, source="ceiling-south")
    assert _get(server, PATH, other).status_code == 401


def test_proposal_returns_json_corners_without_caching_or_touching_the_frame():
    raw = _field_jpeg()
    server = _server(raw)
    response = _get(server, PATH, _lease(server))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Seq"] == "7"
    body = json.loads(response.body)
    assert body["source"] == "ceiling-north"
    assert body["frame_seq"] == 7
    assert body["image"] == {"width": 640, "height": 360}
    assert body["reason"] == "ok"
    assert body["detector"]["version"]
    proposal = body["proposal"]
    assert len(proposal["corners"]) == 4 and len(proposal["corners_normalized"]) == 4
    assert proposal["shape"] in ("square", "rectangle")
    assert 0.5 <= proposal["confidence"] <= 1.0
    assert server.latest_frame("ceiling-north").jpeg == raw


def test_no_field_is_an_explicit_null_proposal():
    server = _server(_field_jpeg(field=False))
    body = json.loads(_get(server, PATH, _lease(server)).body)
    assert body["proposal"] is None
    assert body["reason"] and body["reason"] != "ok"


def test_stale_or_missing_frame_fails_like_the_frame_route():
    stale = _server(_field_jpeg(), captured_at=time.time() - 5.0, max_age=1.0)
    response = _get(stale, PATH, _lease(stale))
    assert response.status_code == 404
    assert response.headers["X-Frame-State"] == "stale"

    empty = IngestServer({"ceiling-north": "phone-token"},
                         preview_signer=VisionLeaseSigner("p" * 32))
    assert _get(empty, PATH, _lease(empty)).status_code == 404


def test_undecodable_frame_is_a_422_not_a_crash():
    server = _server(b"not-a-jpeg")
    response = _get(server, PATH, _lease(server))
    assert response.status_code == 422
    assert response.headers["X-Frame-State"] == "detection-error"


def test_proposal_has_its_own_rate_bucket_and_does_not_starve_frames():
    server = _server(_field_jpeg())
    lease = _lease(server)
    assert _get(server, PATH, lease).status_code == 200
    assert _get(server, PATH, lease).status_code == 429
    frame = _get(server, "/api/vision/sources/ceiling-north/frame", lease)
    assert frame.status_code == 200


def test_detection_is_cached_per_frame_seq(monkeypatch):
    import overhead.ingest as ingest

    calls = []
    real = ingest.detect_field_jpeg

    def counting(jpeg):
        calls.append(1)
        return real(jpeg)

    monkeypatch.setattr(ingest, "detect_field_jpeg", counting)
    server = _server(_field_jpeg())
    _get(server, PATH, _lease(server, principal="a"))
    _get(server, PATH, _lease(server, principal="b"))
    assert len(calls) == 1


def test_unknown_sub_route_is_404():
    server = _server(_field_jpeg())
    lease = _lease(server)
    assert _get(server, "/api/vision/sources/ceiling-north/other", lease).status_code == 404
    assert _get(server, "/api/vision/sources/ceiling-north/field-proposal/x", lease).status_code == 404


def test_proposal_http_route_from_running_vision_server():
    server = _server(_field_jpeg())
    lease = _lease(server)

    async def request():
        websocket_server = await server.start("127.0.0.1", 0)
        port = websocket_server.sockets[0].getsockname()[1]
        try:
            async with httpx.AsyncClient() as client:
                return await client.get(f"http://127.0.0.1:{port}{PATH}",
                                        headers={"Authorization": lease})
        finally:
            websocket_server.close()
            await websocket_server.wait_closed()

    response = asyncio.run(request())
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json()["proposal"] is not None


def _counting_detector(monkeypatch):
    import threading

    import overhead.ingest as ingest

    calls = []
    real = ingest.detect_field_jpeg

    def counting(jpeg):
        calls.append(threading.current_thread() is threading.main_thread())
        return real(jpeg)

    monkeypatch.setattr(ingest, "detect_field_jpeg", counting)
    return calls


def _replace_frame(server, seq):
    now = time.time()
    server._sources["ceiling-north"].latest = LatestFrame(
        header=FrameHeader(seq=seq, age_ms=0, width=640, height=360, rotation_deg=0),
        jpeg=_field_jpeg(), captured_at=now, received_at=now,
    )


def test_detection_runs_off_the_event_loop_at_most_once_per_second_per_source(monkeypatch):
    import overhead.ingest as ingest

    calls = _counting_detector(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(ingest.time, "monotonic", lambda: clock[0])
    server = _server(_field_jpeg(), seq=7)

    assert json.loads(_get(server, PATH, _lease(server, principal="a")).body)["frame_seq"] == 7
    _replace_frame(server, 8)
    clock[0] += 0.5  # a second subject has its own rate bucket but shares the detector budget
    body = json.loads(_get(server, PATH, _lease(server, principal="b")).body)
    assert body["frame_seq"] == 7
    assert calls == [False]

    clock[0] += 1.0
    body = json.loads(_get(server, PATH, _lease(server, principal="c")).body)
    assert body["frame_seq"] == 8
    assert calls == [False, False]


def test_cache_is_keyed_by_frame_identity_and_dropped_with_the_source(monkeypatch):
    import overhead.ingest as ingest

    calls = _counting_detector(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(ingest.time, "monotonic", lambda: clock[0])
    server = _server(_field_jpeg(), seq=7)
    connection = object()
    server._sources["ceiling-north"].connection = connection

    _get(server, PATH, _lease(server, principal="a"))
    _replace_frame(server, 7)  # a reconnecting phone restarts at the same seq
    clock[0] += 1.1
    _get(server, PATH, _lease(server, principal="b"))
    assert len(calls) == 2

    server._drop_if_current("ceiling-north", connection)
    assert "ceiling-north" not in server._field_cache
