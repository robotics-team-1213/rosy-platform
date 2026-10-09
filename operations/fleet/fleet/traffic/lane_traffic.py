"""D-517 3 (M1): the Fleet block table over every open trip — computed and shown, never sent.

Each trip period ``TripRunner`` hands its trips here. The active map's ``Layout`` is cut once per
map version (zones from site config ``fleet.traffic.zones``; a two-way lane becomes a
direction-locked zone by itself), each trip robot becomes a ``blocks.Robot`` and
``blocks.step`` runs. No authority goes to a robot (that is M2, safety-reviewed); the trip loop
only holds back a junction instruction into a refused block (``holds``).

D-517 6: a robot whose trip ended, or whose trip is on another map version, keeps its last
grants and body as ``pinned`` units until a fresh ``LOCALIZED`` pose shows it clear of them
(the pose's units replace the pins); a map activation re-pins every robot from its last pose.

D-525 (S1): virtual signals from site config ``fleet.traffic.signals`` run here each period; a
signalled zone is granted only to its green approach (``blocks.step(green=...)``). A plan that fails
``signal_phase.check`` on the active map keeps its zone red. Robots get no colour, only D-517 authority.

The single writer of lane-trip grants (D-517 3). ``traffic_reservations.py`` (D-426 segment
states) writes no trip grant; it stays only as the Gazebo conformance harness's segment record."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from typing import Iterable, Mapping, Optional

from core_common.robot_body import PINKY_PRO  # public read-only anchor (D-430 §3); RobotBody is not
from fleet.localization.map_pose import MapPoseConfig
from fleet.traffic import blocks, handover, signal_phase
from fleet.routing.execute import arc_id
from fleet.server.trip_ports import ODOM_DRIFT_PER_M, TripConfig, pose_view

LOCALIZED = "LOCALIZED"
#: D-517 3: blocks one robot holds at worst (occupancy 2 + one grant ahead on the demo blocks).
HELD_PER_ROBOT = 3
#: Before its junction instruction goes out a robot asks for the block just past the place.
PAST_PLACE_M = 0.05
#: D-517 9 M3 (Safety-Review): the most a convoy member may reverse below the farthest point it reached,
#: added to the follower's moving-block gap. D-407 stuck back-off: one ``recovery_back_m`` (default 0.08,
#: config cap 0.20; a next attempt needs that much forward travel first); then a D-468 retrace: ≤ 0.15 m
#: (target within 0.15 m, ≤ 5 s from the checkpoint at ≤ 0.03 m/s). Fleet cannot read the robot's
#: recovery config (not in caps), so the caps are summed. d_stop(v) + u alone is 0.18–0.24 m.
MEMBER_REVERSE_M = 0.20 + 0.15
#: D-525 real-map finding: D-517 needs every estimate within u of the body. A front that moved further
#: between two periods than the robot can (max speed × time + 2u + this) is a jump, not travel: that
#: period it is UNKNOWN (no new authority). A jump below the bound stays invisible; u must be true.
JUMP_MARGIN_M = 0.05
#: A refused front is taken once this many periods in a row agree with it (a robot moved by hand, a real
#: correction). A one-frame glitch never gets there. Until then the robot holds every instruction.
JUMP_SETTLE_PERIODS = 3
#: D-525 4 / D-443: a manual green lasts while a named operator's console says it is there this often.
PRESENCE_S = 10.0


class TrafficService:
    def __init__(self, store, config: TripConfig = TripConfig(), *,
                 zones: Optional[Mapping[str, tuple[Iterable[str], int]]] = None,
                 signals: Iterable[signal_phase.SignalPlan] = (),
                 body=PINKY_PRO, held_per_robot: int = HELD_PER_ROBOT, clock=time.time,
                 signal_clock=time.monotonic) -> None:
        self._store, self._config, self._zones = store, config, dict(zones or {})
        #: D-525: plan per signal id, its phase state (a restart starts all red), the active map's
        #: check errors, and the last table's busy units (None: not known yet, so busy)
        self._signals = {plan.id: plan for plan in signals}
        self._phase = {signal_id: signal_phase.SignalState() for signal_id in self._signals}
        self._signal_errors: dict[str, list[str]] = {}
        self._busy: Optional[frozenset] = None
        self._signal_clock = signal_clock
        self._present_until = -math.inf  # D-525 4: a manual green needs an operator present
        self._ahead: dict[str, dict] = {}  # robot id -> its next signal (D-525 rev 3)
        # ponytail: one body for the whole site (Pinky); the longest registered body (D-517 3 L)
        # comes from robot capabilities once a second kind joins.
        self._body, self._length = body, body.front_x_m - body.rear_x_m
        self._held, self._clock = held_per_robot, clock
        self._u_max = config.expect_tol_min_m + ODOM_DRIFT_PER_M * MapPoseConfig().max_dead_reckon_m
        self._version, self._layout, self._state = None, None, blocks.TableState()
        self._view: dict = _empty(None)
        #: robot id -> its last LOCALIZED map pose ``(x, y, yaw)``, to re-pin it on a new map version.
        self._last_pose: dict[str, tuple[float, float, float]] = {}
        #: robot id -> (route id, trim_m, spans) of the last period, to shift grants when laps are dropped.
        self._seen: dict[str, tuple[str, float, tuple]] = {}
        self._parked, self._warned = {}, False  # map poses read this period for ``pinned`` robots (D-517 6)
        #: D-517 5 (M4): robot id -> when it was first seen UNKNOWN; robot id -> (route id, edges) of the
        #: replan given; the last wait cycle and how many periods in a row it was seen
        self._unknown_since: dict[str, float] = {}
        self._tried: dict[str, tuple[str, list]] = {}
        self._cycle: tuple[frozenset, int] = (frozenset(), 0)
        #: robot id -> (route id, trim, front in route metres, clock) of its last accepted front
        self._front: dict[str, tuple[str, float, float, float]] = {}
        #: robot id -> (front, clock, periods in a row) of a refused front that may settle (JUMP_SETTLE_PERIODS)
        self._jumped: dict[str, tuple[float, float, int]] = {}

    # ---- the table ------------------------------------------------------------------------

    def _layout_for(self, active) -> Optional[blocks.Layout]:
        if active is None:
            return None
        if active[0] != self._version:  # a new map version starts a new table, occupancy carried over
            rules = blocks.BlockRules(self._length, self._u_max, self._body.resume_gap_m)
            layout = blocks.build_layout(active[2], rules, self._zones)
            old, state = self._state, blocks.TableState()
            for robot_id in {*old.route, *old.held, *old.last_occupied, *old.pinned}:
                pose = self._last_pose.get(robot_id)
                units = self._under(layout, active[2], pose) if pose is not None else {}
                if units:
                    state.pinned[robot_id] = units
            self._layout, self._version, self._state, self._seen = layout, active[0], state, {}
            self._signal_errors = {i: signal_phase.check(plan, active[2], layout) for i, plan in self._signals.items()}
            self._busy = None
        return self._layout

    def _under(self, layout: blocks.Layout, graph, pose: tuple[float, float, float]) -> dict[str, bool]:
        """``{unit: forward}`` a robot body at ``pose`` (± its length and u along the lane) may touch."""
        x, y, yaw = pose
        reach = self._length + self._u_max
        units: dict[str, bool] = {}
        for arc in graph.arcs.values():
            if not arc.forward:
                continue
            dist, s, tangent = arc.project(x, y)
            if dist > arc.width_m / 2 + self._u_max:
                continue
            forward = yaw is None or math.cos(yaw - tangent) >= 0.0
            for unit, s0, s1 in layout.edge_units[arc.edge_id]:
                if s1 > s - reach and s0 < s + reach:
                    units[unit] = forward
        return units

    def _pin(self, robot_id: str) -> None:
        """Its trip left the table: grants and last body stay as pins (D-517 6)."""
        state = self._state
        kept = dict(state.pinned.get(robot_id, {}))
        kept.update(state.last_occupied.get(robot_id, {}))
        kept.update({unit: forward for unit, forward in state.held.get(robot_id, {}).values()})
        blocks.release_robot(state, robot_id)
        if kept:
            state.pinned[robot_id] = kept

    def _robot(self, layout: blocks.Layout, graph, live) -> blocks.Robot:
        segments, pose = live.segments, live.view.get("pose") or {}
        speed = (live.view.get("caps") or {}).get("max_speed") or 0.0
        lookahead, d = self._body.resume_gap_m(speed), None
        if pose.get("state") == LOCALIZED and live.at is not None:
            index, s = live.at
            d = segments[0]["s_from"] + live.progress(index, s) + self._body.front_x_m  # route m of the FRONT
            remaining = segments[index]["s_to"] - s
            # The table runs after the steps, so the block past a place is asked for two periods
            # before the robot is within ``arm_distance_m`` of it (a trip that starts there is not).
            if live.place(index) and remaining <= self._config.arm_distance_m + 2 * self._config.period_s * speed:
                lookahead = max(lookahead, remaining + PAST_PLACE_M)
        reckoned = pose.get("dead_reckon_m")
        u = self._u_max if reckoned is None else min(
            self._u_max, self._config.expect_tol_min_m + ODOM_DRIFT_PER_M * reckoned)
        # ponytail: the route is cut again every period (linear in segments); cache by route_rev
        # and plan length if 30 robots on long repeat trips measure slow (D-517 7: 100 ms).
        spans = layout.route(graph, [arc_id(seg) for seg in segments])
        robot_id, route_id = live.view["robot_id"], f"{live.view['trip_id']}:{live.route_rev}"
        if live.view.get("traffic_authority") == "core":  # only an until_m can be overrun by a jump
            d = self._jump_guard(robot_id, route_id, d, live.trim_m, speed, u, live.at_stamp)
        seen = self._seen.get(robot_id)
        if seen is not None and seen[0] == route_id and live.trim_m > seen[1]:
            _shift(self._state, robot_id, seen[2], live.trim_m - seen[1])
        self._seen[robot_id] = (route_id, live.trim_m, spans)
        line = getattr(live, "junction", None) or {}  # this period's CORE line-follow read (lane segments)
        return blocks.Robot(robot_id, spans, d, lookahead, u, self._length, route_id=route_id,
                            convoy=getattr(live, "convoy", None), recovering=line.get("line_recovering") is True)

    def _jump_guard(self, robot_id: str, route_id: str, d: Optional[float], trim: float, speed: float,
                    u: float, stamp: Optional[float] = None) -> Optional[float]:
        """``d``, or None when it jumped from the last accepted front on the same route (JUMP_MARGIN_M).
        Time is the pose's own stamp (a stale pose that refreshes is travel, not a jump), else the clock."""
        if d is None:
            return None
        now, prev = (stamp if stamp is not None else self._clock()), self._front.get(robot_id)
        if prev is not None and prev[:2] == (route_id, trim):  # same route metres (dropped laps restart it)
            allowed = speed * max(0.0, now - prev[3]) + 2 * u + JUMP_MARGIN_M
            if abs(d - prev[2]) > allowed:
                last = self._jumped.get(robot_id)
                if last is None:
                    logging.getLogger("fleet.server.trip_runner").warning(
                        "%s map pose jumped %.2f m (allowed %.2f m): no new authority until it settles",
                        robot_id, d - prev[2], allowed)
                agree = last is not None and abs(d - last[0]) <= speed * max(0.0, now - last[1]) + 2 * u + JUMP_MARGIN_M
                count = last[2] + 1 if agree else 1
                if count < JUMP_SETTLE_PERIODS:
                    self._jumped[robot_id] = (d, now, count)
                    return None
        self._jumped.pop(robot_id, None)
        self._front[robot_id] = (route_id, trim, d, now)
        return d

    def jumped(self, robot_id: str) -> bool:
        """Its last front was refused as a jump: it holds every instruction (D-525 real-map finding)."""
        return robot_id in self._jumped

    def _link(self, graph, robots: list, trips: dict) -> dict:
        """D-517 9 M3: each follower of an open convoy follows the nearest localized member ahead on
        the same arcs (moving block); ``{follower: gap m from its front to that member's rear}``.

        Latest start first (Safety-Review liveness): two followers that both read the other as ahead
        (estimate noise nose to tail, or a lap wrap) would both stand. The earlier-started one, ahead in
        the convoy, never follows a later one that follows it; it falls back to its other members or
        fixed blocks."""
        gaps, follows = {}, {}
        order = lambda r: (trips[r.id].view.get("created_at") or 0.0, r.id)  # noqa: E731
        for robot in sorted((r for r in robots if r.convoy is not None), key=order, reverse=True):
            live = trips[robot.id]
            members = [r for r in robots if robot.convoy in (r.id, r.convoy) and not (
                follows.get(r.id) == robot.id and order(r) > order(robot))] if robot.convoy in trips else []
            front = blocks.follow(
                robot, members, lambda m, after: _front_on(graph, live, trips[m.id], m.d, after, self._length),
                self._body.resume_gap_m((live.view.get("caps") or {}).get("max_speed") or 0.0) + MEMBER_REVERSE_M)
            follows[robot.id] = robot.follows
            if front is not None:
                gaps[robot.id] = round(front - self._length - robot.d, 3)
        return gaps

    def pinned(self) -> list[str]:
        """Robots that block with pins: the trip loop reads their poses (``step(poses=...)``)."""
        return sorted(self._state.pinned)

    def step(self, lives: Iterable, poses: Optional[Mapping[str, object]] = None) -> None:
        """One period over every open trip on the active map version.

        ``poses`` are map poses read this period for robots without an open trip (``pinned``).
        """
        lives = list(lives)
        fresh = {robot_id: pose_view(pose) for robot_id, pose in (poses or {}).items()}
        fresh.update({live.view["robot_id"]: live.view.get("pose") for live in lives if live.open})
        fresh = {robot_id: (p["x"], p["y"], p["yaw"]) for robot_id, p in fresh.items()
                 if p and p.get("state") == LOCALIZED and p.get("x") is not None and p.get("y") is not None}
        self._last_pose.update(fresh)
        active = self._store.active()
        layout = self._layout_for(active)
        trips = {live.view["robot_id"]: live for live in lives
                 if live.open and layout is not None and live.view["map_version"] == active[0]}
        for live in lives:
            if live.open and live.view["robot_id"] not in trips:  # no table for its map: no instruction
                live.traffic = {"waiting_for": [], "authority_end_m": None, "refused_at_m": 0.0}
        if layout is None:
            self._view = _empty(None)
            self._view["signals"] = self._signal_view(None)
            self._unknown_since, self._tried, self._cycle = {}, {}, (frozenset(), 0)
            return
        state = self._state
        for robot_id in {*state.route, *state.held, *state.last_occupied} - set(trips):
            self._pin(robot_id)
        moving = {live.view["robot_id"] for live in lives if live.open}  # open trips on an old map
        for robot_id in [r for r in state.pinned if r not in trips and r in fresh]:
            units = self._under(layout, active[2], fresh[robot_id])
            if robot_id in moving:  # still driving: its pose may lag a period, so pins only grow
                state.pinned[robot_id] = {**state.pinned[robot_id], **units}
            elif units:  # where it stands now replaces the pins
                state.pinned[robot_id] = units
            else:
                blocks.release_robot(state, robot_id)
        robots = [self._robot(layout, active[2], live) for live in trips.values()]
        gaps = self._link(active[2], robots, trips)
        now = self._clock()
        result = blocks.step(layout, robots, self._state, now, green=self._green())
        self._busy = result.busy
        self._ahead = self._signals_ahead(robots)
        refused_unit: dict[str, str] = {}
        for robot in robots:
            live, waiting = trips[robot.id], result.waiting_for.get(robot.id, ())
            used = {"front_d_m": robot.d, "pose_stamp": None if robot.d is None else live.at_stamp}  # D-517 4
            if result.unplaced:  # a robot never localized could be anywhere: no instruction for anyone
                live.traffic = {"waiting_for": [r for r in result.unplaced if r != robot.id],
                                "authority_end_m": result.authority_end.get(robot.id), "refused_at_m": 0.0, **used}
                continue
            refused = 0.0 if self.jumped(robot.id) else None  # a refused jump holds every instruction
            if waiting and robot.d is not None:
                held = self._state.held.get(robot.id, {})
                index = next((i for i, span in enumerate(robot.spans) if span.d1 > robot.d and i not in held), None)
                if index is not None:
                    refused_unit[robot.id] = robot.spans[index].unit
                    refused = robot.spans[index].d0 - live.segments[0]["s_from"]  # back to plan metres
            live.traffic = {"waiting_for": list(waiting) or (["pose_jump"] if self.jumped(robot.id) else []),
                            "authority_end_m": result.authority_end.get(robot.id), "refused_at_m": refused, **used}
        self._view = self._make_view(active[0], layout, active[2], trips, result, refused_unit, robots, gaps)
        self._view["signals"] = self._signal_view(active[2])
        for row in self._view["robots"]:
            row["signal_ahead"] = self.signal_ahead(row["robot_id"])
        self._hand_over(layout, trips, robots, refused_unit, now)

    def _hand_over(self, layout, trips: dict, robots, refused_unit: dict, now: float) -> None:
        """D-517 5 (M4): Fleet's resolver for a wait cycle or a 30 s UNKNOWN (``handover.decide``)."""
        localized = {robot.id for robot in robots if robot.d is not None}
        unknown = set(self._state.pinned) | (set(self._state.last_occupied) - localized)  # as the view's UNKNOWN
        self._unknown_since = {r: self._unknown_since.get(r, now) for r in unknown}
        route = {robot.id: robot.route_id for robot in robots}
        self._tried = {r: tried for r, tried in self._tried.items() if route.get(r) == tried[0]}
        avoidable = {}
        for robot_id, unit in refused_unit.items():
            live = trips[robot_id]
            index = live.view["segment_index"]
            edges = [edge for edge, parts in layout.edge_units.items() if any(p[0] == unit for p in parts)]
            if index < len(live.segments) - 1 and live.segments[index]["edge_id"] not in edges:
                avoidable[robot_id] = edges  # the unit lies past its next place: plan around it from there
        cycle = self._view["wait_cycle"]
        seen = frozenset(cycle or ())
        self._cycle = (seen, self._cycle[1] + 1 if seen and seen == self._cycle[0] else int(bool(seen)))
        pending = {r for r, live in trips.items()  # a replan hold with a route to confirm (none: human)
                   if (live.view["hold"] or {}).get("reason") == "replan" and live.view["hold"].get("plan")}
        decisions = handover.decide(cycle, self._cycle[1], avoidable, {r: t[1] for r, t in self._tried.items()},
                                    pending, self._unknown_since, now)
        decisions = {r: row for r, row in decisions.items() if not r.startswith("signal:")}  # D-525 pseudo node
        for robot_id, row in decisions.items():
            if row["decision"] == "replan":
                self._tried[robot_id] = (route[robot_id], row["blocked_edges"])
            if robot_id in trips:
                trips[robot_id].traffic["resolver"] = row
        self._view["resolver"] = [{"robot_id": r, **row} for r, row in sorted(decisions.items())]

    def view(self) -> dict:
        return self._view

    def zone_edges(self) -> dict[str, tuple]:
        """Site zones ``{zone: (edges, capacity)}`` (D-536 guide reads them)."""
        return dict(self._zones)

    # ---- D-525 virtual signals ------------------------------------------------------------

    def _green(self) -> dict[str, frozenset]:
        """Advance every signal and return ``{zone: approaches allowed in}``; a refused plan stays red."""
        now, green = self._signal_clock(), {}
        for signal_id, plan in self._signals.items():
            state = self._phase[signal_id]
            if state.mode == "manual" and now >= self._present_until:  # nobody there: all red, not cycle
                signal_phase.command(plan, state, "all_red", now)
            signal_phase.advance(plan, state, now, self._busy is None or plan.zone in self._busy)
            green[plan.zone] = frozenset() if self._signal_errors.get(signal_id) else signal_phase.green(plan, state)
        return green

    def _signals_ahead(self, robots) -> dict[str, dict]:
        """D-525 rev 3: each localized trip robot's next signalled zone on its route: the signal, the
        approach it enters from, front-to-stop-line metres (negative: already past it) and whether it
        already holds that zone (may enter; the D-517 authority is still what lets it move)."""
        zones = {plan.zone: plan.id for plan in self._signals.values()}
        out = {}
        for robot in robots:
            if robot.d is None or not zones:
                continue
            held = self._state.held.get(robot.id, {})
            for index, span in enumerate(robot.spans):
                if span.unit in zones and span.d1 > robot.d:
                    out[robot.id] = {"signal_id": zones[span.unit], "approach": span.entry,
                                     "distance_m": round(span.d0 - robot.d, 3), "may_enter": index in held}
                    break
        return out

    def signal_ahead(self, robot_id: str) -> Optional[dict]:
        """The next signal on this robot's trip with its approach's countdown (advisory), or None."""
        ahead = self._ahead.get(robot_id)
        if ahead is None:
            return None
        plan = self._signals[ahead["signal_id"]]
        row = next((a for a in self._signal_row(plan, None)["approaches"] if a["approach"] == ahead["approach"]), {})
        return {"robot_id": robot_id, **ahead, "virtual": True, "advisory": True,
                **{k: row.get(k) for k in ("lamp", "left_s", "green_in_s", "exact")}}

    def signal_command(self, signal_id: str, verb: str, approach: Optional[str] = None) -> dict:
        """Operator verb (D-525 4): ``cycle``, ``hold``, ``all_red`` or ``set_aspect`` (green for one
        approach while the operator is present). KeyError: unknown signal; ValueError: bad verb or
        approach; PermissionError: a manual green without presence."""
        plan = self._signals[signal_id]
        now = self._signal_clock()
        if verb == "set_aspect":
            if approach not in {a for a, _green in plan.phases}:
                raise ValueError(approach)
            if now >= self._present_until:
                raise PermissionError("presence")
        elif verb not in ("cycle", "hold", "all_red"):
            raise ValueError(verb)
        signal_phase.command(plan, self._phase[signal_id], verb, now, approach)
        return self._signal_row(plan, None)

    def signal_presence(self) -> dict:
        """A named operator's console is open (D-525 4): a manual green may stay for PRESENCE_S."""
        self._present_until = self._signal_clock() + PRESENCE_S
        return {"present": True, "for_s": PRESENCE_S}

    def signals_all_red(self) -> None:
        """E-stop: every virtual signal all red at once (D-525 4)."""
        now = self._signal_clock()
        for signal_id, plan in self._signals.items():
            signal_phase.command(plan, self._phase[signal_id], "all_red", now)

    def signal_refusal(self, segments, authority_mode: str) -> Optional[tuple[str, dict]]:
        """D-525 1/6 trip start check: no route starting inside a signalled zone, and only a robot that
        takes CORE authority may cross one (junction hold-back alone does not stop it at red)."""
        if not self._signals or not segments:
            return None
        layout = self._layout_for(self._store.active())
        if layout is None:
            return None
        zones = {plan.zone: signal_id for signal_id, plan in self._signals.items()}
        spans = layout.route(self._store.active()[2], [arc_id(seg) for seg in segments])
        if spans and spans[0].unit in zones:
            return "TRIP_SIGNAL_START_IN_ZONE", {"signal_id": zones[spans[0].unit]}
        crossed = sorted({zones[s.unit] for s in spans if s.unit in zones})
        if crossed and authority_mode != "core":
            return "TRIP_SIGNAL_NEEDS_AUTHORITY", {"signals": crossed}
        return None

    def _signal_row(self, plan, graph) -> dict:
        state, now = self._phase[plan.id], self._signal_clock()
        lit = signal_phase.green(plan, state)
        last = plan.phases[state.phase][0] if state.phase >= 0 else None
        held = now - state.since
        left = {"green": (plan.phases[state.phase][1] - held) if state.mode == "cycle" else None,
                "yellow": plan.yellow_s - held, "all_red": plan.all_red_s - held}[state.aspect]
        approaches = []
        errors = self._signal_errors.get(plan.id) or []
        busy = self._busy is None or plan.zone in self._busy
        ahead = signal_phase.forecast(plan, state, now, busy)
        for approach, green_s in plan.phases:
            lamp = "green" if approach in lit else "yellow" if state.aspect == "yellow" and approach == last else "red"
            row = {"approach": approach, "lamp": lamp, "green_s": green_s,
                   **({"left_s": None, "green_in_s": None, "exact": False} if errors else
                      {k: ahead[approach][k] for k in ("left_s", "green_in_s", "exact")})}
            if graph is not None and approach in graph.arcs:  # the stop line: where the approach meets the zone
                arc = graph.arcs[approach]
                x, y, yaw = arc.point_at(arc.length_m)
                row["stop_line"] = {"x": round(x, 3), "y": round(y, 3), "yaw": round(yaw, 4)}
            approaches.append(row)
        manual = plan.phases[state.manual][0] if state.mode == "manual" and state.manual is not None else None
        return {"signal_id": plan.id, "zone": plan.zone, "virtual": True, "mode": state.mode, "manual": manual,
                "aspect": "all_red" if errors else state.aspect,
                "left_s": None if left is None or errors else round(max(0.0, left), 1),
                "zone_busy": busy,
                "approaches": approaches, "errors": errors, "alert": signal_phase.alert(plan, state, now)}

    def _signal_view(self, graph) -> list[dict]:
        return [self._signal_row(plan, graph) for _id, plan in sorted(self._signals.items())]

    def holds(self, live, index: int) -> bool:
        refused = (live.traffic or {}).get("refused_at_m")  # D-517 3: refused before PAST_PLACE_M past the place
        return refused is not None and refused < live.progress(index, live.segments[index]["s_to"]) + PAST_PLACE_M

    def watch(self, inflight: dict, busy, read) -> None:
        """A pinned robot without a trip or a read in flight gets one (hub cache, no forced REST read)."""
        for robot_id in self.pinned():
            task = inflight.get(robot_id)
            if not busy(robot_id) and (task is None or task.done()):
                inflight[robot_id] = asyncio.ensure_future(self._watch(robot_id, read))

    async def _watch(self, robot_id: str, read) -> None:
        with contextlib.suppress(Exception):  # an unread pose keeps the pins
            self._parked[robot_id] = await read(robot_id)

    def period(self, lives) -> None:
        """``step`` with this period's parked poses; a fault never ends a trip (logged once)."""
        poses, self._parked = self._parked, {}
        try:
            self.step(lives, poses)
            self._warned = False
        except Exception:  # the table is shown only (M1); a fault never ends a trip
            for live in lives:  # no stale refusal holds a robot or hides a stall
                live.traffic = None
            if not self._warned:
                logging.getLogger("fleet.server.trip_runner").exception(  # the trip loop's logger (D-517 split)
                    "traffic table step failed (repeats muted until it works)")
            self._warned = True

    # ---- start check ----------------------------------------------------------------------

    def _loop(self, layout, graph, lap_arcs) -> tuple[frozenset, int]:
        return _edges(lap_arcs), blocks.loop_capacity(layout.route(graph, list(lap_arcs)), layout, self._held)

    def loop_full(self, lap_arcs, lives: Iterable) -> Optional[dict]:
        """D-517 3: ``TRIP_LOOP_FULL`` detail when one more repeat trip on this loop breaks N·h ≤ S − 1.

        A loop is the set of edges of one lap (the cycle via…, to), not the approach to it;
        repeat trips whose laps drive the same set share it. S counts the lap's blocks only.
        """
        active = self._store.active()
        layout = self._layout_for(active)
        if layout is None or not lap_arcs:
            return None
        edges, capacity = self._loop(layout, active[2], lap_arcs)
        robots = 1 + sum(1 for live in lives if live.open and live.repeat and _edges(live.lap_arcs) == edges)
        if robots <= capacity:
            return None
        return {"robots": robots, "capacity": capacity, "held_per_robot": self._held}

    # ---- the read-only view ---------------------------------------------------------------

    def _make_view(self, version, layout, graph, trips: dict, result, refused_unit: dict, robots, gaps) -> dict:
        state = self._state
        holders: dict[str, set] = {}
        unknown: dict[str, set] = {}
        occupied: dict[str, set] = {}
        for robot_id, held in state.held.items():
            for unit, _forward in held.values():
                holders.setdefault(unit, set()).add(robot_id)
        localized = {r for r, live in trips.items() if (live.view.get("pose") or {}).get("state") == LOCALIZED}
        for table in (state.last_occupied, state.pinned):
            for robot_id, units in table.items():
                for unit in units:
                    (occupied if robot_id in localized and table is state.last_occupied else unknown) \
                        .setdefault(unit, set()).add(robot_id)
        units = []
        for unit_id, unit in sorted(layout.units.items()):
            who = holders.get(unit_id, set()) | occupied.get(unit_id, set()) | unknown.get(unit_id, set())
            status = ("UNKNOWN" if unit_id in unknown else "OCCUPIED" if unit_id in occupied
                      else "GRANTED" if unit_id in holders else "FREE")
            units.append({"id": unit_id, "capacity": unit.capacity, "zone": unit.zone, "two_way": unit.two_way,
                          "state": status, "holders": sorted(who),
                          "waiting": sorted(r for r, u in refused_unit.items() if u == unit_id)})
        loops = {}
        for robot_id, live in trips.items():
            if live.repeat and live.lap_arcs:
                edges, capacity = self._loop(layout, graph, live.lap_arcs)
                loops.setdefault(edges, {"edges": sorted(edges), "capacity": capacity, "robots": []})["robots"] \
                    .append(robot_id)
        cycle = blocks.wait_cycle(result.waiting_for)
        at = {robot.id: robot for robot in robots}
        return {
            "map_version": version,
            "block_length_m": {edge: round(parts[0][2] - parts[0][1], 3)
                               for edge, parts in sorted(layout.edge_units.items())},
            "units": units,
            "robots": [{"robot_id": robot_id, "authority_end_m": _round(result.authority_end.get(robot_id)),
                        "front_d_m": _round(at[robot_id].d), "convoy": at[robot_id].convoy and {
                            "leader": at[robot_id].convoy, "follows": at[robot_id].follows,
                            "gap_m": gaps.get(robot_id)},
                        "waiting_for": list(result.waiting_for.get(robot_id, ())), "lap": live.view.get("lap"),
                        "trip_state": live.view["state"]} for robot_id, live in sorted(trips.items())],
            "loop_capacity": list(loops.values()),
            "wait_cycle": list(cycle) if cycle else None,
            "unplaced": list(result.unplaced),
        }


