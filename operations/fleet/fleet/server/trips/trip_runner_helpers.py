"""Read queries, view builders, and robot/pose helpers for ``TripRunner``."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Optional

import httpx

from fleet.hub.hub import HubError
from fleet.routing.cost import STOP
from fleet.routing.execute import lane_action
from fleet.server.trip_geometry import pose_view
from fleet.server.trip_halts import error_code as _code
from fleet.server.trip_laps import convoy_refusal
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_ports import TripError
from fleet.swarm.transport import RobotApiError

_LOG = logging.getLogger("fleet.server.trip_runner")
_ROBOT_ERRORS = (RobotApiError, HubError, OSError, RuntimeError, ValueError, httpx.HTTPError)


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


def _caps_view(caps) -> dict:
    return {
        "kind": caps.kind, "modes": sorted(caps.modes), "max_speed": caps.max_speed,
        "junction_turn": caps.junction_turn, "junction_pivot": caps.junction_pivot,
        "lane_arc": caps.lane_arc, "lane_arc_map_anchor": getattr(caps, "lane_arc_map_anchor", False),
        "line_follow_authority": getattr(caps, "line_follow_authority", False),  # D-760 3: shrink
        "line_follow_authority_shrink": getattr(caps, "line_follow_authority_shrink", False),
        "lane_instruction_stamp": getattr(caps, "lane_instruction_stamp", False),
        "line_follow_route_guide": getattr(caps, "line_follow_route_guide", False),
        "line_follow_advice": getattr(caps, "line_follow_advice", False),
        "lane_turn_map_entry": getattr(caps, "lane_turn_map_entry", False),
        "lane_bend": caps.lane_bend, "lane_bend_next_line": getattr(caps, "lane_bend_next_line", False),
        "lane_bend_map_entry": getattr(caps, "lane_bend_map_entry", False),
    }


def _check_start_traffic(runner, robot_id: str, plan: dict, request: dict,
                         arcs, caps, repeat: bool) -> Optional[str]:
    leader = (request.get("convoy") or {}).get("leader")
    refused = leader and (runner.convoy_refusal(robot_id, leader, arcs=arcs, segments=plan["segments"]) or (
        runner.authority.mode(caps) != "core" and ("TRIP_CONVOY_NO_AUTHORITY", {"leader": leader})))
    if refused:  # D-517 9 M3: a follower keeps its gap only through CORE authority
        raise TripError(422, *refused)
    refused = runner.traffic.signal_refusal(plan["segments"], runner.authority.mode(caps))
    if refused:  # D-525 1/6: not from inside a signalled zone; crossing one needs CORE authority
        raise TripError(422, *refused)
    if repeat:  # D-517 3: no await from this check to the trip opening
        full = runner.traffic.loop_full(arcs, runner._live.values())
        if full is not None:  # a convoy counts as 1 + N robots
            raise TripError(422, "TRIP_CONVOY_LOOP_FULL" if leader else "TRIP_LOOP_FULL", full)
    return leader


def _build_started_view(*, plan_id: str, robot_id: str, principal_id: str, notes: dict,
                        plan: dict, pose, now: float, body, pose_observed_at: float,
                        repeat: bool, caps_view: dict, traffic_authority: str,
                        leader: Optional[str], lease, moved, enable: bool, turns) -> dict:
    view = {
        "trip_id": plan_id, "plan_id": plan_id, "robot_id": robot_id, "started_by": principal_id,
        "state": "started", "reason": None, "detail": notes, "map_version": plan["map_version"],
        "plan": {k: plan[k] for k in ("segments", "places", "actions")}, "segment_index": 0,
        "hold": None, "pose": pose_view(pose), "created_at": now, "updated_at": now,
        "body_half_width_m": body.half_width_m if body is not None else None,
        "pose_observed_at": pose_observed_at,
        "repeat": repeat, "lap": 1 if repeat else None, "caps": caps_view,
        "traffic_authority": traffic_authority, "convoy": leader and {"leader": leader},
        "lease": lease, "stop_moved": moved,
    }
    if enable:  # D-760 2: lease -> line ON -> first authority (CORE refuses one while OFF)
        view["detail"]["line_follow_started"] = False
    if turns:  # D-603: the alignment turns CORE made before this start
        view["detail"]["aligned"] = turns
    return view


class TripRunnerHelpers:
    """Read queries and robot/pose/persistence helpers mixed into ``TripRunner``."""

    def open_trips(self) -> list[dict]:
        return [live.view for live in self._live.values() if live.open]

    def running(self) -> Optional[dict]:
        """The most recently started open trip (the one-trip console reads it); ``open_trips`` has all."""
        views = self.open_trips()
        return max(views, key=lambda view: view["created_at"]) if views else None

    def robot_busy(self, robot_id: str) -> bool:
        """A running trip owns this robot's motion (other Fleet commands answer TRIP_ROBOT_BUSY)."""
        live = self._live.get(robot_id)
        return live is not None and live.open

    def leg_mode(self, robot_id: str) -> Optional[str]:
        """Drive mode (``lane``/``free``) of the open trip's current segment; None when it cannot be told."""
        live = self._live.get(robot_id)
        try:
            return live.arc(live.view["segment_index"]).drive_mode if live is not None and live.open else None
        except (KeyError, IndexError, TypeError):
            return None

    def convoy_refusal(self, robot_id: str, leader: str, **cycle) -> Optional[tuple]:
        return convoy_refusal(self._live, robot_id, leader, **cycle)

    def _find(self, trip_id: str) -> Optional[LiveTrip]:
        return next((live for live in self._live.values() if live.view["trip_id"] == trip_id), None)

    def view(self, trip_id: str) -> Optional[dict]:
        live = self._find(trip_id)
        return live.view if live is not None else self._store.trip(trip_id)

    def recent(self, limit: int = 20) -> list[dict]:
        return [self.view(t["trip_id"]) for t in self._store.trips(limit=limit)]

    async def _call(self, value, code: Optional[str] = None):
        """One bounded robot/provider call; with ``code`` a failure is that start refusal."""
        try:
            return await asyncio.wait_for(_maybe(value), self.config.port_timeout_s)
        except _ROBOT_ERRORS as exc:
            if code is None:
                raise
            raise TripError(422, code, {"error": _code(exc)}) from exc

    def _graph_for(self, version):
        active = self._store.active()
        if active is None or active[0] != version:
            raise TripError(422, "TRIP_MAP_CHANGED", {"map_version": active[0] if active else None})
        return active[2]

    def _auto_locate_on(self, robot_id: str) -> bool:
        check = getattr(self._poses, "auto_locate_enabled", None)
        return check is not None and check(robot_id) is True

    def _lock_for(self, robot_id: str) -> asyncio.Lock:
        return self._locks.setdefault(robot_id, asyncio.Lock())

    def _open(self, trip_id: str) -> LiveTrip:
        live = self._find(trip_id)
        if live is None:
            if self._store.trip(trip_id) is None:
                raise TripError(404, "TRIP_UNKNOWN")
            raise TripError(409, "TRIP_NOT_RUNNING")
        if not live.open:
            raise TripError(409, "TRIP_NOT_RUNNING", {"state": live.view["state"]})
        return live

    def _describe(self, live: LiveTrip) -> None:
        index = live.view["segment_index"]
        live.view.update(current_edge=live.segments[index]["edge_id"], drive_mode=live.arc(index).drive_mode,
                         next_place=live.place(index),
                         next_action=STOP if live.view["hold"] else lane_action(live.graph, live.segments, index,
                                                                                self._routing))

    def _save(self, live: LiveTrip) -> None:
        if not live.open:
            live.view["detail"].pop("bend_candidate", None)
            self.lease.close(live)  # D-541 7: DELETE after the halt
            self.authority.forget(live.view["robot_id"], live.view["detail"].get("stop_sent") is True)  # MEDIUM-2
        live.view["updated_at"] = self._clock()
        self._store.put_trip(live.view)
