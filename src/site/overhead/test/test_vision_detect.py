import cv2
import numpy as np

from overhead.detect import detect_markers


def _jpeg_with_marker(marker_id=7):
    canvas = np.full((320, 320), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 140)
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
