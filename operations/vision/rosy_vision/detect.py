"""CPU ArUco detector; OpenCV is deliberately isolated in this module."""

from __future__ import annotations

import cv2
import numpy as np

from rosy_vision.project import MarkerQuad

_DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def _detector_parameters(aruco):
    """4.6-era `DetectorParameters_create` when present — on those builds a
    direct `DetectorParameters()` construction feeds detectMarkers a native
    object it segfaults on (dock_tag.py hit the same wall)."""
    create = getattr(aruco, "DetectorParameters_create", None)
    return create() if create is not None else aruco.DetectorParameters()


_PARAMETERS = _detector_parameters(cv2.aruco)
# D-562: a 40 mm robot sticker is ~10 px on the 1280x720 ceiling frame; the
# 0.03 default drops it. 0.015 kept the wrong-id count on 124 real frames.
_PARAMETERS.minMarkerPerimeterRate = 0.015


def _marker_detector(aruco):
    """detectMarkers for DICT_4X4_50 on any shipped OpenCV: the 4.7+
    `ArucoDetector` when present, else the 4.6-era module function on a
    grayscale frame (dock_tag.py precedent — CI and the device image ship
    4.6)."""
    if hasattr(aruco, "ArucoDetector"):
        return aruco.ArucoDetector(_DICTIONARY, _PARAMETERS).detectMarkers

    def _detect_legacy(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return aruco.detectMarkers(gray, _DICTIONARY, parameters=_PARAMETERS)

    return _detect_legacy


_DETECT_MARKERS = _marker_detector(cv2.aruco)


def generate_marker_image(marker_id: int, side_pixels: int):
    """Synthesize one DICT_4X4_50 marker on any shipped OpenCV: 4.7+
    `generateImageMarker`, else the 4.6-era `drawMarker` (same version gap
    as _marker_detector; tests use this to build fixtures)."""
    generate = getattr(cv2.aruco, "generateImageMarker", None)
    if generate is not None:
        return generate(_DICTIONARY, marker_id, side_pixels)
    return cv2.aruco.drawMarker(_DICTIONARY, marker_id, side_pixels)


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
