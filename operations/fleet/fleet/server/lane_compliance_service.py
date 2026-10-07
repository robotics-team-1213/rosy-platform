"""D-511 M0: lane-compliance monitor — observe and notify only, never a command to a robot.

Every tick (2 Hz, D-511 2) each roster robot is judged from `MapPoseService.arbitrated_pose`
against the active site graph. A robot whose odom moved within `max_odom_age_s` (beyond the `moving_min_m` / `moving_min_deg` jitter deadband) gets
`refresh(force_rest=True)` first, the trip loop's read; a still robot keeps its heartbeat odom.
The console raises WARN/ACT only for `moving` robots (D-511 2: the watch is on moving robots).
When the map pose is not LOCALIZED (a site without corner or robot markers) and an
`identity` service is wired, the robot's D-472 LED-confirmed track is judged instead (addendum 3:
lane compliance only; the track never reaches MapPoseService, trips, initialpose or commands). The
track counts only when CONFIRMED, no older than the map pose's `sighting_lease_s` and on the active
site map id. Its blob has no heading: the heading is the direction from the last track position
that moved more than `moving_min_m`, else the arc is chosen without the heading gate
(`heading_source` `pose` | `track_motion` | `none`, logged on every change). `pose_source` says
which input produced the sample (`map_pose` | `led_track`); `pose_state` stays the map pose state.
The latest result per robot is read by `GET /api/fleet/state` rows (`lane_compliance`) and
`GET /api/fleet/robots/{id}/lane-compliance`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict
from typing import Callable, Iterable, Optional

from fastapi import HTTPException

from fleet.localization.lane_compliance import (UNKNOWN, LaneComplianceConfig,
                                                LaneComplianceTracker)
from fleet.localization.map_pose import LOCALIZED, MapPose

#: D-511 2: the monitor reads poses at 2 Hz or faster, like the trip loop (D-494 appendix).
PERIOD_S = 0.5

logger = logging.getLogger("fleet.lane_compliance")


class LaneComplianceMonitor:
    def __init__(self, robot_ids: Callable[[], Iterable[str]], *, poses, site_maps,
                 config: LaneComplianceConfig = LaneComplianceConfig(), identity=None,
                 wall: Callable[[], float] = time.time) -> None:
        self.config = config
        self._robot_ids = robot_ids
        self._poses = poses              # MapPoseService: moved / refresh / arbitrated_pose
        self._site_maps = site_maps      # SiteMapStore: active() -> (version, map, graph, painted)
        self._identity = identity        # D-472 IdentityService: confirmed_track_pose only
        self._wall = wall
        self._track_from: dict[str, tuple[float, float]] = {}   # last track point beyond the deadband
        self._input: dict[str, tuple[str, str]] = {}            # (pose_source, heading_source), for logs
        self._trackers: dict[str, LaneComplianceTracker] = {}
        self._latest: dict[str, dict] = {}

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._robot_ids())

    async def tick(self) -> None:
        roster = list(self._robot_ids())
        for gone in set(self._trackers) - set(roster):
            self._trackers.pop(gone, None)
            self._latest.pop(gone, None)
            self._track_from.pop(gone, None)
            self._input.pop(gone, None)
        cfg = self.config
        movers = [r for r in roster if self._poses.moved(r, cfg.moving_min_m, cfg.moving_min_deg)]
        # A failed or slow read (cut at one period) leaves the last odom, which goes UNKNOWN
        # after max_odom_age_s; one slow robot never holds up the others' judgement.
        await asyncio.gather(*(asyncio.wait_for(self._poses.refresh(r, force_rest=True), PERIOD_S)
                               for r in movers), return_exceptions=True)
        active = self._site_maps.active()
        graph = active[2] if active is not None else None
        for robot_id in roster:
            tracker = self._trackers.setdefault(robot_id, LaneComplianceTracker(self.config))
            arbitrated = self._poses.arbitrated_pose(robot_id)
            pose, source, heading = self._input_pose(robot_id, arbitrated)
            if self._input.get(robot_id) != (source, heading):
                self._input[robot_id] = (source, heading)
                logger.info("lane compliance %s: judged from %s, heading %s%s", robot_id, source, heading,
                            " (still LED track: nearest arc, no heading gate)" if heading == "none" else "")
            result = tracker.judge(pose, graph)
            self._latest[robot_id] = {**asdict(result), "pose_state": getattr(arbitrated, "state", UNKNOWN),
                                      "pose_source": source, "heading_source": heading,
                                      "moving": robot_id in movers,
                                      "map_version": active[0] if active is not None else None,
                                      "at": self._wall()}

    def _input_pose(self, robot_id: str, arbitrated) -> tuple:
        """(pose to judge, pose_source, heading_source): the map pose, else a fresh LED track."""
        if self._identity is None or getattr(arbitrated, "state", None) == LOCALIZED:
            self._track_from.pop(robot_id, None)
            return arbitrated, "map_pose", "pose"
        track = self._identity.confirmed_track_pose(robot_id)
        active_map = self._poses.active_map_id()
        if (track.get("state") != "CONFIRMED" or track.get("age_s") is None
                or track["age_s"] > self._poses.config.sighting_lease_s
                or (active_map is not None and track.get("map_id") != active_map)):
            self._track_from.pop(robot_id, None)
            return arbitrated, "map_pose", "pose"
        x, y, yaw, heading = track["x"], track["y"], track.get("yaw"), "pose"
        if yaw is None:
            # The blob tracker has no heading: take the direction of travel once the track moved
            # beyond the monitor's moving deadband; a still robot is judged without the heading gate.
            last = self._track_from.get(robot_id)
            if last is None or math.hypot(x - last[0], y - last[1]) > self.config.moving_min_m:
                self._track_from[robot_id] = (x, y)
            if last is not None and math.hypot(x - last[0], y - last[1]) > self.config.moving_min_m:
                yaw, heading = math.atan2(y - last[1], x - last[0]), "track_motion"
            else:
                heading = "none"
        return (MapPose(x, y, yaw, LOCALIZED, "led_track", 0.0, track["age_s"], map_id=track.get("map_id")),
                "led_track", heading)

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
