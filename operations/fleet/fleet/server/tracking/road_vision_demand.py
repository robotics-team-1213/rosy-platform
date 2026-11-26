"""Renew the ceiling camera stream while Fleet supervises a road trip or its traffic hold."""
import asyncio
import logging
import time

_LOG = logging.getLogger(__name__)
RENEW_S = 10.0  # The existing per-source Vision stream hold is 30 s.


class RoadVisionDemand:
    def __init__(self, reader, sightings, *, clock=time.monotonic):
        self.reader, self.sightings, self.clock = reader, sightings, clock
        self._next = {}
        self._tasks = {}
        self._failed = set()

    def period(self, runner):
        robots = {robot for robot, live in runner._live.items() if live.open and
                  (live.nav2 or live.segment_is_lane(live.view["segment_index"]))}
        wanted = set()
        active = runner._store.active() if robots else None
        if active is not None:
            eligible = [src for src in self.sightings.sources if src.map_id == active[1].map_id]
            latest = None
            for robot in robots:
                choices = {src.source_id for src in eligible if robot in src.robot_ids
                           and runner._live[robot].view["map_version"] == active[0]}
                if len(choices) == 1:
                    wanted.update(choices)
                elif choices:
                    if latest is None:
                        latest = self.sightings.snapshot()["sightings"]
                    source = next((row["source_id"] for row in latest if row["robot_id"] == robot
                                   and row.get("map_id") == active[1].map_id and row["source_id"] in choices), None)
                    if source:
                        wanted.add(source)
        for source, task in list(self._tasks.items()):
            if task.done():
                del self._tasks[source]
            elif source not in wanted:
                task.cancel()
        now = self.clock()
        for source in wanted:
            if source not in self._tasks and now >= self._next.get(source, 0.):
                self._next[source] = now + RENEW_S
                self._tasks[source] = asyncio.create_task(self._send(source))

    async def _send(self, source):
        try:
            await self.reader.hold_stream(source)
        except Exception as exc:
            if source not in self._failed:
                _LOG.warning("road camera demand failed for %s (%s)", source, type(exc).__name__)
            self._failed.add(source)
        else:
            if source in self._failed:
                _LOG.info("road camera demand restored for %s", source)
            self._failed.discard(source)

    async def aclose(self):
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self.reader.aclose()
