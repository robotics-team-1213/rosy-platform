"""Subject: lane following — floor line to lateral error plus loss tracking.

Two camera modes share one LaneObservation contract, both classical CV with
no model and no YOLO (SRS NAV-007):

  single line   one bright line on a dark floor; threshold plus column centroid
                (`detect_lane_error`)
  two-line lane a lane bounded by two white lines; per-row line runs projected
                to metres on a calibrated ground plane, steering to the midpoint
                (`detect_lane_centre`). No ground plane, no lane mode.

The tracker turns the observation stream into TRACKING/LOST: loss beyond the
grace period demands stop, never a blind search drive. ROS-free, same contract
onboard and in fixtures.
"""

from __future__ import annotations

import time
import math
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np


#: NAV-007 lane crawl cap. A separate mode cap, not the SAF-004 profile cap.
LANE_MAX_LINEAR_M_S = 0.10

#: Loss grace before stop is demanded (SRS NAV-007: 3 s).
LANE_LOST_GRACE_S = 3.0

_BRIGHT = 180
_WASHED_FRACTION = 0.40


@dataclass(frozen=True)
class LaneObservation:
    """Lateral error in [-1, 1]: 0 centred, positive means the lane is right
    of centre (steer right)."""

    error: float
    confidence: float


@dataclass(frozen=True)
class IRLineCalibration:
    """Per-channel black/white endpoints in robot left/centre/right order.

    Endpoint order carries polarity, so hardware whose ADC reads lower on
    white does not need a separate and easily-misconfigured boolean.
    """

    black: tuple[float, float, float]
    white: tuple[float, float, float]
    min_span: float = 100.0

    def __post_init__(self) -> None:
        if len(self.black) != 3 or len(self.white) != 3:
            raise ValueError("IR calibration requires left, centre, right endpoints")
        values = tuple(self.black) + tuple(self.white) + (self.min_span,)
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(float(value)) for value in values):
            raise ValueError("IR calibration endpoints must be finite numbers")
        if self.min_span <= 0:
            raise ValueError("IR calibration min_span must be positive")
        if any(abs(float(white) - float(black)) < self.min_span
               for black, white in zip(self.black, self.white)):
            raise ValueError("IR calibration endpoints are not physically separated")

    def normalize(self, values) -> tuple[float, float, float]:
        if len(values) != 3:
            raise ValueError("IR sample requires left, centre, right values")
        normalized = []
        for raw, black, white in zip(values, self.black, self.white):
            if (isinstance(raw, bool) or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))):
                raise ValueError("IR sample values must be finite numbers")
            value = (float(raw) - float(black)) / (float(white) - float(black))
            normalized.append(max(0.0, min(1.0, value)))
        return tuple(normalized)


def detect_ir_line(values, calibration: IRLineCalibration, *,
                   min_white: float = 0.55,
                   min_contrast: float = 0.15) -> LaneObservation | None:
    """Convert three calibrated reflectance channels to a line centroid."""
    if not 0.0 < min_white <= 1.0 or not 0.0 < min_contrast <= 1.0:
        raise ValueError("IR thresholds must be in (0, 1]")
    strengths = calibration.normalize(values)
    peak = max(strengths)
    contrast = peak - min(strengths)
    if peak < min_white or contrast < min_contrast:
        return None
    total = sum(strengths)
    if total <= 0.0:
        return None
    error = sum(weight * value for weight, value in zip((-1.0, 0.0, 1.0), strengths)) / total
    confidence = min(1.0, peak * min(1.0, contrast / 0.5))
    return LaneObservation(error=max(-1.0, min(1.0, error)), confidence=confidence)


