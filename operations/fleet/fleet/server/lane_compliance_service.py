"""D-511 M0: lane-compliance monitor — observe and notify only, never a command to a robot.

Every tick (2 Hz, D-511 2) each roster robot is judged from `MapPoseService.arbitrated_pose`
against the active site graph. A robot whose odom moved within `max_odom_age_s` gets
`refresh(force_rest=True)` first, the trip loop's read; a still robot keeps its heartbeat odom.
The latest result per robot is read by `GET /api/fleet/state` rows (`lane_compliance`) and
`GET /api/fleet/robots/{id}/lane-compliance`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Callable, Iterable, Optional

from fastapi import HTTPException

from fleet.localization.lane_compliance import (UNKNOWN, LaneComplianceConfig,
                                                LaneComplianceTracker)

#: D-511 2: the monitor reads poses at 2 Hz or faster, like the trip loop (D-494 appendix).
PERIOD_S = 0.5


class LaneComplianceMonitor:
    def __init__(self, robot_ids: Callable[[], Iterable[str]], *, poses, site_maps,
                 config: LaneComplianceConfig = LaneComplianceConfig(),
                 wall: Callable[[], float] = time.time) -> None:
        self.config = config
        self._robot_ids = robot_ids
        self._poses = poses              # MapPoseService: moved / refresh / arbitrated_pose
        self._site_maps = site_maps      # SiteMapStore: active() -> (version, map, graph, painted)
        self._wall = wall
        self._trackers: dict[str, LaneComplianceTracker] = {}
        self._latest: dict[str, dict] = {}

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._robot_ids())

    async def tick(self) -> None:
        roster = list(self._robot_ids())
        for gone in set(self._trackers) - set(roster):
            self._trackers.pop(gone, None)
            self._latest.pop(gone, None)
        movers = [robot_id for robot_id in roster if self._poses.moved(robot_id)]
        # A failed read leaves the last odom, which goes UNKNOWN after max_odom_age_s.
        await asyncio.gather(*(self._poses.refresh(r, force_rest=True) for r in movers),
                             return_exceptions=True)
        active = self._site_maps.active()
        graph = active[2] if active is not None else None
        for robot_id in roster:
            tracker = self._trackers.setdefault(robot_id, LaneComplianceTracker(self.config))
            result = tracker.judge(self._poses.arbitrated_pose(robot_id), graph)
            self._latest[robot_id] = {**asdict(result), "moving": robot_id in movers,
                                      "map_version": active[0] if active is not None else None,
                                      "at": self._wall()}

    def view(self, robot_id: str) -> Optional[dict]:
        return self._latest.get(robot_id)


def install_lane_compliance_routes(app, *, monitor: LaneComplianceMonitor, read_guard) -> None:
    @app.get("/api/fleet/robots/{robot_id}/lane-compliance", dependencies=read_guard, tags=["fleet"])
    async def robot_lane_compliance(robot_id: str) -> dict:
        if not monitor.knows(robot_id):
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT",
                                                         "message": "robot is not on the roster"})
        latest = monitor.view(robot_id)
        if latest is None:          # before the first tick
            latest = {"level": UNKNOWN, "pose_state": None, "at": None}
        return {"robot_id": robot_id, **latest}
