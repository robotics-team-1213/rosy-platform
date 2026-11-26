"""Preview-only camera lens undistortion and plane rectification (D-318), and the
D-560 map plane: the raw frame warped to a top-down picture of the map through the
approved tracking calibration record. Both are display copies; the raw frame is untouched.
"""

from __future__ import annotations

import math
from collections import OrderedDict
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
_LUT_CACHE_MAX = 8
_LUT_CACHE: OrderedDict[tuple, tuple[np.ndarray, np.ndarray, np.ndarray]] = OrderedDict()


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
    valid_mask: np.ndarray


def crop_map_plane(plane: MapPlane, x: float, y: float, radius_m: float
                   ) -> tuple[bytes, tuple[int, int], tuple[float, float, float, float]] | None:
    """The signed robot neighborhood in map metres, clipped to this calibrated plane."""
    left, top, right, bottom = _crop_window(plane, x, y, radius_m)
    if right <= left or bottom <= top:
        return None
    image = _decode(plane.jpeg)[top:bottom, left:right]
    min_x, _, _, max_y = plane.bounds_m
    ppm = plane.px_per_m
    bounds = (min_x + left / ppm, max_y - bottom / ppm, min_x + right / ppm, max_y - top / ppm)
    return _encode(image), (right - left, bottom - top), bounds


def _crop_window(plane, x, y, radius_m):
    if not all(math.isfinite(v) for v in (x, y, radius_m)) or radius_m <= 0:
        raise ValueError("invalid map crop")
    min_x, _, _, max_y = plane.bounds_m
    ppm = plane.px_per_m
    return (max(0, round((x - radius_m - min_x) * ppm)),
            max(0, round((max_y - y - radius_m) * ppm)),
            min(plane.size[0], round((x + radius_m - min_x) * ppm)),
            min(plane.size[1], round((max_y - y + radius_m) * ppm)))


def plane_observed_fraction(plane: MapPlane, crop=None) -> float:
    mask = plane.valid_mask
    if crop is not None:
        left, top, right, bottom = _crop_window(plane, *crop)
        if right <= left or bottom <= top:
            return 0.0
        mask = mask[top:bottom, left:right]
    return float(mask.mean())


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


