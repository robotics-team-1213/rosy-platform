"""Subject: JPEG bytes for camera/front/compressed (D-373 decision 3).

The capture stream is encoded from the frame camera_detect_node already holds,
so the recorded pixels are the ones perception saw. It never leaves the robot
(D-136); it exists so the snapshot ring buffer fits in memory."""

from __future__ import annotations

import cv2
import numpy as np

DEFAULT_QUALITY = 85
FORMAT = "jpeg"  # sensor_msgs/CompressedImage.format understood by image_transport


def encode_jpeg(bgr: np.ndarray, quality: int = DEFAULT_QUALITY) -> tuple[bytes, str]:
    q = int(quality)
    if not 1 <= q <= 100:
        raise ValueError(f"JPEG quality {quality} outside 1..100")
    ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(bgr), [int(cv2.IMWRITE_JPEG_QUALITY), q])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes(), FORMAT
