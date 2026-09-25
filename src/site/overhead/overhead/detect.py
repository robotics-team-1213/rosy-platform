"""CPU ArUco detector; OpenCV is deliberately isolated in this module."""

from __future__ import annotations

import cv2
import numpy as np

from overhead.project import MarkerQuad

_DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_PARAMETERS = cv2.aruco.DetectorParameters()
_DETECTOR = cv2.aruco.ArucoDetector(_DICTIONARY, _PARAMETERS)


def detect_markers(jpeg: bytes) -> dict[int, MarkerQuad]:
    """Decode one JPEG and return marker corners; malformed frames are empty."""

    if not isinstance(jpeg, bytes) or not jpeg:
        return {}
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return {}
    corners, marker_ids, _rejected = _DETECTOR.detectMarkers(image)
    if marker_ids is None:
        return {}
    found: dict[int, MarkerQuad] = {}
    for marker_id, quad in zip(marker_ids.reshape(-1), corners):
        points = tuple((float(point[0]), float(point[1])) for point in quad.reshape(4, 2))
        found[int(marker_id)] = points  # type: ignore[assignment]
    return found
