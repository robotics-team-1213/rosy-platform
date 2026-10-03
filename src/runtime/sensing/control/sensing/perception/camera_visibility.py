"""Subject: conservative raw-frame low-light evidence, never enhanced pixels.

The camera's frozen exposure may produce coloured darkness well above digital
black. A tiny bright lamp must not make the dark road appear observable. These
initial conservative thresholds are an observation gate, not a lux calibration.
"""

import cv2
import numpy as np


def visibility_reason(bgr: np.ndarray) -> str:
    if (not isinstance(bgr, np.ndarray) or bgr.dtype != np.uint8
            or bgr.ndim != 3 or bgr.shape[2] != 3 or min(bgr.shape[:2]) < 8):
        return 'low_light'
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # A bright ceiling/lamp is not evidence that the road is observable.
    road = gray[int(h * .35):int(h * .95), int(w * .10):int(w * .90)]
    # Clipped road pixels cannot distinguish white paint from its background.
    # Luminance avoids treating a saturated colour channel as white clipping.
    if np.mean(road > 247) > .95:
        return 'overexposed'
    p90, p99 = np.percentile(road, [90, 99])
    return 'low_light' if p90 < 45 and p99 < 80 else 'usable'


def is_low_light(bgr: np.ndarray) -> bool:
    return visibility_reason(bgr) == 'low_light'
