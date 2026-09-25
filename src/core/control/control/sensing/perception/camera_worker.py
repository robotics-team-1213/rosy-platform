"""Bounded, ROS-free camera preprocessing for the device worker.

The worker owns capture-frame hygiene and timing evidence.  It deliberately
does not decide whether a robot may move: ``classify_frame`` remains an
observation producer and the IR/LiDAR safety policy remains authoritative.
Keeping this subject ROS-free makes the same contract usable by the onboard
node and by a deterministic fixture or replay test.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
import time
from typing import Any

import numpy as np

from .camera import classify_frame


def _rotate(image: np.ndarray, degrees: int) -> np.ndarray:
    """Rotate a frame clockwise in quarter turns and make it contiguous."""

    turns = (degrees // 90) % 4
    if turns:
        image = np.rot90(image, turns)
    return np.ascontiguousarray(image)


def _rss_bytes() -> int | None:
    """Return a best-effort process high-water mark without a new dependency."""

    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports KiB; macOS reports bytes.  Device is Linux, but keep
        # the fallback correct for host replay tests.
        return value * 1024 if value < 10_000_000 else value
    except (AttributeError, ImportError, OSError, ValueError):
        return None


@dataclass(frozen=True)
class CameraPreprocessProfile:
    """Immutable device capture contract."""

    width: int = 320
    height: int = 240
    fps: float = 8.0
    rotate_deg: int = 180
    revision: str = "camera-profile-v1"
    max_latency_ms: float = 125.0

    def __post_init__(self) -> None:
        if type(self.width) is not int or not 8 <= self.width <= 4096:
            raise ValueError("camera width must be an integer in [8, 4096]")
        if type(self.height) is not int or not 8 <= self.height <= 4096:
            raise ValueError("camera height must be an integer in [8, 4096]")
        if (type(self.fps) not in (int, float) or not math.isfinite(float(self.fps))
                or not 0.5 <= float(self.fps) <= 60.0):
            raise ValueError("camera fps must be in [0.5, 60]")
        if type(self.rotate_deg) is not int or self.rotate_deg % 90:
            raise ValueError("camera rotate_deg must be a multiple of 90")
        if (type(self.revision) is not str or not self.revision.strip()
                or self.revision != self.revision.strip() or len(self.revision) > 128):
            raise ValueError("camera profile revision must be a bounded non-empty string")
        if (type(self.max_latency_ms) not in (int, float)
                or not math.isfinite(float(self.max_latency_ms))
                or not 1.0 <= float(self.max_latency_ms) <= 2000.0):
            raise ValueError("camera max_latency_ms must be in [1, 2000]")


@dataclass(frozen=True)
class CameraFrame:
    """One captured BGR frame with source identity."""

    frame_id: int
    captured_at: float
    pixels: np.ndarray


@dataclass(frozen=True)
class CameraTelemetry:
    """Secret-free, serialisable processing evidence."""

    frame_id: int
    profile_revision: str
    image_size: tuple[int, int]
    dropped_frames: int
    processing_latency_ms: float
    capture_age_ms: float | None
    cpu_time_ms: float
    memory_bytes: int | None
    quality_valid: bool
    quality_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "profile_revision": self.profile_revision,
            "image_size": list(self.image_size),
            "dropped_frames": self.dropped_frames,
            "processing_latency_ms": round(self.processing_latency_ms, 3),
            "capture_age_ms": (None if self.capture_age_ms is None
                                else round(self.capture_age_ms, 3)),
            "cpu_time_ms": round(self.cpu_time_ms, 3),
            "memory_bytes": self.memory_bytes,
            "quality": {
                "valid": self.quality_valid,
                "reason": self.quality_reason,
            },
        }


@dataclass(frozen=True)
class ProcessedCameraFrame:
    frame: CameraFrame
    pixels: np.ndarray
    result: Mapping[str, Any]
    telemetry: CameraTelemetry


class CameraPreprocessWorker:
    """Process camera frames with bounded and replayable evidence."""

    def __init__(self, profile: CameraPreprocessProfile | None = None, *,
                 classifier: Callable[..., Mapping[str, Any]] = classify_frame,
                 monotonic: Callable[[], float] = time.perf_counter,
                 wall_clock: Callable[[], float] = time.time,
                 cpu_clock: Callable[[], float] = time.process_time,
                 memory_reader: Callable[[], int | None] = _rss_bytes) -> None:
        self.profile = profile or CameraPreprocessProfile()
        self._classifier = classifier
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._cpu_clock = cpu_clock
        self._memory_reader = memory_reader
        self._last_frame_id: int | None = None
        self._dropped_frames = 0
        self._floor_hsv: Any = None

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def floor_hsv(self) -> Any:
        return self._floor_hsv

    def reset_floor_reference(self) -> None:
        """Discard a reference captured under a previous exposure profile."""

        self._floor_hsv = None

    def process(self, frame: CameraFrame) -> ProcessedCameraFrame:
        self._validate_frame_metadata(frame)
        started = self._monotonic()
        cpu_started = self._cpu_clock()
        dropped = self._account_sequence(frame.frame_id)
        pixels = frame.pixels
        if self._valid_pixels(pixels):
            if pixels.shape[:2] != (self.profile.height, self.profile.width):
                result: Mapping[str, Any] = {
                    "quality": {"valid": False, "reason": "resolution_mismatch"},
                    "floor_hsv": None,
                }
            else:
                pixels = _rotate(pixels, self.profile.rotate_deg)
                result = None
        else:
            result = {
                "quality": {"valid": False, "reason": "invalid_image"},
                "floor_hsv": None,
            }

        if result is None and dropped:
            result = {
                "quality": {"valid": False, "reason": "out_of_order_frame"},
                "floor_hsv": None,
            }
        elif result is None:
            try:
                candidate = self._classifier(pixels, floor_hsv=self._floor_hsv)
                result = (candidate if isinstance(candidate, Mapping) else {
                    "quality": {"valid": False, "reason": "classifier_error"},
                    "floor_hsv": None,
                })
            except Exception:
                # A worker callback failure is unavailable evidence.  Do not
                # serialize exception text: it can contain paths or secrets.
                result = {
                    "quality": {"valid": False, "reason": "classifier_error"},
                    "floor_hsv": None,
                }
            new_floor = result.get("floor_hsv")
            if new_floor is not None:
                self._floor_hsv = new_floor
        elif dropped:
            # Sequence errors take precedence over a frame's content: the
            # consumer must not treat an old frame as fresh evidence.
            result = {
                "quality": {"valid": False, "reason": "out_of_order_frame"},
                "floor_hsv": None,
            }

        elapsed_ms = max(0.0, (self._monotonic() - started) * 1000.0)
        cpu_ms = max(0.0, (self._cpu_clock() - cpu_started) * 1000.0)
        quality = dict(result.get("quality") or {})
        valid = bool(quality.get("valid", False))
        reason = str(quality.get("reason", "unknown"))
        if elapsed_ms > float(self.profile.max_latency_ms):
            valid = False
            reason = "latency_budget_exceeded"
            result = dict(result)
            result["quality"] = {**quality, "valid": False, "reason": reason}
        elif "quality" not in result:
            result = dict(result)
            result["quality"] = {"valid": valid, "reason": reason}

        if isinstance(pixels, np.ndarray) and pixels.ndim == 3:
            size = (int(pixels.shape[1]), int(pixels.shape[0]))
        else:
            size = (0, 0)
        capture_age = None
        if frame.captured_at > 0.0:
            capture_age = max(0.0, (self._wall_clock() - frame.captured_at) * 1000.0)
        telemetry = CameraTelemetry(
            frame_id=frame.frame_id,
            profile_revision=self.profile.revision,
            image_size=size,
            dropped_frames=self._dropped_frames,
            processing_latency_ms=elapsed_ms,
            capture_age_ms=capture_age,
            cpu_time_ms=cpu_ms,
            memory_bytes=self._memory_reader(),
            quality_valid=valid,
            quality_reason=reason,
        )
        return ProcessedCameraFrame(frame, pixels, result, telemetry)

    def _valid_pixels(self, pixels: Any) -> bool:
        return (isinstance(pixels, np.ndarray) and pixels.dtype == np.uint8
                and pixels.ndim == 3 and pixels.shape[2] == 3
                and min(pixels.shape[:2]) >= 8)

    def _validate_frame_metadata(self, frame: CameraFrame) -> None:
        if type(frame.frame_id) is not int or frame.frame_id < 0:
            raise ValueError("camera frame_id must be a non-negative integer")
        if (type(frame.captured_at) not in (int, float)
                or not math.isfinite(float(frame.captured_at)) or frame.captured_at < 0):
            raise ValueError("camera captured_at must be a finite non-negative timestamp")

    def _account_sequence(self, frame_id: int) -> bool:
        if self._last_frame_id is None:
            self._last_frame_id = frame_id
            return False
        if frame_id <= self._last_frame_id:
            self._dropped_frames += 1
            return True
        self._dropped_frames += max(0, frame_id - self._last_frame_id - 1)
        self._last_frame_id = frame_id
        return False
