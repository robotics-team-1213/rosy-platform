"""D-494 1/3/4 ports of the trip loop (``trip_runner``), its site config and runtime state.

``TripCaps`` (``console_view``, from the robot's capabilities) and ``MapPose``
(``fleet.localization.map_pose``) are the providers' own types; app.py injects the capability
closure, the ``MapPoseService`` and ``HttpLaneJunction`` (through the console's robot clients).
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, fields
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from fleet.hub.hub import HubError
from fleet.localization.map_pose import MapPose
from fleet.server.console_view import TripCaps
from fleet.routing.cost import LEFT, RIGHT, STRAIGHT, wrap
from fleet.routing.execute import arc_id, ends_at_place
from fleet.site_map import ENDPOINT_TOL_M

_LOG = logging.getLogger(__name__)

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

    async def send_authority(self, robot_id: str, body: dict) -> dict:
        """D-517 4: ``POST /api/v1/line-follow/authority`` (``trip_authority``)."""
        return await self._client(robot_id).line_follow_authority(body)

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
    #: D-507 2: the narrowest ``expect_tol_m`` sent (site calibration knob, at most 0.30).
    expect_tol_min_m: float = 0.12
    #: Robots of trips open before a restart are stopped every this long, this many times at most.
    restart_retry_s: float = 10.0
    restart_attempts: int = 30

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not (
                    math.isfinite(value) and value > 0):
                raise ValueError(f"fleet.trip.{item.name} must be a positive finite number")
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
#: Along-track odom drift per metre of odom travel (wheel slip on carpet): the map pose's
#: dead-reckoned distance and, since CORE measures the window in odom path length (2026-10-08),
#: the distance driven from the send to the place.
ODOM_DRIFT_PER_M = 0.05
#: ponytail: a fixed allowance for the send's HTTP time and CORE taking the instruction after the
#: send starts; measure it on the site network and make it site config if it is off.
SEND_ALLOWANCE_S = 0.2
_monotonic = time.monotonic  # the read-to-send clock (a test replaces it)
#: D-507 B9 diagnostic: a lane heading change this large is a bend (``bend_candidate`` only).
MAX_WINDOW_BEND_DEG = 15.0
#: The lane heading is checked this often ahead of the robot.
WINDOW_BEND_STEP_M = 0.02
# D-507 B9 diagnostic only: inspect the current edge, never authorize motion from this.
BEND_PREVIEW_M = 0.40
BEND_MAX_ANGLE_DEG = 80.0  # keeper's non-square bend limit
#: The cross line search steps this far, then halves the last step to 1 mm.
LINE_STEP_M = 0.01


def bend_candidate(arc, s: float, pose: dict, *, end_s: float | None = None) -> Optional[dict]:
    """A nearby turn in this lane edge, using only a fresh, aligned map pose. No motion grant."""
    if arc.drive_mode != "lane" or not isinstance(pose, dict):
        return None
    keys = ("x", "y", "yaw", "age_s", "dead_reckon_m")
    if any(isinstance(pose.get(key), bool) or not isinstance(pose.get(key), (int, float))
           or not math.isfinite(pose[key]) for key in keys):
        return None
    if not 0 <= pose["age_s"] <= 0.30 or not 0 <= pose["dead_reckon_m"] <= ENDPOINT_TOL_M:
        return None
    offset, projected_s, heading = arc.project(pose["x"], pose["y"])
    if (offset > 0.04 or abs(projected_s - s) > ENDPOINT_TOL_M
            or abs(math.degrees(wrap(pose["yaw"] - heading))) > MAX_WINDOW_BEND_DEG):
        return None
    limit = min(arc.length_m if end_s is None else end_s, s + BEND_PREVIEW_M)
    if not math.isfinite(limit) or limit <= s:
        return None
    first, change = None, 0.0
    steps = math.ceil((limit - s) / WINDOW_BEND_STEP_M)
    for index in range(1, steps + 1):
        ahead = (limit - s) * index / steps
        _, _, future = arc.point_at(s + ahead)
        change = math.degrees(wrap(future - heading))
        if abs(change) > BEND_MAX_ANGLE_DEG:
            return None
        if first is None and abs(change) >= MAX_WINDOW_BEND_DEG:
            first = ahead
    if first is None:
        return None
    return {"arc_id": arc.id, "bend_in_m": round(first, 3),
            "heading_change_deg": round(change, 1), "map_offset_m": round(offset, 3)}


def record_bend_candidate(live: "LiveTrip", pose: MapPose, active, index: int, s: float) -> None:
    """Put a map-bound, read-only bend hint in the current trip view when its evidence holds."""
    if (live.view["hold"] is not None or active is None or active[0] != live.view["map_version"]
            or pose.map_id not in (None, active[1].map_id)):
        return
    cue = bend_candidate(live.arc(index), s, vars(pose), end_s=live.segments[index]["s_to"])
    if cue is not None:
        live.view["detail"]["bend_candidate"] = {
            **cue, "map_id": active[1].map_id, "map_version": active[0]}


def junction_fields(live: "LiveTrip", index: int, action: str, remaining: float, active,
                    config: TripConfig) -> Optional[dict]:
    """D-507 2 fields for a ``junction_pivot`` robot: ``map_id``, ``pivot_past_line_m`` (not for
    ``stop``; the place minus the first painted line ``line_past`` finds along the lane heading at
    the place, or the outgoing half-width and no window when it finds none) and the window pair:
    ``expect_in_m`` = ``remaining``, the distance along the lane from the robot's snapped position
    to the place, which CORE compares with its odom path length (2026-10-08 user decision, curves
    included), when it is in (0, 2]; none on another map version
    (logged, ``detail.junction_fields_dropped``). ``arm_distance_m`` should be at least the
    keeper's 0.45 m + pivot + tol so the instruction comes first; SIM checks the default 0.6.
    The trip loop never sends a ``left``/``right`` without the window (``junction_no_window``).
    """
    view = live.view
    caps, pose = view.get("caps") or {}, view.get("pose") or {}
    if caps.get("junction_pivot") is not True:
        return None
    if active is None or active[0] != view["map_version"]:
        if view["detail"].get("junction_fields_dropped") != "map_version":
            _LOG.warning("trip %s: active map is not the plan's version %s; junction fields not sent",
                         view.get("trip_id"), view["map_version"])
        view["detail"]["junction_fields_dropped"] = "map_version"
        return None
    fields = {"map_id": active[1].map_id}
    expect_in = round(remaining, 3)
    window = 0.0 < expect_in <= MAX_EXPECT_IN_M
    if action in (STRAIGHT, LEFT, RIGHT):
        # 2026-10-08: the first painted line past the place along the lane's heading there (on a
        # curved approach the robot's heading is not the line's).
        x, y, heading = live.arc(index).point_at(live.segments[index]["s_to"])
        past = line_past(live.graph, x, y, heading)
        if past is None:  # no line near the place: the old near-edge half-width, and no window
            width = live.arc(index + 1).width_m
            fields["pivot_past_line_m"] = round(min(width / 2, MAX_PIVOT_PAST_LINE_M), 3)
            return fields
        if window:
            fields["pivot_past_line_m"] = -past
        # No negative pivot without a window: map-backed CORE holds any unplaced sighting.
    if not window:
        return fields  # no window: map-backed CORE holds a junction sighting here
    tol = _pose_tol(live, config, expect_in,
                    _curve_offset_m(live.arc(index), live.segments[index]["s_to"], remaining, pose))
    fields.update(expect_in_m=expect_in, expect_tol_m=tol)
    return fields


def _pose_tol(live: "LiveTrip", config: TripConfig, travel: float = 0.0, extra: float = 0.0) -> float:
    """How well the map pose places the robot along its lane, at most ``MAX_EXPECT_TOL_M``:
    ``travel`` is the odom path CORE measures to the place, ``extra`` widens a known pose."""
    caps, pose = live.view.get("caps") or {}, live.view.get("pose") or {}
    speed, age, reckoned = caps.get("max_speed") or 0.0, pose.get("age_s"), pose.get("dead_reckon_m")
    if age is None or reckoned is None or live.pose_read_at is None:
        return MAX_EXPECT_TOL_M  # an unknown pose error is the widest window, never none
    # ponytail: the map pose has no along-path error estimate, so it is odom drift over the
    # distance dead-reckoned since the last sighting and over the path CORE measures to the
    # place, plus how far the robot drives at its trip speed over the pose age, the measured
    # read-to-send time and SEND_ALLOWANCE_S, floored by the site knob ``expect_tol_min_m``;
    # replace with the provider's own covariance once MapPose reports one.
    latency = age + (_monotonic() - live.pose_read_at) + SEND_ALLOWANCE_S
    tol = max(config.expect_tol_min_m,
              ODOM_DRIFT_PER_M * (reckoned + travel) + speed * latency + ENDPOINT_TOL_M)
    return round(min(tol + extra, MAX_EXPECT_TOL_M), 3)

def bend_geometry(place, arc) -> Optional[tuple[float, float, float, float]]:
    """``(s of the arc start, s of its end, signed turn deg, radius)`` of a ``bend`` place on this
    lane arc in its direction of travel, or None. Both tangent points must lie on the arc and the
    lane must run the bend's entering way at the start (either drawn direction of the place)."""
    if getattr(place, "kind", None) != "bend" or arc.drive_mode != "lane":
        return None
    turn = wrap(place.exit_yaw - place.yaw)
    for entry, delta in ((place.yaw, turn), (wrap(place.exit_yaw + math.pi), -turn)):
        t = place.radius_m * math.tan(abs(delta) / 2)
        off_a, s_a, heading = arc.project(place.x - t * math.cos(entry), place.y - t * math.sin(entry))
        off_e, s_e, _ = arc.project(place.x + t * math.cos(entry + delta), place.y + t * math.sin(entry + delta))
        if (max(off_a, off_e) <= ENDPOINT_TOL_M and s_e > s_a
                and abs(math.degrees(wrap(heading - entry))) <= MAX_WINDOW_BEND_DEG):
            return s_a, s_e, math.degrees(delta), place.radius_m
    return None


