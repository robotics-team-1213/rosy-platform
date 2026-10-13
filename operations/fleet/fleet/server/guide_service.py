"""D-536: ``GET /api/fleet/guide`` — every robot's map situation and guide findings, read-only.

Reads only what Fleet already holds: the shared robot snapshot (``SharedGather``, 1 s), the
arbitrated map pose (D-494), Rosy Cam tracking (D-457), the active site graph and the traffic zones.
It keeps one thing of its own: since when each robot has stood still (for STOPPED_IN_ZONE).
"""

from __future__ import annotations

import time
from typing import Callable, Mapping, Optional

from core_common.robot_body import PINKY_PRO  # public read-only anchor (D-430 §3)
from fleet.guide.situation import GuideConfig, add_near, situation, worst

#: below these the robot is standing (odom twist, m/s and rad/s)
STILL_LINEAR, STILL_ANGULAR = 0.01, 0.05


class GuideService:
    def __init__(self, *, gather, poses, site_maps, tracking=None,
                 zones: Callable[[], Mapping[str, tuple]] = dict, body=PINKY_PRO,
                 config: GuideConfig = GuideConfig(), clock: Callable[[], float] = time.monotonic) -> None:
        self._gather, self._poses, self._site_maps, self._tracking = gather, poses, site_maps, tracking
        self._zones, self._body, self.config, self._clock = zones, body, config, clock
        self._still_since: dict[str, float] = {}

    def _stopped_s(self, robot_id: str, state: Optional[Mapping], now: float) -> float:
        velocity = (state or {}).get("velocity") or {}
        still = abs(velocity.get("linear") or 0.0) < STILL_LINEAR and abs(velocity.get("angular") or 0.0) < STILL_ANGULAR
        if not still:
            self._still_since.pop(robot_id, None)
            return 0.0
        return now - self._still_since.setdefault(robot_id, now)

    async def view(self) -> dict:
        snapshot = await self._gather()
        tracking = self._tracking.snapshot() if self._tracking is not None else {}
        tracked = {row.get("robot_id"): row for row in tracking.get("robots") or []}
        camera_ok = next((s.get("source_id") for s in tracking.get("sources") or [] if s.get("status") == "OK"), None)
        anonymous = any(u.get("marker_id") is None for u in tracking.get("unknown") or [])  # D-596
        active = self._site_maps.active()
        graph = active[2] if active is not None else None
        zone_of = {edge: zone for zone, (edges, _cap) in (self._zones() or {}).items() for edge in edges}
        now = self._clock()
        records = []
        for row in snapshot.get("robots") or []:
            robot_id = row["robot_id"]
            records.append(situation(
                robot_id, online=bool(row.get("online")), pose=self._poses.arbitrated_pose(robot_id),
                tracking_row=tracked.get(robot_id), camera_ok=camera_ok, graph=graph, zone_of=zone_of,
                body_radius_m=self._body.rotation_radius_m, body_half_width_m=self._body.half_width_m,
                stopped_s=self._stopped_s(robot_id, row.get("state"), now), anonymous_seen=anonymous,
                config=self.config))
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
