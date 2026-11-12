"""Lane observation contracts, IR/single-line/between detectors, wire payload, and loss tracker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import math
import time

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
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("IR calibration endpoints must be finite numbers")
        if self.min_span <= 0:
            raise ValueError("IR calibration min_span must be positive")
        if any(
            abs(float(white) - float(black)) < self.min_span
            for black, white in zip(self.black, self.white)
        ):
            raise ValueError("IR calibration endpoints are not physically separated")

    @property
    def revision(self) -> str:
        """Stable digest of the exact per-robot endpoints used to normalize IR."""
        payload = json.dumps(
            {
                "black": [float(value) for value in self.black],
                "white": [float(value) for value in self.white],
                "min_span": float(self.min_span),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def normalize(self, values) -> tuple[float, float, float]:
        if len(values) != 3:
            raise ValueError("IR sample requires left, centre, right values")
        normalized = []
        for raw, black, white in zip(values, self.black, self.white):
            if (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not math.isfinite(float(raw))
            ):
                raise ValueError("IR sample values must be finite numbers")
            value = (float(raw) - float(black)) / (float(white) - float(black))
            normalized.append(max(0.0, min(1.0, value)))
        return tuple(normalized)


def detect_ir_line(
    values,
    calibration: IRLineCalibration,
    *,
    min_white: float = 0.55,
    min_contrast: float = 0.15,
) -> LaneObservation | None:
    """Convert three calibrated reflectance channels to a line centroid."""
    if not 0.0 < min_white <= 1.0 or not 0.0 < min_contrast <= 1.0:
        raise ValueError("IR thresholds must be in (0, 1]")
    strengths = calibration.normalize(values)
    peak = max(strengths)
    contrast = peak - min(strengths)
    if peak < min_white or contrast < min_contrast:
        return None
    # Bright left and right over a darker centre are two separate bands
    # (260919 crosswalk stripes run along the lane), not one line.
    outer = min(strengths[0], strengths[2])
    if outer >= min_white and outer - strengths[1] >= min_contrast:
        return None
    total = sum(strengths)
    if total <= 0.0:
        return None
    error = (
        sum(weight * value for weight, value in zip((-1.0, 0.0, 1.0), strengths))
        / total
    )
    confidence = min(1.0, peak * min(1.0, contrast / 0.5))
    return LaneObservation(error=max(-1.0, min(1.0, error)), confidence=confidence)


def detect_lane_error(
    bgr: np.ndarray,
    *,
    bright_threshold: int = _BRIGHT,
    roi_top_fraction: float = 0.4,
    washed_fraction: float = _WASHED_FRACTION,
    min_pixels: int = 1,
) -> LaneObservation | None:
    """Find the lane centroid in the bottom band, or None when there is no
    lane to follow."""
    if (
        isinstance(bright_threshold, bool)
        or not isinstance(bright_threshold, int)
        or not 1 <= bright_threshold <= 254
    ):
        raise ValueError("bright_threshold must be an integer from 1 through 254")
    if (
        not isinstance(roi_top_fraction, (int, float))
        or not math.isfinite(roi_top_fraction)
        or not 0.0 <= roi_top_fraction < 1.0
    ):
        raise ValueError("roi_top_fraction must be in [0, 1)")
    if (
        not isinstance(washed_fraction, (int, float))
        or not math.isfinite(washed_fraction)
        or not 0.0 < washed_fraction <= 1.0
    ):
        raise ValueError("washed_fraction must be in (0, 1]")
    if isinstance(min_pixels, bool) or not isinstance(min_pixels, int) or min_pixels < 1:
        raise ValueError("min_pixels must be a positive integer")
    if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
        raise ValueError("camera frame must be a non-empty grayscale or BGR array")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    band = gray[int(gray.shape[0] * roi_top_fraction) :, :]
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


def _row_runs(bright_row: np.ndarray, min_run_px: int, max_run_px: float):
    """(first, last) lit column of each horizontal bright run of plausible
    boundary-line width."""
    lit = np.concatenate(([0], (bright_row > 0).astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(lit))
    return [
        (int(start), int(stop) - 1)
        for start, stop in zip(edges[0::2], edges[1::2])
        if min_run_px <= stop - start <= max_run_px
    ]


class LaneBetweenKeeper:
    """Image-space two-boundary lane keeper ('between' mode), no ground plane."""

    def __init__(
        self,
        *,
        default_lane_width_fraction: float = 0.6,
        width_alpha: float = 0.2,
    ) -> None:
        for name, value in (
            ("default_lane_width_fraction", default_lane_width_fraction),
            ("width_alpha", width_alpha),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.0 < value <= 1.0
            ):
                raise ValueError(f"{name} must be in (0, 1]")
        self._default_fraction = float(default_lane_width_fraction)
        self._alpha = float(width_alpha)
        self._widths: dict[int, float] = {}
        self._reference: float | None = None

    def reset(self) -> None:
        self._widths.clear()
        self._reference = None

    def lane_width_px(self, row: int, frame_width: int) -> float:
        return self._widths.get(row, self._default_fraction * frame_width)

    def update(
        self,
        bgr: np.ndarray,
        *,
        bright_threshold: int = _BRIGHT,
        roi_top_fraction: float = 0.6,
        washed_fraction: float = _WASHED_FRACTION,
        rows: int = 8,
        min_rows: int = 2,
        min_run_px: int = 2,
        max_run_fraction: float = 0.25,
    ) -> LaneObservation | None:
        if (
            isinstance(bright_threshold, bool)
            or not isinstance(bright_threshold, int)
            or not 1 <= bright_threshold <= 254
        ):
            raise ValueError("bright_threshold must be an integer from 1 through 254")
        if (
            isinstance(roi_top_fraction, bool)
            or not isinstance(roi_top_fraction, (int, float))
            or not math.isfinite(roi_top_fraction)
            or not 0.0 <= roi_top_fraction < 1.0
        ):
            raise ValueError("roi_top_fraction must be in [0, 1)")
        for name, value in (
            ("washed_fraction", washed_fraction),
            ("max_run_fraction", max_run_fraction),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.0 < value <= 1.0
            ):
                raise ValueError(f"{name} must be in (0, 1]")
        for name, value in (
            ("rows", rows),
            ("min_rows", min_rows),
            ("min_run_px", min_run_px),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(bgr, np.ndarray) or bgr.ndim not in (2, 3) or bgr.size == 0:
            raise ValueError("camera frame must be a non-empty grayscale or BGR array")
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        height, width = gray.shape[:2]
        top = min(int(height * roi_top_fraction), height - 1)
        _, bright = cv2.threshold(gray[top:, :], bright_threshold, 255, cv2.THRESH_BINARY)
        if (bright > 0).sum() > washed_fraction * bright.size:
            self._reference = None
            return None
        reference = width / 2.0 if self._reference is None else self._reference
        max_run_px = max_run_fraction * width
        both, one = [], []
        sampled = sorted(set(np.linspace(top, height - 1, rows).astype(int).tolist()))
        for row in sampled:
            left = right = None
            for first, last in _row_runs(bright[row - top], min_run_px, max_run_px):
                if (first + last) / 2.0 < reference:
                    left = last if left is None else max(left, last)
                elif right is None or first < right:
                    right = first
            if left is not None and right is not None:
                span = float(right - left)
                both.append((left + right) / 2.0)
                if span >= 0.1 * width:
                    previous = self._widths.get(row)
                    self._widths[row] = (
                        span
                        if previous is None
                        else previous + self._alpha * (span - previous)
                    )
            elif left is not None:
                one.append(left + self.lane_width_px(row, width) / 2.0)
            elif right is not None:
                one.append(right - self.lane_width_px(row, width) / 2.0)
        if len(both) >= min_rows:
            target = float(np.median(both))
            confidence = 0.5 + 0.5 * len(both) / len(sampled)
        elif len(both) + len(one) >= min_rows:
            target = float(np.median(both + one))
            confidence = 0.6 * (len(both) + len(one)) / len(sampled)
        else:
            self._reference = None
            return None
        target = max(0.0, min(float(width - 1), target))
        self._reference = target
        error = max(-1.0, min(1.0, (target - width / 2.0) / (width / 2.0)))
        return LaneObservation(error=error, confidence=min(1.0, confidence))


def detect_lane_between(bgr: np.ndarray, **kwargs) -> LaneObservation | None:
    """Stateless single-frame `LaneBetweenKeeper.update`."""
    return LaneBetweenKeeper().update(bgr, **kwargs)


#: Floor models a camera observation may be labelled with (D-364 section 3).
GROUND_LABELS = ("NOMINAL",)


def line_observation_payload(
    source: str,
    stamp: float,
    observation: LaneObservation | None,
    *,
    ir_calibrated: bool = False,
    calibration_revision: str | None = None,
    ground: str | None = None,
) -> dict:
    """One compact wire shape shared by IR and camera publishers."""
    if source not in ("IR_LINE", "CAMERA_LINE"):
        raise ValueError("unsupported line observation source")
    if (
        isinstance(stamp, bool)
        or not isinstance(stamp, (int, float))
        or not math.isfinite(float(stamp))
    ):
        raise ValueError("line observation stamp must be finite")
    if source == "IR_LINE":
        if type(ir_calibrated) is not bool:
            raise ValueError("IR calibrated marker must be a boolean")
        if ir_calibrated and (
            not isinstance(calibration_revision, str)
            or not calibration_revision.strip()
        ):
            raise ValueError("calibrated IR evidence requires a revision")
    metadata = (
        {"ir_calibrated": ir_calibrated, "calibration_revision": calibration_revision}
        if source == "IR_LINE"
        else {}
    )
    if ground is not None:
        if source != "CAMERA_LINE" or ground not in GROUND_LABELS:
            raise ValueError(
                "ground label is only for camera evidence: "
                + ", ".join(GROUND_LABELS)
            )
        metadata["ground"] = ground
    if observation is None:
        return {
            "source": source,
            "stamp": float(stamp),
            "visible": False,
            "error": None,
            "confidence": 0.0,
            **metadata,
        }
    return {
        "source": source,
        "stamp": float(stamp),
        "visible": True,
        "error": float(observation.error),
        "confidence": float(observation.confidence),
        **metadata,
    }


def steer_correction(
    error: float, *, gain: float = 1.0, max_angular: float = 0.4
) -> float:
    """Lane error to angular velocity (ROS CCW+)."""
    if (
        isinstance(error, bool)
        or not isinstance(error, (int, float))
        or not math.isfinite(float(error))
    ):
        raise ValueError("lane error must be a finite number")
    if (
        isinstance(gain, bool)
        or not isinstance(gain, (int, float))
        or not math.isfinite(float(gain))
        or not float(gain) > 0
    ):
        raise ValueError("steering gain must be positive")
    if (
        isinstance(max_angular, bool)
        or not isinstance(max_angular, (int, float))
        or not math.isfinite(float(max_angular))
        or not float(max_angular) > 0
    ):
        raise ValueError("max angular velocity must be positive")
    raw = -float(gain) * max(-1.0, min(1.0, float(error)))
    return max(-float(max_angular), min(float(max_angular), raw))


class LaneTracker:
    """Loss accounting. `update` feeds observations (None = missed frame);
    `stop_demanded` fires once the gap outlasts the grace period."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        lost_grace_s: float = LANE_LOST_GRACE_S,
    ) -> None:
        self._clock = clock
        self._grace = float(lost_grace_s)
        self.state = "IDLE"
        self._last_seen: float | None = None

    def update(
        self, observation: LaneObservation | None, at: float | None = None
    ) -> None:
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


__all__ = [
    "GROUND_LABELS",
    "IRLineCalibration",
    "LANE_LOST_GRACE_S",
    "LANE_MAX_LINEAR_M_S",
    "LaneBetweenKeeper",
    "LaneObservation",
    "LaneTracker",
    "_BRIGHT",
    "_WASHED_FRACTION",
    "_row_runs",
    "detect_ir_line",
    "detect_lane_between",
    "detect_lane_error",
    "line_observation_payload",
    "steer_correction",
]