def next_bend(live: "LiveTrip", index: int, s: float) -> Optional[dict]:
    """The first bend on this segment the robot has not passed and Fleet has not finished."""
    found = []
    for place_id, place in live.graph.places.items():
        geometry = None if place_id in live.bends_done else bend_geometry(place, live.arc(index))
        if geometry is not None and s < geometry[1] and geometry[0] < live.segments[index]["s_to"]:
            found.append((geometry[0], place_id, geometry))
    if not found:
        return None
    s_start, place_id, (_, s_end, turn, radius) = min(found)
    return {"place_id": place_id, "s_start": s_start, "s_end": s_end, "turn_deg": turn, "radius_m": radius}


def straight_approach(arc, s: float, s_start: float) -> bool:
    """The lane runs within ``MAX_WINDOW_BEND_DEG`` of its heading at ``s_start`` from ``s`` on:
    CORE measures ``bend_in_m`` as odom travel, and through a corner the robot cuts the lane short
    (SIM 2026-10-08: sent inside the W->S corner, the arc started late, 5 cm outside)."""
    heading = arc.point_at(s_start)[2]
    steps = max(1, math.ceil((s_start - s) / WINDOW_BEND_STEP_M))
    return all(abs(math.degrees(wrap(arc.point_at(s + (s_start - s) * k / steps)[2] - heading)))
               <= MAX_WINDOW_BEND_DEG for k in range(steps + 1))