def detect_lane_error(bgr: np.ndarray, *, bright_threshold: int = _BRIGHT,
                      roi_top_fraction: float = 0.4,
                      washed_fraction: float = _WASHED_FRACTION,
                      min_pixels: int = 1) -> LaneObservation | None:
    """Find the lane centroid in the bottom band, or None when there is no
    lane to follow. A washed-out frame (lights on full white) is also None —
    driving on would be a guess, not tracking."""
    if (isinstance(bright_threshold, bool) or not isinstance(bright_threshold, int)
            or not 1 <= bright_threshold <= 254):
        raise ValueError("bright_threshold must be an integer from 1 through 254")
    if not isinstance(roi_top_fraction, (int, float)) or not math.isfinite(roi_top_fraction) \
            or not 0.0 <= roi_top_fraction < 1.0:
        raise ValueError("roi_top_fraction must be in [0, 1)")
    if not isinstance(washed_fraction, (int, float)) or not math.isfinite(washed_fraction) \
            or not 0.0 < washed_fraction <= 1.0:
        raise ValueError("washed_fraction must be in (0, 1]")
    if isinstance(min_pixels, bool) or not isinstance(min_pixels, int) or min_pixels < 1:
        raise ValueError("min_pixels must be a positive integer")
    if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
        raise ValueError("camera frame must be a non-empty grayscale or BGR array")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    band = gray[int(gray.shape[0] * roi_top_fraction):, :]
    _, bright = cv2.threshold(band, bright_threshold, 255, cv2.THRESH_BINARY)
    lit = (bright > 0).sum()
    if lit < min_pixels:
        return None
    if lit > washed_fraction * band.size:
        return None
    column = bright.sum(axis=0).astype(np.float64)
    total = float(column.sum())
    width = float(band.shape[1])
    centroid = float((column * np.arange(band.shape[1])).sum() / total)
    error = max(-1.0, min(1.0, (centroid - width / 2.0) / (width / 2.0)))
    confidence = min(1.0, float(lit) / 1500.0)
    if confidence <= 0.0:
        return None
    return LaneObservation(error=error, confidence=confidence)


def detect_lane_centre(bgr: np.ndarray, ground, *,
                       bright_threshold: int = _BRIGHT,
                       lane_half_width_m: float,
                       roi_top_fraction: float,
                       roi_bottom_fraction: float,
                       washed_fraction: float = _WASHED_FRACTION,
                       max_line_width_m: float = 0.06,
                       row_step: int = 2) -> LaneObservation | None:
    """Steer to the midpoint between the two boundary lines of a lane.

    Each sampled row is split into horizontal runs of bright pixels, projected
    to metres on `ground` (+ right of the optical axis). The nearest run on each
    side is a boundary line; runs wider than `max_line_width_m` are stop lines
    or crosswalk bars seen across and are dropped. With one line in view the
    centre is inferred from the lane half-width. `ground is None` returns None:
    an uncalibrated camera never drives in lane mode.
    """
    if (isinstance(bright_threshold, bool) or not isinstance(bright_threshold, int)
            or not 1 <= bright_threshold <= 254):
        raise ValueError("bright_threshold must be an integer from 1 through 254")
    if (isinstance(lane_half_width_m, bool)
            or not isinstance(lane_half_width_m, (int, float))
            or not math.isfinite(lane_half_width_m) or not lane_half_width_m > 0.0):
        raise ValueError("lane_half_width_m must be a positive finite number")
    if not isinstance(roi_top_fraction, (int, float)) or not math.isfinite(roi_top_fraction)             or not 0.0 <= roi_top_fraction < 1.0:
        raise ValueError("roi_top_fraction must be in [0, 1)")
    if not isinstance(roi_bottom_fraction, (int, float))             or not math.isfinite(roi_bottom_fraction)             or not roi_top_fraction < roi_bottom_fraction <= 1.0:
        raise ValueError("roi_bottom_fraction must be in (roi_top_fraction, 1]")
    if not isinstance(washed_fraction, (int, float)) or not math.isfinite(washed_fraction)             or not 0.0 < washed_fraction <= 1.0:
        raise ValueError("washed_fraction must be in (0, 1]")
    if (isinstance(max_line_width_m, bool)
            or not isinstance(max_line_width_m, (int, float))
            or not math.isfinite(max_line_width_m) or not max_line_width_m > 0.0):
        raise ValueError("max_line_width_m must be a positive finite number")
    if isinstance(row_step, bool) or not isinstance(row_step, int) or row_step < 1:
        raise ValueError("row_step must be a positive integer")
    if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
        raise ValueError("camera frame must be a non-empty grayscale or BGR array")
    if ground is None:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    top = int(gray.shape[0] * roi_top_fraction)
    bottom = int(gray.shape[0] * roi_bottom_fraction)
    band = gray[top:bottom, :]
    if band.size == 0:
        return None
    _, bright = cv2.threshold(band, bright_threshold, 255, cv2.THRESH_BINARY)
    if (bright > 0).sum() > washed_fraction * band.size:
        return None

    half = float(lane_half_width_m)
    sampled = 0
    centres = []
    for offset in range(0, band.shape[0], row_step):
        sampled += 1
        row = top + offset
        if ground.distance(row) is None:
            continue
        lit = np.concatenate(([0], (bright[offset] > 0).astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(lit))
        left = right = None
        for start, stop in zip(edges[0::2], edges[1::2]):
            # Pixel centres sit on integer columns; the run spans half a pixel
            # beyond its first and last lit column.
            near = ground.lateral(start - 0.5, row)
            far = ground.lateral(stop - 0.5, row)
            middle = ground.lateral((start + stop - 1) / 2.0, row)
            if near is None or far is None or middle is None:
                continue
            if far - near > max_line_width_m:
                continue
            if middle < 0.0:
                if left is None or middle > left:
                    left = middle
            elif right is None or middle < right:
                right = middle
        if left is not None and right is not None:
            if not 1.2 * half <= right - left <= 2.8 * half:
                continue
            centres.append((left + right) / 2.0)
        elif left is not None:
            centres.append(left + half)
        elif right is not None:
            centres.append(right - half)
    if not centres or sampled == 0:
        return None
    error = max(-1.0, min(1.0, float(np.median(centres)) / half))
    return LaneObservation(error=error, confidence=len(centres) / sampled)


def line_observation_payload(source: str, stamp: float,
                             observation: LaneObservation | None) -> dict:
    """One compact wire shape shared by IR and camera publishers."""
    if source not in ("IR_LINE", "CAMERA_LINE"):
        raise ValueError("unsupported line observation source")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) \
            or not math.isfinite(float(stamp)):
        raise ValueError("line observation stamp must be finite")
    if observation is None:
        return {
            "source": source,
            "stamp": float(stamp),
            "visible": False,
            "error": None,
            "confidence": 0.0,
        }
    return {
        "source": source,
        "stamp": float(stamp),
        "visible": True,
        "error": float(observation.error),
        "confidence": float(observation.confidence),
    }


