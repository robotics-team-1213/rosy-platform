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

# D-575: a 40 mm sticker is ~10 px on the ceiling frame and decodes in only part of
# the frames (D-562: ~61 %). A rejected candidate this small is read once more from
# a 4x crop around it; the full frame is never enlarged (D-562 rejected that for CPU).
_REREAD_MAX_PX = 16
_REREAD_SCALE = 4
_REREAD_PAD_PX = 6
_REREAD_BORDER_PX = 20


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
    corners, marker_ids, rejected = _DETECT_MARKERS(image)
    found: dict[int, MarkerQuad] = {}
    for marker_id, quad in zip(() if marker_ids is None else marker_ids.reshape(-1), corners):
        points = tuple((float(point[0]), float(point[1])) for point in quad.reshape(4, 2))
        found[int(marker_id)] = points  # type: ignore[assignment]
    _reread_small(image, rejected, found)
    return found


def _reread_small(image, rejected, found: dict[int, MarkerQuad]) -> None:
    """D-575: decode small rejected candidates from an enlarged crop; first id wins."""
    height, width = image.shape[:2]
    pad, scale, border = _REREAD_PAD_PX, _REREAD_SCALE, _REREAD_BORDER_PX
    for candidate in rejected:
        points = np.asarray(candidate, dtype=float).reshape(4, 2)
        low, high = points.min(axis=0), points.max(axis=0)
        if (high - low).max() > _REREAD_MAX_PX:
            continue
        x0, y0 = (max(0, int(v) - pad) for v in np.floor(low))
        x1, y1 = min(width, int(np.ceil(high[0])) + pad), min(height, int(np.ceil(high[1])) + pad)
        if x1 <= x0 or y1 <= y0:
            continue
        crop = cv2.resize(image[y0:y1, x0:x1], None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_CUBIC)
        crop = cv2.copyMakeBorder(crop, border, border, border, border, cv2.BORDER_REPLICATE)
        corners, marker_ids, _ = _DETECT_MARKERS(crop)
        if marker_ids is None:
            continue
        for marker_id, quad in zip(marker_ids.reshape(-1), corners):
            if int(marker_id) in found:
                continue
            back = (quad.reshape(4, 2) - border + 0.5) / scale - 0.5 + (x0, y0)
            found[int(marker_id)] = tuple(  # type: ignore[assignment]
                (float(x), float(y)) for x, y in back)
