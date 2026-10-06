"""D-490 1·2: the active site map as directed lanes (arcs).

A ``one_way`` edge is one arc, a ``two_way`` edge two opposite arcs with the same
``edge_id``. Arc ids are ``<edge_id>:fwd`` / ``<edge_id>:rev`` (edge ids carry no ':').
Each polyline end is pinned onto its place (the schema allows ``ENDPOINT_TOL_M``) so a
straight line between places never exceeds a lane length — the A* bound needs that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Tangents are read over this much of the schema polyline as drawn (not the pinned one), at
#: most half its length (D-489 부록 3): pinning moves only the end point, so the local
#: direction stays the drawn one, and a short window does not bend a curved lane's end.
TANGENT_M = 0.05

Point = tuple[float, float]


def _knots(points: tuple[Point, ...]) -> tuple[float, ...]:
    knots = [0.0]
    for a, b in zip(points, points[1:]):
        knots.append(knots[-1] + math.dist(a, b))
    return tuple(knots)


def lead_tangent(points) -> float:
    """Heading from the first point to the point ``TANGENT_M`` along (at most half the line)."""
    knots = _knots(tuple(points))
    window = min(TANGENT_M, knots[-1] / 2)
    for index in range(1, len(points)):
        if knots[index] >= window and knots[index] > knots[index - 1]:
            t = (window - knots[index - 1]) / (knots[index] - knots[index - 1])
            (ax, ay), (bx, by) = points[index - 1], points[index]
            x, y = ax + t * (bx - ax), ay + t * (by - ay)
            return math.atan2(y - points[0][1], x - points[0][0])
    return 0.0  # a zero-length line; the schema refuses those


def pinned(polyline, start: Point, end: Point) -> tuple[Point, ...]:
    points = [(float(x), float(y)) for x, y in polyline]
    points[0], points[-1] = (float(start[0]), float(start[1])), (float(end[0]), float(end[1]))
    return tuple(points)


def polyline_length(points) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


@dataclass(frozen=True)
class Arc:
    id: str
    edge_id: str
    forward: bool
    start_place: str
    end_place: str
    polyline: tuple[Point, ...]
    knots: tuple[float, ...]
    width_m: float
    speed_cap_mps: float
    drive_mode: str
    robot_kinds: tuple[str, ...] | None
    start_tangent: float = 0.0
    end_tangent: float = 0.0

    @property
    def length_m(self) -> float:
        return self.knots[-1]

    def point_at(self, s_m: float) -> tuple[float, float, float]:
        """``(x, y, segment heading)`` at ``s_m`` along the direction of travel."""
        s_m = min(max(s_m, 0.0), self.length_m)
        found = None
        for index in range(len(self.polyline) - 1):
            span = self.knots[index + 1] - self.knots[index]
            if span == 0.0:
                continue
            found = index
            if s_m <= self.knots[index + 1]:
                break
        if found is None:  # the schema refuses zero-length lanes; never recurse on one
            x, y = self.polyline[-1]
            return x, y, 0.0
        (ax, ay), (bx, by) = self.polyline[found], self.polyline[found + 1]
        span = self.knots[found + 1] - self.knots[found]
        t = min(max((s_m - self.knots[found]) / span, 0.0), 1.0)
        return ax + t * (bx - ax), ay + t * (by - ay), math.atan2(by - ay, bx - ax)

    def project(self, x: float, y: float) -> tuple[float, float, float]:
        """``(distance, s, tangent)`` of the closest polyline point."""
        best = (math.inf, 0.0, 0.0)
        for index in range(len(self.polyline) - 1):
            (ax, ay), (bx, by) = self.polyline[index], self.polyline[index + 1]
            dx, dy = bx - ax, by - ay
            span2 = dx * dx + dy * dy
            if span2 == 0.0:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / span2))
            dist = math.hypot(x - ax - t * dx, y - ay - t * dy)
            if dist < best[0]:
                best = (dist, self.knots[index] + t * math.sqrt(span2), math.atan2(dy, dx))
        return best


@dataclass(frozen=True)
class Graph:
    version: int | None
    arcs: dict[str, Arc]
    out_of: dict[str, tuple[str, ...]]
    places: dict[str, object]
    bans: frozenset[tuple[str, str, str]]
    #: Successor lists per routing config, built on first use (D-490 6: once per map version).
    _successors: dict = field(default_factory=dict, compare=False, repr=False)

    def successors(self, config, transition) -> dict[str, tuple[tuple[str, float], ...]]:
        """``{arc id: ((next arc id, transition cost s), ...)}`` without banned or refused turns.

        ``transition(arc, next arc, place kind)`` is the turn cost for ``config``.
        """
        found = self._successors.get(config)
        if found is None:
            found = {}
            for arc in self.arcs.values():
                place = arc.end_place
                kind = getattr(self.places[place], "kind", "junction")
                steps = []
                for nxt_id in self.out_of.get(place, ()):
                    nxt = self.arcs[nxt_id]
                    if (place, arc.edge_id, nxt.edge_id) in self.bans:
                        continue
                    step = transition(arc, nxt, kind)
                    if step is not None:
                        steps.append((nxt_id, step))
                found[arc.id] = tuple(steps)
            self._successors[config] = found
        return found

    def place_xy(self, place_id: str) -> Point:
        place = self.places[place_id]
        return float(place.x), float(place.y)


def build_graph(site_map, *, version: int | None = None) -> Graph:
    """``site_map`` is a ``fleet.site_map.SiteMap`` (duck-typed: places, edges, turn_bans)."""
    places = {place.id: place for place in site_map.places}
    arcs: dict[str, Arc] = {}
    for edge in site_map.edges:
        start, end = places[edge.from_], places[edge.to]
        points = pinned(edge.polyline, (start.x, start.y), (end.x, end.y))
        drawn = tuple((float(x), float(y)) for x, y in edge.polyline)
        kinds = tuple(edge.robot_kinds) if edge.robot_kinds is not None else None
        ways = [(True, edge.from_, edge.to, points, drawn)]
        if edge.direction == "two_way":
            ways.append((False, edge.to, edge.from_, tuple(reversed(points)), tuple(reversed(drawn))))
        for forward, src, dst, line, raw in ways:
            arc_id = f"{edge.id}:{'fwd' if forward else 'rev'}"
            end_tangent = lead_tangent(tuple(reversed(raw))) + math.pi
            arcs[arc_id] = Arc(arc_id, edge.id, forward, src, dst, line, _knots(line),
                               float(edge.width_m), float(edge.speed_cap_mps), edge.drive_mode, kinds,
                               lead_tangent(raw), math.atan2(math.sin(end_tangent), math.cos(end_tangent)))
    arcs = dict(sorted(arcs.items()))
    out_of: dict[str, list[str]] = {place_id: [] for place_id in places}
    for arc in arcs.values():
        out_of[arc.start_place].append(arc.id)
    bans = frozenset((ban.at, ban.from_edge, ban.to_edge) for ban in getattr(site_map, "turn_bans", ()))
    return Graph(version, arcs, {k: tuple(v) for k, v in out_of.items()}, places, bans)
