"""D-517 3 (M0): fixed-block traffic arithmetic for several robots on one site map.

Pure: no network, clock, or robot calls. Fleet (M1) feeds it map poses and sends nothing yet.

- A *unit* is what one grant holds: a plain block (capacity 1) or a zone (a junction, or a
  two-way lane with a direction lock) with its own capacity.
- A robot's position is its front's distance ``d`` along its own route (a list of arcs). Its
  route is cut into unit spans, so occupancy and authority are interval questions.
- Occupancy is a fact: every unit the body (front ``d``, length ``L``) ± ``u`` touches.
  Grants never shrink (D-517 4): a granted unit stays held until the robot is past it.
- D-517 9 M3 convoy: a follower ``follows`` the localized convoy member right ahead (moving block):
  its authority ends at that member's rear − (d_stop + 2u + u_ahead), and only that member's units
  may be granted to it as well. Without it (member unknown, off the shared arcs, trip ended) the
  follower is back on fixed blocks, and a shared grant ends its authority while the member holds it.
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
    #: D-517 9 M3: its convoy's leader (followers only); such a robot never re-sends an end smaller
    #: than one it had: it gets none and stops on expiry (D-517 4).
    convoy: Optional[str] = None
    #: the convoy member it follows this tick (moving block) and the end that member's rear allows
    follows: Optional[str] = None
    follow_end: float = math.inf
    #: CORE line follow is not plain following (a D-407 stuck or a RECOVERING state such as a D-468
    #: retrace): it may reverse, so nobody follows it on a moving block (Safety-Review).
    recovering: bool = False


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
    #: robot id -> {span index: convoy member ahead} for its grants of units that member held too
    shared: dict[str, dict[int, str]] = field(default_factory=dict)


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
    #: robots with no position ever (never localized, nothing held): nobody gets a new grant
    #: while one exists, since its body could be anywhere. A trip starts only LOCALIZED (D-494).
    unplaced: tuple[str, ...] = ()


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
            for table in (state.held, state.authority, state.last_occupied, state.shared):
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
                state.shared.get(robot.id, {}).pop(i, None)

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

    def free_for(robot: Robot, span: Span, by: Mapping[str, set[str]]) -> tuple[bool, tuple[str, ...], Optional[str]]:
        """``(free, blockers, via)``; ``via``: the convoy member it follows, whose unit it may share where
        the span reaches past the moving-block end (right behind that member, the same occurrence)."""
        unit = layout.units[span.unit]
        others = by.get(span.unit, set()) - {robot.id}
        # Only a capacity-1 unit is shared: in a zone of capacity c the pair counts as two, never c + 1.
        via = (robot.follows if unit.capacity == 1 and robot.follows in others and span.d1 > robot.follow_end
               else None)
        others = others - {via}
        locked = unit.two_way and span.unit in direction and direction[span.unit] != span.forward \
            and bool(blocking.get(span.unit, set()) - {robot.id, via})
        return len(others) < unit.capacity and not locked, tuple(sorted(others)), via

    def grant(robot: Robot, index: int, via: Optional[str]) -> None:
        span = robot.spans[index]
        state.held[robot.id][index] = (span.unit, span.forward)
        if via is not None:
            state.shared.setdefault(robot.id, {})[index] = via
        add_grant(robot.id, span.unit, span.forward)

    unplaced = tuple(sorted(r.id for r in robots if r.d is None and not state.held.get(r.id)
                            and r.id not in state.last_occupied and r.id not in state.pinned))
    if unplaced:
        authority = {r.id: state.authority[r.id] for r in robots if r.d is not None and r.id in state.authority}
        return TickResult(authority, {r.id: () for r in robots}, _conflicts(layout, granted, state), unplaced)

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
        ok, _others, via = (False, (), None) if front is None or front in state.held[robot.id] \
            else free_for(robot, robot.spans[front], present)
        if ok:
            grant(robot, front, via)
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
        full_want = robot.d + robot.uncertainty_m + robot.lookahead_m
        want = min(full_want, robot.follow_end + robot.uncertainty_m)  # nothing past the member it follows
        shared = state.shared.get(robot.id, {})
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
                ok, others, via = free_for(robot, span, blocking)
                if not ok:
                    blockers = others
                    break
                grant(robot, index, via)
            elif index in shared and shared[index] != robot.follows and shared[index] in blocking.get(span.unit, ()):
                blockers = (shared[index],)  # shared with a member it no longer follows: fixed blocks end here
                break
            end = span.d1
        if end is None:  # past the end of its route
            end = robot.spans[-1].d1
        # Grant-backed only: an estimate already past its grants never becomes authority (the
        # robot then stands), and an earlier value stays because its grants are still held.
        issued, last = min(end - robot.uncertainty_m, robot.follow_end), state.authority.get(robot.id, -math.inf)
        if end >= want or end >= robot.spans[-1].d1:
            state.waiting_since.pop(robot.id, None)
            if want < full_want:  # standing back behind the member it follows
                waiting_for[robot.id] = (robot.follows,)
        else:
            waiting_for[robot.id] = blockers
            state.waiting_since.setdefault(robot.id, now)
        if robot.convoy is not None and issued < last:  # D-517 4: no smaller end; it stops on expiry
            waiting_for[robot.id] = waiting_for[robot.id] or (robot.follows or robot.convoy,)
            continue
        state.authority[robot.id] = authority[robot.id] = max(issued, last)
    return TickResult(authority, waiting_for, _conflicts(layout, granted, state))


def _conflicts(layout: Layout, granted: Mapping[str, set[str]], state: TableState) -> tuple[str, ...]:
    """Units granted past capacity; a follower sharing a capacity-1 unit with the member it follows counts once."""
    def paired(robot_id: str, unit: str, holders: set[str]) -> bool:
        held = state.held.get(robot_id, {})
        return any(i in held and held[i][0] == unit and member in holders
                   for i, member in state.shared.get(robot_id, {}).items())

    def count(unit: str, holders: set[str]) -> int:
        return len({r for r in holders if layout.units[unit].capacity > 1 or not paired(r, unit, holders)})
    return tuple(sorted(u for u, rs in granted.items() if count(u, rs) > layout.units[u].capacity))


def follow(robot: Robot, members: Iterable[Robot], front_of: Callable[[Robot, float], Optional[float]],
           stop_m: float) -> Optional[float]:
    """D-517 9 M3: set ``robot.follows``/``follow_end`` from the nearest localized convoy member ahead
    and return that member's front (None: fixed blocks only).

    ``front_of(member, after)`` is that member's front in ``robot``'s route metres: the first place
    past ``after`` on the same arcs, or None. ``after`` lies a body and both u behind ``robot``'s
    front, so estimate noise between close robots never turns the member right ahead into one a lap
    away (the robot then stands). The gap is ``stop_m`` (d_stop(v), plus any reverse travel the caller
    bounds) + 2u + the member's u. A nearest member that is ``recovering`` is not followed: fixed blocks.
    """
    robot.follows, robot.follow_end = None, math.inf
    if robot.d is None:
        return None
    best = None
    for member in members:
        if member.d is None or member.id == robot.id:
            continue
        front = front_of(member, robot.d - robot.body_length_m - robot.uncertainty_m - member.uncertainty_m)
        if front is not None and (best is None or front < best[0]):
            best = (front, member)
    if best is None:
        return None
    front, member = best
    if member.recovering:
        return None
    robot.follows = member.id
    robot.follow_end = front - member.body_length_m - (stop_m + 2 * robot.uncertainty_m + member.uncertainty_m)
    return front


def release_robot(state: TableState, robot_id: str) -> None:
    """Drop every hold of a robot that evidence shows is off the lanes (operator, D-517 6)."""
    for table in (state.held, state.route, state.authority, state.waiting_since, state.last_occupied,
                  state.pinned, state.shared):
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
