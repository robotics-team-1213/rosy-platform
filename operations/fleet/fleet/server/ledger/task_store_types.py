"""Shared task-ledger exceptions and timestamp helper."""

from datetime import datetime, timezone


class IdempotencyConflict(ValueError):
    """The same actor reused an idempotency key for a different task request."""


class InvalidTaskTransition(ValueError):
    """A task status transition is outside the declared state machine."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