def _build_plane_lut(image_to_plane: np.ndarray, centre_plane: np.ndarray,
                     width: int, height: int, out_w: int, out_h: int,
                     lp: Mapping | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    u, v = np.meshgrid(np.arange(out_w, dtype=np.float64), np.arange(out_h, dtype=np.float64))
    inverse = np.linalg.inv(image_to_plane)
    raw = inverse @ np.stack((u.ravel(), v.ravel(), np.ones(u.size, dtype=np.float64)))
    reference_w = float((inverse @ centre_plane)[2])
    with np.errstate(divide="ignore", invalid="ignore"):
        xu, yu = raw[0] / raw[2], raw[1] / raw[2]
    if lp is not None and any(abs(float(c)) > 1e-12 for c in lp["D"]):
        k = np.asarray(lp["K"], dtype=np.float64)
        d = [float(c) for c in lp["D"]]
        fx, fy, cx, cy = k[0, 0], k[1, 1], k[0, 2], k[1, 2]
        xn, yn = (xu - cx) / fx, (yu - cy) / fy
        if lp["model"] == "fisheye":
            r = np.hypot(xn, yn)
            th = np.arctan(r)
            t2 = th * th
            thd = th * (1.0 + d[0] * t2 + d[1] * t2 * t2 + d[2] * (t2 ** 3) + d[3] * (t2 ** 4))
            scale = np.where(r > 1e-12, thd / np.maximum(r, 1e-12), 1.0)
            xd, yd = xn * scale, yn * scale
        else:
            r2 = xn * xn + yn * yn
            k1, k2, p1, p2 = d[0], d[1], d[2], d[3]
            k3 = d[4] if len(d) > 4 else 0.0
            rad = 1.0 + k1 * r2 + k2 * (r2 * r2) + k3 * (r2 * r2 * r2)
            xd = xn * rad + 2.0 * p1 * xn * yn + p2 * (r2 + 2.0 * xn * xn)
            yd = yn * rad + p1 * (r2 + 2.0 * yn * yn) + 2.0 * p2 * xn * yn
        x, y = xd * fx + cx, yd * fy + cy
    else:
        x, y = xu, yu
    valid = (np.isfinite(x) & np.isfinite(y) & (raw[2] * reference_w > 1e-12)
             & (x >= 0) & (y >= 0) & (x < width - 1) & (y < height - 1)).reshape(out_h, out_w)
    map_x = np.where(valid, x.reshape(out_h, out_w), -1.0).astype(np.float32)
    map_y = np.where(valid, y.reshape(out_h, out_w), -1.0).astype(np.float32)
    return map_x, map_y, valid


def map_plane_jpeg(jpeg: bytes, record: Mapping | None, *, source_id: str, map_id: str,
                   lens) -> MapPlane | None:
    """The D-560 map plane of ``jpeg``, or None when the record does not fit this frame."""
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
    ppm = min(PLANE_PX_PER_M, math.floor(PLANE_MAX_SIDE_PX / max(span_x, span_y) * 1e4) / 1e4)
    out_w = max(2, min(PLANE_MAX_SIDE_PX, round(span_x * ppm)))
    out_h = max(2, min(PLANE_MAX_SIDE_PX, round(span_y * ppm)))
    max_x, min_y = min_x + out_w / ppm, max_y - out_h / ppm
    map_to_plane = np.array([[ppm, 0.0, -min_x * ppm - 0.5],
                             [0.0, -ppm, max_y * ppm - 0.5],
                             [0.0, 0.0, 1.0]])
    image_to_plane = map_to_plane @ np.asarray(calibration.image_to_map, dtype=float).reshape(3, 3)
    centre_plane = map_to_plane @ np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 1.0])
    lp = calibration.lens_profile
    lp_key = None if lp is None else (lp["model"], tuple(v for row in lp["K"] for v in row), tuple(lp["D"]))
    cache_key = (calibration.revision, width, height, out_w, out_h, min_x, min_y, max_x, max_y, ppm,
                 calibration.image_to_map, lp_key)
    cached = _LUT_CACHE.get(cache_key)
    if cached is not None:
        _LUT_CACHE.move_to_end(cache_key)
        map_x, map_y, valid = cached
    else:
        map_x, map_y, valid = _build_plane_lut(image_to_plane, centre_plane, width, height, out_w, out_h, lp)
        _LUT_CACHE[cache_key] = (map_x, map_y, valid)
        if len(_LUT_CACHE) > _LUT_CACHE_MAX:
            _LUT_CACHE.popitem(last=False)

    plane = cv2.remap(image, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=PLANE_FILL_BGR)
    u_i, v_i = np.meshgrid(np.arange(out_w), np.arange(out_h))
    hatch = np.where(((u_i + v_i) // 8) % 2 == 0, 24, 40).astype(np.uint8)
    plane[~valid] = hatch[~valid, None]
    return MapPlane(jpeg=_encode(plane), bounds_m=(min_x, min_y, max_x, max_y), px_per_m=ppm,
                    size=(out_w, out_h), revision=calibration.revision,
                    image_to_plane=tuple(float(v) for v in image_to_plane.reshape(-1)), valid_mask=valid)


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
    source = np.array([(x * (width - 1), y * (height - 1))
                       for x, y in settings.corners], dtype=np.float32)
    if np.any(distortion):
        image = cv2.undistort(image, camera_matrix, distortion)
        source = cv2.undistortPoints(source.reshape(-1, 1, 2), camera_matrix, distortion,
                                     P=camera_matrix).reshape(-1, 2).astype(np.float32)
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
