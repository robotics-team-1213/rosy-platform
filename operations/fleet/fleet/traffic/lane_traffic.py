"""D-517 3 (M1): the Fleet block table over every open trip — computed and shown, never sent.

Each trip period ``TripRunner`` hands its trips here. The active map's ``Layout`` is cut once per
map version (zones from site config ``fleet.traffic.zones``; a two-way lane becomes a
direction-locked zone by itself), each trip robot becomes a ``blocks.Robot`` and
``blocks.step`` runs. No authority goes to a robot (that is M2, safety-reviewed); the trip loop
only holds back a junction instruction into a refused block (``holds``).

D-517 6: a robot whose trip ended, or whose trip is on another map version, keeps its last
grants and body as ``pinned`` units until a fresh ``LOCALIZED`` pose shows it clear of them
(the pose's units replace the pins); a map activation re-pins every robot from its last pose.

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
from fleet.traffic import blocks
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


class TrafficService:
    def __init__(self, store, config: TripConfig = TripConfig(), *,
                 zones: Optional[Mapping[str, tuple[Iterable[str], int]]] = None,
                 body=PINKY_PRO, held_per_robot: int = HELD_PER_ROBOT, clock=time.time) -> None:
        self._store, self._config, self._zones = store, config, dict(zones or {})
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
        seen = self._seen.get(robot_id)
        if seen is not None and seen[0] == route_id and live.trim_m > seen[1]:
            _shift(self._state, robot_id, seen[2], live.trim_m - seen[1])
        self._seen[robot_id] = (route_id, live.trim_m, spans)
        line = getattr(live, "junction", None) or {}  # this period's CORE line-follow read (lane segments)
        return blocks.Robot(robot_id, spans, d, lookahead, u, self._length, route_id=route_id,
                            convoy=getattr(live, "convoy", None), recovering=line.get("line_recovering") is True)

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
        result = blocks.step(layout, robots, self._state, self._clock())
        refused_unit: dict[str, str] = {}
        for robot in robots:
            live, waiting = trips[robot.id], result.waiting_for.get(robot.id, ())
            used = {"front_d_m": robot.d, "pose_stamp": None if robot.d is None else live.at_stamp}  # D-517 4
            if result.unplaced:  # a robot never localized could be anywhere: no instruction for anyone
                live.traffic = {"waiting_for": [r for r in result.unplaced if r != robot.id],
                                "authority_end_m": result.authority_end.get(robot.id), "refused_at_m": 0.0, **used}
                continue
            refused = None
            if waiting and robot.d is not None:
                held = self._state.held.get(robot.id, {})
                index = next((i for i, span in enumerate(robot.spans) if span.d1 > robot.d and i not in held), None)
                if index is not None:
                    refused_unit[robot.id] = robot.spans[index].unit
                    refused = robot.spans[index].d0 - live.segments[0]["s_from"]  # back to plan metres
            live.traffic = {"waiting_for": list(waiting), "authority_end_m": result.authority_end.get(robot.id),
                            "refused_at_m": refused, **used}
        self._view = self._make_view(active[0], layout, active[2], trips, result, refused_unit, robots, gaps)

    def view(self) -> dict:
        return self._view

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
            "wait_cycle": None, "unplaced": []}
