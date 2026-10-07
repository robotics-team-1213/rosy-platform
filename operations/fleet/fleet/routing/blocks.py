"""D-517 3 (M0): fixed-block traffic arithmetic for several robots on one site map.

Pure: no network, clock, or robot calls. Fleet (M1) feeds it map poses and sends nothing yet.

- A *unit* is what one grant holds: a plain block (capacity 1) or a zone (a junction, or a
  two-way lane with a direction lock) with its own capacity.
- A robot's position is its front's distance ``d`` along its own route (a list of arcs). Its
  route is cut into unit spans, so occupancy and authority are interval questions.
- Occupancy is a fact: every unit the body (front ``d``, length ``L``) ± ``u`` touches.
  Grants never shrink (D-517 4): a granted unit stays held until the robot is past it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Sequence

from fleet.routing.graph import Graph


@dataclass(frozen=True)
class BlockRules:
    """D-517 3: ``ℓ ≥ L + max(d_stop(v) + 2u, horizon + margin)``. Every input is measured."""

    body_length_m: float              # the longest registered body on the site (D-424)
    uncertainty_m: float              # u: sighting floor + bridged odom drift (D-517 3)
    stop_gap: Callable[[float], float]  # d_stop(v), D-422/D-500 (RobotBody.stop_gap_m + hysteresis)
    horizon_m: float = 0.40           # CORE line_follow obstacle_path_horizon_m
    horizon_margin_m: float = 0.05

    def block_length(self, speed_mps: float) -> float:
        gap = max(self.stop_gap(speed_mps) + 2 * self.uncertainty_m, self.horizon_m + self.horizon_margin_m)
        return self.body_length_m + gap


@dataclass(frozen=True)
class Unit:
    id: str
    capacity: int = 1
    two_way: bool = False             # direction lock: holders must all travel the same way
    zone: bool = False                # a junction zone or a two-way lane (priority inside, D-517 3)


@dataclass(frozen=True)
class Span:
    """One unit along one route: ``[d0, d1)`` in route metres, travelled ``forward`` on its edge."""

    unit: str
    d0: float
    d1: float
    forward: bool = True


@dataclass(frozen=True)
class Layout:
    units: Mapping[str, Unit]
    #: edge id -> ((unit id, s_from, s_to), ...) in the edge's own forward metres
    edge_units: Mapping[str, tuple[tuple[str, float, float], ...]]

    def route(self, graph: Graph, arc_ids: Sequence[str]) -> tuple[Span, ...]:
        """Unit spans along ``arc_ids`` driven in order; neighbouring spans of one unit merge."""
        spans: list[Span] = []
        base = 0.0
        for arc_id in arc_ids:
            arc = graph.arcs[arc_id]
            length = arc.length_m
            parts = self.edge_units[arc.edge_id]
            if not arc.forward:
                parts = tuple((u, length - s1, length - s0) for u, s0, s1 in reversed(parts))
            for unit, s0, s1 in parts:
                if spans and spans[-1].unit == unit:
                    spans[-1] = Span(unit, spans[-1].d0, base + s1, arc.forward)
                else:
                    spans.append(Span(unit, base + s0, base + s1, arc.forward))
            base += length
        return tuple(spans)


def build_layout(graph: Graph, rules: BlockRules, zones: Mapping[str, tuple[Iterable[str], int]] = ()) -> Layout:
    """Cut every edge into blocks of at least ``rules.block_length(speed cap)``.

    ``zones`` maps a zone id to ``(edge ids, capacity)``. A zone edge is one span of its zone. A
    two-way edge outside any zone becomes its own direction-locked zone of capacity 1 (D-517 3).
    """
    zones = dict(zones)
    zone_of = {edge: zone for zone, (edges, _cap) in zones.items() for edge in edges}
    units: dict[str, Unit] = {zone: Unit(zone, int(cap), zone=True) for zone, (_edges, cap) in zones.items()}
    by_edge: dict[str, list] = {}
    two_way = {arc.edge_id for arc in graph.arcs.values() if not arc.forward}
    for arc in sorted(graph.arcs.values(), key=lambda a: a.id):
        if not arc.forward:
            continue
        edge, length = arc.edge_id, arc.length_m
        if edge in zone_of:
            by_edge[edge] = [(zone_of[edge], 0.0, length)]
        elif edge in two_way:
            unit = f"lane:{edge}"
            units[unit] = Unit(unit, 1, two_way=True, zone=True)
            by_edge[edge] = [(unit, 0.0, length)]
        else:
            count = max(1, math.floor(length / rules.block_length(arc.speed_cap_mps)))
            step = length / count
            by_edge[edge] = []
            for index in range(count):
                unit = f"{edge}#{index}"
                units[unit] = Unit(unit)
                by_edge[edge].append((unit, index * step, (index + 1) * step))
    return Layout(units, {edge: tuple(parts) for edge, parts in by_edge.items()})


@dataclass
class Robot:
    """One trip robot as the table sees it this tick."""

    id: str
    spans: tuple[Span, ...]           # its route cut into units (a lap repeats them)
    d: Optional[float]                # front position along the route; None = pose not LOCALIZED
    lookahead_m: float                # authority must reach this far past the front (d_stop(v))
    uncertainty_m: float
    body_length_m: float
    #: Holds are span occurrences of this route. A new route id (a new plan) starts from what
    #: the body covers; Fleet sends one only while the robot stands (D-517 4: no shrink).
    route_id: str = ""


@dataclass
class TableState:
    #: robot id -> span indices granted to it, per occurrence along its route. Only grants
    #: extend a robot's own authority; occupancy (with its ±u pad) only blocks others.
    held: dict[str, set[int]] = field(default_factory=dict)
    route: dict[str, str] = field(default_factory=dict)
    #: robot id -> the last authority end issued on its route; it never goes down (D-517 4)
    authority: dict[str, float] = field(default_factory=dict)
    #: robot id -> tick its current unmet request started (for the merge wait bound)
    waiting_since: dict[str, float] = field(default_factory=dict)
    #: robot id -> last occupancy, kept while its pose is UNKNOWN (D-426 3)
    last_occupied: dict[str, set[int]] = field(default_factory=dict)


@dataclass(frozen=True)
class TickResult:
    #: robot id -> route metres its front may reach: the last granted unit's end minus u, so a
    #: front that is really u ahead of its estimate still stays inside its grants, and never
    #: below an earlier value. It may be behind the estimate: the robot stands. A robot without a localized pose gets no entry: no new
    #: authority, it stops on expiry (D-517 4).
    authority_end: dict[str, float]
    #: robot id -> every robot holding the unit it needs next (empty: not waiting on a robot)
    waiting_for: dict[str, tuple[str, ...]]
    conflicts: tuple[str, ...]        # units granted to more robots than capacity (must stay empty)


def _occupied(robot: Robot) -> set[int]:
    rear, front = robot.d - robot.body_length_m - robot.uncertainty_m, robot.d + robot.uncertainty_m
    return {i for i, s in enumerate(robot.spans) if s.d1 > rear and s.d0 < front}


def step(layout: Layout, robots: Sequence[Robot], state: TableState, now: float, *,
         merge_max_wait_s: float = 20.0) -> TickResult:
    """One Fleet tick: occupancy, release, grants in fair order, authority ends.

    Order: robots that waited past ``merge_max_wait_s`` first, then robots already inside a
    zone, then by wait start, then id. Grants are contiguous from the front: a refused unit
    stops the robot there. Holds a robot already has count past its lookahead too, so the
    authority covers every unit it was given. A robot that leaves the list keeps its holds
    until Fleet drops it with evidence (``release_robot``).
    """
    for robot in robots:
        if state.route.get(robot.id) != robot.route_id:
            state.route[robot.id] = robot.route_id
            for table in (state.held, state.authority, state.last_occupied):
                table.pop(robot.id, None)
    occupied: dict[str, set[int]] = {}
    for robot in robots:
        if robot.d is None:
            occupied[robot.id] = set(state.last_occupied.get(robot.id, ()))
        else:
            occupied[robot.id] = _occupied(robot)
            state.last_occupied[robot.id] = occupied[robot.id]
    spans_of = {robot.id: robot.spans for robot in robots}
    # Release what a localized robot is fully past; never release while UNKNOWN.
    for robot in robots:
        held = state.held.setdefault(robot.id, set())
        if robot.d is not None:
            rear = robot.d - robot.body_length_m - robot.uncertainty_m
            held -= {i for i in held if robot.spans[i].d1 <= rear and i not in occupied[robot.id]}
    # Who blocks a unit: its grantees and anyone whose padded body touches it.
    holders: dict[str, set[str]] = {}
    granted: dict[str, set[str]] = {}
    direction: dict[str, bool] = {}
    for robot_id, held in state.held.items():
        spans = spans_of.get(robot_id)
        if spans is None:
            continue
        for i in held:
            unit = spans[i].unit
            granted.setdefault(unit, set()).add(robot_id)
            holders.setdefault(unit, set()).add(robot_id)
            if layout.units[unit].two_way:
                direction[unit] = spans[i].forward
        for i in occupied.get(robot_id, ()):
            holders.setdefault(spans[i].unit, set()).add(robot_id)
    conflicts = tuple(sorted(u for u, rs in granted.items() if len(rs) > layout.units[u].capacity))

    def inside_zone(robot: Robot) -> bool:
        return any(layout.units[robot.spans[i].unit].zone for i in occupied[robot.id])

    def key(robot: Robot):
        since = state.waiting_since.get(robot.id, now)
        return (now - since < merge_max_wait_s, not inside_zone(robot), since, robot.id)

    authority: dict[str, float] = {}
    waiting_for: dict[str, tuple[str, ...]] = {}
    for robot in sorted(robots, key=key):
        held = state.held[robot.id]
        waiting_for[robot.id] = ()
        if robot.d is None:  # no new grant without a localized pose; it stops on expiry
            continue
        want = robot.d + robot.uncertainty_m + robot.lookahead_m
        # Coverage starts where the unit under the front starts, not at the estimate: a robot
        # whose own unit is not granted has no authority past that unit's start.
        end, blockers = None, ()
        for index, span in enumerate(robot.spans):
            if span.d1 <= robot.d:
                continue
            if end is None:
                end = span.d0
            if index not in held:
                if end >= want:
                    break
                unit = layout.units[span.unit]
                others = holders.get(span.unit, set()) - {robot.id}
                locked = unit.two_way and span.unit in direction and direction[span.unit] != span.forward
                if len(others) >= unit.capacity or locked:
                    blockers = tuple(sorted(others))
                    break
                held.add(index)
                holders.setdefault(span.unit, set()).add(robot.id)
                if unit.two_way:
                    direction[span.unit] = span.forward
            end = span.d1
        # Grant-backed only: an estimate already past its grants never becomes authority (the
        # robot then stands), and an earlier value stays because its grants are still held.
        if end is None:  # past the end of its route
            end = robot.spans[-1].d1
        issued = max(end - robot.uncertainty_m, state.authority.get(robot.id, -math.inf))
        state.authority[robot.id] = issued
        authority[robot.id] = issued
        if end >= want or end >= robot.spans[-1].d1:
            state.waiting_since.pop(robot.id, None)
        else:
            waiting_for[robot.id] = blockers
            state.waiting_since.setdefault(robot.id, now)
    return TickResult(authority, waiting_for, conflicts)


def release_robot(state: TableState, robot_id: str) -> None:
    """Drop every hold of a robot that evidence shows is off the lanes (operator, D-517 6)."""
    for table in (state.held, state.route, state.authority, state.waiting_since, state.last_occupied):
        table.pop(robot_id, None)


def loop_capacity(spans: Sequence[Span], layout: Layout, held_per_robot: int) -> int:
    """D-517 3: robots N on a one-way cycle need ``N·h ≤ S − 1``; S counts a zone by its capacity."""
    units = {s.unit for s in spans}
    slots = sum(layout.units[u].capacity for u in units)
    return max(0, (slots - 1) // max(1, held_per_robot))


def wait_cycle(waiting_for: Mapping[str, Sequence[str]]) -> Optional[tuple[str, ...]]:
    """A cycle in "robot waits for robot", or None. Linear in robots plus wait edges.

    Waiting on any holder counts, so a cycle may be reported where one holder would leave on
    its own; that escalates to the resolver (D-517 5), which is the safe side.
    """
    colour: dict[str, int] = {}
    for start in sorted(waiting_for):
        if colour.get(start):
            continue
        colour[start] = 1
        path = [start]
        stack = [iter(sorted(waiting_for.get(start, ())))]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                colour[path.pop()] = 2
                stack.pop()
            elif colour.get(nxt) == 1:
                return tuple(path[path.index(nxt):])
            elif not colour.get(nxt):
                colour[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(waiting_for.get(nxt, ()))))
    return None
