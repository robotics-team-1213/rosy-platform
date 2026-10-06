"""D-486 1·2: the active site map as directed lanes (arcs).

A ``one_way`` edge is one arc, a ``two_way`` edge two opposite arcs with the same
``edge_id``. Arc ids are ``<edge_id>:fwd`` / ``<edge_id>:rev`` (edge ids carry no ':').
Each polyline end is pinned onto its place (the schema allows ``ENDPOINT_TOL_M``) so a
straight line between places never exceeds a lane length — the A* bound needs that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

#: Tangents are read over this much polyline, so a 1 cm wiggle at a node is not a turn.
TANGENT_M = 0.05

Point = tuple[float, float]


def _knots(points: tuple[Point, ...]) -> tuple[float, ...]:
    knots = [0.0]
    for a, b in zip(points, points[1:]):
        knots.append(knots[-1] + math.dist(a, b))
    return tuple(knots)


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

    @property
    def length_m(self) -> float:
        return self.knots[-1]

    def point_at(self, s_m: float) -> tuple[float, float, float]:
        """``(x, y, tangent)`` at ``s_m`` along the direction of travel."""
        s_m = min(max(s_m, 0.0), self.length_m)
        last = len(self.polyline) - 2
        for index in range(last + 1):
            end = self.knots[index + 1]
            span = end - self.knots[index]
            if (s_m > end and index < last) or span == 0.0:
                continue
            t = (s_m - self.knots[index]) / span
            (ax, ay), (bx, by) = self.polyline[index], self.polyline[index + 1]
            return ax + t * (bx - ax), ay + t * (by - ay), math.atan2(by - ay, bx - ax)
        x, y = self.polyline[-1]
        return x, y, self.end_tangent

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

    @cached_property
    def start_tangent(self) -> float:
        x, y, _ = self.point_at(min(TANGENT_M, self.length_m / 2))
        return math.atan2(y - self.polyline[0][1], x - self.polyline[0][0])

    @cached_property
    def end_tangent(self) -> float:
        x, y = self.polyline[-1]
        px, py, _ = self.point_at(self.length_m - min(TANGENT_M, self.length_m / 2))
        return math.atan2(y - py, x - px)


@dataclass(frozen=True)
class Graph:
    version: int | None
    arcs: dict[str, Arc]
    out_of: dict[str, tuple[str, ...]]
    places: dict[str, object]
    bans: frozenset[tuple[str, str, str]]

    def place_xy(self, place_id: str) -> Point:
        place = self.places[place_id]
        return float(place.x), float(place.y)


def build_graph(site_map, *, version: int | None = None) -> Graph:
    """``site_map`` is a ``fleet.site_map.SiteMap`` (duck-typed: places, edges, turn_bans)."""
    places = {place.id: place for place in site_map.places}
    arcs: dict[str, Arc] = {}
    for edge in site_map.edges:
        start, end = places[edge.from_], places[edge.to]
        points = [(float(x), float(y)) for x, y in edge.polyline]
        points[0], points[-1] = (float(start.x), float(start.y)), (float(end.x), float(end.y))
        kinds = tuple(edge.robot_kinds) if edge.robot_kinds is not None else None
        ways = [(True, edge.from_, edge.to, tuple(points))]
        if edge.direction == "two_way":
            ways.append((False, edge.to, edge.from_, tuple(reversed(points))))
        for forward, src, dst, line in ways:
            arc_id = f"{edge.id}:{'fwd' if forward else 'rev'}"
            arcs[arc_id] = Arc(arc_id, edge.id, forward, src, dst, line, _knots(line),
                               float(edge.width_m), float(edge.speed_cap_mps), edge.drive_mode, kinds)
    arcs = dict(sorted(arcs.items()))
    out_of: dict[str, list[str]] = {place_id: [] for place_id in places}
    for arc in arcs.values():
        out_of[arc.start_place].append(arc.id)
    bans = frozenset((ban.at, ban.from_edge, ban.to_edge) for ban in getattr(site_map, "turn_bans", ()))
    return Graph(version, arcs, {k: tuple(v) for k, v in out_of.items()}, places, bans)