def bend_fields(live: "LiveTrip", bend: dict, s: float, active, config: TripConfig) -> Optional[dict]:
    """D-507 addendum: ``map_id``, ``bend_in_m`` (lane distance to the arc start), ``bend_tol_m``
    and ``bend_radius_m``; None on another map version, when the arc start is not 0-2 m ahead or
    while the lane before it still turns (``straight_approach``)."""
    bend_in = round(bend["s_start"] - s, 3)
    if (active is None or active[0] != live.view["map_version"] or not 0.0 < bend_in <= MAX_EXPECT_IN_M
            or not straight_approach(live.arc(live.view["segment_index"]), s, bend["s_start"])):
        return None
    return {"map_id": active[1].map_id, "bend_in_m": bend_in, "bend_tol_m": _pose_tol(live, config),
            "bend_radius_m": bend["radius_m"]}


def line_past(graph, x: float, y: float, heading: float) -> Optional[float]:
    """How far along ``heading`` from ``(x, y)`` the first painted cross line is, or None when
    ``(x, y)`` is off the lanes or the lanes run on past ``MAX_PIVOT_PAST_LINE_M``. Only
    ``lane`` arcs are painted (a ``free`` arc is no tape).

    D-507 2 (2026-10-08): the painted lines are the edge of the lanes' union, each lane a band of
    ``width_m`` around its centre line. A lane mouth breaks a line (the roundabout's outer line at
    a spoke); an island keeps one (its inner line, the far edge the keeper measures at the 260919
    SW spoke: 0.404 m here against 0.402 m in SIM).
    """
    cos, sin = math.cos(heading), math.sin(heading)
    near = [arc for arc in graph.arcs.values()
            if arc.drive_mode == "lane" and arc.project(x, y)[0] <= MAX_PIVOT_PAST_LINE_M + arc.width_m]

    def off(t: float) -> bool:
        return all(arc.project(x + t * cos, y + t * sin)[0] > arc.width_m / 2 for arc in near)

    if off(0.0):
        return None
    t, step = 0.0, LINE_STEP_M
    while t <= MAX_PIVOT_PAST_LINE_M and not off(t + step):
        t += step
    while step > 0.001:
        step /= 2
        if not off(t + step):
            t += step
    past = round(t + step, 3)
    return past if past <= MAX_PIVOT_PAST_LINE_M else None


