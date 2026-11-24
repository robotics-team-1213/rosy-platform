"""CPU ArUco and robot QR detector; OpenCV is deliberately isolated in this module."""

from __future__ import annotations

import re
from collections.abc import Iterable

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


def detect_markers(jpeg: bytes) -> DetectedMarkers:
    """Decode one JPEG and return marker corners; malformed frames are empty."""

    if not isinstance(jpeg, bytes) or not jpeg:
        return DetectedMarkers()
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return DetectedMarkers()
    corners, marker_ids, rejected = _DETECT_MARKERS(image)
    found: dict[int, MarkerQuad] = {}
    for marker_id, quad in zip(() if marker_ids is None else marker_ids.reshape(-1), corners):
        points = tuple((float(point[0]), float(point[1])) for point in quad.reshape(4, 2))
        found[int(marker_id)] = points  # type: ignore[assignment]
    _reread_small(image, rejected, found)
    qr_ids = _detect_qr_robot_markers(image, found)
    return DetectedMarkers(found, qr_ids=qr_ids)


class DetectedMarkers(dict):
    """Marker id -> 4 pixel corners; ``qr_ids`` names ids decoded from robot QR codes."""

    def __init__(self, *args, qr_ids: Iterable[int] = (), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.qr_ids: frozenset[int] = frozenset(qr_ids)


_QR_ROBOT_LABEL = re.compile(r"^\s*rosy[-_\s]?(\d{1,2})\s*$", re.IGNORECASE)
_QR_STD = cv2.QRCodeDetector()
_QR_ARUCO = cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else None
_QR_DETECTOR = _QR_ARUCO or _QR_STD
_QR_MIN_SIDE_PX = 12.0
_QR_MAX_CANDIDATES = 8
_QR_WARP_SIZE = 270
_QR_WARP_MARGIN = 30
_QR_WARP_DST = np.array([
    [_QR_WARP_MARGIN, _QR_WARP_MARGIN],
    [_QR_WARP_SIZE - _QR_WARP_MARGIN, _QR_WARP_MARGIN],
    [_QR_WARP_SIZE - _QR_WARP_MARGIN, _QR_WARP_SIZE - _QR_WARP_MARGIN],
    [_QR_WARP_MARGIN, _QR_WARP_SIZE - _QR_WARP_MARGIN],
], dtype=np.float32)


def parse_robot_qr_id(text: str) -> int | None:
    """Parse ``ROSY-45`` / ``rosy_45`` -> ``45``, or None for unrelated QR payloads."""
    if not isinstance(text, str):
        return None
    match = _QR_ROBOT_LABEL.fullmatch(text)
    return int(match.group(1)) if match else None


def generate_qr_image(text: str, side_pixels: int, *, border_modules: int = 2) -> np.ndarray:
    """Synthesize a square grayscale robot QR image (for unit tests)."""
    if side_pixels <= 0:
        raise ValueError("side_pixels must be positive")
    params = cv2.QRCodeEncoder_Params()
    params.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_L
    raw = cv2.QRCodeEncoder.create(params).encode(text)
    if border_modules > 0:
        raw = cv2.copyMakeBorder(raw, border_modules, border_modules, border_modules, border_modules,
                                 cv2.BORDER_CONSTANT, value=255)
    # Integer module scale first so module edges stay crisp before camera-like downsampling.
    uniform = cv2.resize(raw, None, fx=10, fy=10, interpolation=cv2.INTER_NEAREST)
    interp = cv2.INTER_AREA if side_pixels < uniform.shape[0] else cv2.INTER_NEAREST
    return cv2.resize(uniform, (side_pixels, side_pixels), interpolation=interp)


def _decode_qr_points(detector, image: np.ndarray, pts: np.ndarray) -> str:
    try:
        res = detector.decode(image, pts.reshape(1, 4, 2))
    except cv2.error:
        return ""
    if isinstance(res, tuple):
        return str(res[0] or "")
    return str(res or "")


def _quad_ok(pts: np.ndarray, *, min_side: float = _QR_MIN_SIDE_PX) -> bool:
    if pts.shape != (4, 2) or not np.all(np.isfinite(pts)):
        return False
    sides = [float(np.linalg.norm(pts[(i + 1) % 4] - pts[i])) for i in range(4)]
    return min(sides) >= min_side


def _decode_qr_quad(gray: np.ndarray, pts: np.ndarray) -> tuple[str, np.ndarray]:
    """Decode one detected QR quad and return ``(text, canonical_quad)``."""
    direct = _decode_qr_points(_QR_DETECTOR, gray, pts)
    if direct:
        return direct, pts
    try:
        h_mat = cv2.getPerspectiveTransform(pts.astype(np.float32), _QR_WARP_DST)
        warped = cv2.warpPerspective(gray, h_mat, (_QR_WARP_SIZE, _QR_WARP_SIZE),
                                     flags=cv2.INTER_CUBIC, borderValue=255)
    except cv2.error:
        return "", pts
    _, otsu = cv2.threshold(warped, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for candidate in (warped, otsu):
        for detector in (_QR_STD, _QR_ARUCO):
            if detector is None:
                continue
            try:
                text, w_pts, _ = detector.detectAndDecode(candidate)
            except cv2.error:
                text, w_pts = "", None
            if text:
                if w_pts is not None:
                    w_arr = np.asarray(w_pts, dtype=np.float32).reshape(-1, 2)
                    if w_arr.shape == (4, 2) and np.all(np.isfinite(w_arr)):
                        try:
                            mapped = cv2.perspectiveTransform(w_arr.reshape(1, 4, 2), np.linalg.inv(h_mat)).reshape(4, 2)
                            if _quad_ok(mapped):
                                return str(text), mapped
                        except (cv2.error, np.linalg.LinAlgError):
                            pass
                return str(text), pts
        decoded = _decode_qr_points(_QR_STD, candidate, _QR_WARP_DST)
        if decoded:
            return decoded, pts
    return "", pts


def _detect_qr_robot_markers(image: np.ndarray, found: dict[int, MarkerQuad]) -> set[int]:
    """Detect robot QR stickers on ``image`` without colliding with already-decoded ArUco ids."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    try:
        ok, quads = _QR_DETECTOR.detectMulti(gray)
    except cv2.error:
        return set()
    if not ok or quads is None:
        return set()
    qr_ids: set[int] = set()
    for raw_quad in quads[:_QR_MAX_CANDIDATES]:
        pts = np.asarray(raw_quad, dtype=np.float32).reshape(-1, 2)
        if not _quad_ok(pts):
            continue
        text, canonical = _decode_qr_quad(gray, pts)
        marker_id = parse_robot_qr_id(text)
        if marker_id is None or marker_id in found:
            continue
        found[marker_id] = tuple((float(x), float(y)) for x, y in canonical)  # type: ignore[assignment]
        qr_ids.add(marker_id)
    return qr_ids


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
