"""One shared geometry computation for the active map's platoon display."""

import asyncio
import math

from fleet import lane_progress
from fleet.speed_table import speed_table


def _geometry(site):
    edges = lane_progress.main_loop(site)
    if edges is None:
        return None
    loop = lane_progress.Loop(site, edges)
    segments = [(edge, True, 0.0, math.inf) for edge in edges]
    return edges, loop, speed_table(site, segments, closed=True)


class PlatoonGeometry:
    """Keep only the latest map version; poses and headways stay per request."""

    def __init__(self):
        self._version = self._task = None

    async def get(self, active):
        if self._task is None or self._version != active[0]:
            self._version = active[0]
            self._task = asyncio.create_task(asyncio.to_thread(_geometry, active[1]))
        task = self._task
        try:
            # A disconnected reader must not cancel geometry shared by the next poll.
            return await asyncio.shield(task)
        except Exception:
            if self._task is task:
                self._task = None
            raise
