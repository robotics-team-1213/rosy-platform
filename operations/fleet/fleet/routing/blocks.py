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
    #: Grants are span occurrences of this route. Fleet sends a new route id (a new plan) only
    #: while the robot stands (D-517 4). What the robot held before keeps blocking others
    #: until it is localized on the new route.
    route_id: str = ""


@dataclass
class TableState:
    #: robot id -> {span index: (unit id, forward)} granted on its current route. The unit id is
    #: stored so a grant keeps blocking even in a tick where the robot is missing.
    held: dict[str, dict[int, tuple[str, bool]]] = field(default_factory=dict)
    route: dict[str, str] = field(default_factory=dict)
    #: robot id -> the last authority end issued on its route; it never goes down (D-517 4)
    authority: dict[str, float] = field(default_factory=dict)
    #: robot id -> tick its current unmet request started (for the merge wait bound)
    waiting_since: dict[str, float] = field(default_factory=dict)
    #: robot id -> {unit id: forward} its padded body last covered; blocks others while the
    #: robot is UNKNOWN or missing (D-426 3)
    last_occupied: dict[str, dict[str, bool]] = field(default_factory=dict)
    #: robot id -> {unit id: forward} kept from before a route change until it is localized
    pinned: dict[str, dict[str, bool]] = field(default_factory=dict)


@dataclass(frozen=True)
class TickResult:
    #: robot id -> route metres its front may reach: the end of its contiguous grants minus u,
    #: so a front that is really u ahead of its estimate still stays inside them, and never
    #: below an earlier value. It may be behind the estimate: the robot stands. A robot
    #: without a localized pose gets no entry: no new authority, it stops on expiry (D-517 4).
    authority_end: dict[str, float]
    #: robot id -> every robot blocking the unit it needs next (empty: not waiting on a robot)
    waiting_for: dict[str, tuple[str, ...]]
    conflicts: tuple[str, ...]        # units granted to more robots than capacity (must stay empty)


def _occupied(robot: Robot) -> set[int]:
    rear, front = robot.d - robot.body_length_m - robot.uncertainty_m, robot.d + robot.uncertainty_m
    return {i for i, s in enumerate(robot.spans) if s.d1 > rear and s.d0 < front}


