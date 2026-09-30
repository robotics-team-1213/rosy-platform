"""D-375 map-proposal route: the D-360 lease, header and freshness rules, plus a paint gate."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from core_common.protocol.vision_preview import VisionLeaseSigner
from rosy_vision.ingest import IngestServer, LatestFrame
from rosy_vision.map_register import load_map_paint
from rosy_vision.protocol import FrameHeader
from map_paint_frames import STL, render, similarity

PATH = "/api/vision/sources/ceiling-north/map-proposal"


@pytest.fixture(scope="module")
def paint():
    return load_map_paint(STL)


@pytest.fixture(scope="module")
def track_jpeg(paint):
    ok, encoded = cv2.imencode(".jpg", render(paint, similarity(440.0, 180.0, (780.0, 360.0))))
    assert ok
    return encoded.tobytes()


def _get(server, path, authorization):
    return asyncio.run(server._preview_response(path, authorization))


def _server(jpeg, paint, *, captured_at=None, max_age=30.0):
    captured_at = time.time() if captured_at is None else captured_at
    server = IngestServer({"ceiling-north": "phone-token"},
                          preview_signer=VisionLeaseSigner("p" * 32),
                          preview_max_age_s=max_age, map_paint=paint)
    server._sources["ceiling-north"] = SimpleNamespace(latest=LatestFrame(
        header=FrameHeader(seq=9, age_ms=0, width=1280, height=720, rotation_deg=0),
        jpeg=jpeg, captured_at=captured_at, received_at=captured_at,
    ))
    return server


def _lease(server, source="ceiling-north", principal="viewer"):
    return f"Bearer {server.preview_signer.issue(principal_id=principal, source_id=source)}"


def test_map_proposal_requires_a_source_scoped_lease(track_jpeg, paint):
    server = _server(track_jpeg, paint)
    assert _get(server, PATH, None).status_code == 401
    assert _get(server, PATH, _lease(server, source="ceiling-south")).status_code == 401


def test_map_proposal_without_configured_paint_is_not_found(track_jpeg):
    server = _server(track_jpeg, None)
    assert _get(server, PATH, _lease(server)).status_code == 404


def test_map_proposal_returns_homography_coverage_and_cut_side(track_jpeg, paint):
    server = _server(track_jpeg, paint)
    response = _get(server, PATH, _lease(server))
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    body = json.loads(response.body)
    assert body["accepted"] is True and body["reason"] == "ok"
    assert body["rejected_fit"] is None
    proposal = body["proposal"]
    assert np.array(proposal["image_to_map"]).shape == (3, 3)
    assert np.array(proposal["map_to_image"]).shape == (3, 3)
    assert proposal["cut_sides"] == ["-x"] and proposal["cut_directions"] == ["west"]
    assert 0.6 < proposal["coverage"] < 0.9
    assert proposal["mirrored"] is False
    assert body["registrar"]["version"]
    # A second read of the same frame reuses the result instead of registering again.
    run = server._map_cache["ceiling-north"]
    _get(server, PATH, _lease(server, principal="other"))
    assert server._map_cache["ceiling-north"] is run


def test_blank_floor_is_a_null_proposal_with_reason(paint):
    ok, encoded = cv2.imencode(".jpg", np.full((720, 1280, 3), 105, np.uint8))
    server = _server(encoded.tobytes(), paint)
    body = json.loads(_get(server, PATH, _lease(server)).body)
    assert body["accepted"] is False and body["proposal"] is None
    assert body["reason"] and body["reason"] != "ok"


def test_stale_frame_fails_like_the_frame_route(track_jpeg, paint):
    server = _server(track_jpeg, paint, captured_at=time.time() - 5.0, max_age=1.0)
    assert _get(server, PATH, _lease(server)).status_code == 404

def test_one_viewer_is_rate_limited_per_second(track_jpeg, paint):
    server = _server(track_jpeg, paint)
    assert _get(server, PATH, _lease(server, principal="warm")).status_code == 200
    lease = _lease(server)
    assert _get(server, PATH, lease).status_code == 200  # served from the cached run
    limited = _get(server, PATH, lease)
    assert limited.status_code == 429 and limited.headers["Retry-After"] == "1"


def test_corrupt_jpeg_is_a_consistent_422(paint):
    server = _server(b"\xff\xd8\xff" + bytes(range(256)) * 8, paint)
    first = _get(server, PATH, _lease(server, principal="a"))
    again = _get(server, PATH, _lease(server, principal="b"))
    assert first.status_code == 422 and again.status_code == 422
    assert first.headers["X-Frame-State"] == "detection-error"


def test_rejected_fit_carries_placement_hints_but_no_homography(paint):
    truth = similarity(400.0, 0.0, (640.0, 360.0))
    first = render(paint, truth, seed=1)
    second = render(paint, similarity(400.0, 0.0, (680.0, 388.0)), seed=1)
    ok, encoded = cv2.imencode(".jpg", np.maximum(first, second))
    server = _server(encoded.tobytes(), paint)
    body = json.loads(_get(server, PATH, _lease(server)).body)
    assert body["accepted"] is False and body["proposal"] is None
    fit = body["rejected_fit"]
    assert "coverage" in fit and "cut_sides" in fit
    assert "image_to_map" not in fit and "map_to_image" not in fit


def test_map_registration_is_single_flight_per_source(monkeypatch, track_jpeg, paint):
    import threading
    import rosy_vision.ingest as ingest

    release, calls = threading.Event(), []

    def slow(jpeg, paint_):
        calls.append(threading.current_thread().name)
        release.wait(5.0)
        return ingest.RegistrationResult(None, False, "stub", 1.0, (1280, 720))

    monkeypatch.setattr(ingest, "register_map_jpeg", slow)
    server = _server(track_jpeg, paint)

    async def scenario():
        first = asyncio.create_task(server._preview_response(PATH, _lease(server, principal="a")))
        await asyncio.sleep(0.2)
        # A new frame arrives while the first run is still going: no second run starts.
        src = server._sources["ceiling-north"]
        src.latest = LatestFrame(header=FrameHeader(seq=10, age_ms=0, width=1280, height=720,
                                                    rotation_deg=0),
                                 jpeg=track_jpeg, captured_at=time.time(), received_at=time.time())
        busy = await server._preview_response(PATH, _lease(server, principal="b"))
        release.set()
        return await first, busy

    first, busy = asyncio.run(scenario())
    assert busy.status_code == 429 and busy.headers["Retry-After"] == "1"
    assert first.status_code == 200
    assert len(calls) == 1 and calls[0].startswith("map-register")
