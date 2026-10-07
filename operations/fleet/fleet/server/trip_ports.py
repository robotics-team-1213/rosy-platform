"""D-491 1/3/4 ports of the trip loop (``trip_runner``), its site config and their default wiring.

``TripCaps`` (robot capability fields), ``MapPose`` (the Fleet trip map pose) and the lane
junction / line-follow calls are injected so their providers plug in when they land. The
defaults answer "nothing known" (the trip start refuses) and the HTTP junction port goes through
the console's robot clients.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from fleet.hub.hub import HubError


@dataclass(frozen=True)
class TripCaps:
    """D-491 1 capability fields as Fleet reads them from the robot's capabilities."""

    kind: Optional[str]
    modes: frozenset
    max_speed: Optional[float]
    #: D-492 3: CORE runs the bounded junction turn (``turn_deg``); without it no lane left/right.
    junction_turn: bool = False


@dataclass(frozen=True)
class MapPose:
    """D-491 3 ``map_pose`` output."""

    x: float
    y: float
    yaw: float
    state: str
    source: str
    dead_reckon_m: float
    age_s: float
    #: Seconds since the sighting anchor; a trip starts only on a fresh one (``start_anchor_age_s``).
    anchor_age_s: Optional[float] = None
    #: Provider diagnostics, shown when a trip stops for its pose.
    sightings_filtered_map_id: Optional[object] = None
    odom_refused: Optional[object] = None


class TripCapsPort(Protocol):
    def caps_for(self, robot_id: str) -> "Optional[TripCaps] | Awaitable[Optional[TripCaps]]": ...


class MapPosePort(Protocol):
    def arbitrated_pose(self, robot_id: str) -> "Optional[MapPose] | Awaitable[Optional[MapPose]]": ...

    async def refresh(self, robot_id: str, force_rest: bool = True) -> None:
        """Optional: read the robot's state/odom now. The loop calls it once per tick (2 Hz)."""


class LaneJunctionPort(Protocol):
    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float, turn_deg: Optional[float] = None,
                            advance_m: Optional[float] = None) -> dict: ...

    async def junction_state(self, robot_id: str) -> Optional[dict]:
        """The snapshot's ``line_follow.junction`` ({pending_action, place_id, state, seq}) or None."""

    async def hold(self, robot_id: str) -> dict:
        """Stop line following now (not at the next junction)."""

    async def line_follow_mode(self, robot_id: str) -> Optional[str]:
        """The robot's selected line-follow mode (``GET /api/v1/line-follow`` ``mode``)."""


class NoTripCaps:
    """Default until the D-491 1 provider lands: no robot has trip capabilities."""

    def caps_for(self, robot_id: str) -> None:
        return None


class NoMapPose:
    """Default until the D-491 3 provider lands: no robot has a trip pose."""

    def arbitrated_pose(self, robot_id: str) -> None:
        return None


class HttpLaneJunction:
    """D-491 4 through the console's robot clients (``HttpRobotClient.line_follow_junction``)."""

    def __init__(self, clients: Callable[[], Mapping[str, Any]]) -> None:
        self._clients = clients

    def _client(self, robot_id: str):
        client = self._clients().get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return client

    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float, turn_deg: Optional[float] = None,
                            advance_m: Optional[float] = None) -> dict:
        return await self._client(robot_id).line_follow_junction(
            action, place_id, stop_after_m=stop_after_m, expires_s=expires_s, turn_deg=turn_deg,
            advance_m=advance_m)

    async def junction_state(self, robot_id: str) -> Optional[dict]:
        junction = ((await self._client(robot_id).state()).get("line_follow") or {}).get("junction")
        return junction if isinstance(junction, dict) else None

    async def hold(self, robot_id: str) -> dict:
        # ponytail: CORE POST /line-follow/hold extends a hold-to-run session (D-344 8, it keeps the
        # robot going), so the immediate stop is mode OFF, the existing Fleet-allowed selection.
        return await self._client(robot_id).line_follow_mode("OFF")

    async def line_follow_mode(self, robot_id: str) -> Optional[str]:
        mode = (await self._client(robot_id).line_follow()).get("mode")
        return mode if isinstance(mode, str) else None


@dataclass(frozen=True)
class TripConfig:
    period_s: float = 0.5
    #: D-491 5: the next place's action goes to CORE this far before the place.
    arm_distance_m: float = 0.6
    #: CORE keeps one junction instruction at most 30 s (D-491 4); refreshed at half this.
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
    #: D-492 1: CORE turns at most this much at a junction.
    max_turn_deg: float = 150.0
    #: CORE ``waiting`` (at a junction without an instruction) this long stops the trip.
    junction_wait_s: float = 10.0
    #: A trip starts only within this long after the pose's sighting anchor.
    start_anchor_age_s: float = 2.0
    #: No ``stall_m`` of progress along the plan for this long (outside a junction manoeuvre or a
    #: replan hold) stops the trip (site config ``fleet.trip.stall_s``).
    stall_s: float = 20.0
    stall_m: float = 0.05
    #: Every robot call of the loop gives up after this long (a stuck robot is an error).
    port_timeout_s: float = 1.5

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not (
                    math.isfinite(value) and value > 0):
                raise ValueError(f"fleet.trip.{item.name} must be a positive finite number")

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
