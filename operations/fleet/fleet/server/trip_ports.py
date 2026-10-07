"""D-491 1/3/4 ports of the trip loop (``trip_runner``) and their default wiring.

``TripCaps`` (robot capability fields), ``MapPose`` (the Fleet trip map pose) and the lane
junction / line-follow calls are injected so their providers plug in when they land. The
defaults answer "nothing known" (the trip start refuses) and the HTTP junction port goes through
the console's robot clients.
"""

from __future__ import annotations

from dataclasses import dataclass
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
