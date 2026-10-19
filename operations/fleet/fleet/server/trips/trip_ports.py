"""D-494 trip ports/config/state; app.py injects TripCaps, MapPoseService and HttpLaneJunction.

Junction/bend geometry is ``trip_geometry``, the per-robot runtime state ``LiveTrip`` is ``trip_live`` (D-798 split).
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, fields
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from fleet.hub.hub import HubError
from rosy.world.state.projections.map_pose import MapPose
from fleet.server.console_view import TripCaps

_LOG = logging.getLogger(__name__)

#: Trip states that are still going.
OPEN = ("started", "running", "link_wait")  # D-760 4: a robot without a link keeps its trip open


#: D-494 1: ``caps(robot_id) -> TripCaps | None`` (sync or async), app.py's capability closure.
TripCapsPort = Callable[[str], "Optional[TripCaps] | Awaitable[Optional[TripCaps]]"]


class MapPosePort(Protocol):
    """D-494 3: ``MapPoseService`` (``arbitrated_pose`` + ``refresh(force_rest=True)``)."""

    def arbitrated_pose(self, robot_id: str) -> "Optional[MapPose] | Awaitable[Optional[MapPose]]": ...

    async def refresh(self, robot_id: str, *, force_rest: bool = False) -> None:
        """Optional: read the robot's state/odom (D-760 8: the shared read). Once per tick (2 Hz)."""


class LaneJunctionPort(Protocol):
    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float, turn_deg: Optional[float] = None,
                            advance_m: Optional[float] = None, expect: Optional[dict] = None) -> dict: ...

    async def junction_state(self, robot_id: str, after: int = 0) -> Optional[dict]:
        """``after`` only on a port with ``read_number`` (D-760 8 review). The snapshot's ``line_follow.junction`` ({pending_action, place_id, state, seq}) or None."""

    async def hold(self, robot_id: str) -> dict:
        """Stop line following now (not at the next junction)."""

    async def line_follow_mode(self, robot_id: str) -> Optional[str]:
        """The robot's selected line-follow mode (``GET /api/v1/line-follow`` ``mode``)."""

    async def start_camera_line(self, robot_id: str) -> dict:
        """D-601 A: ``PUT /api/v1/line-follow/mode {mode: CAMERA_LINE}`` from the trip lease owner."""

    async def front_camera(self, robot_id: str) -> dict:
        """D-601 B: ``GET /api/v1/vision/front/status``."""

    async def rotate_to(self, robot_id: str, delta_deg: float, operator_name: str) -> dict:
        """D-603: ``POST /api/v1/motion/rotate_to`` (the trip start's alignment turn)."""

    async def rotate_status(self, robot_id: str) -> dict:
        """D-603: ``GET /api/v1/motion/rotate_to``."""

    async def rotate_stop(self, robot_id: str) -> dict:
        """D-603: ``DELETE /api/v1/motion/rotate_to``."""


