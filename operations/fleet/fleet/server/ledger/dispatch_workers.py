"""App-owned durable Mission dispatch and feedback scheduling loops."""
import asyncio


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