def _curve_offset_m(arc, s_to: float, remaining: float, pose: dict) -> float:
    """A robot this far beside the lane drives a curve this much longer or shorter than its
    centre line: the offset times the heading change (rad) along the rest of the lane. Safety
    review 2026-10-08: the window compares travelled distance, so this widens it."""
    if pose.get("x") is None or pose.get("y") is None:
        return 0.0
    offset = arc.project(pose["x"], pose["y"])[0]
    steps = max(1, math.ceil(remaining / WINDOW_BEND_STEP_M))
    headings = [arc.point_at(s_to - remaining * (1 - k / steps))[2] for k in range(steps + 1)]
    return offset * sum(abs(wrap(b - a)) for a, b in zip(headings, headings[1:]))


def pose_view(pose: Optional[MapPose]) -> Optional[dict]:
    if pose is None:
        return None

    def rounded(value, digits):
        return None if value is None else round(value, digits)

    return {"x": rounded(pose.x, 3), "y": rounded(pose.y, 3), "yaw": rounded(pose.yaw, 3), "state": pose.state,
            "source": pose.source, "dead_reckon_m": rounded(pose.dead_reckon_m, 3),
            "age_s": rounded(pose.age_s, 2), "anchor_age_s": getattr(pose, "anchor_age_s", None)}


class LiveTrip:
    """Runtime state of one robot's trip (``trip_runner``); ``view`` is what is stored and returned."""

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
        #: ``time.monotonic()`` when the trip's map pose was last read (D-507 2 send latency).
        self.pose_read_at: Optional[float] = None
        self.best_progress = -math.inf
        self.progress_at: Optional[float] = None
        #: D-517 2: a repeat trip and the last lap's route (``route_key``) a new lap must match.
        self.repeat = bool(request.get("repeat"))
        self.lap_route: Optional[list] = None
        #: D-517 3: the arc ids of one lap of the cycle (via…, to); the loop it shares with others.
        self.lap_arcs: tuple[str, ...] = ()
        #: Failed lap checks in a row and when the last one ran (retried every ``LAP_RETRY_S``).
        self.lap_tries = 0
        self.lap_tried_at = -math.inf
        #: Index of the current lap's first segment; finished laps before it are dropped (bounded plan).
        self.lap_start = 0
        #: Route metres (whole arcs) dropped from the plan's front so far; the block table shifts by it.
        self.trim_m = 0.0
        #: Bumped when an operator confirms another plan (the block table's route id, D-517 3).
        self.route_rev = 0
        #: ``(segment index, s)`` where the last step located the robot.
        self.at: Optional[tuple[int, float]] = None
        #: The block table's answer for this robot (``TrafficService``): waiting_for, authority, refused_at_m.
        self.traffic: Optional[dict] = None
        #: D-517 4: the odom stamp of the pose ``at`` came from (set with it); CORE's last ``authority``.
        self.at_stamp: Optional[float] = None
        self.authority: Optional[dict] = None
        #: D-507 addendum: bend place ids CORE finished (or the robot passed without one).
        self.bends_done: set[str] = set()

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

    def see(self, pose) -> None:
        """Keep the map pose just read and when it was read."""
        self.view["pose"], self.pose_read_at = pose_view(pose), _monotonic()

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
