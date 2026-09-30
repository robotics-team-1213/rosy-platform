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
