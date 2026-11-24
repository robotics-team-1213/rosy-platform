import math

import cv2
import numpy as np
import pytest

from rosy_vision.detect import (
    detect_markers,
    generate_marker_image,
    generate_qr_image,
    parse_robot_qr_id,
)


def _jpeg_with_marker(marker_id=7):
    canvas = np.full((320, 320), 255, dtype=np.uint8)
    marker = generate_marker_image(marker_id, 140)
    canvas[90:230, 90:230] = marker
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 100])
    assert ok
    return encoded.tobytes()


def test_detect_markers_decodes_jpeg_and_returns_four_pixel_corners():
    found = detect_markers(_jpeg_with_marker())

    assert set(found) == {7}
    assert len(found[7]) == 4
    assert all(len(point) == 2 for point in found[7])


def test_detect_markers_returns_empty_for_invalid_jpeg():
    assert detect_markers(b"not a jpeg") == {}


def test_detect_markers_finds_a_ten_pixel_robot_sticker_in_a_ceiling_frame():
    # D-562: a 40 mm sticker (30 mm black) is ~10 px wide in the 1280x720 ceiling
    # frame; the OpenCV default minMarkerPerimeterRate 0.03 misses it.
    frame = np.full((720, 1280), 60, dtype=np.uint8)  # dark robot top
    frame[297:313, 597:613] = 255  # white rim
    frame[300:310, 600:610] = cv2.resize(generate_marker_image(40, 60), (10, 10),
                                         interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok

    assert set(detect_markers(encoded.tobytes())) == {40}


def test_detect_markers_rereads_an_eight_pixel_sticker_the_full_frame_pass_rejects():
    # D-575: on the site frame of 2026-10-09 the 9dfk sticker (id 41) was a rejected
    # candidate in every frame; a 4x crop around the candidate decodes it.
    frame = np.full((720, 1280), 60, dtype=np.uint8)
    frame[293:311, 597:611] = 255  # white rim
    frame[300:308, 600:608] = cv2.resize(generate_marker_image(41, 60), (8, 8),
                                         interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok

    found = detect_markers(encoded.tobytes())

    assert set(found) == {41}
    center = np.mean(found[41], axis=0)
    assert np.allclose(center, (604, 304), atol=1.0)


@pytest.mark.parametrize("text, expected", [
    ("ROSY-42", 42),
    ("ROSY-45", 45),
    ("ROSY-46", 46),
    ("ROSY-48", 48),
    ("rosy_45", 45),
    ("ROSY 42", 42),
    ("BOX-123", None),
    ("https://example.com/ROSY-45", None),
    ("rosyov://host:8443/?t=abc&s=ceiling_north", None),
    ("ROSY-100", None),
    ("ROSY-45-X", None),
])
def test_parse_robot_qr_id(text, expected):
    assert parse_robot_qr_id(text) == expected


@pytest.mark.parametrize("angle_deg", [0, 30, 90, 180, 270])
def test_detect_markers_decodes_rotated_robot_qr_and_preserves_top_edge(angle_deg):
    frame = np.full((720, 1280, 3), 85, dtype=np.uint8)
    qr = generate_qr_image("ROSY-45", 64, border_modules=2)
    pad = 112
    patch = np.full((pad, pad), 75, dtype=np.uint8)
    off = (pad - 64) // 2
    patch[off:off + 64, off:off + 64] = qr
    mat = cv2.getRotationMatrix2D((pad / 2, pad / 2), angle_deg, 1.0)
    rot = cv2.warpAffine(patch, mat, (pad, pad), borderValue=75, flags=cv2.INTER_LINEAR)
    x0, y0 = 560, 280
    frame[y0:y0 + pad, x0:x0 + pad] = cv2.cvtColor(rot, cv2.COLOR_GRAY2BGR)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok

    found = detect_markers(encoded.tobytes())
    assert set(found) == {45}
    assert 45 in found.qr_ids
    quad = np.asarray(found[45], dtype=float)
    center = quad.mean(axis=0)
    assert np.allclose(center, (x0 + pad / 2, y0 + pad / 2), atol=2.5)
    top_mid = (quad[0] + quad[1]) / 2
    # In image coords (y down), getRotationMatrix2D(+angle) rotates top (-90 deg) CCW to (-90 - angle).
    expected_rad = math.radians(-90.0 - angle_deg)
    measured_rad = math.atan2(top_mid[1] - center[1], top_mid[0] - center[0])
    assert abs(math.remainder(measured_rad - expected_rad, math.tau)) < math.radians(10.0)


def test_detect_markers_ignores_non_robot_qr_and_keeps_aruco_together():
    frame = np.full((720, 1280, 3), 85, dtype=np.uint8)
    # Place non-robot QR + ArUco id 40 + robot QR ROSY-45
    aruco_img = generate_marker_image(40, 48)
    frame[100:148, 100:148] = cv2.cvtColor(aruco_img, cv2.COLOR_GRAY2BGR)
    other_qr = generate_qr_image("BOX-123", 64, border_modules=2)
    frame[100:164, 300:364] = cv2.cvtColor(other_qr, cv2.COLOR_GRAY2BGR)
    robot_qr = generate_qr_image("ROSY-45", 64, border_modules=2)
    frame[300:364, 500:564] = cv2.cvtColor(robot_qr, cv2.COLOR_GRAY2BGR)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    assert ok

    found = detect_markers(encoded.tobytes())
    assert set(found) == {40, 45}
    assert found.qr_ids == frozenset({45})


def test_detect_markers_roi_zoom_decodes_small_top_sticker_and_ignores_unreadable_blur():
    frame = np.full((720, 1280, 3), 85, dtype=np.uint8)
    # Place a small 40 px QR sticker inside a dark robot silhouette (raw detectMulti misses <=40 px).
    frame[575:635, 295:355] = 35
    small_qr = generate_qr_image("ROSY-46", 40, border_modules=2)
    frame[585:625, 305:345] = cv2.cvtColor(small_qr, cv2.COLOR_GRAY2BGR)
    # Also place an unreadable tiny blurred patch elsewhere to ensure clean fallback without crash.
    frame[200:220, 420:440] = 230
    frame[204:216, 424:436] = 140
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok

    found = detect_markers(encoded.tobytes())
    assert 46 in found
    assert 46 in found.qr_ids
    quad = np.asarray(found[46], dtype=float)
    assert np.allclose(quad.mean(axis=0), (325.0, 605.0), atol=3.0)


def test_detect_markers_reread_small_caps_crops_and_qr_reread_can_be_skipped(monkeypatch):
    from rosy_vision import detect as detect_mod

    image = np.full((200, 200, 3), 120, dtype=np.uint8)
    rejected = [
        np.array([[10 + i * 15, 10], [18 + i * 15, 10], [18 + i * 15, 18], [10 + i * 15, 18]], dtype=float)
        for i in range(12)
    ]
    calls = []
    orig_detect = detect_mod._DETECT_MARKERS
    monkeypatch.setattr(detect_mod, "_DETECT_MARKERS", lambda _crop: (calls.append(1), ((), None, ()))[1])
    detect_mod._reread_small(image, rejected, {})
    assert len(calls) == detect_mod._REREAD_MAX_CROPS == 6
    monkeypatch.setattr(detect_mod, "_DETECT_MARKERS", orig_detect)

    qr_calls = []
    monkeypatch.setattr(detect_mod, "_reread_small_qr", lambda *args: qr_calls.append(1))
    frame = np.full((320, 320, 3), 255, dtype=np.uint8)
    marker = generate_marker_image(7, 140)
    frame[90:230, 90:230] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
    assert ok
    assert set(detect_markers(encoded.tobytes(), reread_qr=False)) == {7}
    assert set(detect_markers(encoded.tobytes(), expected_marker_ids={7})) == {7}
    assert qr_calls == []
    assert set(detect_markers(encoded.tobytes(), expected_marker_ids={7, 45})) == {7}
    assert len(qr_calls) == 1
