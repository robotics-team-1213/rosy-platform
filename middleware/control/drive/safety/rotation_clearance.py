"""Use the conservative body bound when exact pivot coverage is unavailable."""
import math


def rotation_clearance_allowed(conservative, fully_observed, fresh, pivot_margin, ranges):
    if not fresh:
        return False
    if not fully_observed:
        # The conservative check already uses the learned swept radius,
        # configured margin, nearest return and all required range sectors.
        return bool(conservative)
    # D-424: the exact pivot margin over a fully observed scan decides; an empty bumper
    # sector (no return beyond the chassis cut) is not a reason to refuse a turn.
    return pivot_margin is not None and math.isfinite(pivot_margin) and pivot_margin > .010
