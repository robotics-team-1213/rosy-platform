"""How long a Rosy read keeps the ceiling camera sending (D-691).

Any authorized Vision preview read asks the phone to send. The request is not
tied to one product: Fleet, Robot, Pilot, the install screen, and the record
and calibration tools all use the same preview lease. Vision's own tracking
does not ask. After the last read the phone keeps sending for
:data:`STREAM_HOLD_S`, then the server tells it to stop.
"""

from __future__ import annotations

import time
from collections.abc import Callable

STREAM_HOLD_S = 30.0


class StreamDemand:
    """Per-source hold. ``wanted`` is true while ``now < last_request + hold``."""

    def __init__(self, hold_s: float = STREAM_HOLD_S, clock: Callable[[], float] = time.monotonic):
        if not isinstance(hold_s, (int, float)) or hold_s <= 0:
            raise ValueError("hold_s must be positive")
        self.hold_s = float(hold_s)
        self._clock = clock
        self._until: dict[str, float] = {}

    def note(self, source: str, now: float | None = None) -> bool:
        """Refresh ``source``. Return True when this read starts a quiet source."""
        now = self._clock() if now is None else now
        started = not self.wanted(source, now)
        self._until[source] = now + self.hold_s
        return started

    def wanted(self, source: str, now: float | None = None) -> bool:
        now = self._clock() if now is None else now
        until = self._until.get(source)
        return until is not None and now < until

    def drop(self, source: str) -> None:
        self._until.pop(source, None)
