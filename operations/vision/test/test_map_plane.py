"""D-560 S1: Vision serves the latest frame warped to the map plane (``mode: map``)."""

import asyncio
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from core_common.protocol.vision_preview import PreviewRectification, VisionLeaseSigner
from rosy_vision.ingest import IngestServer, LatestFrame
from rosy_vision.protocol import FrameHeader
from rosy_vision.rectify import map_plane_jpeg

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
POINT = (0.5, 0.25)


def _frame_jpeg():
    """640x360 frame (half the record size) with a white dot at the image of POINT."""
    image = np.full((360, 640, 3), 120, np.uint8)
    u, v = 400 + 200 * POINT[0], 360 - 200 * POINT[1]  # record pixel index
    # Rescaled by pixel centres to half size: k (u + 0.5) - 0.5.
    cv2.circle(image, (round(0.5 * (u + 0.5) - 0.5), round(0.5 * (v + 0.5) - 0.5)), 3,
               (255, 255, 255), -1)
    return cv2.imencode(".jpg", image)[1].tobytes()


def _server(lens=LENS, jpeg=None):
    server = IngestServer({SOURCE: "phone-token"}, preview_signer=VisionLeaseSigner("p" * 32))
    now = time.time()
    server._sources[SOURCE] = SimpleNamespace(lens=lens, latest=LatestFrame(
        header=FrameHeader(seq=42, age_ms=0, width=640, height=360, rotation_deg=0),
        jpeg=jpeg or _frame_jpeg(), captured_at=now, received_at=now))
    return server


def _get(server, rectification={"mode": "map"}):
    token = server.preview_signer.issue(principal_id="viewer", source_id=SOURCE,
                                        rectification=rectification)
    return asyncio.run(server._preview_response(f"/api/vision/sources/{SOURCE}/frame",
                                                f"Bearer {token}"))