def _shift(state: blocks.TableState, robot_id: str, old_spans, shift: float) -> None:
    """A repeat trip dropped ``shift`` route metres of finished laps: its grants, shared grants and
    authority move with the route (span ``i`` becomes ``i - n``), so the same route id stays valid.
    Every other table is keyed by unit, not span index."""
    n = sum(1 for span in old_spans if span.d1 <= shift + 1e-6)
    held = state.held.get(robot_id)
    if held is not None:
        state.held[robot_id] = {i - n: grant for i, grant in held.items() if i >= n}
    shared = state.shared.get(robot_id)
    if shared is not None:  # span-indexed too: a stale index would let a shared unit pass (Safety-Review)
        state.shared[robot_id] = {i - n: member for i, member in shared.items() if i >= n}
    if robot_id in state.authority:
        if state.held.get(robot_id):
            state.authority[robot_id] -= shift
        else:  # every grant was in the dropped laps: no authority without a grant behind it
            del state.authority[robot_id]


def _front_on(graph, live, other, d: float, after: float, body: float) -> Optional[float]:
    """``other``'s front ``d`` (its route metres) in ``live``'s route metres: the first place past
    ``after`` where the arcs under its body come in the same order, or None (not on shared arcs)."""
    mine, theirs = _arcs(graph, live), _arcs(graph, other)
    i = max((k for k, (_arc, base) in enumerate(theirs) if base <= d), default=0)
    j = i
    while j > 0 and theirs[j][1] > d - body:
        j -= 1
    need = [arc for arc, _base in theirs[j:i + 1]]
    for k in range(i - j, len(mine)):
        front = mine[k][1] + d - theirs[i][1]
        if front > after and [arc for arc, _base in mine[k - (i - j):k + 1]] == need:
            return front
    return None


def _arcs(graph, live) -> list:
    """``(arc id, route metres where it starts)`` along a trip's plan."""
    out, base = [], 0.0
    for seg in live.segments:
        out.append((arc_id(seg), base))
        base += graph.arcs[arc_id(seg)].length_m
    return out


def _edges(arc_ids) -> frozenset:
    return frozenset(arc.rsplit(":", 1)[0] for arc in arc_ids)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 3)


def _empty(version) -> dict:
    return {"map_version": version, "block_length_m": {}, "units": [], "robots": [], "loop_capacity": [],
            "wait_cycle": None, "unplaced": [], "resolver": [], "signals": []}
