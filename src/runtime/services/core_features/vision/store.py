"""ROS-free, latest-only camera preview store.

The store is deliberately not a queue. A slow dashboard may skip frames but
must never add backpressure to camera perception or the command path.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import threading
import time
from typing import Optional


def _source_label(value: object) -> str:
    clean = re.sub(r"[^A-Z0-9_-]+", "_", str(value).strip().upper())
    return clean.strip("_")[:32] or "UNKNOWN"


def parse_preview_format(value: str) -> Optional[dict]:
    """Parse the bounded metadata suffix carried by CompressedImage.format."""
    parts = [part.strip() for part in str(value).split(";")]
    if not parts or parts[0].lower() not in {"jpeg", "jpg"}:
        return None
    fields: dict[str, str] = {}
    for part in parts[1:]:
        key, separator, raw = part.partition("=")
        if separator:
            fields[key.strip().lower()] = raw.strip()

    def dimension(name: str) -> int:
        try:
            result = int(fields.get(name, "0"))
        except ValueError:
            return 0
        return result if 0 <= result <= 4096 else 0

    return {
        "source": _source_label(fields.get("source", "UNKNOWN")),
        "width": dimension("width"),
        "height": dimension("height"),
        "overlay": fields.get("overlay", "none")[:80] or "none",
    }


@dataclass(frozen=True)
class VisionFrame:
    data: bytes
    captured_at: float
    received_at: float
    frame_id: str
    source: str
    width: int
    height: int
    overlay: str
    sequence: int


class VisionFrameAdvanced(RuntimeError):
    """The latest frame no longer matches the status sequence requested."""

    def __init__(self, sequence: int) -> None:
        super().__init__(f"camera frame advanced to sequence {sequence}")
        self.sequence = int(sequence)


class VisionPullRateLimited(RuntimeError):
    """A viewer requested JPEG bytes faster than the bounded API rate."""

    def __init__(self, retry_after_s: float) -> None:
        super().__init__("camera preview pull rate exceeded")
        self.retry_after_s = max(0.0, float(retry_after_s))


class VisionFrameStore:
    """Keep one validated JPEG and report freshness from local receipt time."""

    def __init__(self, *, max_bytes: int = 512_000,
                 stale_after_s: float = 2.0,
                 min_pull_interval_s: float = 0.4) -> None:
        if (isinstance(max_bytes, bool)
                or not 4 <= int(max_bytes) <= 512_000):
            raise ValueError(
                "maximum frame bytes must be in [4, 512000]")
        if (isinstance(stale_after_s, bool)
                or not math.isfinite(float(stale_after_s))
                or float(stale_after_s) <= 0.0):
            raise ValueError("stale_after_s must be positive and finite")
        if (isinstance(min_pull_interval_s, bool)
                or not math.isfinite(float(min_pull_interval_s))
                or float(min_pull_interval_s) < 0.4):
            raise ValueError(
                "min_pull_interval_s must be finite and at least 0.4")
        self._max_bytes = int(max_bytes)
        self._stale_after_s = float(stale_after_s)
        self._min_pull_interval_s = float(min_pull_interval_s)
        self._lock = threading.Lock()
        self._frame: Optional[VisionFrame] = None
        self._sequence = 0
        self._last_pull_by_viewer: dict[str, float] = {}

    def publish(self, data: bytes, *, captured_at: float,
                frame_id: str, source: str, width: int = 0,
                height: int = 0, overlay: str = "none",
                received_at: Optional[float] = None) -> VisionFrame:
        payload = bytes(data)
        if len(payload) < 4 or not (
                payload.startswith(b"\xff\xd8")
                and payload.endswith(b"\xff\xd9")):
            raise ValueError("camera preview must be a complete JPEG")
        if len(payload) > self._max_bytes:
            raise ValueError("camera preview exceeds maximum frame bytes")
        captured = float(captured_at)
        received = time.monotonic() if received_at is None else float(received_at)
        if not math.isfinite(captured) or not math.isfinite(received):
            raise ValueError("camera timestamps must be finite")
        clean_width = int(width)
        clean_height = int(height)
        if clean_width < 0 or clean_height < 0:
            raise ValueError("camera dimensions cannot be negative")
        clean_frame_id = str(frame_id).strip()[:160]
        clean_source = _source_label(source)
        clean_overlay = str(overlay).strip()[:80] or "none"

        with self._lock:
            if (self._frame is not None
                    and received - self._frame.received_at
                    <= self._stale_after_s
                    and captured < self._frame.captured_at):
                raise ValueError("older camera frame cannot replace latest frame")
            self._sequence += 1
            frame = VisionFrame(
                data=payload,
                captured_at=captured,
                received_at=received,
                frame_id=clean_frame_id,
                source=clean_source,
                width=clean_width,
                height=clean_height,
                overlay=clean_overlay,
                sequence=self._sequence,
            )
            self._frame = frame
            return frame

    def _snapshot(self) -> Optional[VisionFrame]:
        with self._lock:
            return self._frame

    def frame(self, *, now: Optional[float] = None) -> Optional[VisionFrame]:
        frame = self._snapshot()
        if frame is None:
            return None
        current = time.monotonic() if now is None else float(now)
        if current - frame.received_at > self._stale_after_s:
            return None
        return frame

    def frame_for_viewer(
            self, viewer_id: str, *, expected_sequence: Optional[int] = None,
            now: Optional[float] = None) -> Optional[VisionFrame]:
        """Atomically bind a fresh frame to status sequence and viewer rate."""
        current = time.monotonic() if now is None else float(now)
        if not math.isfinite(current):
            raise ValueError("frame pull timestamp must be finite")
        viewer = str(viewer_id).strip()
        if not viewer:
            raise ValueError("viewer id is required")
        with self._lock:
            frame = self._frame
            if frame is None or current - frame.received_at > self._stale_after_s:
                return None
            if (expected_sequence is not None
                    and int(expected_sequence) != frame.sequence):
                raise VisionFrameAdvanced(frame.sequence)
            previous = self._last_pull_by_viewer.get(viewer)
            if (previous is not None and current >= previous
                    and current - previous + 1e-9
                    < self._min_pull_interval_s):
                raise VisionPullRateLimited(
                    self._min_pull_interval_s - (current - previous))
            self._last_pull_by_viewer[viewer] = current
            # Keep the bounded auth population from becoming a historical map.
            expiry = current - max(self._stale_after_s,
                                   self._min_pull_interval_s) * 2.0
            self._last_pull_by_viewer = {
                key: pulled for key, pulled in self._last_pull_by_viewer.items()
                if pulled >= expiry
            }
            return frame

    def status(self, *, now: Optional[float] = None) -> dict:
        frame = self._snapshot()
        if frame is None:
            return {
                "available": False,
                "stale": False,
                "source": None,
                "frame_id": None,
                "captured_at": None,
                "age_ms": None,
                "width": 0,
                "height": 0,
                "overlay": "none",
                "sequence": 0,
            }
        current = time.monotonic() if now is None else float(now)
        age_s = max(0.0, current - frame.received_at)
        stale = age_s > self._stale_after_s
        return {
            "available": not stale,
            "stale": stale,
            "source": frame.source,
            "frame_id": frame.frame_id,
            "captured_at": frame.captured_at,
            "age_ms": int(round(age_s * 1000.0)),
            "width": frame.width,
            "height": frame.height,
            "overlay": frame.overlay,
            "sequence": frame.sequence,
        }
