"""Pure progress timestamps and Mission-to-step projection; no transition or admission owner."""

from __future__ import annotations

import math
from datetime import datetime, timezone

ACTION_FRESHNESS_SECONDS = 15.0
GOAL_FRESHNESS_SECONDS = 2.0


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            return None
        if not finite:
            return None
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness(observed_at: datetime | None, *, now: datetime,
               max_age_s: float) -> str:
    if observed_at is None:
        return "UNKNOWN"
    age = (now - observed_at).total_seconds()
    return "FRESH" if 0 <= age <= max_age_s else "STALE"


def mission_step_state(status: str) -> str:
    return {
        "PROPOSED": "NOT_ADMITTED", "READY": "READY",
        "RUNNING": "RUNNING",
        "ACTION_SUCCEEDED": "AWAITING_GOAL_EVIDENCE",
        "GOAL_CONFIRMED": "COMPLETED", "HOLD": "HOLD",
        "CANCELED": "CANCELED",
    }.get(status, "UNKNOWN")