class HttpLaneJunction:
    """D-494 4 through the console's robot clients (``HttpRobotClient.line_follow_junction``)."""

    def __init__(self, clients: Callable[[], Mapping[str, Any]], read=None, read_number=None) -> None:
        self._clients, self.read_number = clients, read_number  # D-760 8: map_pose's shared read and its numbers
        self._read = read or (lambda robot_id, after=0: self._client(robot_id).state())  # alone: a direct read

    def _client(self, robot_id: str):
        if (client := self._clients().get(robot_id)) is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return client

    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float, turn_deg: Optional[float] = None,
                            advance_m: Optional[float] = None, expect: Optional[dict] = None) -> dict:
        return await self._client(robot_id).line_follow_junction(
            action, place_id, stop_after_m=stop_after_m, expires_s=expires_s, turn_deg=turn_deg,
            advance_m=advance_m, expect=expect)

    async def junction_state(self, robot_id: str, after: int = 0) -> Optional[dict]:
        line = (await self._read(robot_id, after=after)).get("line_follow") or {}  # D-760 8 review: read > after
        junction = line.get("junction")
        # D-507 3: the line-follow reason beside it, shown when the trip stops at an unexpected junction.
        # D-517 M3: a D-407 stuck or a RECOVERING state may reverse; no follower follows it then.
        # D-520 2: ``arc`` is CORE's ``line_follow.arc`` record (arc_seq, from_place_id, state, ...)
        recovering = line.get("state") == "RECOVERING" or line.get("stuck") is not None
        return ({**junction, "line_reason": line.get("reason"), "line_recovering": recovering,
                 "arc": line.get("arc"), "regulation_wait": line.get("regulation_wait")}  # D-763 8 (API v1.227)
                if isinstance(junction, dict) else None)

    async def hold(self, robot_id: str) -> dict:
        # ponytail: CORE POST /line-follow/hold extends a hold-to-run session (D-344 8, it keeps the
        # robot going), so the immediate stop is mode OFF, the existing Fleet-allowed selection.
        return await self._client(robot_id).line_follow_mode("OFF")

    async def send_authority(self, robot_id: str, body: dict) -> dict:
        """D-517 4: ``POST /api/v1/line-follow/authority`` (``trip_authority``)."""
        return await self._client(robot_id).line_follow_authority(body)

    async def send_advice(self, robot_id: str, body: dict) -> dict:
        """D-551: ``POST /api/v1/line-follow/advice`` (``trip_advice``)."""
        return await self._client(robot_id).line_follow_advice(body)

    async def trip_lease(self, robot_id: str, body: dict) -> dict:
        """D-541 7: ``PUT /api/v1/trip-lease`` with Fleet's own robot token (``fleet.traffic.trip_lease``)."""
        return await self._client(robot_id).trip_lease(body)

    async def trip_lease_release(self, robot_id: str, lease_id: str) -> dict:
        return await self._client(robot_id).trip_lease_release(lease_id)

    async def line_follow_mode(self, robot_id: str) -> Optional[str]:
        mode = (await self._client(robot_id).line_follow()).get("mode")
        return mode if isinstance(mode, str) else None

    async def start_camera_line(self, robot_id: str) -> dict:
        return await self._client(robot_id).line_follow_trip_start()

    async def front_camera(self, robot_id: str) -> dict:
        return await self._client(robot_id).front_status()

    async def rotate_to(self, robot_id: str, delta_deg: float, operator_name: str) -> dict:
        return await self._client(robot_id).rotate_to(delta_deg, operator_name)

    async def rotate_status(self, robot_id: str) -> dict:
        return await self._client(robot_id).rotate_to_status()

    async def rotate_stop(self, robot_id: str) -> dict:
        return await self._client(robot_id).rotate_to_stop()


