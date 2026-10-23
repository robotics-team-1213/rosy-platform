"""App-owned durable Mission dispatch and feedback scheduling loops."""
import asyncio

from fleet.server.cancel_all import DriveCancelFence
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService


async def mission_feedback_schedule_loop(scheduler, logger) -> None:
    """Populate the durable outbox only; this loop never invokes a provider."""
    while True:
        try:
            before = scheduler.turn_store.capacity_dropped_count()
            await asyncio.to_thread(scheduler.poll_once)
            dropped = scheduler.turn_store.capacity_dropped_count()
            if dropped > before:
                logger.error(
                    "Mission feedback outbox is at capacity; dropped enqueue attempts=%d",
                    dropped,
                )
        except Exception:
            logger.exception("Mission feedback outbox scan failed")
        await asyncio.sleep(1.0)


async def mission_dispatch_loop(dispatcher, logger) -> None:
    """Run the explicit, disabled-by-default Mission to OMX bridge off request handlers."""
    while True:
        try:
            await asyncio.to_thread(dispatcher.dispatch_next)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Fleet Mission dispatcher cycle failed")
        await asyncio.sleep(0.25)


async def task_dispatch_loop(console: FleetConsole, task_service: FleetTaskService,
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
