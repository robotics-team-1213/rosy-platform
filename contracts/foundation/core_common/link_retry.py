"""Transport-independent bounded reconnect jitter (D-432).

Callers preserve transport-specific exponential caps and reset only after a
stable session. Authentication/conflict errors are terminal policy decisions,
not input to an automatic network retry.
"""

import math
import random


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
