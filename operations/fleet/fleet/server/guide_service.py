"""D-536: ``GET /api/fleet/guide`` — every robot's map situation and guide findings, read-only.

Reads only what Fleet already holds: the shared robot snapshot (``SharedGather``, 1 s), the
arbitrated map pose (D-494), Rosy Cam tracking (D-457), the active site graph and the traffic zones.
It keeps one thing of its own: since when each robot has stood still (for STOPPED_IN_ZONE).
"""

from __future__ import annotations

import math
import time
from typing import Callable, Mapping, Optional

from core_common.robot_body import PINKY_PRO  # public read-only anchor (D-430 §3)
from fleet.guide.situation import GuideConfig, add_near, situation, worst
from fleet.server.named_stop_map_pose import approved_slam_site_pose
from rosy.world.state.projections.map_pose import MapPose

#: below these the robot is standing (odom twist, m/s and rad/s)
STILL_LINEAR, STILL_ANGULAR = 0.01, 0.05
#: Display-only cap so offline robots stay visible between D-691 30 s overhead bursts.
OFFLINE_DISPLAY_MAX_AGE_S = 600.0


class GuideService:
    def __init__(self, *, gather, poses, site_maps, tracking=None, sightings=None,
                 zones: Callable[[], Mapping[str, tuple]] = dict, body=PINKY_PRO,
                 config: GuideConfig = GuideConfig(), clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._gather, self._poses, self._site_maps = gather, poses, site_maps
        self._tracking, self._sightings = tracking, sightings
        self._zones, self._body, self.config, self._clock, self._wall = zones, body, config, clock, wall
        self._still_since: dict[str, float] = {}

    def _stopped_s(self, robot_id: str, state: Optional[Mapping], now: float) -> float:
        velocity = (state or {}).get("velocity") or {}
        still = abs(velocity.get("linear") or 0.0) < STILL_LINEAR and abs(velocity.get("angular") or 0.0) < STILL_ANGULAR
        if not still:
            self._still_since.pop(robot_id, None)
            return 0.0
        return now - self._still_since.setdefault(robot_id, now)

    def _sighting_fallback(self, robot_id: str, active_map_id: Optional[str]) -> Optional[MapPose]:
        if self._sightings is None:
            return None
        for row in self._sightings.snapshot().get("sightings") or ():
            if row.get("robot_id") != robot_id:
                continue
            raw_age = row.get("age_ms")
            if not isinstance(raw_age, (int, float)) or not math.isfinite(raw_age):
                if row.get("stale") is True:
                    continue
                age_s = 0.0
            else:
                age_s = round(max(0.0, float(raw_age) / 1000.0), 2)
                if row.get("stale") is True and age_s > OFFLINE_DISPLAY_MAX_AGE_S:
                    continue
            if active_map_id is not None and row.get("map_id") != active_map_id:
                continue
            try:
                x, y, yaw = float(row["x"]), float(row["y"]), float(row["yaw"])
            except (KeyError, TypeError, ValueError):
                return None
            if not all(math.isfinite(v) for v in (x, y, yaw)):
                return None
            return MapPose(
                x, y, yaw, "DEGRADED", "sighting", 0.0, age_s,
                anchor_age_s=age_s, map_id=row.get("map_id"),
                anchor_source="sighting", last_sighting_age_s=age_s,
            )
        return None

    def _display_pose(self, robot_id: str, *, online: bool = True, active_map_id: Optional[str] = None):
        """D-989: an auto-located robot is shown at its SLAM pose through the fitted transform (read-only
        display; lane compliance and the other consumers keep `arbitrated_pose`). Offline robots fall back
        to a fresh ceiling-camera sighting as DEGRADED read-only display pose."""
        driving = getattr(self._poses, "driving_pose", None)
        pose = driving(robot_id) if driving is not None else self._poses.arbitrated_pose(robot_id)
        if not online and (pose is None or pose.state == "UNKNOWN"):
            sighting = self._sighting_fallback(robot_id, active_map_id)
            if sighting is not None:
                return sighting
        return pose

    async def view(self) -> dict:
        snapshot = await self._gather()
        tracking = self._tracking.snapshot() if self._tracking is not None else {}
        tracked = {row.get("robot_id"): row for row in tracking.get("robots") or []}
        camera_ok = next((s.get("source_id") for s in tracking.get("sources") or [] if s.get("status") == "OK"), None)
        anonymous = any(u.get("marker_id") is None for u in tracking.get("unknown") or [])  # D-596
        active = self._site_maps.active()
        graph = active[2] if active is not None else None
        active_map_id = active[1].map_id if active is not None and active[1] is not None else None
        zone_of = {edge: zone for zone, (edges, _cap) in (self._zones() or {}).items() for edge in edges}
        now = self._clock()
        now_wall = self._wall()
        records = []
        for row in snapshot.get("robots") or []:
            robot_id = row["robot_id"]
            online = bool(row.get("online"))
            bound = approved_slam_site_pose(self._site_maps, robot_id, row.get("state"), now_wall) if online else None
            pose = bound[0] if bound is not None else self._display_pose(robot_id, online=online, active_map_id=active_map_id)
            records.append(situation(
                robot_id, online=online, pose=pose,
                tracking_row=tracked.get(robot_id), camera_ok=camera_ok, graph=graph, zone_of=zone_of,
                body_radius_m=self._body.rotation_radius_m, body_half_width_m=self._body.half_width_m,
                stopped_s=self._stopped_s(robot_id, row.get("state"), now), anonymous_seen=anonymous,
                active_map_id=active_map_id, config=self.config))
        add_near(records, self.config)
        for record in records:
            record["worst"] = worst(record)
        return {"map_version": active[0] if active is not None else None, "camera": camera_ok,
                "robots": records}


def install_guide_routes(app, *, service: GuideService, read_guard) -> None:
    @app.get("/api/fleet/guide", dependencies=read_guard, tags=["fleet"])
    async def fleet_guide() -> dict:
        """D-536: each robot's map pose, body circle, lane context and guide findings."""
        return await service.view()
