"""Transport-independent bounded reconnect jitter (D-432).

Callers preserve transport-specific exponential caps and reset only after a
stable session. Authentication/conflict errors are terminal policy decisions,
not input to an automatic network retry.
"""

import math
import random
import time


def retry_delay(current_s: float, *, maximum_s: float, remaining_s: float | None = None,
                random_value=random.random) -> float:
    """Equal jitter in [half interval, interval], capped by attempt deadline."""
    values = [current_s, maximum_s] + ([] if remaining_s is None else [remaining_s])
    if any(not math.isfinite(value) or value < 0 for value in values) or maximum_s <= 0:
        raise ValueError('retry intervals must be finite and nonnegative with a positive cap')
    sample = random_value()
    if not math.isfinite(sample) or not 0 <= sample <= 1:
        raise ValueError('retry random sample must be within 0-1')
    interval = min(current_s, maximum_s)
    delay = interval * (.5 + .5 * sample)
    return delay if remaining_s is None else min(delay, remaining_s)


def start_offset(interval_s: float, random_value=random.random) -> float:
    """A random start offset in [0, interval) so periodic loops do not run in lockstep."""
    return interval_s * random_value()


class ReconnectBackoff:
    """Mixin: reconnect delays from ``retry_delay``, doubling from ``reconnect_base_s`` to ``reconnect_max_s``.

    A session that lasted ``reconnect_stable_s`` resets the interval (reset only after a stable session).
    """
    reconnect_base_s, reconnect_max_s, reconnect_stable_s = 5.0, 60.0, 60.0

    def reconnect_delay(self, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        current, session_start = getattr(self, "_reconnect_state", (self.reconnect_base_s, None))
        if session_start is not None and now - session_start >= self.reconnect_stable_s:
            current = self.reconnect_base_s
        delay = retry_delay(current, maximum_s=self.reconnect_max_s)
        self._reconnect_state = (min(current * 2, self.reconnect_max_s), now + delay)
        return delay
