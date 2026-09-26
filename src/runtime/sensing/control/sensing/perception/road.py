"""ROS-free camera evidence for semantic road markings and traffic signals.

Semantic truth from the simulation scene is deliberately not an input here.
The detector sees only the BGR camera frame and an optional, independently
validated ground-plane model used for metric range.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2
import numpy as np

from .lane import LaneObservation


@dataclass(frozen=True)
class RoadPerceptionConfig:
    bright_threshold: int = 180
    lane_roi_top_fraction: float = 0.30
    horizontal_min_fraction: float = 0.40
    horizontal_padding_px: int = 2
    crosswalk_min_bars: int = 3
    crosswalk_max_gap_px: int = 20
    signal_roi_bottom_fraction: float = 0.35
    signal_min_pixels: int = 50


@dataclass(frozen=True)
class RoadPreviewConfig:
    """Hard transport budget for the observation-only dashboard stream."""

    fps: float = 2.0
    max_width: int = 640
    jpeg_quality: int = 72
    max_bytes: int = 512_000
    source: str = "PINKY"

    def __post_init__(self) -> None:
        fps = float(self.fps)
        if isinstance(self.fps, bool) or not math.isfinite(fps) \
                or not 0.2 <= fps <= 2.0:
            raise ValueError("preview fps must be finite and in [0.2, 2.0]")
        if isinstance(self.max_width, bool) \
                or not 160 <= int(self.max_width) <= 640:
            raise ValueError("preview max_width must be in [160, 640]")
        if isinstance(self.jpeg_quality, bool) \
                or not 40 <= int(self.jpeg_quality) <= 90:
            raise ValueError("preview jpeg_quality must be in [40, 90]")
        if isinstance(self.max_bytes, bool) \
                or not 4 <= int(self.max_bytes) <= 512_000:
            raise ValueError("preview max_bytes must be in [4, 512000]")
        if not str(self.source).strip():
            raise ValueError("preview source is required")


class PreviewRateLimiter:
    """Local-clock limiter, independent from replayed ROS capture stamps."""

    def __init__(self, *, fps: float) -> None:
        value = float(fps)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("preview limiter fps must be positive and finite")
        self._interval_s = 1.0 / value
        self._last_allowed: float | None = None

    def allow(self, now: float) -> bool:
        current = float(now)
        if not math.isfinite(current):
            return False
        if (self._last_allowed is None or current < self._last_allowed
                or current - self._last_allowed >= self._interval_s):
            self._last_allowed = current
            return True
        return False


@dataclass(frozen=True)
class RoadMarkingObservation:
    image_row: float
    distance_m: float | None
    confidence: float


@dataclass(frozen=True)
class TrafficSignalObservation:
    colour: str
    confidence: float


@dataclass(frozen=True)
class RoadObservation:
    lane: LaneObservation | None
    stop_line: RoadMarkingObservation | None
    crosswalk: RoadMarkingObservation | None
    signal: TrafficSignalObservation | None
    signal_conflict: bool = False


def render_road_preview(bgr: np.ndarray, observation: RoadObservation, *,
                        source: str, max_width: int = 640) -> np.ndarray:
    """Render an observation-only preview; never feed this back to detection."""
    if not isinstance(bgr, np.ndarray) or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("road preview requires a BGR frame")
    if not isinstance(observation, RoadObservation):
        raise ValueError("road preview requires a RoadObservation")
    limit = int(max_width)
    if limit < 160 or limit > 640:
        raise ValueError("road preview max_width must be in [160, 640]")
    scale = min(1.0, limit / float(bgr.shape[1]))
    width = max(1, int(round(bgr.shape[1] * scale)))
    height = max(1, int(round(bgr.shape[0] * scale)))
    preview = cv2.resize(
        bgr, (width, height), interpolation=cv2.INTER_AREA).copy()
    cyan = (255, 220, 0)
    white = (245, 248, 250)
    shadow = (12, 18, 28)

    if observation.lane is not None:
        lane_x = int(round(
            width * (0.5 + 0.5 * float(observation.lane.error))))
        cv2.line(preview, (width // 2, height - 1),
                 (lane_x, int(height * 0.42)), cyan, 2)
    for marking, label, colour in (
        (observation.crosswalk, "CROSSWALK", (255, 190, 0)),
        (observation.stop_line, "STOP", (40, 70, 255)),
    ):
        if marking is None:
            continue
        row = max(0, min(height - 1,
                         int(round(marking.image_row * scale))))
        cv2.line(preview, (0, row), (width - 1, row), colour, 2)
        cv2.putText(preview, label, (8, max(18, row - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, colour, 1,
                    cv2.LINE_AA)

    signal = "CONFLICT" if observation.signal_conflict else (
        observation.signal.colour if observation.signal is not None else "NONE")
    signal_colours = {
        "RED": (40, 70, 255),
        "YELLOW": (0, 220, 255),
        "GREEN": (60, 220, 90),
        "CONFLICT": (180, 80, 255),
        "NONE": (130, 145, 160),
    }
    cv2.rectangle(preview, (0, 0), (width - 1, 28), shadow, -1)
    cv2.putText(preview, str(source).upper()[:16], (8, 19),
                cv2.FONT_HERSHEY_SIMPLEX, 0.43, white, 1, cv2.LINE_AA)
    cv2.circle(preview, (width - 84, 14), 5, signal_colours[signal], -1)
    cv2.putText(preview, signal, (width - 73, 19),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, white, 1, cv2.LINE_AA)
    return preview


def _groups(flags: np.ndarray) -> list[tuple[int, int]]:
    indexes = np.flatnonzero(flags)
    if indexes.size == 0:
        return []
    result = []
    start = previous = int(indexes[0])
    for raw in indexes[1:]:
        current = int(raw)
        if current != previous + 1:
            result.append((start, previous))
            start = current
        previous = current
    result.append((start, previous))
    return result


def _crosswalk_cluster(groups: list[tuple[int, int]], max_gap: int,
                       minimum: int) -> list[int]:
    """Return indexes of the largest regularly nearby horizontal cluster."""
    best: list[int] = []
    current: list[int] = []
    previous = None
    for index, (top, bottom) in enumerate(groups):
        centre = (top + bottom) / 2.0
        if previous is None or centre - previous <= max_gap:
            current.append(index)
        else:
            if len(current) > len(best):
                best = current
            current = [index]
        previous = centre
    if len(current) > len(best):
        best = current
    return best if len(best) >= minimum else []


def _ground_distance(ground, row: float, column: float) -> float | None:
    if ground is None:
        return None
    try:
        value = ground.distance(row, column)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or value < 0.0):
        return None
    return float(value)


def _marking(group_indexes: list[int], groups: list[tuple[int, int]],
             bright: np.ndarray, ground) -> RoadMarkingObservation | None:
    if not group_indexes:
        return None
    selected = [groups[index] for index in group_indexes]
    row = float(max((top + bottom) / 2.0 for top, bottom in selected))
    pixels = sum(int((bright[top:bottom + 1] > 0).sum())
                 for top, bottom in selected)
    capacity = max(1, sum(bottom - top + 1 for top, bottom in selected)
                   * bright.shape[1])
    return RoadMarkingObservation(
        image_row=row,
        distance_m=_ground_distance(ground, row, bright.shape[1] / 2.0),
        confidence=min(1.0, pixels / capacity),
    )


def _lane(bright: np.ndarray, horizontal_groups: list[tuple[int, int]],
          config: RoadPerceptionConfig) -> LaneObservation | None:
    masked = bright.copy()
    for top, bottom in horizontal_groups:
        start = max(0, top - config.horizontal_padding_px)
        end = min(masked.shape[0], bottom + config.horizontal_padding_px + 1)
        masked[start:end, :] = 0
    roi_top = int(masked.shape[0] * config.lane_roi_top_fraction)
    band = masked[roi_top:, :]
    lit = int((band > 0).sum())
    if lit == 0 or lit > band.size * 0.40:
        return None
    column = band.sum(axis=0).astype(np.float64)
    total = float(column.sum())
    if total <= 0.0:
        return None
    width = float(band.shape[1])
    centroid = float((column * np.arange(band.shape[1])).sum() / total)
    error = max(-1.0, min(1.0, (centroid - width / 2.0) / (width / 2.0)))
    confidence = min(1.0, lit / max(1.0, band.shape[0] * 8.0))
    return LaneObservation(error=error, confidence=confidence)


def _signal(bgr: np.ndarray, config: RoadPerceptionConfig):
    bottom = max(1, int(bgr.shape[0] * config.signal_roi_bottom_fraction))
    hsv = cv2.cvtColor(bgr[:bottom], cv2.COLOR_BGR2HSV)
    masks = {
        "RED": (cv2.inRange(hsv, (0, 120, 100), (10, 255, 255))
                | cv2.inRange(hsv, (170, 120, 100), (179, 255, 255))),
        "YELLOW": cv2.inRange(hsv, (18, 120, 100), (38, 255, 255)),
        "GREEN": cv2.inRange(hsv, (40, 100, 80), (90, 255, 255)),
    }
    counts = {colour: int((mask > 0).sum()) for colour, mask in masks.items()}
    active = [colour for colour, count in counts.items()
              if count >= config.signal_min_pixels]
    if len(active) > 1:
        return None, True
    if not active:
        return None, False
    colour = active[0]
    confidence = min(
        1.0, counts[colour] / max(1.0, config.signal_min_pixels * 2.0))
    observation = TrafficSignalObservation(
        colour=colour, confidence=confidence)
    return observation, False


def detect_road_observation(bgr: np.ndarray, *, ground=None,
                            config: RoadPerceptionConfig | None = None
                            ) -> RoadObservation:
    """Detect road markings and signal from a processed BGR frame."""
    if not isinstance(bgr, np.ndarray) or bgr.ndim != 3 or bgr.shape[2] != 3 \
            or bgr.size == 0:
        raise ValueError("road camera frame must be a non-empty BGR array")
    config = config or RoadPerceptionConfig()
    if not 1 <= config.bright_threshold <= 254:
        raise ValueError("bright_threshold must be in [1, 254]")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(
        gray, config.bright_threshold, 255, cv2.THRESH_BINARY)
    row_fraction = (bright > 0).mean(axis=1)
    horizontal_groups = _groups(row_fraction >= config.horizontal_min_fraction)
    crosswalk_indexes = _crosswalk_cluster(
        horizontal_groups,
        config.crosswalk_max_gap_px,
        config.crosswalk_min_bars,
    )
    crosswalk_set = set(crosswalk_indexes)
    stop_indexes = [index for index in range(len(horizontal_groups))
                    if index not in crosswalk_set]
    # A single stop-line verdict is the closest independent horizontal mark.
    stop_indexes = stop_indexes[-1:] if stop_indexes else []
    signal, conflict = _signal(bgr, config)
    return RoadObservation(
        lane=_lane(bright, horizontal_groups, config),
        stop_line=_marking(stop_indexes, horizontal_groups, bright, ground),
        crosswalk=_marking(
            crosswalk_indexes, horizontal_groups, bright, ground),
        signal=signal,
        signal_conflict=conflict,
    )


def _marking_payload(observation: RoadMarkingObservation | None) -> dict:
    return {
        "visible": observation is not None,
        "image_row": (
            None if observation is None else float(observation.image_row)),
        "distance_m": None if observation is None else observation.distance_m,
        "confidence": (
            0.0 if observation is None else float(observation.confidence)),
    }


def road_observation_payload(source: str, stamp: float, map_id: str,
                             scene_revision: str,
                             observation: RoadObservation, *,
                             context_id: str | None = None,
                             context_confidence: float | None = None,
                             context_profile_revision: str | None = None
                             ) -> dict:
    """Build revision-bound JSON evidence for CORE's traffic policy.

    The optional scene context (D-162) is additive: when any context field
    is given all three are required, and the "context" key is present only
    for consumers that opted in, so older CORE builds keep decoding.
    """
    if source != "CAMERA_ROAD":
        raise ValueError("unsupported road observation source")
    if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
            or not math.isfinite(float(stamp))):
        raise ValueError("road observation stamp must be finite")
    if not isinstance(map_id, str) or not map_id.strip():
        raise ValueError("road observation map_id is required")
    if not isinstance(scene_revision, str) or not scene_revision.strip():
        raise ValueError("road observation scene_revision is required")
    if not isinstance(observation, RoadObservation):
        raise ValueError("road observation is required")
    provided = (
        context_id is not None,
        context_confidence is not None,
        context_profile_revision is not None,
    )
    if any(provided) and not all(provided):
        raise ValueError(
            "road observation context requires id, confidence and revision")
    if context_id is not None:
        if not isinstance(context_id, str) or not context_id.strip():
            raise ValueError("road observation context_id is required")
        if (isinstance(context_confidence, bool)
                or not isinstance(context_confidence, (int, float))
                or not math.isfinite(float(context_confidence))
                or not 0.0 <= float(context_confidence) <= 1.0):
            raise ValueError(
                "road observation context_confidence must be in [0, 1]")
        if (not isinstance(context_profile_revision, str)
                or not context_profile_revision.strip()):
            raise ValueError(
                "road observation context_profile_revision is required")
    lane = observation.lane
    signal = observation.signal
    payload = {
        "source": source,
        "stamp": float(stamp),
        "map_id": map_id,
        "scene_revision": scene_revision,
        "lane": {
            "visible": lane is not None,
            "error": None if lane is None else float(lane.error),
            "confidence": 0.0 if lane is None else float(lane.confidence),
        },
        "stop_line": _marking_payload(observation.stop_line),
        "crosswalk": _marking_payload(observation.crosswalk),
        "signal": {
            "visible": signal is not None,
            "colour": None if signal is None else signal.colour,
            "confidence": 0.0 if signal is None else float(signal.confidence),
            "conflict": bool(observation.signal_conflict),
        },
    }
    if context_id is not None:
        payload["context"] = {
            "id": context_id,
            "confidence": float(context_confidence),
            "profile_revision": context_profile_revision,
        }
    return payload