@dataclass(frozen=True)
class TripConfig:
    period_s: float = 0.5
    #: D-494 5: the next place's action goes to CORE this far before the place.
    arm_distance_m: float = 0.6
    #: CORE keeps one junction instruction at most 30 s (D-494 4); refreshed at half this.
    junction_expires_s: float = 15.0
    #: A lane robot this close to its last place (after the stop went out) has arrived.
    arrive_lane_m: float = 0.15
    #: The D-463 ``DONE_M``: a free robot this close to the end has arrived.
    arrive_free_m: float = 0.05
    #: A free robot this close to a segment's end is on the next segment.
    advance_free_m: float = 0.05
    #: CORE idle (or a newer seq) this close to the place means the instruction was carried out.
    pass_window_m: float = 0.3
    #: The pose is on the next lane once it is this far along it (and closer to it).
    advance_eps_m: float = 0.02
    #: A free goal is sent again only when its point moved this much.
    goal_resend_m: float = 0.05
    #: D-495 1: CORE turns at most this much at a junction.
    max_turn_deg: float = 150.0
    #: CORE ``waiting`` (at a junction without an instruction) this long stops the trip.
    junction_wait_s: float = 10.0
    #: A trip starts only within this long after the pose's sighting anchor.
    start_anchor_age_s: float = 2.0
    #: D-593 7 (user, 2026-10-10): an operator-pin anchor up to the map pose's anchor age limit
    #: (10 s) also starts a trip, but only while odom has moved at most this much since the pin.
    pin_start_still_m: float = 0.02
    pin_start_still_deg: float = 2.0
    #: D-601 D (user, 2026-10-10): a lane trip starts only with the robot within this of its first
    #: lane's direction (and on that lane); the planner's own snap allows ``fleet.routing.heading_tol_deg``.
    start_heading_tol_deg: float = 20.0
    #: D-601 B: a lane plan needs the robot's front preview live; false only where none exists (SIM).
    lane_camera_check: bool = True
    #: D-603: a start refused TRIP_START_HEADING_MISMATCH on its lane asks CORE ``rotate_to`` first
    #: (off until field-accepted).
    auto_align: bool = False
    #: No ``stall_m`` of progress along the plan for this long (outside a junction manoeuvre or a
    #: replan hold) stops the trip (site config ``fleet.trip.stall_s``).
    stall_s: float = 20.0
    stall_m: float = 0.05
    #: Every robot call of the loop gives up after this long (a stuck robot is an error).
    port_timeout_s: float = 1.5
    expect_tol_min_m: float = 0.12  #: D-507 2: the narrowest ``expect_tol_m`` sent (site calibration knob, at most 0.30)
    bend_send_s: float = 0.01  #: D-507 bend lead: the instruction's HTTP send + CORE take time (site knob; local ~0.01)
    #: D-520 1: a lane within this of one circle is an ``exit_segment`` (260919 ring: 0.00007 m).
    arc_fit_tol_m: float = 0.005
    #: D-520 1: lane centre to the outer painted line's centre on a curve (260919 ring: line
    #: radii 0.155/0.345 m, half of 0.19); the site map has no paint, so it is site config.
    arc_outer_line_offset_m: float = 0.095
    #: Robots of trips open before a restart are stopped every this long, this many times at most.
    restart_retry_s: float = 10.0
    restart_attempts: int = 30

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in ("lane_camera_check", "auto_align"):
                if not isinstance(value, bool):
                    raise ValueError(f"fleet.trip.{item.name} must be true or false")
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not (
                    math.isfinite(value) and value > 0):
                raise ValueError(f"fleet.trip.{item.name} must be a positive finite number")
        if not 0.05 <= self.arc_outer_line_offset_m <= 0.20:  # D-520 1: CORE's range
            raise ValueError("fleet.trip.arc_outer_line_offset_m must be in [0.05, 0.20]")
        if self.start_heading_tol_deg > 90.0:
            raise ValueError("fleet.trip.start_heading_tol_deg must be at most 90")
        if self.pin_start_still_m > 0.10 or self.pin_start_still_deg > 10.0:  # D-593 7: "not moved"
            raise ValueError("fleet.trip.pin_start_still_m/deg must be at most 0.10 m / 10 deg")
        if self.expect_tol_min_m > MAX_EXPECT_TOL_M:
            raise ValueError(f"fleet.trip.expect_tol_min_m must be at most {MAX_EXPECT_TOL_M}")

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping]) -> "TripConfig":
        raw = dict(raw or {})
        unknown = set(raw) - {item.name for item in fields(cls)}
        if unknown:
            raise ValueError(f"fleet.trip has unknown keys: {sorted(unknown)}")
        return cls(**raw)


class TripError(Exception):
    def __init__(self, status: int, code: str, detail: Optional[dict] = None) -> None:
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail or {}


def pose_diagnostics(pose) -> dict:
    # the provider's types are its own; the trip row stores JSON (a dataclass becomes its str)
    keys = ("sightings_filtered_map_id", "odom_refused", "odom_refused_reason")
    return json.loads(json.dumps({key: getattr(pose, key, None) for key in keys}, default=str))


#: D-507 2: CORE takes ``expect_in_m`` in (0, 2], ``expect_tol_m`` in (0, 0.30] and
#: ``pivot_past_line_m`` in [-0.30, 0.30] (the D-495 ``MAX_ADVANCE_M``, signed since 2026-10-08).
MAX_EXPECT_IN_M = 2.0
MAX_EXPECT_TOL_M = 0.30
MAX_PIVOT_PAST_LINE_M = 0.30
_monotonic = time.monotonic  # the read-to-send clock (a test replaces it)
