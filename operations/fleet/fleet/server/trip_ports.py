"""D-494 1/3/4 ports of the trip loop (``trip_runner``), its site config and runtime state.

``TripCaps`` (``console_view``, from the robot's capabilities) and ``MapPose``
(``fleet.localization.map_pose``) are the providers' own types; app.py injects the capability
closure, the ``MapPoseService`` and ``HttpLaneJunction`` (through the console's robot clients).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from fleet.hub.hub import HubError
from fleet.localization.map_pose import MapPose
from fleet.server.console_view import TripCaps
from fleet.routing.cost import LEFT, RIGHT
from fleet.routing.execute import arc_id, ends_at_place
from fleet.site_map import ENDPOINT_TOL_M

#: Trip states that are still going.
OPEN = ("started", "running")


#: D-494 1: ``caps(robot_id) -> TripCaps | None`` (sync or async), app.py's capability closure.
TripCapsPort = Callable[[str], "Optional[TripCaps] | Awaitable[Optional[TripCaps]]"]


class MapPosePort(Protocol):
    """D-494 3: ``MapPoseService`` (``arbitrated_pose`` + ``refresh(force_rest=True)``)."""

    def arbitrated_pose(self, robot_id: str) -> "Optional[MapPose] | Awaitable[Optional[MapPose]]": ...

    async def refresh(self, robot_id: str, *, force_rest: bool = False) -> None:
        """Optional: read the robot's state/odom now. The loop calls it once per tick (2 Hz)."""


class LaneJunctionPort(Protocol):
    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float, turn_deg: Optional[float] = None,
                            advance_m: Optional[float] = None, expect: Optional[dict] = None) -> dict: ...

    async def junction_state(self, robot_id: str) -> Optional[dict]:
        """The snapshot's ``line_follow.junction`` ({pending_action, place_id, state, seq}) or None."""

    async def hold(self, robot_id: str) -> dict:
        """Stop line following now (not at the next junction)."""

    async def line_follow_mode(self, robot_id: str) -> Optional[str]:
        """The robot's selected line-follow mode (``GET /api/v1/line-follow`` ``mode``)."""


class HttpLaneJunction:
    """D-494 4 through the console's robot clients (``HttpRobotClient.line_follow_junction``)."""

    def __init__(self, clients: Callable[[], Mapping[str, Any]]) -> None:
        self._clients = clients

    def _client(self, robot_id: str):
        client = self._clients().get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return client

    async def send_junction(self, robot_id: str, action: str, place_id: str, stop_after_m: Optional[float],
                            expires_s: float, turn_deg: Optional[float] = None,
                            advance_m: Optional[float] = None, expect: Optional[dict] = None) -> dict:
        return await self._client(robot_id).line_follow_junction(
            action, place_id, stop_after_m=stop_after_m, expires_s=expires_s, turn_deg=turn_deg,
            advance_m=advance_m, expect=expect)

    async def junction_state(self, robot_id: str) -> Optional[dict]:
        line = (await self._client(robot_id).state()).get("line_follow") or {}
        junction = line.get("junction")
        # D-507 3: the line-follow reason beside it, shown when the trip stops at an unexpected junction
        return {**junction, "line_reason": line.get("reason")} if isinstance(junction, dict) else None

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
    #: No ``stall_m`` of progress along the plan for this long (outside a junction manoeuvre or a
    #: replan hold) stops the trip (site config ``fleet.trip.stall_s``).
    stall_s: float = 20.0
    stall_m: float = 0.05
    #: Every robot call of the loop gives up after this long (a stuck robot is an error).
    port_timeout_s: float = 1.5
    #: Robots of trips open before a restart are stopped every this long, this many times at most.
    restart_retry_s: float = 10.0
    restart_attempts: int = 30

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


def pose_diagnostics(pose) -> dict:
    # the provider's types are its own; the trip row stores JSON (a dataclass becomes its str)
    keys = ("sightings_filtered_map_id", "odom_refused", "odom_refused_reason")
    return json.loads(json.dumps({key: getattr(pose, key, None) for key in keys}, default=str))


#: D-507 2: CORE takes ``expect_in_m`` in (0, 2], ``expect_tol_m`` in (0, 0.30] and
#: ``pivot_past_line_m`` in [0, 0.30] (the D-495 ``MAX_ADVANCE_M``).
MAX_EXPECT_IN_M = 2.0
MAX_EXPECT_TOL_M = 0.30
MAX_PIVOT_PAST_LINE_M = 0.30
#: Along-track odom drift per metre dead-reckoned since the last sighting (wheel slip on carpet).
ODOM_DRIFT_PER_M = 0.05


