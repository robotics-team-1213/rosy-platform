"""ROS-independent admission rules for a calibrated workcell camera frame."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraStreamConfig:
    camera_identity: str
    optical_frame_id: str
    calibration_revision: str
    camera_info_sha256: str
    max_frame_age_s: float = 0.5

    def __post_init__(self) -> None:
        for name in ("camera_identity", "optical_frame_id", "calibration_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not re.fullmatch(r"[0-9a-f]{64}", self.camera_info_sha256):
            raise ValueError("camera_info_sha256 must be a lowercase SHA-256 digest")
        if isinstance(self.max_frame_age_s, bool):
            raise ValueError("max_frame_age_s must be positive and finite")
        try:
            age = float(self.max_frame_age_s)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_frame_age_s must be positive and finite") from exc
        if not math.isfinite(age) or age <= 0:
            raise ValueError("max_frame_age_s must be positive and finite")
        object.__setattr__(self, "max_frame_age_s", age)


@dataclass(frozen=True)
class CameraFrameMetadata:
    camera_identity: str
    optical_frame_id: str
    calibration_revision: str
    capture_time_ns: int
    width: int
    height: int
    sequence: int
    received_at: float


class CameraFrameGate:
    """Admit only fresh, exactly synchronized image/calibration metadata pairs.

    `image` and `camera_info` are duck-typed ROS Image/CameraInfo messages.
    The gate retains metadata only; a ROS adapter may retain at most one paired
    image for local consumers and must not expose it to Fleet/Core by default.
    """

    def __init__(self, config: CameraStreamConfig) -> None:
        self.config = config
        self._sequence = 0
        self._last_capture_time_ns = -1
        self.latest: CameraFrameMetadata | None = None

    @staticmethod
    def camera_info_fingerprint(camera_info: object) -> str:
        """Hash all ROS CameraInfo calibration fields, excluding its header."""
        roi = camera_info.roi
        calibration = {
            "width": camera_info.width,
            "height": camera_info.height,
            "distortion_model": camera_info.distortion_model,
            "d": [float(value) for value in camera_info.d],
            "k": [float(value) for value in camera_info.k],
            "r": [float(value) for value in camera_info.r],
            "p": [float(value) for value in camera_info.p],
            "binning_x": camera_info.binning_x,
            "binning_y": camera_info.binning_y,
            "roi": [roi.x_offset, roi.y_offset, roi.width, roi.height, roi.do_rectify],
        }
        try:
            encoded = json.dumps(
                calibration, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("CameraInfo calibration fields are invalid") from exc
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _stamp_ns(header: object) -> int:
        stamp = header.stamp
        sec, nanosec = stamp.sec, stamp.nanosec
        if (
            type(sec) is not int
            or type(nanosec) is not int
            or sec < 0
            or not 0 <= nanosec < 1_000_000_000
        ):
            raise ValueError("camera capture stamp is invalid")
        return sec * 1_000_000_000 + nanosec

    def accept(
        self, image: object, camera_info: object, *, received_at: float
    ) -> CameraFrameMetadata:
        try:
            received_at = float(received_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("receive time must be finite monotonic time") from exc
        if not math.isfinite(received_at):
            raise ValueError("receive time must be finite monotonic time")
        image_ns = self._stamp_ns(image.header)
        info_ns = self._stamp_ns(camera_info.header)
        if image_ns != info_ns:
            raise ValueError("image and CameraInfo capture stamps differ")
        if image_ns <= self._last_capture_time_ns:
            raise ValueError("camera capture stamp did not advance")
        if (
            image.header.frame_id != self.config.optical_frame_id
            or camera_info.header.frame_id != self.config.optical_frame_id
        ):
            raise ValueError("camera optical frame does not match configured identity")
        if (
            type(image.width) is not int
            or type(image.height) is not int
            or image.width <= 0
            or image.height <= 0
        ):
            raise ValueError("image dimensions must be positive integers")
        if (camera_info.width, camera_info.height) != (image.width, image.height):
            raise ValueError("image and CameraInfo dimensions differ")
        try:
            intrinsics = [float(value) for value in camera_info.k]
        except (TypeError, ValueError) as exc:
            raise ValueError("CameraInfo intrinsic matrix must contain nine finite values") from exc
        if len(intrinsics) != 9 or not all(math.isfinite(value) for value in intrinsics):
            raise ValueError("CameraInfo intrinsic matrix must contain nine finite values")
        if not any(value != 0.0 for value in intrinsics):
            raise ValueError("uncalibrated CameraInfo is not admitted")
        fingerprint = self.camera_info_fingerprint(camera_info)
        if not hmac.compare_digest(fingerprint, self.config.camera_info_sha256):
            raise ValueError("CameraInfo does not match configured calibration digest")
        self._sequence += 1
        self._last_capture_time_ns = image_ns
        metadata = CameraFrameMetadata(
            camera_identity=self.config.camera_identity,
            optical_frame_id=self.config.optical_frame_id,
            calibration_revision=self.config.calibration_revision,
            capture_time_ns=image_ns,
            width=image.width,
            height=image.height,
            sequence=self._sequence,
            received_at=received_at,
        )
        self.latest = metadata
        return metadata

    def is_fresh(self, *, now: float) -> bool:
        if isinstance(now, bool):
            return False
        try:
            current = float(now)
        except (TypeError, ValueError):
            return False
        return (
            self.latest is not None
            and math.isfinite(current)
            and current >= self.latest.received_at
            and current - self.latest.received_at <= self.config.max_frame_age_s
        )
