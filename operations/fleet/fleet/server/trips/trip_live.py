"""D-494 runtime state of one robot's trip (``LiveTrip``), moved out of ``trip_ports`` unchanged (D-798)."""

from __future__ import annotations

import math
from typing import Optional

from core_common.protocol.evidence import STALE_VELOCITY_S
from rosy.world.state.projections.map_pose_samples import parse_utc

from fleet.routing.execute import arc_id, ends_at_place
from fleet.server import trip_ports as _ports
from fleet.server.trip_geometry import pose_view
from fleet.server.trip_ports import OPEN, TripConfig


def trip_wait_reason(view):
    if view["state"] not in OPEN:
        return None
    hold, detail = view.get("hold") or {}, view.get("detail") or {}
    if hold.get("reason") == "fleet_hold":
        return "fleet_hold" if (hold.get("stop") or {}).get("confirmed") is True else "fleet_hold_unconfirmed"
    if view["state"] == "link_wait":
        return "link_wait"
    if peer := detail.get("peer_wait"):
        before_send = peer.get("stage") == "pre_dispatch_peer_check" and peer.get("dispatch_attempted") is False
        return "peer_pre_dispatch" if before_send else "peer_clearance"
    receipt = detail.get("wait_prefix") or {}
    if detail.get("traffic_hold") and not (receipt.get("kind") == "hold_point"
                                           and receipt.get("state") in ("dispatched", "waiting_stop_confirmation")):
        return "traffic_hold"  # standing under a table cut, not driving to its hold point
    parking = detail.get("parking_handoff") or {}
    if parking.get("phase") in ("waiting_for_commission", "waiting_for_clearance"):
        return parking.get("reason") or parking["phase"]
    return None


def _measured_motion(robot_id, sample):
    if sample is None:
        return "unknown", None, None
    state, read_start, now = sample
    if state.get("robot_id") != robot_id or state.get("online", True) is not True:
        return "unknown", None, None
    velocity = state.get("velocity") or {}
    evidence = (state.get("evidence") or {}).get("velocity") or {}
    stamp = evidence.get("sampled_at")
    sampled, captured = parse_utc(stamp), parse_utc(state.get("timestamp"))
    ttl = evidence.get("stale_after_s", STALE_VELOCITY_S)
    speeds = (velocity.get("linear"), velocity.get("angular"))
    if (evidence.get("evidence") != "fresh" or sampled is None or captured is None
            or type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0
            or not all(type(v) in (int, float) and math.isfinite(v) for v in speeds)
            or not 0 <= captured - sampled <= STALE_VELOCITY_S or not 0 <= now - read_start
            or captured - sampled + now - read_start > min(ttl, STALE_VELOCITY_S)):
        return "unknown", None, None
    motion = "moving" if abs(speeds[0]) > .01 or abs(speeds[1]) > .02 else "stationary"
    return motion, stamp, read_start - (captured - sampled)


def trip_execution(view, live=None, sample=None):
    """Read-only command phase and independently measured base motion, scoped to this trip."""
    detail = view.get("detail") or {}
    peer = detail.get("peer_wait") or {}
    parking = detail.get("parking_handoff") or {}
    reason = trip_wait_reason(view)
    waiting_on = peer.get("waiting_on") or (detail.get("traffic_hold") or {}).get("waiting_for") or ()
    motion, sampled_at, mono = _measured_motion(view["robot_id"], sample if view["state"] in OPEN else None)
    if view["state"] not in OPEN:
        phase, reason = "terminal", view.get("reason")
    elif reason in ("fleet_hold", "fleet_hold_unconfirmed"):
        phase = "paused"
    elif reason == "peer_pre_dispatch":
        phase = "pre_dispatch_wait"
    elif reason or detail.get("goal_wait") or (view.get("wait") or {}).get("waiting"):
        phase = "goal_wait"
        reason = reason or detail.get("goal_wait") or view["wait"].get("reason")
    elif parking.get("phase") == "submitting":
        phase, reason = "received", "dock_submitting"
    elif parking.get("phase") == "docking" and parking.get("operation"):
        ack = live.command_ack_mono if live is not None else None
        phase = motion if ack is not None and mono is not None and mono >= ack else "dispatched"
        reason = "dock_accepted"
    elif live is not None and live.command_ack_mono is not None and (
            (live.active_route and not live.active_route.get("superseded")) or live.last_goal is not None
            or detail.get("line_follow_started") or live.sent):
        phase = motion if mono is not None and mono >= live.command_ack_mono else "dispatched"
    else:
        phase = "received"
    return {"phase": phase, "motion": motion, "sampled_at": sampled_at, "reason": reason,
            "command_robot_id": view["robot_id"],
            "waiting_on": list(waiting_on) if phase in ("paused", "pre_dispatch_wait", "goal_wait") else []}