def junction_fields(graph, segments: list, index: int, action: str, remaining: float, view: dict,
                    active) -> Optional[dict]:
    """D-507 2: the optional junction fields, only for a robot whose caps report ``junction_pivot``.

    ``map_id`` (the active map the plan runs on) always; the expectation (``expect_in_m``,
    ``expect_tol_m``, ``pivot_past_line_m``) only while the place is (0, 2] m along the lane,
    otherwise CORE keeps today's behaviour for it.
    """
    caps, pose = view.get("caps") or {}, view.get("pose") or {}
    if caps.get("junction_pivot") is not True or active is None or active[0] != view["map_version"]:
        return None
    fields = {"map_id": active[1].map_id}
    expect_in = round(remaining, 3)
    if not 0.0 < expect_in <= MAX_EXPECT_IN_M:
        return fields
    # ponytail: the map pose has no heading-direction error estimate, so it is odom drift over the
    # distance dead-reckoned since the last sighting plus how far the robot drives at its trip speed
    # while the pose ages; replace with the provider's own covariance once MapPose reports one.
    error = (ODOM_DRIFT_PER_M * (pose.get("dead_reckon_m") or 0.0)
             + (caps.get("max_speed") or 0.0) * (pose.get("age_s") or 0.0))
    fields.update(expect_in_m=expect_in, expect_tol_m=round(min(error + ENDPOINT_TOL_M, MAX_EXPECT_TOL_M), 3))
    if action in (LEFT, RIGHT):  # the place is on the outgoing lane's centre line (D-490)
        width = graph.arcs[arc_id(segments[index + 1])].width_m
        fields["pivot_past_line_m"] = round(min(width / 2, MAX_PIVOT_PAST_LINE_M), 3)
    return fields


def pose_view(pose: Optional[MapPose]) -> Optional[dict]:
    if pose is None:
        return None

    def rounded(value, digits):
        return None if value is None else round(value, digits)

    return {"x": rounded(pose.x, 3), "y": rounded(pose.y, 3), "yaw": rounded(pose.yaw, 3), "state": pose.state,
            "source": pose.source, "dead_reckon_m": rounded(pose.dead_reckon_m, 3),
            "age_s": rounded(pose.age_s, 2), "anchor_age_s": getattr(pose, "anchor_age_s", None)}


class LiveTrip:
    """Runtime state of the one open trip (``trip_runner``); ``view`` is what is stored and returned."""

    def __init__(self, view: dict, graph, request: dict) -> None:
        self.view = view
        self.graph = graph
        self.request = request
        #: The last instruction CORE accepted: index, action, place, seq, at.
        self.sent: Optional[dict] = None
        self.first_seq: Optional[int] = None
        #: Our held replan stop (seq) that the confirmed plan's action may replace while executing.
        self.replaceable: Optional[int] = None
        self.last_goal: Optional[tuple[float, float]] = None
        self.replan_pending = False
        self.waiting_since: Optional[float] = None
        self.junction: dict = {}
        self.best_progress = -math.inf
        self.progress_at: Optional[float] = None

    def junction_end(self, now: float, remaining: Optional[float], config: TripConfig) -> Optional[tuple]:
        """``(reason, detail)`` when CORE's junction state ends the trip, else None.

        D-495 ``junction``: ``aborted``/``unresolved`` after our first instruction, or ``waiting``
        for ``junction_wait_s``. D-507 3 ``junction_unexpected``, at once: on a lane segment
        (``remaining`` m to its place) CORE is ``unexpected``, or ``waiting`` with the place
        beyond ``arm_distance_m`` (no instruction of ours is due there). The trip view keeps the
        map pose; ``line_reason`` is CORE's line-follow reason beside the junction state.
        """
        junction = self.junction
        state = junction.get("state")
        self.waiting_since = (self.waiting_since or now) if state == "waiting" else None
        detail = {"junction_state": state, "junction_place": junction.get("place_id"),
                  "junction_reason": junction.get("reason")}
        if remaining is not None and (state == "unexpected" or (
                state == "waiting" and remaining > config.arm_distance_m)):
            return "junction_unexpected", {**detail, "line_reason": junction.get("line_reason")}
        ours = self.first_seq is not None and (junction.get("seq") or 0) >= self.first_seq
        if (state in ("aborted", "unresolved") and ours) or (
                state == "waiting" and now - self.waiting_since >= config.junction_wait_s):
            return "junction", detail
        return None

    @property
    def segments(self) -> list:
        return self.view["plan"]["segments"]

    @property
    def open(self) -> bool:
        return self.view["state"] in OPEN

    def arc(self, index: int):
        return self.graph.arcs[arc_id(self.segments[index])]

    def place(self, index: int) -> Optional[str]:
        return ends_at_place(self.graph, self.segments[index])

    def progress(self, index: int, s: float) -> float:
        """Metres along the whole plan."""
        done = sum(seg["s_to"] - seg["s_from"] for seg in self.segments[:index])
        return done + s - self.segments[index]["s_from"]
