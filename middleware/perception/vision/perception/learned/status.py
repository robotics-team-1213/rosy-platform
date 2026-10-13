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
MAX_GAP_S = 1.0  # a longer stamp gap is a camera restart, not queue drops


def rate_limited(now: float, last: float | None, max_rate_hz: float) -> bool:
    """True when fewer than 1/max_rate_hz seconds passed since the last inference
    (learned_lane_node max_rate_hz, D-373 CPU budget). max_rate_hz <= 0: no limit."""
    return max_rate_hz > 0 and last is not None and now - last < 1.0 / max_rate_hz


def expected_frames(gap_s: float, *, period_s: float, max_gap_s: float = MAX_GAP_S) -> int:
    """Frames the camera produced for one arrival: 1 + those lost between.

    The camera subscription is KEEP_LAST 1 (D-185), so frames that arrive
    while a callback runs are replaced silently; only the stamp gap shows them."""
    if not period_s > 0:
        raise ValueError("period_s must be > 0")
    if gap_s <= 0 or gap_s > max_gap_s:
        return 1
    return max(1, int(round(gap_s / period_s)))


class LearnedStatus:
    """Cumulative frame counters plus the median of the last `window` latencies."""

    def __init__(self, window: int = 50, period_s: float = 0.125):
        if window < 1:
            raise ValueError("window must be >= 1")
        if not period_s > 0:
            raise ValueError("period_s must be > 0")
        self._period_s = float(period_s)
        self._last_stamp: float | None = None
        self.frames_in = 0
        self.frames_expected = 0
        self.frames_inferred = 0
        self.frames_skipped = 0
        self.frames_rate_limited = 0
        self._latency = deque(maxlen=window)

    def frame_in(self, stamp: float | None = None) -> None:
        self.frames_in += 1
        if stamp is None or self._last_stamp is None:
            self.frames_expected += 1
        else:
            self.frames_expected += expected_frames(stamp - self._last_stamp,
                                                    period_s=self._period_s)
        if stamp is not None:
            self._last_stamp = max(stamp, self._last_stamp or stamp)

    def frame_skipped(self) -> None:
        self.frames_skipped += 1

    def frame_rate_limited(self) -> None:
        """Left out on purpose by max_rate_hz, not by overload."""
        self.frames_rate_limited += 1

    def frame_inferred(self, latency_ms: float) -> None:
        self.frames_inferred += 1
        self._latency.append(float(latency_ms))

    def payload(self, *, model_revision: str | None, last_error: str | None,
                signed: bool | None = None) -> dict:
        if model_revision is None and last_error is None:
            last_error = NO_MODEL  # D-62: off is reported, not silent
        p50 = round(statistics.median(self._latency), 3) if self._latency else None
        # Everything the camera produced that was not inferred and not left out
        # on purpose by the rate limit: queue drops, busy skips, and frames seen
        # while no model was loaded. skip_ratio is overload only.
        missed = max(0, self.frames_expected - self.frames_inferred - self.frames_rate_limited)
        ratio = missed / self.frames_expected if self.frames_expected else 0.0
        out = {
            "schema": STATUS_SCHEMA,
            "model_revision": model_revision,
            "last_error": last_error,
            "frames_in": self.frames_in,
            "frames_expected": self.frames_expected,
            "frames_inferred": self.frames_inferred,
            "frames_skipped": self.frames_skipped,
            "frames_rate_limited": self.frames_rate_limited,
            "skip_ratio": round(ratio, 4),
            "latency_ms_p50": p50,
        }
        if signed is not None:  # D-423: whether the loaded model's manifest is release-signed
            out["signed"] = bool(signed)
        return out