class LiveTrip:
    """Runtime state of one robot's trip (``trip_runner``); ``view`` is what is stored and returned."""

    def __init__(self, view: dict, graph, request: dict) -> None:
        self.view = view
        self.graph = graph
        self.request = request
        # Read projection only. A pre-ACK wheel sample cannot prove this dispatch moved the base.
        self.command_ack_mono: float | None = None
        #: The last instruction CORE accepted: index, action, place, seq, at.
        self.sent: Optional[dict] = None
        self.first_seq: Optional[int] = None
        #: D-520 2: CORE's last ``arc_seq`` at our first send; a newer arc is one of this trip's.
        self.arc_base: Optional[int] = None
        #: Our held replan stop (seq) that the confirmed plan's action may replace while executing.
        self.replaceable: Optional[int] = None
        self.last_goal: Optional[tuple[float, float]] = None
        #: Active D-1009 Nav2 route span dispatched to CORE (``{"end_index", "points"}``).
        self.active_route: Optional[dict] = None
        #: Bounded Nav2 failure recovery state (alternate-path replans and cooldown retries).
        self.road_profile_key = None
        self.road_profile = []
        self.road_pose = None
        self.nav2_retries: int = 0
        self.nav2_retry_at: float = -math.inf
        self.nav2_replans: int = 0
        self.nav2_blocked: set[str] = set()
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
        self.off_lane_ticks: int = 0

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
        self.road_pose = pose
        self.view["pose"], self.pose_read_at = pose_view(pose), _ports._monotonic()

    @property
    def segments(self) -> list:
        return self.view["plan"]["segments"]

    @property
    def open(self) -> bool:
        return self.view["state"] in OPEN

    @property
    def nav2(self) -> bool:
        """Whether this trip drives painted lanes via CORE Nav2 ``navigation/route``."""
        return self.request.get("drive_mode") == "nav2"

    @property
    def nav2_binding_scope(self) -> tuple[int, str] | None:
        binding_id = self.view["detail"].get("nav2_binding_id")
        return (self.view["map_version"], binding_id) if binding_id is not None else None

    def segment_is_lane(self, index: int) -> bool:
        camera = self.view["detail"].get("camera_lane_fallback") or {}
        driving_camera = camera.get("phase") == "running" and camera.get("index") == index
        return (not self.nav2 or driving_camera) and self.arc(index).drive_mode == "lane"

    def effective_mode(self, index: int) -> str:
        return "lane" if self.segment_is_lane(index) else "free"

    def arc(self, index: int):
        return self.graph.arcs[arc_id(self.segments[index])]

    def place(self, index: int) -> Optional[str]:
        place = ends_at_place(self.graph, self.segments[index])
        return (place if place is not None or self.view["repeat"] or index != len(self.segments) - 1
                else self.view["plan"]["actions"][-1]["place_id"])

    def reset_nav2_recovery(self) -> None:
        self.nav2_retries = 0
        self.nav2_retry_at = -math.inf
        self.nav2_replans = 0
        self.nav2_blocked.clear()
        self.view["detail"].pop("nav2_problem", None)

    def progress(self, index: int, s: float) -> float:
        """Metres along the whole plan."""
        done = sum(seg["s_to"] - seg["s_from"] for seg in self.segments[:index])
        return done + s - self.segments[index]["s_from"]
