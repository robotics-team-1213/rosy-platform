"""D-491 3: feed accepted sightings and robot `odom_pose` into one map pose tracker per robot.

Sightings come only from `SightingService.accept` (source token bound to the robot id, lease,
order) and, when a map id provider is given, only for the active site map frame. Odom comes from
every state snapshot the console reads (hub heartbeat or REST) and from `refresh`.
`arbitrated_pose` is for the trip loop (D-491 5) only; `/route`, D-395 and traffic keep
`FleetConsole.trusted_map_pose`. D-457 tracking is not an input.
"""

from __future__ import annotations

import asyncio
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


class MapPoseService:
    def __init__(self, robot_ids: Callable[[], Iterable[str]], *,
                 config: MapPoseConfig = MapPoseConfig(),
                 gather: Optional[Callable[[str], Awaitable[Optional[Mapping]]]] = None,
                 map_id: Optional[Callable[[], Optional[str]]] = None,
                 wall: Callable[[], float] = time.time) -> None:
        self.config = config
        self._robot_ids = robot_ids
        self._gather = gather
        #: The active site map frame id; None (or no provider) accepts any sighting map id.
        self._map_id = map_id
        self._wall = wall           # sighting captured_at and odom stamps are site wall time
        self._trackers: dict[str, MapPoseTracker] = {}
        self._refreshing: dict[str, asyncio.Future] = {}

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
        expected = self._map_id() if self._map_id is not None else None
        if expected is not None and sighting.map_id != expected:
            return
        tracker = self._tracker(sighting.robot_id)
        if tracker is not None:
            tracker.add_sighting(sighting, self._wall())

    def observe_state(self, robot_id: str, state: Optional[Mapping]) -> None:
        if not isinstance(state, Mapping) or state.get("odom_pose") is None:
            return                  # a robot before D-491 2: nothing to count
        tracker = self._tracker(robot_id)
        if tracker is None:
            return
        sample = odom_from_snapshot(state)
        if sample is None:
            tracker.refuse_odom("malformed")
        else:
            tracker.add_odom(sample, self._wall())

    async def refresh(self, robot_id: str) -> None:
        """Read the robot's state now (hub snapshot when fresh, else REST) and feed its odom.

        Concurrent callers share one read; a read is skipped while odom is fresher than 0.2 s."""
        tracker = self._tracker(robot_id)
        if self._gather is None or tracker is None:
            return
        latest = tracker.latest_odom_stamp
        if latest is not None and self._wall() - latest < REFRESH_FRESH_S:
            return
        running = self._refreshing.get(robot_id)
        if running is None:
            running = self._refreshing[robot_id] = asyncio.ensure_future(self._gather(robot_id))
            running.add_done_callback(lambda _f: self._refreshing.pop(robot_id, None))
        state = await asyncio.shield(running)
        self.observe_state(robot_id, state)

    def arbitrated_pose(self, robot_id: str) -> Optional[MapPose]:
        """The robot's map pose for trip execution; None for a robot not on the roster."""
        tracker = self._tracker(robot_id)
        return tracker.pose(self._wall()) if tracker is not None else None


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
