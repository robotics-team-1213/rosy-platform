"""Age re-check and counters for every POST from Vision to Fleet (no queue, no retry).

Fleet refuses a detection whose ``captured_at`` is older than its lease (1 s), so a payload that
aged during decoding or after a slow earlier POST only costs a round trip. ``post`` re-checks the
age right before the call and drops a stale payload; the drop is counted, never kept.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

#: Below Fleet's DETECTION_LEASE_S (1.0 s) so the request still has time to arrive.
MAX_POST_AGE_S = 0.8


class PostGuard:
    def __init__(self, source_id: str, clock: Callable[[], float] = time.time,
                 max_age_s: float = MAX_POST_AGE_S) -> None:
        self.source_id = source_id
        self._clock = clock
        self.max_age_s = max_age_s
        self.posted = 0
        self.dropped_stale = 0
        self.post_errors = 0
        self.last_post_age_ms: int | None = None

    async def post(self, captured_at: float, call: Callable[[], Awaitable]):
        """Await ``call()`` unless the payload is stale (then None); errors propagate, counted."""
        if self._clock() - captured_at > self.max_age_s:
            self.dropped_stale += 1
            return None
        try:
            result = await call()
        except Exception:
            self.post_errors += 1
            raise
        self.posted += 1
        self.last_post_age_ms = round((self._clock() - captured_at) * 1000.0)
        return result

    def stats_line(self) -> str:
        age = "-" if self.last_post_age_ms is None else self.last_post_age_ms
        return (f"{self.source_id}: fleet_posts posted={self.posted} dropped_stale={self.dropped_stale} "
                f"post_errors={self.post_errors} last_post_age_ms={age}")
