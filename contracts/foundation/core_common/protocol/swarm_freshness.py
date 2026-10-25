"""Pure UTC lifetime calculation for original swarm pose references (D-870)."""

import math


CLOCK_SKEW_BUDGET_S = 0.1


def remaining_reference_s(
    sampled_at: float | None, *, now: float, timeout_s: float,
) -> float | None:
    """Require source and receiver UTC errors within ±50 ms each.

    This operational precondition is not a measurement of clock quality.
    Callers convert the remaining duration to their own monotonic deadline.
    """
    try:
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value <= 0
               for value in (sampled_at, now, timeout_s)):
            return None
    except OverflowError:
        return None

    if sampled_at > now + CLOCK_SKEW_BUDGET_S:
        return None
    conservative_age = max(0.0, now - sampled_at) + CLOCK_SKEW_BUDGET_S
    remaining = timeout_s - conservative_age
    return remaining if remaining > 0 else None
