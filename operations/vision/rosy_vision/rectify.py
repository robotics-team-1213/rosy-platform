"""Preview-only camera lens undistortion and plane rectification (D-318), and the
D-560 map plane: the raw frame warped to a top-down picture of the map through the
approved tracking calibration record. Both are display copies; the raw frame is untouched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import cv2
import numpy as np
from core_common.protocol.vision_preview import PreviewRectification

from rosy_vision.track.calibration import from_record

#: D-560 2: margin around ``track_bounds_m``, fixed scale, longest side, off-frame fill.
PLANE_MARGIN_M = 0.15
PLANE_PX_PER_M = 400.0
PLANE_MAX_SIDE_PX = 1920
PLANE_FILL_BGR = (24, 24, 24)


@dataclass(frozen=True)
class MapPlane:
    """A map-plane JPEG. Pixel (u, v) in canvas coordinates (pixel edges) is map
    ``x = min_x + u / px_per_m``, ``y = max_y - v / px_per_m``."""

    jpeg: bytes
    bounds_m: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y, margin included
    px_per_m: float
    size: tuple[int, int]
    revision: str
    #: Frame pixel index to plane pixel index (row-major 3x3), the matrix the warp used.
    image_to_plane: tuple[float, ...]


def crop_map_plane(plane: MapPlane, x: float, y: float, radius_m: float
                   ) -> tuple[bytes, tuple[int, int], tuple[float, float, float, float]] | None:
    """The signed robot neighborhood in map metres, clipped to this calibrated plane."""
    min_x, _, _, max_y = plane.bounds_m
    ppm = plane.px_per_m
    left = max(0, math.floor((x - radius_m - min_x) * ppm))
    right = min(plane.size[0], math.ceil((x + radius_m - min_x) * ppm))
    top = max(0, math.floor((max_y - y - radius_m) * ppm))
    bottom = min(plane.size[1], math.ceil((max_y - y + radius_m) * ppm))
    if right <= left or bottom <= top:
        return None
    image = _decode(plane.jpeg)[top:bottom, left:right]
    bounds = (min_x + left / ppm, max_y - bottom / ppm, min_x + right / ppm, max_y - top / ppm)
    return _encode(image), (right - left, bottom - top), bounds


def _decode(jpeg: bytes) -> np.ndarray:
    if not isinstance(jpeg, bytes) or not jpeg:
        raise ValueError("preview JPEG is empty")
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("preview JPEG decode failed")
    height, width = image.shape[:2]
    if width < 2 or height < 2 or width > 8192 or height > 8192:
        raise ValueError("preview dimensions are outside the supported range")
    return image


def _encode(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError("preview JPEG encode failed")
    return encoded.tobytes()


def map_plane_jpeg(jpeg: bytes, record: Mapping | None, *, source_id: str, map_id: str,
                   lens) -> MapPlane | None:
    """The D-560 map plane of ``jpeg``, or None when the record does not fit this frame
    (no record, another source/map/lens, or an aspect off by more than 1 %)."""
    image = _decode(jpeg)
    height, width = image.shape[:2]
    calibration = from_record(record, source_id=source_id, map_id=map_id,
                              frame_size=(width, height), lens=lens)
    if calibration is None:
        return None
    b = calibration.track_bounds_m
    min_x, min_y = round(b[0] - PLANE_MARGIN_M, 4), round(b[1] - PLANE_MARGIN_M, 4)
    max_x, max_y = round(b[2] + PLANE_MARGIN_M, 4), round(b[3] + PLANE_MARGIN_M, 4)
    span_x, span_y = max_x - min_x, max_y - min_y
    if not (span_x > 0 and span_y > 0):
        return None
    # Floor to the 4 decimals the header carries, so the header is the exact scale used.
    ppm = min(PLANE_PX_PER_M, math.floor(PLANE_MAX_SIDE_PX / max(span_x, span_y) * 1e4) / 1e4)
    out_w = max(2, min(PLANE_MAX_SIDE_PX, round(span_x * ppm)))
    out_h = max(2, min(PLANE_MAX_SIDE_PX, round(span_y * ppm)))
    # The header rectangle is exactly the image at this scale (rounding moves max_x, min_y).
    max_x, min_y = min_x + out_w / ppm, max_y - out_h / ppm
    # Map metres to plane pixel index; OpenCV puts pixel centres on integers, the header
    # formula uses pixel edges, hence the half pixel.
    map_to_plane = np.array([[ppm, 0.0, -min_x * ppm - 0.5],
                             [0.0, -ppm, max_y * ppm - 0.5],
                             [0.0, 0.0, 1.0]])
    image_to_plane = map_to_plane @ np.asarray(calibration.image_to_map, dtype=float).reshape(3, 3)
    # ponytail: plane points beyond the camera horizon would sample a mirrored image; an
    # overhead camera over track bounds + 15 cm never sees its horizon. Mask by w if one does.
    plane = cv2.warpPerspective(image, image_to_plane, (out_w, out_h), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=PLANE_FILL_BGR)
    return MapPlane(jpeg=_encode(plane), bounds_m=(min_x, min_y, max_x, max_y), px_per_m=ppm,
                    size=(out_w, out_h), revision=calibration.revision,
                    image_to_plane=tuple(float(v) for v in image_to_plane.reshape(-1)))


def rectify_jpeg(jpeg: bytes, settings: PreviewRectification) -> bytes:
    """Return a newly encoded preview; never modifies the source JPEG/frame."""
    image = _decode(jpeg)
    height, width = image.shape[:2]
    if settings.is_identity:
        return jpeg

    camera_matrix = np.array([
        [settings.fx * width, 0.0, settings.cx * width],
        [0.0, settings.fy * height, settings.cy * height],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    distortion = np.array([settings.k1, settings.k2, settings.p1,
                           settings.p2, settings.k3], dtype=np.float64)
    if np.any(distortion):
        image = cv2.undistort(image, camera_matrix, distortion)

    source = np.array([(x * (width - 1), y * (height - 1))
                       for x, y in settings.corners], dtype=np.float32)
    top = float(np.linalg.norm(source[1] - source[0]))
    bottom = float(np.linalg.norm(source[2] - source[3]))
    left = float(np.linalg.norm(source[3] - source[0]))
    right = float(np.linalg.norm(source[2] - source[1]))
    quad_width = max(2.0, (top + bottom) / 2 + 1.0)
    quad_height = max(2.0, (left + right) / 2 + 1.0)
    aspect = settings.output_aspect or quad_width / quad_height
    out_width = max(2, min(1920, round(quad_width)))
    out_height = max(2, round(out_width / aspect))
    if out_height > 1080:
        out_height = 1080
        out_width = max(2, min(1920, round(out_height * aspect)))
    target = np.array([(0, 0), (out_width - 1, 0),
                       (out_width - 1, out_height - 1), (0, out_height - 1)],
                      dtype=np.float32)
    homography = cv2.getPerspectiveTransform(source, target)
    image = cv2.warpPerspective(image, homography, (out_width, out_height))
    return _encode(image)
