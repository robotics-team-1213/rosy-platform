"""CPU ArUco detector; OpenCV is deliberately isolated in this module."""

from __future__ import annotations

import cv2
import numpy as np

from overhead.project import MarkerQuad

_DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_PARAMETERS = cv2.aruco.DetectorParameters()


def _marker_detector(aruco):
    """detectMarkers for DICT_4X4_50 on any shipped OpenCV: the 4.7+
    `ArucoDetector` when present, else the 4.6-era module function
    (dock_tag.py precedent — CI and the device image ship 4.6)."""
    if hasattr(aruco, "ArucoDetector"):
        return aruco.ArucoDetector(_DICTIONARY, _PARAMETERS).detectMarkers
    return lambda image: aruco.detectMarkers(
        image, _DICTIONARY, parameters=_PARAMETERS)


_DETECT_MARKERS = _marker_detector(cv2.aruco)


def detect_markers(jpeg: bytes) -> dict[int, MarkerQuad]:
    """Decode one JPEG and return marker corners; malformed frames are empty."""

    if not isinstance(jpeg, bytes) or not jpeg:
        return {}
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return {}
    corners, marker_ids, _rejected = _DETECT_MARKERS(image)
    if marker_ids is None:
        return {}
    found: dict[int, MarkerQuad] = {}
    for marker_id, quad in zip(marker_ids.reshape(-1), corners):
        points = tuple((float(point[0]), float(point[1])) for point in quad.reshape(4, 2))
        found[int(marker_id)] = points  # type: ignore[assignment]
    return found