def test_a_map_point_lands_at_the_plane_pixel_of_the_header_formula():
    plane = map_plane_jpeg(_frame_jpeg(), RECORD, source_id=SOURCE, map_id=MAP, lens=LENS)
    min_x, min_y, max_x, max_y = plane.bounds_m
    assert (min_x, min_y, max_x, max_y) == (-1.15, -0.65, 1.15, 0.65)
    assert plane.px_per_m == 400 and plane.size == (920, 520)
    image = cv2.imdecode(np.frombuffer(plane.jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image.shape == (520, 920)
    vs, us = np.nonzero(image > 128)
    # Pixel centres (index + 0.5) in canvas coordinates, back through the D-560 formula.
    x = min_x + (us.mean() + 0.5) / plane.px_per_m
    y = max_y - (vs.mean() + 0.5) / plane.px_per_m
    assert (x, y) == pytest.approx(POINT, abs=0.01)  # one frame pixel is 1 cm here
    # Map +x is right and +y up: the dot is right of and above the plane centre.
    assert us.mean() > 460 and vs.mean() < 260


def test_the_warp_homography_matches_the_header_formula_exactly():
    """A half-pixel slip in the plane transform fails here (1e-9 m, not one frame pixel)."""
    plane = map_plane_jpeg(_frame_jpeg(), RECORD, source_id=SOURCE, map_id=MAP, lens=LENS)
    min_x, _, _, max_y = plane.bounds_m
    # Frame pixel index of POINT: record index rescaled to half size by pixel centres.
    u, v = 400 + 200 * POINT[0], 360 - 200 * POINT[1]
    frame_point = np.array([0.5 * (u + 0.5) - 0.5, 0.5 * (v + 0.5) - 0.5, 1.0])
    i, j, w = np.asarray(plane.image_to_plane).reshape(3, 3) @ frame_point
    i, j = i / w, j / w  # OpenCV plane pixel index; canvas coordinate = index + 0.5
    assert min_x + (i + 0.5) / plane.px_per_m == pytest.approx(POINT[0], abs=1e-9)
    assert max_y - (j + 0.5) / plane.px_per_m == pytest.approx(POINT[1], abs=1e-9)


def test_a_wide_track_shrinks_so_the_long_side_fits_1920_px():
    record = {**RECORD, "track_bounds_m": {"min_x": -3.0, "min_y": -0.5, "max_x": 3.0, "max_y": 0.5}}
    plane = map_plane_jpeg(_frame_jpeg(), record, source_id=SOURCE, map_id=MAP, lens=LENS)
    assert plane.px_per_m == pytest.approx(1920 / 6.3, abs=1e-4) and plane.px_per_m < 400
    assert max(plane.size) <= 1920
    # The header rectangle is the image size at this scale, after rounding the pixel size.
    min_x, min_y, max_x, max_y = plane.bounds_m
    assert (max_x - min_x) * plane.px_per_m == pytest.approx(plane.size[0], abs=1e-9)
    assert (max_y - min_y) * plane.px_per_m == pytest.approx(plane.size[1], abs=1e-9)
    image = cv2.imdecode(np.frombuffer(plane.jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    # The plane's left edge (x = -3.15 m) is outside the frame: constant dark fill there,
    # the frame itself in the middle.
    assert image[plane.size[1] // 2, 0] == pytest.approx(24, abs=4)
    assert image[plane.size[1] // 2, plane.size[0] // 4] == pytest.approx(120, abs=4)


def test_map_plane_response_headers():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    response = _get(server)
    assert response.status_code == 200
    headers = response.headers
    assert headers["Content-Type"] == "image/jpeg"
    assert headers["X-Frame-Rectified"] == "map"
    assert headers["X-Frame-Plane"] == "-1.1500,-0.6500,1.1500,0.6500,400.0000"
    assert headers["X-Frame-Calibration"] == "paint-test"
    assert (headers["X-Frame-Width"], headers["X-Frame-Height"]) == ("920", "520")
    assert headers["X-Frame-Seq"] == "42"
    assert "X-Frame-Age-Ms" in headers and "X-Frame-Captured-At" in headers
    assert headers["X-Source-Lens"] == "kind=standard;focal_mm=5.4;hfov_deg=67.8"
    image = cv2.imdecode(np.frombuffer(response.body, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (520, 920)


def test_ai_map_crop_lease_returns_only_the_robot_neighborhood():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    token = server.preview_signer.issue(principal_id="ai-case", source_id=SOURCE,
                                        rectification={"mode": "map"}, crop_map=(0.0, 0.0, 0.5),
                                        crop_map_id=MAP, crop_revision=RECORD["calibration_revision"])
    response = asyncio.run(server._preview_response(f"/api/vision/sources/{SOURCE}/frame", f"Bearer {token}"))
    assert response.status_code == 200
    assert response.headers["X-Frame-Rectified"] == "map-crop"
    image = cv2.imdecode(np.frombuffer(response.body, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (400, 400)


@pytest.mark.parametrize("changed", [{"map_id": "other"}, {"calibration_revision": "next"}])
def test_ai_crop_lease_cannot_follow_a_map_or_calibration_switch(changed):
    server = _server()
    token = server.preview_signer.issue(principal_id="ai-case", source_id=SOURCE,
                                        rectification={"mode": "map"}, crop_map=(0.0, 0.0, 0.5),
                                        crop_map_id=MAP, crop_revision=RECORD["calibration_revision"])
    server.report_calibration(SOURCE, {**RECORD, **changed}, changed.get("map_id", MAP))
    response = asyncio.run(server._preview_response(f"/api/vision/sources/{SOURCE}/frame", f"Bearer {token}"))
    assert response.status_code == 409 and response.headers["X-Frame-State"] == "plane-unavailable"


@pytest.mark.parametrize("record, lens", [
    (None, LENS),                                                     # no record
    (RECORD, {**LENS, "focal_mm": 2.2}),                              # lens changed
    ({**RECORD, "image": {"width": 1280, "height": 960}}, LENS),      # aspect differs
    ({**RECORD, "source_id": "ceiling_south"}, LENS),                 # another source
    ({**RECORD, "map_id": "other_map"}, LENS),                        # another map
])
def test_map_plane_is_409_and_never_the_raw_frame_when_the_record_does_not_fit(record, lens):
    server = _server(lens=lens)
    if record is not None:
        server.report_calibration(SOURCE, record, MAP)
    response = _get(server)
    assert response.status_code == 409
    assert response.headers["X-Frame-State"] == "plane-unavailable"
    assert response.body == b"map plane unavailable\n"


def test_a_cleared_record_makes_the_plane_unavailable_again():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    server.report_calibration(SOURCE, None, MAP)
    assert _get(server).status_code == 409


@pytest.mark.parametrize("revision", [None, "", "bad revision", "x" * 97, "a\r\nX-Evil: 1"])
def test_a_record_with_a_malformed_revision_is_no_record(revision):
    server = _server()
    server.report_calibration(SOURCE, {**RECORD, "calibration_revision": revision}, MAP)
    assert _get(server).status_code == 409


def test_an_undecodable_frame_under_map_mode_is_422_never_raw():
    server = _server(jpeg=b"not-a-jpeg")
    server.report_calibration(SOURCE, RECORD, MAP)
    response = _get(server)
    assert response.status_code == 422
    assert response.headers["X-Frame-State"] == "rectification-error"
    assert response.body != b"not-a-jpeg"


def test_a_new_frame_with_the_same_revision_is_warped_again():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    assert _get(server).headers["X-Frame-Seq"] == "42"
    task = server._plane_cache[SOURCE][2]
    now = time.time()
    server._sources[SOURCE].latest = LatestFrame(
        header=FrameHeader(seq=43, age_ms=0, width=640, height=360, rotation_deg=0),
        jpeg=_frame_jpeg(), captured_at=now, received_at=now)
    server._preview_last_sent.clear()
    response = _get(server)
    assert response.status_code == 200 and response.headers["X-Frame-Seq"] == "43"
    assert server._plane_cache[SOURCE][2] is not task


def test_one_warp_per_frame_and_revision_for_all_readers():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    first = _get(server)
    task = server._plane_cache[SOURCE][2]
    server._preview_last_sent.clear()
    second = _get(server, {"mode": "map"})
    assert server._plane_cache[SOURCE][2] is task and second.body == first.body
    server.report_calibration(SOURCE, {**RECORD, "calibration_revision": "paint-next"}, MAP)
    server._preview_last_sent.clear()
    assert _get(server).headers["X-Frame-Calibration"] == "paint-next"
    assert server._plane_cache[SOURCE][2] is not task


def test_manual_and_auto_are_unchanged_by_a_reported_record():
    server = _server()
    server.report_calibration(SOURCE, RECORD, MAP)
    manual = _get(server, {"corners": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]})
    assert manual.status_code == 200 and manual.headers["X-Frame-Rectified"] == "true"
    assert "X-Frame-Plane" not in manual.headers
    server._preview_last_sent.clear()
    auto = _get(server, {"mode": "auto"})  # no field report: raw frame, as before D-560
    assert auto.headers["X-Frame-Rectified"] == "false"
    assert auto.headers["X-Frame-State"] == "field-unavailable"
    assert auto.body == server.latest_frame(SOURCE).jpeg


def test_lease_schema_accepts_map_mode_and_rejects_extra_fields():
    signer = VisionLeaseSigner("x" * 32)
    token = signer.issue(principal_id="viewer", source_id=SOURCE, rectification={"mode": "map"}, now=100)
    assert signer.verify(token, source_id=SOURCE, now=101)["rectification"] == {"mode": "map"}
    assert PreviewRectification.from_mapping({"mode": "map"}).is_identity is False
    for extra in ({"mode": "map", "fx": 1.0}, {"mode": "map", "output_aspect": 0.0},
                  {"mode": "map", "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]},
                  {"mode": "map", "plane": 1}):
        with pytest.raises(ValueError):
            PreviewRectification.from_mapping(extra)
    with pytest.raises(ValueError):
        PreviewRectification.from_mapping({"mode": "plane"})
