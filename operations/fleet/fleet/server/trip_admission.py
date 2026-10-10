"""D-494 5 start admission of the trip loop (``trip_runner``): the capability, line-follow and map
pose checks a trip start (and each D-517 2 lap) passes, moved out of ``trip_runner`` (2026-10-10 seam,
docs/plans/2026-10-07-fleet-site-map-web-server-seam.md); ``TripRunner`` mixes it in. D-601: the start
alignment against the first lane (``start_check``) and the plan-time line camera check.
"""

from __future__ import annotations

import math

from fleet.localization.map_pose import OPERATOR_PIN
from fleet.routing.cost import wrap
from fleet.routing.execute import arc_id, unsupported
from fleet.server.trip_ports import MapPose, TripError

LOCALIZED = "LOCALIZED"
#: CORE takes junction instructions only on CAMERA_LINE (IR_LINE: 409 JUNCTION_CAMERA_ONLY).
LINE_MODES = ("CAMERA_LINE",)


def start_check(graph, segments: list, x: float, y: float, yaw, tol_deg: float) -> dict:
    """D-601 D: the robot against its plan's first lane (``code`` None: it may start). Off the lane is
    the trip loop's own rule (more than half the lane width, ``_locate``); the heading is compared
    with the lane's direction at the robot's projection (one-way or the planned way)."""
    arc = graph.arcs[arc_id(segments[0])] if segments else None
    if arc is None or arc.drive_mode != "lane":
        return {"code": None}
    dist, _s, tangent = arc.project(x, y)
    err = None if yaw is None else round(math.degrees(wrap(yaw - tangent)), 1)
    code = ("TRIP_START_OFF_LANE" if dist > arc.width_m / 2
            else "TRIP_START_HEADING_MISMATCH" if err is None or abs(err) > tol_deg else None)
    return {"code": code, "edge_id": arc.edge_id, "heading_err_deg": err, "tol_deg": tol_deg,
            "off_lane_m": round(max(0.0, dist - arc.width_m / 2), 3)}


class TripAdmission:
    async def _caps_checks(self, robot_id: str, graph, segments: list, repeat: bool, final_place=None):
        """D-494 start checks on the robot's capabilities; the caps, or ``TripError``."""
        map_id = self._store.active()[1].map_id
        lane = any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in segments)
        caps = await self._call(self._caps(robot_id), "TRIP_ROBOT_CAPS_UNKNOWN")
        if caps is None:
            raise TripError(422, "TRIP_ROBOT_CAPS_UNKNOWN")
        refused = unsupported(graph, segments, kind=caps.kind, modes=caps.modes,
                              junction_turn=caps.junction_turn, config=self._routing,
                              max_turn_deg=self.config.max_turn_deg, repeat=repeat,
                              final_place=final_place)
        if refused is not None:
            raise TripError(422, "TRIP_MODE_UNSUPPORTED", refused)
        floor = caps.site_floor_map_id  # D-507 9: absent (older CORE) or null declares no floor
        if lane and floor is not None and floor != map_id:
            raise TripError(422, "TRIP_SITE_FLOOR_MISMATCH", {"site_floor_map_id": floor, "map_id": map_id})
        if lane and self.authority.mode(caps) == "core" and caps.line_follow_authority_required is not True:
            raise TripError(422, "TRIP_AUTHORITY_NOT_REQUIRED")  # D-517 4: no first-authority gap after a restart
        if lane and self.authority.mode(caps) != "core" and caps.line_follow_authority_required is True:
            raise TripError(422, "TRIP_AUTHORITY_SITE_OFF")  # D-517 M5: no authority goes out, so CORE never moves
        return caps

    async def _pose_checks(self, robot_id: str, graph, segments: list, *, start: bool = False):
        """D-494 start checks on line following and the map pose: ``(pose, enable)`` or ``TripError``.
        D-601 A: at a start (not a lap) a robot with line following OFF passes, ``enable`` True: the
        trip turns the camera line on itself once it is open. D-601 D: a start also checks alignment."""
        enable = False
        if any(graph.arcs[arc_id(seg)].drive_mode == "lane" for seg in segments):
            mode = await self._call(self._junction.line_follow_mode(robot_id), "TRIP_LINE_FOLLOW_NOT_ACTIVE")
            # review HIGH 1: only a trip that starts on a lane; a free first segment keeps the refusal
            enable = start and mode == "OFF" and graph.arcs[arc_id(segments[0])].drive_mode == "lane"
            if mode not in LINE_MODES and not enable:
                raise TripError(422, "TRIP_LINE_FOLLOW_NOT_ACTIVE", {"mode": mode})
        pose = await self.map_pose(robot_id)
        anchor_age = getattr(pose, "anchor_age_s", None)
        if pose is None or pose.state != LOCALIZED or anchor_age is None or (
                anchor_age > self.config.start_anchor_age_s and not self._still_on_pin(pose)):
            raise TripError(422, "TRIP_POSE_UNTRUSTED", {"pose_state": pose.state if pose else None,
                                                         "anchor_age_s": anchor_age})
        if start:
            check = start_check(graph, segments, pose.x, pose.y, pose.yaw, self.config.start_heading_tol_deg)
            if check["code"] is not None:
                raise TripError(422, check["code"], check)
        return pose, enable

    async def camera_check(self, robot_id: str) -> None:
        """D-601 B (plan time, lane plans): the robot's front camera, the line camera, must be live
        (CORE ``vision/front/status`` ``available``); else 422 ``TRIP_LANE_CAMERA_UNAVAILABLE``. Off with
        ``fleet.trip.lane_camera_check: false`` (Gazebo SIM publishes no front preview)."""
        if not self.config.lane_camera_check:
            return
        status = await self._call(self._junction.front_camera(robot_id), "TRIP_LANE_CAMERA_UNAVAILABLE") or {}
        if status.get("available") is not True:
            raise TripError(422, "TRIP_LANE_CAMERA_UNAVAILABLE", {"stale": status.get("stale"),
                                                                    "age_ms": status.get("age_ms")})

    def _still_on_pin(self, pose: MapPose) -> bool:
        """D-593 7: a LOCALIZED operator-pin pose (its anchor is then <= max_anchor_age_s old) whose
        odom has not moved since the pin. An odom reset drops the anchor, so it is never still."""
        return (getattr(pose, "anchor_source", None) == OPERATOR_PIN
                and pose.dead_reckon_m <= self.config.pin_start_still_m
                and getattr(pose, "bridge_turn_deg", math.inf) <= self.config.pin_start_still_deg)
