import cv2
import numpy as np

from rosy_vision.detect import detect_markers, generate_marker_image


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
