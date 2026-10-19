"""D-517 2 / D-559 replanning of the trip loop: operator and AI-confirmed replans, the next lap and a
failed lap's retry. Moved out of ``trip_runner`` unchanged (D-798); ``TripRunner`` mixes it in.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

from fleet.routing.cost import STOP
from fleet.routing.execute import replan_hold
from fleet.server.trip_laps import carry_on, hold_back_m, next_lap
from fleet.server.trip_live import LiveTrip
from fleet.server.trip_ports import TripError


class TripReplan:
    """``TripRunner``'s replanning methods; state and ports live on the runner."""

    async def confirm_replan(self, trip_id: str, principal_id: str) -> dict:
        async with self._lock_for(self._open(trip_id).view["robot_id"]):
            live = self._open(trip_id)
            hold = live.view["hold"]
            if hold is None:
                raise TripError(409, "TRIP_NO_REPLAN")
            if hold.get("plan") is None and hold.get("reason") == "lap":  # the operator retries the lap check
                # carried on, or a changed lap (shown first, confirmed next); a failed retry leaves a hold
                if await self._retry_lap(live, live.view["segment_index"]) or live.view["hold"].get("plan") is not None:
                    self._describe(live)
                    self._save(live)
                    return live.view
                hold = live.view["hold"]
            if hold.get("plan") is None:
                raise TripError(409, "TRIP_REPLAN_FAILED", {"code": hold.get("code")})
            await self._admit_replan(live, hold, principal_id)  # D-763 10 (c): checked as at a start
            self._describe(live)
            self._save(live)
            return live.view

    def _apply_replan(self, live: LiveTrip, hold: dict, principal_id: str) -> None:
        """Switch to the held new route (operator confirm, or D-610 7 an AI replan that passed the start checks)."""
        active = self._store.active()
        if active is None or active[0] != hold["map_version"]:  # plan again at this place
            live.view["hold"], live.replan_pending = None, True
            self._save(live)
            raise TripError(409, "TRIP_MAP_CHANGED", {"map_version": active[0] if active else None})
        live.view.update(plan=hold["plan"], map_version=hold["map_version"], segment_index=0, hold=None)
        live.graph = active[2]
        live.route_rev += 1
        live.bends_done.clear()  # the plan is renumbered (review); D-507 addendum: a new lap drives its bends again
        if "lap_route" in hold:  # D-517 2: the operator took the changed lap
            live.lap_route = hold["lap_route"]
            live.lap_arcs = tuple(f"{edge}:{'fwd' if forward else 'rev'}"
                                  for edge, forward, _s in hold["lap_route"])
            live.view["lap"] += 1
        live.view["detail"]["replan_confirmed_by"] = principal_id
        sent = live.sent
        live.replaceable = sent["seq"] if sent is not None and sent["action"] == STOP else None
        live.sent, live.last_goal, live.replan_pending, live.at, live.at_stamp = None, None, False, None, None
        live.lap_start = 0

    async def _ai_confirm(self, live: LiveTrip, principal_id: str = "fleet-ai") -> Optional[bool]:
        """D-610 7: an AI replan switches without ``replan_hold`` once the new route passes the D-494/D-601
        start checks a first trip passes; a refusal leaves the hold for the operator (D-517 M4)."""
        hold = live.view["hold"]
        if not hold or hold.get("reason") != "replan" or hold.get("plan") is None:
            return
        robot_id, segments = live.view["robot_id"], hold["plan"]["segments"]
        selected = deepcopy(hold)
        token = (self._stop_epoch, self._start_cancels.get(robot_id, 0), live.route_rev)

        def current():
            return (live.open and self._live.get(robot_id) is live and live.view["hold"] is hold
                    and hold == selected
                    and token == (self._stop_epoch, self._start_cancels.get(robot_id, 0), live.route_rev)
                    and (principal_id != "fleet-rule" or robot_id in self.autonomous_robots))

        try:
            graph = self._graph_for(hold["map_version"])
            await self._caps_checks(robot_id, graph, segments, bool(live.repeat), detail=live.view["detail"])
            if not current():
                return
            await self._pose_checks(robot_id, graph, segments)
            if current():
                self._apply_replan(live, hold, principal_id)
                return True
        except TripError as exc:
            live.view["detail"]["ai_replan_refused"] = exc.code

    async def _retry_lap(self, live: LiveTrip, index: int) -> bool:
        """Plan the failed lap again; True when it carries on (the held stop at the place may be replaced)."""
        hold, live.view["hold"] = live.view["hold"], None
        await self._next_lap(live, index)
        if live.view["hold"] is not None or not live.open:
            if live.view["hold"] is None:
                live.view["hold"] = hold
            return False
        sent = live.sent
        live.replaceable = sent["seq"] if sent is not None and sent["action"] == STOP else None
        live.sent, live.last_goal = None, None
        return True

    async def _next_lap(self, live: LiveTrip, index: int) -> None:
        """D-517 2: plan the next lap from this lap's end after the D-494 start checks (``trip_laps.carry_on``)."""
        robot_id, segments = live.view["robot_id"], live.segments
        end = live.arc(len(segments) - 1).point_at(segments[-1]["s_to"])
        try:
            graph = self._graph_for(live.view["map_version"])
            await self._pose_checks(robot_id, graph, segments[index:])
            body, hold = next_lap(self._store.active(), end, live.request, live.view["caps"] or {}, frozenset(
                self._blocked()), self._routing, self.config.max_turn_deg, self.traffic)
            await self._caps_checks(robot_id, graph, body["segments"] if body else segments[index:], True, detail=live.view["detail"])
        except TripError as exc:
            body, hold = None, {"plan": None, "code": exc.code, "detail": exc.detail}
        if not live.open:
            return
        carry_on(live, index, segments, body, hold, self._clock())

    def _needs_replan(self, live: LiveTrip, index: int) -> bool:
        active = self._store.active()
        if active is None or active[0] != live.view["map_version"]:
            return True
        blocked = self._blocked()
        return any(seg["edge_id"] in blocked for seg in live.segments[index + 1:])

    def _replan(self, live: LiveTrip, index: int, closed: frozenset = frozenset()) -> None:
        """D-489 9: plan again from just before the next place; a changed route holds there.
        ``closed``: edges Fleet's resolver plans around (D-517 5), on top of ``blocked``."""
        segment = live.segments[index]
        live.replan_pending = hold_back_m(self.traffic, segment) is None  # D-517 3: no hold in a zone; the next place
        live.view["hold"] = None if live.replan_pending else replan_hold(
            self._store.active(), live.arc(index).point_at(max(segment["s_to"] - 0.01, segment["s_from"])),
            live.segments[index:], live.request, live.view.get("caps") or {}, frozenset(self._blocked()) | closed,
            {live.place(i) for i in range(index)}, live.view["map_version"], self._routing,
            self.config.max_turn_deg)
