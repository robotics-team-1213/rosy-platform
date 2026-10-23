"""App-owned periodic maintenance, separated from the HTTP app factory."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fleet.server.cancel_all import DriveCancelFence
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService

_LOG = logging.getLogger(__name__)


async def control_unit_loop(service):
    while True:
        try:
            await service.refresh()
        except (OSError, sqlite3.Error):
            _LOG.error("control-unit journal refresh failed")
        await asyncio.sleep(1.0)


async def proposal_expiry_loop(proposal_store, logger) -> None:
    while True:
        try:
            proposal_store.purge_expired()
        except (OSError, sqlite3.Error):
            logger.exception("expired Fleet proposal cleanup failed")
        await asyncio.sleep(3600)


async def goal_evidence_expiry_loop(service, logger) -> None:
    """Apply registered grace deadlines without enabling Action dispatch."""
    while True:
        try:
            service.hold_expired_without_evidence()
        except (OSError, ValueError):
            logger.exception("goal evidence grace reconciliation failed")
        await asyncio.sleep(1.0)


async def lane_compliance_loop(monitor, logger, period_s: float) -> None:
    """D-511 M0: judge lane compliance at 2 Hz; observe and notify only."""
    while True:
        try:
            await monitor.tick()
        except Exception:       # one bad tick must not end the watch
            logger.exception("lane compliance tick failed")
        await asyncio.sleep(period_s)


async def goal_lease_renew_loop(console, logger) -> None:
    """D-550 10: every ttl/3 renew the console's leased goals whose source still holds (named
    operator present, attempt open, still yielding: ``goal_lease.GoalLeases``). Trip goals are
    renewed by the trip loop. Fleet stopping stops renewal: CORE then cancels."""
    period_s = console.goal_leases.ttl_s / 3
    while True:
        try:
            await console.goal_leases.renew("console")
        except Exception:       # one bad round must not end renewal (CORE would cancel)
            logger.exception("goal lease renewal failed")
        await asyncio.sleep(period_s)


#: D-550 10: a D-316 attempt is open while its task is being dispatched or driven.
OPEN_ATTEMPT_STATUSES = frozenset({"QUEUED", "ACCEPTED", "RUNNING"})


def attempt_open(store, task_id: str, attempt_id: str) -> bool:
    """The dispatch goal's attempt is still this task's open attempt (else its lease lapses)."""
    task = store.get_task(task_id)
    return (task is not None and task.get("attempt_id") == attempt_id
            and task.get("status") in OPEN_ATTEMPT_STATUSES)


async def _task_dispatch_loop(console: FleetConsole, task_service: FleetTaskService,
                              drive_cancel: DriveCancelFence) -> None:
    """Dispatch one eligible task at a time from the app-owned background worker."""
    while True:
        try:
            task_service.scheduler.expire_queued()
            from fleet.server.channel.execution.outcomes.reconcile import reconcile_tasks
            await reconcile_tasks(task_service, console)
            snapshot = await console.snapshot()
            console.prune_task_queue_entries(task_service.store.queued_task_ids())
            available = {
                row["robot_id"] for row in snapshot["robots"]
                if row["online"] and row["queued"] is None and row["goal"] is None
                and row["state"] is not None
                and row["state"].get("navigation") in {"IDLE", "ARRIVED", "CANCELED", "FAILED"}
                and row["state"].get("mode") in {"IDLE", "NAVIGATION"}
                and not row["state"].get("capabilities_degraded")
                and not console.trip_busy(row["robot_id"])  # D-494 5: the trip loop drives it
                and row["state"].get("safety", {}).get("estop") is False
            }
            await task_service.dispatch_next(
                available, dispatch=lambda task: drive_cancel.fenced_goal(console, task))
        except asyncio.CancelledError:
            raise
        except Exception:
            # A status read failure cannot establish availability. Leave work queued.
            pass
        await asyncio.sleep(0.25)


async def _mission_model_turn_worker_loop(worker) -> None:
    """Consume durable ER 2 turns only when an approved worker is injected."""
    while True:
        try:
            await worker.consume_next(worker_id="fleet-feedback")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception("Fleet Mission model-turn worker cycle failed")
        await asyncio.sleep(0.25)
