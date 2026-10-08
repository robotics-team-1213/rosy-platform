"""D-517 3 (M1): the Fleet block table over every open trip — computed and shown, never sent.

Each trip period ``TripRunner`` hands its trips here. The active map's ``Layout`` is cut once per
map version (zones from site config ``fleet.traffic.zones``; a two-way lane becomes a
direction-locked zone by itself), each trip robot becomes a ``blocks.Robot`` and
``blocks.step`` runs. No authority goes to a robot (that is M2, safety-reviewed); the trip loop
only holds back a junction instruction into a refused block (``trip_runner._traffic_holds``).

D-517 6: a robot whose trip ended, or whose trip is on another map version, keeps its last
grants and body as ``pinned`` units until a fresh ``LOCALIZED`` pose shows it clear of them
(the pose's units replace the pins); a map activation re-pins every robot from its last pose.
"""

from __future__ import annotations

import math
import time
from typing import Iterable, Mapping, Optional

from core_common.robot_body import PINKY_PRO, RobotBody
from fleet.localization.map_pose import MapPoseConfig
from fleet.routing import blocks
from fleet.routing.execute import arc_id
from fleet.server.trip_ports import ODOM_DRIFT_PER_M, TripConfig, pose_view

LOCALIZED = "LOCALIZED"
#: D-517 3: blocks one robot holds at worst (occupancy 2 + one grant ahead on the demo blocks).
HELD_PER_ROBOT = 3
#: Before its junction instruction goes out a robot asks for the block just past the place.
PAST_PLACE_M = 0.05


class TrafficService:
    def __init__(self, store, config: TripConfig = TripConfig(), *,
                 zones: Optional[Mapping[str, tuple[Iterable[str], int]]] = None,
                 body: RobotBody = PINKY_PRO, held_per_robot: int = HELD_PER_ROBOT, clock=time.time) -> None:
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
            d = segments[0]["s_from"] + live.progress(index, s)  # route metres: the first arc from 0
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
        return blocks.Robot(robot_id, spans, d, lookahead, u, self._length, route_id=route_id)

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
        for robot_id in [r for r in state.pinned if r not in trips and r in fresh]:
            units = self._under(layout, active[2], fresh[robot_id])  # where it is now replaces the pins
            if units:
                state.pinned[robot_id] = units
            else:
                blocks.release_robot(state, robot_id)
        robots = [self._robot(layout, active[2], live) for live in trips.values()]
        result = blocks.step(layout, robots, self._state, self._clock())
        refused_unit: dict[str, str] = {}
        for robot in robots:
            live, waiting = trips[robot.id], result.waiting_for.get(robot.id, ())
            if result.unplaced:  # a robot never localized could be anywhere: no instruction for anyone
                live.traffic = {"waiting_for": [r for r in result.unplaced if r != robot.id],
                                "authority_end_m": result.authority_end.get(robot.id), "refused_at_m": 0.0}
                continue
            refused = None
            if waiting and robot.d is not None:
                held = self._state.held.get(robot.id, {})
                index = next((i for i, span in enumerate(robot.spans) if span.d1 > robot.d and i not in held), None)
                if index is not None:
                    refused_unit[robot.id] = robot.spans[index].unit
                    refused = robot.spans[index].d0 - live.segments[0]["s_from"]  # back to plan metres
            live.traffic = {"waiting_for": list(waiting), "authority_end_m": result.authority_end.get(robot.id),
                            "refused_at_m": refused}
        self._view = self._make_view(active[0], layout, active[2], trips, result, refused_unit)

    def view(self) -> dict:
        return self._view

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

    def _make_view(self, version, layout, graph, trips: dict, result, refused_unit: dict) -> dict:
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
        return {
            "map_version": version,
            "block_length_m": {edge: round(parts[0][2] - parts[0][1], 3)
                               for edge, parts in sorted(layout.edge_units.items())},
            "units": units,
            "robots": [{"robot_id": robot_id, "authority_end_m": _round(result.authority_end.get(robot_id)),
                        "waiting_for": list(result.waiting_for.get(robot_id, ())), "lap": live.view.get("lap"),
                        "trip_state": live.view["state"]} for robot_id, live in sorted(trips.items())],
            "loop_capacity": list(loops.values()),
            "wait_cycle": list(cycle) if cycle else None,
            "unplaced": list(result.unplaced),
        }


def _shift(state: blocks.TableState, robot_id: str, old_spans, shift: float) -> None:
    """A repeat trip dropped ``shift`` route metres of finished laps: its grants and authority move
    with the route (span ``i`` becomes ``i - n``), so the same route id stays valid."""
    n = sum(1 for span in old_spans if span.d1 <= shift + 1e-6)
    held = state.held.get(robot_id)
    if held is not None:
        state.held[robot_id] = {i - n: grant for i, grant in held.items() if i >= n}
    if robot_id in state.authority:
        state.authority[robot_id] -= shift


def _edges(arc_ids) -> frozenset:
    return frozenset(arc.rsplit(":", 1)[0] for arc in arc_ids)


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 3)


def _empty(version) -> dict:
    return {"map_version": version, "block_length_m": {}, "units": [], "robots": [], "loop_capacity": [],
            "wait_cycle": None, "unplaced": []}