def step(layout: Layout, robots: Sequence[Robot], state: TableState, now: float, *,
         merge_max_wait_s: float = 20.0) -> TickResult:
    """One Fleet tick: occupancy, release, grants in fair order, authority ends.

    1. A robot's grants and last padded body keep blocking others whether or not it is in
       ``robots`` this tick; only ``release_robot`` (evidence it left the lanes) drops them.
    2. A localized robot first gets the unit under its estimated front unless another robot
       holds a grant there, its unpadded estimated body is there, or its pose is unknown and
       its last body was there. Padding alone does not refuse it, so robots queued nose to
       tail never block each other by padding; the front robot moves first.
    3. Then grants in order: robots that waited past ``merge_max_wait_s``, robots inside a
       zone, wait start, id. Grants are contiguous from the front; only grants extend a
       robot's own authority, padding only blocks others.
    """
    for robot in robots:
        if state.route.get(robot.id, robot.route_id) != robot.route_id:
            kept = dict(state.last_occupied.get(robot.id, {}))
            kept.update({u: f for u, f in state.held.get(robot.id, {}).values()})
            state.pinned[robot.id] = kept
            for table in (state.held, state.authority, state.last_occupied):
                table.pop(robot.id, None)
        state.route[robot.id] = robot.route_id
    occupied: dict[str, set[int]] = {}
    for robot in robots:
        if robot.d is None:
            continue
        occupied[robot.id] = _occupied(robot)
        state.last_occupied[robot.id] = {robot.spans[i].unit: robot.spans[i].forward for i in occupied[robot.id]}
        state.pinned.pop(robot.id, None)
    # Release grants a localized robot is fully past; never while UNKNOWN or missing.
    for robot in robots:
        held = state.held.setdefault(robot.id, {})
        if robot.d is not None:
            rear = robot.d - robot.body_length_m - robot.uncertainty_m
            for i in [i for i in held if robot.spans[i].d1 <= rear and i not in occupied[robot.id]]:
                del held[i]

    granted: dict[str, set[str]] = {}
    blocking: dict[str, set[str]] = {}
    direction: dict[str, bool] = {}

    def add_grant(robot_id: str, unit: str, forward: bool) -> None:
        granted.setdefault(unit, set()).add(robot_id)
        blocking.setdefault(unit, set()).add(robot_id)
        if layout.units[unit].two_way:
            direction[unit] = forward

    for robot_id, held in state.held.items():
        for unit, forward in held.values():
            add_grant(robot_id, unit, forward)
    for table in (state.last_occupied, state.pinned):
        for robot_id, units in table.items():
            for unit, forward in units.items():
                blocking.setdefault(unit, set()).add(robot_id)
                if layout.units[unit].two_way:
                    direction.setdefault(unit, forward)

    def free_for(robot: Robot, span: Span, by: Mapping[str, set[str]]) -> tuple[bool, tuple[str, ...]]:
        unit = layout.units[span.unit]
        others = by.get(span.unit, set()) - {robot.id}
        locked = unit.two_way and span.unit in direction and direction[span.unit] != span.forward \
            and bool(blocking.get(span.unit, set()) - {robot.id})
        return len(others) < unit.capacity and not locked, tuple(sorted(others))

    def grant(robot: Robot, index: int) -> None:
        span = robot.spans[index]
        state.held[robot.id][index] = (span.unit, span.forward)
        add_grant(robot.id, span.unit, span.forward)

    # 2. the unit under each localized front, against grants and real (unpadded) bodies
    present: dict[str, set[str]] = {u: set(rs) for u, rs in granted.items()}
    localized = {robot.id for robot in robots if robot.d is not None}
    for robot in robots:
        if robot.d is not None:
            for s in robot.spans:
                if s.d1 > robot.d - robot.body_length_m and s.d0 < robot.d:
                    present.setdefault(s.unit, set()).add(robot.id)
    for table in (state.last_occupied, state.pinned):
        for robot_id, units in table.items():
            if robot_id not in localized:
                for unit in units:
                    present.setdefault(unit, set()).add(robot_id)
    for robot in sorted(robots, key=lambda r: r.id):
        if robot.d is None:
            continue
        front = next((i for i, s in enumerate(robot.spans) if s.d0 <= robot.d < s.d1), None)
        if front is not None and front not in state.held[robot.id] and free_for(robot, robot.spans[front], present)[0]:
            grant(robot, front)
            present.setdefault(robot.spans[front].unit, set()).add(robot.id)

    def inside_zone(robot: Robot) -> bool:
        return any(layout.units[robot.spans[i].unit].zone for i in occupied.get(robot.id, ()))

    def key(robot: Robot):
        since = state.waiting_since.get(robot.id, now)
        return (now - since < merge_max_wait_s, not inside_zone(robot), since, robot.id)

    # 3. fair-order grants and authority
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
                ok, others = free_for(robot, span, blocking)
                if not ok:
                    blockers = others
                    break
                grant(robot, index)
            end = span.d1
        if end is None:  # past the end of its route
            end = robot.spans[-1].d1
        # Grant-backed only: an estimate already past its grants never becomes authority (the
        # robot then stands), and an earlier value stays because its grants are still held.
        issued = max(end - robot.uncertainty_m, state.authority.get(robot.id, -math.inf))
        state.authority[robot.id] = issued
        authority[robot.id] = issued
        if end >= want or end >= robot.spans[-1].d1:
            state.waiting_since.pop(robot.id, None)
        else:
            waiting_for[robot.id] = blockers
            state.waiting_since.setdefault(robot.id, now)
    conflicts = tuple(sorted(u for u, rs in granted.items() if len(rs) > layout.units[u].capacity))
    return TickResult(authority, waiting_for, conflicts)


def release_robot(state: TableState, robot_id: str) -> None:
    """Drop every hold of a robot that evidence shows is off the lanes (operator, D-517 6)."""
    for table in (state.held, state.route, state.authority, state.waiting_since, state.last_occupied,
                  state.pinned):
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
