"""D-491 3: feed accepted sightings and robot `odom_pose` into one map pose tracker per robot.

Sightings come only from `SightingService.accept` (source token bound to the robot id, lease,
order), odom from every state snapshot the console reads (hub heartbeat or REST) and from
`refresh`. `arbitrated_pose` is for the trip loop (D-491 5) only; `/route`, D-395 and traffic
keep `FleetConsole.trusted_map_pose`. D-457 tracking is not an input.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Awaitable, Callable, Iterable, Mapping, Optional

from fastapi import HTTPException

from fleet.hub.hub import HubError
from fleet.localization.map_pose import (MapPose, MapPoseConfig, MapPoseTracker,
                                         odom_from_snapshot, sighting_from_row)
from fleet.swarm.transport import RobotApiError


class MapPoseService:
    def __init__(self, robot_ids: Callable[[], Iterable[str]], *,
                 config: MapPoseConfig = MapPoseConfig(),
                 gather: Optional[Callable[[str], Awaitable[Optional[Mapping]]]] = None,
                 wall: Callable[[], float] = time.time) -> None:
        self.config = config
        self._robot_ids = robot_ids
        self._gather = gather
        self._wall = wall           # sighting captured_at and odom stamps are site wall time
        self._trackers: dict[str, MapPoseTracker] = {}

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._robot_ids())

    def _tracker(self, robot_id: str) -> Optional[MapPoseTracker]:
        if not self.knows(robot_id):
            self._trackers.pop(robot_id, None)      # removed from the roster
            return None
        tracker = self._trackers.get(robot_id)
        if tracker is None:
            tracker = self._trackers[robot_id] = MapPoseTracker(robot_id, self.config)
        return tracker

    def observe_sighting(self, row: Mapping) -> None:
        sighting = sighting_from_row(row)
        tracker = self._tracker(sighting.robot_id) if sighting is not None else None
        if tracker is not None:
            tracker.add_sighting(sighting, self._wall())

    def observe_state(self, robot_id: str, state: Optional[Mapping]) -> None:
        sample = odom_from_snapshot(state)
        tracker = self._tracker(robot_id) if sample is not None else None
        if tracker is not None:
            tracker.add_odom(sample, self._wall())

    async def refresh(self, robot_id: str) -> None:
        """Read the robot's state now (hub snapshot when fresh, else REST) and feed its odom."""
        if self._gather is not None:
            self.observe_state(robot_id, await self._gather(robot_id))

    def arbitrated_pose(self, robot_id: str) -> Optional[MapPose]:
        """The robot's map pose for trip execution; None for a robot not on the roster."""
        tracker = self._tracker(robot_id)
        return tracker.pose(self._wall()) if tracker is not None else None


def install_map_pose_routes(app, *, service: MapPoseService, read_guard) -> None:
    @app.get("/api/fleet/robots/{robot_id}/map-pose", dependencies=read_guard, tags=["fleet"])
    async def robot_map_pose(robot_id: str) -> dict:
        if not service.knows(robot_id):
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT",
                                                         "message": "robot is not on the roster"})
        try:
            await service.refresh(robot_id)
        except (HubError, RobotApiError, OSError):
            pass    # an unreachable robot reads its last odom, which goes UNKNOWN after 3 s
        return {"robot_id": robot_id, **asdict(service.arbitrated_pose(robot_id))}
