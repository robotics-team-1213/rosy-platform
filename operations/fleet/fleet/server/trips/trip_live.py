"""D-494 runtime state of one robot's trip (``LiveTrip``), moved out of ``trip_ports`` unchanged (D-798)."""

from __future__ import annotations

import math
from typing import Optional

from fleet.routing.execute import arc_id, ends_at_place
from fleet.server import trip_ports as _ports
from fleet.server.trip_geometry import pose_view
from fleet.server.trip_ports import OPEN, TripConfig


class LiveTrip:
    """Runtime state of one robot's trip (``trip_runner``); ``view`` is what is stored and returned."""

    def __init__(self, view: dict, graph, request: dict) -> None:
        self.view = view
        self.graph = graph
        self.request = request
        #: The last instruction CORE accepted: index, action, place, seq, at.
        self.sent: Optional[dict] = None
        self.first_seq: Optional[int] = None
        #: D-520 2: CORE's last ``arc_seq`` at our first send; a newer arc is one of this trip's.
        self.arc_base: Optional[int] = None
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
        #: D-517 9 M3: the leader this trip follows in a lane convoy (None: not a follower).
        self.convoy: Optional[str] = (request.get("convoy") or {}).get("leader")
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
        self.bends_done: set[tuple[int, str]] = set()  # (segment index, place id): a lap may pass one bend on two segments
        self.dismissed = 0  # keeper sightings without a map place, answered ``straight``

    def junction_end(self, now: float, remaining: Optional[float], config: TripConfig) -> Optional[tuple]:
        """``(reason, detail)`` when CORE's junction state ends the trip, else None.

        D-495 ``junction``: ``aborted``/``unresolved`` after our first instruction, or ``waiting``
        for ``junction_wait_s``. D-507 3 ``junction_unexpected``, at once: on a lane segment
        (``remaining`` m to its place) CORE is ``unexpected``, or ``waiting`` with the place
        beyond ``arm_distance_m`` (no instruction of ours is due there). The trip view keeps the
        map pose; ``line_reason`` is CORE's line-follow reason beside the junction state.
        Lap SIM A ``junction_corner_hold``, at once: CORE holds our instruction short of the
        keeper's corner and keeps holding it, so the trip ends now, not at the stall check.
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
        if ours and junction.get("line_reason") == "junction_corner_hold":
            return "junction_corner_hold", {**detail, "line_reason": "junction_corner_hold"}
        if (state in ("aborted", "unresolved") and ours) or (
                state == "waiting" and now - self.waiting_since >= config.junction_wait_s):
            return "junction", detail
        return None

    def see(self, pose) -> None:
        """Keep the map pose just read and when it was read."""
        self.view["pose"], self.pose_read_at = pose_view(pose), _ports._monotonic()

    @property
    def segments(self) -> list:
        return self.view["plan"]["segments"]

    @property
    def open(self) -> bool:
        return self.view["state"] in OPEN

    def arc(self, index: int):
        return self.graph.arcs[arc_id(self.segments[index])]

    def place(self, index: int) -> Optional[str]:
        place = ends_at_place(self.graph, self.segments[index])
        return (place if place is not None or self.view["repeat"] or index != len(self.segments) - 1
                else self.view["plan"]["actions"][-1]["place_id"])

    def progress(self, index: int, s: float) -> float:
        """Metres along the whole plan."""
        done = sum(seg["s_to"] - seg["s_from"] for seg in self.segments[:index])
        return done + s - self.segments[index]["s_from"]
