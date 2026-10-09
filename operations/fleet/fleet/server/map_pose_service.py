"""D-494 3: feed accepted sightings and robot `odom_pose` into one map pose tracker per robot.

Sightings come only from `SightingService.accept` (source token bound to the robot id, lease,
order) and, when a map id provider is given, only for the active site map frame. Odom comes from
every state snapshot the console reads (hub heartbeat or REST) and from `refresh`.
`arbitrated_pose` is for the trip loop (D-494 5) and the D-511 lane-compliance monitor; `/route`, D-395 and traffic keep
`FleetConsole.trusted_map_pose`. D-457 tracking is not an input.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict
from typing import Awaitable, Callable, Iterable, Mapping, Optional

import httpx
from fastapi import HTTPException

from fleet.hub.hub import HubError
from fleet.localization.map_pose import (MapPose, MapPoseConfig, MapPoseTracker,
                                         odom_from_snapshot, sighting_from_row)
from fleet.swarm.transport import RobotApiError

#: `refresh` skips the robot read while the newest odom sample is younger than this.
REFRESH_FRESH_S = 0.2

logger = logging.getLogger("fleet.map_pose")


class MapPoseService:
    def __init__(self, robot_ids: Callable[[], Iterable[str]], *,
                 config: MapPoseConfig = MapPoseConfig(),
                 gather: Optional[Callable[[str], Awaitable[Optional[Mapping]]]] = None,
                 gather_rest: Optional[Callable[[str], Awaitable[Optional[Mapping]]]] = None,
                 map_id: Optional[Callable[[], Optional[str]]] = None,
                 source_map_ids: Iterable[str] = (),
                 wall: Callable[[], float] = time.time) -> None:
        self.config = config
        self._robot_ids = robot_ids
        self._gather = gather              # hub snapshot when fresh, else REST
        self._gather_rest = gather_rest    # always the robot's REST state (trip loop)
        #: The active site map frame id; None (or no provider) accepts any sighting map id.
        self._map_id = map_id
        self._bad_snapshot: set[str] = set()
        self._source_map_ids = frozenset(source_map_ids)
        self._warned_map_ids: set[str] = set()
        self._wall = wall           # sighting captured_at and odom stamps are UTC epoch seconds
        self._trackers: dict[str, MapPoseTracker] = {}
        self._refreshing: dict[tuple[str, bool], asyncio.Future] = {}

    def active_map_id(self) -> Optional[str]:
        """The active site map frame id; warns once per id that no sighting source reports."""
        active = self._map_id() if self._map_id is not None else None
        if (active is not None and self._source_map_ids and active not in self._source_map_ids
                and active not in self._warned_map_ids):
            self._warned_map_ids.add(active)
            logger.warning("map pose: active site map id %r matches no sighting source map_id %s; "
                           "every sighting is filtered and trip map poses stay UNKNOWN",
                           active, sorted(self._source_map_ids))
        return active

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._robot_ids())

    def _tracker(self, robot_id: str) -> Optional[MapPoseTracker]:
        roster = set(self._robot_ids())
        for gone in set(self._trackers) - roster:     # a robot that left starts over if it returns
            del self._trackers[gone]
        if robot_id not in roster:
            return None
        tracker = self._trackers.get(robot_id)
        if tracker is None:
            tracker = self._trackers[robot_id] = MapPoseTracker(robot_id, self.config)
        return tracker

    def observe_sighting(self, row: Mapping) -> None:
        sighting = sighting_from_row(row)
        if sighting is None:
            return
        tracker = self._tracker(sighting.robot_id)
        if tracker is not None:
            tracker.add_sighting(sighting, self._wall(), self.active_map_id())

    def observe_state(self, robot_id: str, state: Optional[Mapping]) -> None:
        try:
            self._observe_state(robot_id, state)
        except Exception:           # a bad snapshot is logged once per robot, never raised
            if robot_id not in self._bad_snapshot:
                self._bad_snapshot.add(robot_id)
                logger.exception("map pose: snapshot of %s not usable", robot_id)

    def _observe_state(self, robot_id: str, state: Optional[Mapping]) -> None:
        if not isinstance(state, Mapping) or state.get("odom_pose") is None:
            return                  # a robot before D-494 2: nothing to count
        tracker = self._tracker(robot_id)
        if tracker is None:
            return
        sample = odom_from_snapshot(state)
        if sample is None:
            tracker.refuse_odom("malformed")
        else:
            tracker.add_odom(sample, self._wall())

    async def refresh(self, robot_id: str, *, force_rest: bool = False) -> None:
        """Read the robot's state now and feed its odom.

        Default: the hub snapshot when fresh, else REST. `force_rest` (the trip loop, at 2 Hz or
        faster) bypasses the hub cache. Concurrent callers share one read per robot and mode; a
        read is skipped while odom is fresher than 0.2 s."""
        gather = self._gather_rest if force_rest else self._gather
        tracker = self._tracker(robot_id)
        if gather is None or tracker is None:
            return
        latest = tracker.latest_odom_stamp
        if latest is not None and self._wall() - latest < REFRESH_FRESH_S:
            return
        key = (robot_id, force_rest)
        running = self._refreshing.get(key)
        if running is None:
            running = self._refreshing[key] = asyncio.ensure_future(gather(robot_id))
            running.add_done_callback(lambda done: self._refresh_done(key, done))
        state = await asyncio.shield(running)
        self.observe_state(robot_id, state)

    def _refresh_done(self, key: tuple, done: asyncio.Future) -> None:
        self._refreshing.pop(key, None)
        # Retrieved here so a read whose waiters were all cancelled never logs "never retrieved".
        if not done.cancelled() and done.exception() is not None:
            logger.debug("map pose: state read for %s failed: %r", key[0], done.exception())

    def moved(self, robot_id: str, min_m: float, min_deg: float) -> bool:
        """D-511 2: the robot's odom moved beyond the deadband within the last `max_odom_age_s`."""
        tracker = self._tracker(robot_id)
        return tracker is not None and tracker.moved_since(
            self._wall() - self.config.max_odom_age_s, min_m, math.radians(min_deg))

    def odom_to_map(self, robot_id: str):
        """D-581 trail anchor: the tracker's (map <- odom, newest odom, anchor captured_at, epoch)."""
        tracker = self._tracker(robot_id)
        return tracker.odom_to_map() if tracker is not None else None

    def arbitrated_pose(self, robot_id: str) -> Optional[MapPose]:
        """The robot's map pose for trip execution and the D-511 lane-compliance monitor
        (D-511 2 widens D-494 3); None for a robot not on the roster."""
        tracker = self._tracker(robot_id)
        return tracker.pose(self._wall(), self.active_map_id()) if tracker is not None else None

    def stuck_pose(self, robot_id: str) -> Optional[dict]:
        """D-577 1: R3's pose input. `sourced` = a sighting ever reached this robot's tracker, so an
        UNKNOWN is a lost pose rather than "Fleet has no map pose for it"."""
        tracker = self._tracker(robot_id)
        if tracker is None:
            return None
        pose = tracker.pose(self._wall(), self.active_map_id())
        return {"state": pose.state, "age_s": pose.age_s, "sourced": tracker.sourced}


def install_map_pose_routes(app, *, service: MapPoseService, read_guard) -> None:
    unknown = HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT",
                                                     "message": "robot is not on the roster"})

    @app.get("/api/fleet/robots/{robot_id}/map-pose", dependencies=read_guard, tags=["fleet"])
    async def robot_map_pose(robot_id: str) -> dict:
        if not service.knows(robot_id):
            raise unknown
        try:
            await service.refresh(robot_id)
        except (HubError, RobotApiError, OSError, httpx.HTTPError, asyncio.TimeoutError):
            pass    # an unreachable robot reads its last odom, which goes UNKNOWN after 3 s
        pose = service.arbitrated_pose(robot_id)
        if pose is None:            # removed from the roster while the read was in flight
            raise unknown
        return {"robot_id": robot_id, **asdict(pose)}
