"""Network load (bounded robot reads): spread the localization service's per-tick robot state reads.

The service reads every robot each 0.5 s tick. Without this, N robots are asked at the same
instant. ``spread`` wraps the read so each robot starts at its own stable offset in
``[0, spread_s)`` and at most ``max_reads`` reads run at once.
"""

from __future__ import annotations

import asyncio
import zlib
from typing import Awaitable, Callable, Mapping

MAX_READS_IN_FLIGHT = 4


def offset(robot_id: str, spread_s: float) -> float:
    """A robot's stable start offset in ``[0, spread_s)``: same robot, same slot every tick."""
    return (zlib.crc32(robot_id.encode("utf-8")) % 1000) / 1000.0 * spread_s


def spread(read: Callable[[str], Awaitable[Mapping]], spread_s: float,
           max_reads: int = MAX_READS_IN_FLIGHT) -> Callable[[str], Awaitable[Mapping]]:
    """``read`` delayed by the robot's offset and capped at ``max_reads`` in flight.

    shortcut: the caller's per-call timeout also covers the offset and the wait for a slot,
    so ``max_reads`` hung robots can time out the queued ones; raise ``max_reads`` if a site
    sees more hung robots at once than that.
    """
    slots = asyncio.Semaphore(max_reads)

    async def spread_read(robot_id: str) -> Mapping:
        await asyncio.sleep(offset(robot_id, spread_s))
        async with slots:
            return await read(robot_id)
    return spread_read
