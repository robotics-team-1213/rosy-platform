"""Fixed-block traffic layout builder and data types (D-517 3 M0)."""

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
    entry: str = ""                   # the arc driven into this span ("" when the route starts in it)


@dataclass(frozen=True)
class Layout:
    units: Mapping[str, Unit]
    #: edge id -> ((unit id, s_from, s_to), ...) in the edge's own forward metres
    edge_units: Mapping[str, tuple[tuple[str, float, float], ...]]

    def route(self, graph: Graph, arc_ids: Sequence[str]) -> tuple[Span, ...]:
        """Unit spans along ``arc_ids`` driven in order; neighbouring spans of one unit merge."""
        spans: list[Span] = []
        base = 0.0
        for k, arc_id in enumerate(arc_ids):
            arc = graph.arcs[arc_id]
            length = arc.length_m
            parts = self.edge_units[arc.edge_id]
            if not arc.forward:
                parts = tuple((u, length - s1, length - s0) for u, s0, s1 in reversed(parts))
            for unit, s0, s1 in parts:
                if spans and spans[-1].unit == unit:
                    spans[-1] = Span(unit, spans[-1].d0, base + s1, arc.forward, spans[-1].entry)
                else:
                    spans.append(Span(unit, base + s0, base + s1, arc.forward,
                                      arc_ids[k - 1] if k and s0 == 0.0 else ""))
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
    #: so a front that is really u ahead of its estimate still stays inside them (and
    #: ``ZONE_STOP_CLEARANCE_M`` more where an ungranted zone begins there), and never
    #: below an earlier value. It may be behind the estimate: the robot stands. A robot
    #: without a localized pose gets no entry: no new authority, it stops on expiry (D-517 4).
    authority_end: dict[str, float]
    #: robot id -> every robot blocking the unit it needs next (empty: not waiting on a robot)
    waiting_for: dict[str, tuple[str, ...]]
    conflicts: tuple[str, ...]        # units granted to more robots than capacity (must stay empty)
    #: robots with no position ever (never localized, nothing held): nobody gets a new grant
    #: while one exists, since its body could be anywhere. A trip starts only LOCALIZED (D-494).
    unplaced: tuple[str, ...] = ()
    #: D-525: units someone holds, or a robot not localized this tick (UNKNOWN or missing) last
    #: covered or pinned. A signal turns the next approach green only while its zone is not here.
    #: A localized robot's padding is left out; one waiting at the line stops ``ZONE_STOP_CLEARANCE_M``
    #: clear of it anyway.
    busy: frozenset[str] = frozenset()
