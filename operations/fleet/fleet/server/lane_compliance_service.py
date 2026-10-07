"""D-511 M0: lane-compliance monitor — observe and notify only, never a command to a robot.

Every tick (2 Hz, D-511 2) each roster robot is judged from `MapPoseService.arbitrated_pose`
against the active site graph. A robot whose odom moved within `max_odom_age_s` (beyond the `moving_min_m` / `moving_min_deg` jitter deadband) gets
`refresh(force_rest=True)` first, the trip loop's read; a still robot keeps its heartbeat odom.
The console raises WARN/ACT only for `moving` robots (D-511 2: the watch is on moving robots).
When the map pose is not LOCALIZED (a site without corner or robot markers) and an
`identity` service is wired, the robot's D-472 LED-confirmed track is judged instead (addendum 3:
lane compliance only; the track never reaches MapPoseService, trips, initialpose or commands). The
track counts only when CONFIRMED, its age within [-MAX_SIGHTING_FUTURE_S, `sighting_lease_s`] like a
map pose sighting, and on the active site map id. Its blob has no heading: while odom says moving
and the track moved more than `track_heading_min_m`, the direction of that move is the heading and
is kept while the track stays fresh (a skipped camera frame repeats the position); before the
first such heading the arc is chosen without the heading gate (`heading_source` `pose` |
`track_motion` | `none`, logged on every change). A change of `pose_source` restarts the
WARN/ACT counts. `pose_source` says
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
from fleet.localization.map_pose import LOCALIZED, MAX_SIGHTING_FUTURE_S, MapPose

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
        self._track_yaw: dict[str, float] = {}                   # last motion heading of the track
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
            self._track_yaw.pop(gone, None)
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
            arbitrated = self._poses.arbitrated_pose(robot_id)
            pose, source, heading = self._input_pose(robot_id, arbitrated, robot_id in movers)
            previous = self._input.get(robot_id)
            if previous is None or previous[0] != source:   # another input: counts start over
                self._trackers[robot_id] = LaneComplianceTracker(self.config)
            tracker = self._trackers[robot_id]
            if previous != (source, heading):
                self._input[robot_id] = (source, heading)
                logger.info("lane compliance %s: judged from %s, heading %s%s", robot_id, source, heading,
                            " (LED track without a motion heading yet: nearest arc, no heading gate)"
                            if heading == "none" else "")
            result = tracker.judge(pose, graph)
            self._latest[robot_id] = {**asdict(result), "pose_state": getattr(arbitrated, "state", UNKNOWN),
                                      "pose_source": source, "heading_source": heading,
                                      "moving": robot_id in movers,
                                      "map_version": active[0] if active is not None else None,
                                      "at": self._wall()}

    def _input_pose(self, robot_id: str, arbitrated, moving: bool) -> tuple:
        """(pose to judge, pose_source, heading_source): the map pose, else a fresh LED track."""
        track = None
        if self._identity is not None and getattr(arbitrated, "state", None) != LOCALIZED:
            track = self._identity.confirmed_track_pose(robot_id)
        age = None if track is None else track.get("age_s")
        if (track is None or track.get("state") != "CONFIRMED" or age is None
                or not -MAX_SIGHTING_FUTURE_S <= age <= self._poses.config.sighting_lease_s
                or self._poses.active_map_id() not in (None, track.get("map_id"))):
            self._track_from.pop(robot_id, None)
            self._track_yaw.pop(robot_id, None)
            return arbitrated, "map_pose", "pose"
        x, y, yaw, heading = track["x"], track["y"], track.get("yaw"), "pose"
        if yaw is None:
            # The blob tracker has no heading. Odom says moving and the blob moved beyond the
            # camera-noise deadband: that direction is the heading, kept while the track is fresh
            # (a skipped frame repeats the position). Before the first one: no heading gate.
            last = self._track_from.get(robot_id)
            if last is None or math.hypot(x - last[0], y - last[1]) > self.config.track_heading_min_m:
                self._track_from[robot_id] = (x, y)
                if last is not None and moving:
                    self._track_yaw[robot_id] = math.atan2(y - last[1], x - last[0])
            yaw = self._track_yaw.get(robot_id)
            heading = "none" if yaw is None else "track_motion"
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
