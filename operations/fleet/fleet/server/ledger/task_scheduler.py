"""Single-process dispatcher coordination backed by durable SQLite claims."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from fleet.server.task_store import FleetTaskStore


class FleetTaskScheduler:
    """Apply queue policy while the store owns atomic claims and robot reservations."""

    def __init__(self, store: FleetTaskStore, *, worker_id: str,
                 monotonic: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        if not worker_id or len(worker_id) > 96:
            raise ValueError("invalid worker_id")
        self.store = store
        self.worker_id = worker_id
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._queued_monotonic: dict[str, float] = {}

    def note_queued(self, task_id: str) -> None:
        """Record a process-local monotonic origin for queue-wait measurements."""
        self._queued_monotonic.setdefault(task_id, self._monotonic())

    def enqueue(self, task_id: str, *, priority_class: int, expires_at: str | None = None,
                actor_id: str = "site-scheduler", source: str = "scheduler") -> dict:
        task = self.store.enqueue(task_id, priority_class=priority_class,
                                  expires_at=expires_at, actor_id=actor_id, source=source)
        self.note_queued(task_id)
        return task

    def claim_next(self, available_robot_ids: set[str], *, lease_seconds: float = 30.0) -> dict | None:
        observed_at = self._monotonic()
        task = self.store.claim_next(worker_id=self.worker_id,
                                     available_robot_ids=available_robot_ids,
                                     lease_seconds=lease_seconds)
        if task is None:
            return None
        queued_at = self._queued_monotonic.pop(task["task_id"], observed_at)
        task["queue_wait_seconds"] = max(0.0, observed_at - queued_at)
        task["total_queue_wait_seconds"] = self._total_queue_wait(task.get("first_queued_at"))
        return task

    def _total_queue_wait(self, first_queued_at: str | None) -> float | None:
        """Wall-clock wait since the task first entered the queue (durable, restart-safe).

        ``queued_at`` is rewritten on traffic release, so the monotonic-based
        ``queue_wait_seconds`` only sees the latest stay; this keeps the total.
        ``None`` when the durable origin is unknown (rows queued before the column).
        """
        if not first_queued_at:
            return None
        try:
            first = datetime.fromisoformat(first_queued_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        return max(0.0, (self._wall_clock() - first).total_seconds())

    def begin_dispatch(self, task_id: str) -> dict:
        return self.store.mark_dispatching(task_id, worker_id=self.worker_id)

    def recover(self) -> int:
        return self.store.recover_interrupted_work()

    def expire_queued(self) -> None:
        """Expire queued work even when no robot is currently dispatchable."""
        self.store.claim_next(worker_id=self.worker_id, available_robot_ids=set())
