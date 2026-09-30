"""Subject: the perception/learned/status wire shape (D-373 decision 2, D-62).

A shadow node that is on but has no runtime or no model must say so instead of
going quiet. The payload is evidence about the node itself: counters and
latency, never a command."""

from __future__ import annotations

import statistics
from collections import deque

STATUS_SCHEMA = "rosy.perception.learned_status/1"
STATUS_TOPIC = "perception/learned/status"
NO_MODEL = "no shadow model loaded"


class LearnedStatus:
    """Cumulative frame counters plus the median of the last `window` latencies."""

    def __init__(self, window: int = 50):
        if window < 1:
            raise ValueError("window must be >= 1")
        self.frames_in = 0
        self.frames_inferred = 0
        self.frames_skipped = 0
        self._latency = deque(maxlen=window)

    def frame_in(self) -> None:
        self.frames_in += 1

    def frame_skipped(self) -> None:
        self.frames_skipped += 1

    def frame_inferred(self, latency_ms: float) -> None:
        self.frames_inferred += 1
        self._latency.append(float(latency_ms))

    def payload(self, *, model_revision: str | None, last_error: str | None) -> dict:
        if model_revision is None and last_error is None:
            last_error = NO_MODEL  # D-62: off is reported, not silent
        p50 = round(statistics.median(self._latency), 3) if self._latency else None
        ratio = self.frames_skipped / self.frames_in if self.frames_in else 0.0
        return {
            "schema": STATUS_SCHEMA,
            "model_revision": model_revision,
            "last_error": last_error,
            "frames_in": self.frames_in,
            "frames_inferred": self.frames_inferred,
            "frames_skipped": self.frames_skipped,
            "skip_ratio": round(ratio, 4),
            "latency_ms_p50": p50,
        }