def steer_correction(error: float, *, gain: float = 1.0,
                     max_angular: float = 0.4) -> float:
    """Lane error to angular velocity (ROS CCW+). Positive error (lane right
    of centre) steers right, i.e. negative. Saturated, never NaN — a steering
    function that throws mid-drive is a stop by accident."""
    if (isinstance(error, bool) or not isinstance(error, (int, float))
            or not math.isfinite(float(error))):
        raise ValueError("lane error must be a finite number")
    if (isinstance(gain, bool) or not isinstance(gain, (int, float))
            or not math.isfinite(float(gain)) or not float(gain) > 0):
        raise ValueError("steering gain must be positive")
    if (isinstance(max_angular, bool) or not isinstance(max_angular, (int, float))
            or not math.isfinite(float(max_angular)) or not float(max_angular) > 0):
        raise ValueError("max angular velocity must be positive")
    raw = -float(gain) * max(-1.0, min(1.0, float(error)))
    return max(-float(max_angular), min(float(max_angular), raw))


class LaneTracker:
    """Loss accounting. `update` feeds observations (None = missed frame);
    `stop_demanded` fires once the gap outlasts the grace period."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 lost_grace_s: float = LANE_LOST_GRACE_S) -> None:
        self._clock = clock
        self._grace = float(lost_grace_s)
        self.state = "IDLE"
        self._last_seen: float | None = None

    def update(self, observation: LaneObservation | None, at: float | None = None) -> None:
        now = self._clock() if at is None else at
        if observation is None:
            return
        self._last_seen = now
        self.state = "TRACKING"

    def stop_demanded(self, at: float | None = None) -> bool:
        if self._last_seen is None:
            return False
        now = self._clock() if at is None else at
        if now - self._last_seen > self._grace:
            self.state = "LOST"
            return True
        return False
