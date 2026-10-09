"""App-owned periodic maintenance, separated from the HTTP app factory."""

import asyncio
import sqlite3


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
