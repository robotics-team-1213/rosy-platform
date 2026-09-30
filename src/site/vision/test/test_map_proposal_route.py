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
from rosy_vision import map_worker, protocol
from rosy_vision.ingest import IngestServer, LatestFrame, _MapRun
from rosy_vision.map_register import RegistrationResult, load_map_paint
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


_SERVERS: list = []


@pytest.fixture(autouse=True)
def _stop_map_workers():
    yield
    while _SERVERS:
        _SERVERS.pop().close_map_worker()


def _server(jpeg, paint, *, captured_at=None, max_age=30.0, tokens=None):
    captured_at = time.time() if captured_at is None else captured_at
    server = IngestServer(tokens or {"ceiling-north": "phone-token"},
                          preview_signer=VisionLeaseSigner("p" * 32),
                          preview_max_age_s=max_age, map_paint=paint)
    server._sources["ceiling-north"] = SimpleNamespace(latest=LatestFrame(
        header=FrameHeader(seq=9, age_ms=0, width=1280, height=720, rotation_deg=0),
        jpeg=jpeg, captured_at=captured_at, received_at=captured_at,
    ))
    _SERVERS.append(server)
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


def test_a_read_during_a_run_gets_the_last_successful_result_not_busy(track_jpeg, paint):
    server = _server(track_jpeg, paint)
    first = _get(server, PATH, _lease(server))
    assert first.status_code == 200 and first.headers["X-Proposal-State"] == "current"
    done = server._map_cache["ceiling-north"]
    # A newer frame is being registered for another reader (single flight, not finished).
    newer = LatestFrame(header=FrameHeader(seq=10, age_ms=0, width=1280, height=720, rotation_deg=0),
                        jpeg=track_jpeg, captured_at=time.time(), received_at=time.time())
    server._sources["ceiling-north"].latest = newer
    server._map_cache["ceiling-north"] = _MapRun(frame=newer)

    response = _get(server, PATH, _lease(server, principal="other"))

    assert response.status_code == 200
    assert response.headers["X-Proposal-State"] == "previous"
    body = json.loads(response.body)
    assert body["frame_seq"] == 9 and body["accepted"] is True
    assert server._map_done["ceiling-north"] is done
    # Nothing finished yet for this source: still 429 with Retry-After.
    server._map_done.clear()
    busy = _get(server, PATH, _lease(server, principal="third"))
    assert busy.status_code == 429 and busy.headers["Retry-After"] == "1"


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


def test_map_registration_is_single_flight_per_source(track_jpeg, paint):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    release, calls = threading.Event(), []

    def slow(jpeg):
        calls.append(threading.current_thread().name)
        release.wait(5.0)
        return RegistrationResult(None, False, "stub", 1.0, (1280, 720))

    server = _server(track_jpeg, paint)
    server._map_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="map-register")
    server._map_job = slow

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
    assert calls == ["map-register_0"]


def _cpu_bound_registration(jpeg: bytes) -> RegistrationResult:
    """Runs in the worker process: 3 s of pure-Python CPU, as a slow registration."""
    deadline = time.perf_counter() + 3.0
    total = 0
    while time.perf_counter() < deadline:
        total += sum(range(2000))
    return RegistrationResult(None, False, f"stub {total > 0}", 3000.0, (1280, 720))


def test_registration_in_flight_does_not_delay_the_ingest_loop(track_jpeg, paint):
    """Live bug (2026-10-01): a registration on a thread starved the event loop, phone
    hellos timed out and frame reads took 10-15 s. It now runs in a worker process."""
    import websockets

    server = _server(track_jpeg, paint, tokens={"ceiling-north": "phone-token", "cam-2": "t2"})
    server._map_job = _cpu_bound_registration

    async def scenario():
        ws_server = await server.start("127.0.0.1", 0)
        port = ws_server.sockets[0].getsockname()[1]
        try:
            # Warm the worker (process spawn and imports) before timing anything.
            server._map_executor = map_worker.start(paint)
            await asyncio.get_running_loop().run_in_executor(server._map_executor, int)
            proposal = asyncio.create_task(server._preview_response(PATH, _lease(server)))
            await asyncio.sleep(0.5)
            assert not proposal.done()
            started = time.perf_counter()
            async with websockets.connect(
                    f"ws://127.0.0.1:{port}{protocol.WS_PATH}",
                    additional_headers={"Authorization": "Bearer t2"}) as ws:
                await ws.send(json.dumps({"type": "hello", "proto": protocol.PROTO,
                                          "source": "cam-2", "app_version": "0.1.0",
                                          "device": "test",
                                          "sensor": {"width": 1280, "height": 720,
                                                     "rotation_deg": 0}}))
                config = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                answered = time.perf_counter() - started
            frame_read = time.perf_counter()
            _ = await server._preview_response(
                "/api/vision/sources/ceiling-north/frame", _lease(server, principal="viewer-2"))
            frame_read = time.perf_counter() - frame_read
            still_running = not proposal.done()
            response = await proposal
            return config, answered, frame_read, still_running, response
        finally:
            ws_server.close()
            await ws_server.wait_closed()

    config, answered, frame_read, still_running, response = asyncio.run(scenario())
    assert config["type"] == "config"
    assert still_running, "the stub registration should still be running"
    assert answered < 0.5, f"hello answered after {answered:.2f} s"
    assert frame_read < 0.5, f"frame read took {frame_read:.2f} s"
    assert response.status_code == 200