"""Cancellation waits for the owned SQLite write to reach a terminal result."""
import asyncio


async def owned(port, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(port, *args, **kwargs))
    cancelled = False
    while not task.done():
        try: await asyncio.shield(task)
        except asyncio.CancelledError: cancelled = True
    result = task.result()
    if cancelled: raise asyncio.CancelledError
    return result
