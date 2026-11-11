"""The draft-map proposal: lane and zone candidates from the map plane, no prior map paint.

A camera whose approved tracking calibration is on record warps its frame to the map plane
(D-560) and this view reads the floor from that plane: bright paint strokes become lane
polylines and saturated colour areas become exclusion-zone candidates, both in map metres.
Nothing here needs the D-375 site-map paint configuration, and the result is a proposal for
operator review only.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from core_common.protocol.vision_preview import VisionLeaseSigner
from rosy_vision.draft_map import DRAFT_MAP_VERSION, detect_draft_map
from rosy_vision.ingest import IngestServer, LatestFrame
from rosy_vision.protocol import FrameHeader

SOURCE = "ceiling_north"
MAP = "map_v2_fleet"
LENS = {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 67.8}
# Record for 1280x720 frames: image u = 400 + 200 x, v = 360 - 200 y (map +y is image up).
RECORD = {
    "source_id": SOURCE, "map_id": MAP, "calibration_revision": "paint-test",
    "map_to_image": [200.0, 0.0, 400.0, 0.0, -200.0, 360.0, 0.0, 0.0, 1.0],
    "image": {"width": 1280, "height": 720},
    "track_bounds_m": {"min_x": -1.0, "min_y": -0.5, "max_x": 1.0, "max_y": 0.5},
    "lens": LENS,
}
PLANE_BOUNDS = (-1.15, -0.65, 1.15, 0.65)   # track bounds + the D-560 margin
PLANE_PPM = 400.0
LANE_FROM, LANE_TO = (-0.5, 0.05), (0.5, 0.05)          # a 1 m paint stroke, 0.1 m wide
ZONE_X, ZONE_Y, ZONE_SIDE = (-0.4, -0.4, 0.3)           # a red 0.3 m square
PATH = f"/api/vision/sources/{SOURCE}/draft-map"


def _map_px(x, y):
    return round(400 + 200 * x), round(360 - 200 * y)


def _frame_jpeg() -> bytes:
    """A grey floor with one white lane stroke and one red zone square at known map points."""
    image = np.full((720, 1280, 3), 120, np.uint8)
    cv2.rectangle(image, _map_px(LANE_FROM[0], 0.1), _map_px(LANE_TO[0], 0.0), (235, 235, 235), -1)
    cv2.rectangle(image, _map_px(ZONE_X, ZONE_Y + ZONE_SIDE), _map_px(ZONE_X + ZONE_SIDE, ZONE_Y),
                  (0, 0, 255), -1)
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def _server(jpeg=None) -> IngestServer:
    server = IngestServer({SOURCE: "phone-token"}, preview_signer=VisionLeaseSigner("p" * 32))
    now = time.time()
    server._sources[SOURCE] = SimpleNamespace(lens=LENS, latest=LatestFrame(
        header=FrameHeader(seq=42, age_ms=0, width=1280, height=720, rotation_deg=0),
        jpeg=jpeg or _frame_jpeg(), captured_at=now, received_at=now))
    return server


def _get(server, principal="viewer"):
    token = server.preview_signer.issue(principal_id=principal, source_id=SOURCE)
    return asyncio.run(server._preview_response(PATH, f"Bearer {token}"))


def _plane_image() -> np.ndarray:
    """The same floor drawn straight on the map plane, for detector unit tests."""
    image = np.full((520, 920, 3), 120, np.uint8)

    def plane_px(x, y):
        return round((x - PLANE_BOUNDS[0]) * PLANE_PPM), round((PLANE_BOUNDS[3] - y) * PLANE_PPM)

    cv2.rectangle(image, plane_px(LANE_FROM[0], 0.1), plane_px(LANE_TO[0], 0.0), (235, 235, 235), -1)
    cv2.rectangle(image, plane_px(ZONE_X, ZONE_Y + ZONE_SIDE),
                  plane_px(ZONE_X + ZONE_SIDE, ZONE_Y), (0, 0, 255), -1)
    return image


def test_detect_draft_map_reads_lanes_and_zones_in_metres():
    result = detect_draft_map(_plane_image(), PLANE_BOUNDS, PLANE_PPM)
    assert result["reason"] == "ok"
    assert len(result["lanes"]) == 1
    lane = sorted(np.round(result["lanes"][0]["polyline_m"], 3).tolist())
    expected = sorted([list(LANE_FROM), list(LANE_TO)])
    for got, want in zip(lane, expected):
        assert got == pytest.approx(want, abs=0.02)
    assert result["lanes"][0]["width_px"] == pytest.approx(0.1 * PLANE_PPM, rel=0.3)
    assert len(result["zones"]) == 1 and result["zones"][0]["kind"] == "exclusion"
    corners = sorted(map(tuple, np.round(result["zones"][0]["polygon_m"], 3).tolist()))
    square = sorted([(ZONE_X + dx, ZONE_Y + dy) for dx in (0, ZONE_SIDE) for dy in (0, ZONE_SIDE)])
    for got, want in zip(corners, square):
        assert got == pytest.approx(want, abs=0.03)


def test_detect_draft_map_with_an_empty_floor_finds_nothing():
    result = detect_draft_map(np.full((520, 920, 3), 120, np.uint8), PLANE_BOUNDS, PLANE_PPM)
    assert result["lanes"] == [] and result["zones"] == []
    assert result["reason"] == "nothing detected"


def test_draft_map_requires_a_source_scoped_lease():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    assert asyncio.run(server._preview_response(PATH, None)).status_code == 401
    other = server.preview_signer.issue(principal_id="viewer", source_id="ceiling_south")
    assert asyncio.run(server._preview_response(PATH, f"Bearer {other}")).status_code == 401


def test_draft_map_without_a_calibration_record_is_refused():
    server = _server()
    response = _get(server)
    assert response.status_code == 409
    assert response.headers.get("X-Frame-State") == "plane-unavailable"


def test_draft_map_needs_no_site_paint_and_reads_candidates_in_metres():
    server = _server()
    assert server.map_paint is None          # the D-375 paint config stays untouched
    server.report_calibration(SOURCE, RECORD, MAP)
    response = _get(server)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["X-Frame-Calibration"] == "paint-test"
    assert response.headers["X-Proposal-State"] == "current"
    body = json.loads(response.body)
    assert body["source"] == SOURCE and body["map_frame"] == "map"
    assert body["detector"]["version"] == DRAFT_MAP_VERSION
    assert list(body["plane"]["bounds_m"]) == list(PLANE_BOUNDS)
    assert body["plane"]["px_per_m"] == PLANE_PPM
    assert body["plane"]["calibration_revision"] == "paint-test"
    lane = sorted(np.round(body["lanes"][0]["polyline_m"], 3).tolist())
    for got, want in zip(lane, sorted([list(LANE_FROM), list(LANE_TO)])):
        assert got == pytest.approx(want, abs=0.03)
    assert body["zones"][0]["kind"] == "exclusion"
    assert len(np.round(body["zones"][0]["polygon_m"], 3)) == 4


def test_draft_map_rate_limits_a_second_read():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    assert _get(server).status_code == 200
    assert _get(server).status_code == 429          # the same viewer waits (D-691)
    assert _get(server, principal="other").status_code == 200   # another viewer's own limit
