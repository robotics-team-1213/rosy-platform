"""Preview-only camera lens undistortion and plane rectification (D-318)."""

from __future__ import annotations

import cv2
import numpy as np
from core_common.protocol.vision_preview import PreviewRectification


def rectify_jpeg(jpeg: bytes, settings: PreviewRectification) -> bytes:
    """Return a newly encoded preview; never modifies the source JPEG/frame."""
    if not isinstance(jpeg, bytes) or not jpeg:
        raise ValueError("preview JPEG is empty")
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("preview JPEG decode failed")
    height, width = image.shape[:2]
    if width < 2 or height < 2 or width > 8192 or height > 8192:
        raise ValueError("preview dimensions are outside the supported range")
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
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError("preview JPEG encode failed")
    return encoded.tobytes()
