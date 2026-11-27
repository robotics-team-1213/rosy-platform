"""Renew the ceiling camera stream while Fleet supervises a road trip or its traffic hold."""
import asyncio
import logging
import time

from fleet.localization.relative_search_prior import MAX_FRAME_AGE_S

_LOG = logging.getLogger(__name__)
RENEW_S = 10.0  # The existing per-source Vision stream hold is 30 s.


def _waiting_peers(live, map_id):
    detail = live.view.get("detail") or {}
    wait = detail.get("peer_wait") or {}
    if (not live.open or live.view.get("hold") or wait.get("stage") != "pre_dispatch_peer_check"
            or wait.get("dispatch_attempted") is not False or wait.get("site_route_map") != map_id
            or not live.view.get("robot_id") or wait.get("command_robot_id") != live.view["robot_id"]
            or wait.get("reason") != "LOCALIZATION_UNTRUSTED"):
        return set()
    peers = set(wait.get("waiting_on") or ())
    proof = wait.get("peer_evidence") or {}
    eligible = {"approved_marker_unavailable", "stationary_interval_pending", "keep_out_intersection"}
    return peers if (live.view["robot_id"] not in peers and wait.get("blocked_by") in peers
                     and all((proof.get(rid) or {}).get("reason") in eligible for rid in peers)) else set()


class RoadVisionDemand:
    def __init__(self, reader, sightings, *, clock=time.monotonic, localization=None):
        self.reader, self.sightings, self.clock = reader, sightings, clock
        self.localization = localization
        self._next = {}
        self._tasks = {}
        self._failed = set()

    def new_peer_observations(self, live, map_id, now):
        """A fresh enrolled observation can request an earlier check, never authorize motion."""
        peers = _waiting_peers(live, map_id)
        if not peers:
            return None
        wait = live.view["detail"]["peer_wait"]
        checked = wait["checked_at"]
        if now - checked < MAX_FRAME_AGE_S or wait.get("observation_retry"):
            return None
        sources = {source.source_id: dict(source.robot_markers) for source in self.sightings.sources
                   if source.map_id == map_id}
        samples = {}
        for row in self.sightings.snapshot()["sightings"]:
            rid, src = row["robot_id"], row["source_id"]
            if (rid in peers and rid in sources.get(src, {}) and row["map_id"] == map_id
                    and checked < row["captured_at"] <= now and now - row["captured_at"] <= MAX_FRAME_AGE_S
                    and row.get("calibration_source") == "approved_record" and row.get("calibration_revision")
                    and row["calibration_revision"] == self.sightings.approved_sighting_revision(src, map_id)):
                samples[rid] = {k: row[k] for k in ("source_id", "seq", "captured_at", "calibration_revision")}
        return {"checked_at": now, "peers": samples} if samples.keys() == peers else None

    def period(self, runner):
        robots = {robot for robot, live in runner._live.items() if live.open and
                  (live.nav2 or live.segment_is_lane(live.view["segment_index"]))}
        tiebreak_robots = (
            set(getattr(self.localization, "_fallback", ()))
            if self.localization is not None else set()
        )
        wanted = set()
        active = runner._store.active() if (robots or tiebreak_robots) else None
        if active is not None:
            eligible = [src for src in self.sightings.sources if src.map_id == active[1].map_id]
            latest = None
            movers = {rid for rid in robots if runner._live[rid].view["map_version"] == active[0]}
            peers = (
                {peer for rid in movers for peer in _waiting_peers(runner._live[rid], active[1].map_id)}
                | tiebreak_robots
            )
            for robot in (*sorted(movers), *sorted(peers - movers)):
                choices = {src.source_id for src in eligible if robot in src.robot_ids
                           and (robot in movers or robot in tiebreak_robots or robot in dict(src.robot_markers))}
                if robot not in movers and choices & wanted:
                    continue
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
