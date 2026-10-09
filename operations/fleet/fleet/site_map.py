"""D-488 ``rosy.site_map/1``: the site map Fleet owns — addresses (places) and directed lanes (edges).

Pure: pydantic and PyYAML only, no network, DB, or clock. The store and routes live in
``fleet.server.site_map_store`` / ``site_map_routes``; the planner reads this through
``fleet.routing.graph`` (D-490).

``from_lane_graph`` turns a generated ``lane_graph.yaml`` (map frame, metres) into the first
map of a site. The file path is site configuration (``--site-map-import``), never a repo path.

D-573 1: ``crosswalks`` are areas, not places. The polygon comes from ``lane_graph.yaml``
(``crosswalks_from_lane_graph``), ``lanes`` is derived from the edges on every validation and
``approach`` (the waiting bands) is drawn in the editor. Map data only; nothing here drives.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Annotated, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fleet.routing.graph import pinned, polyline_length

SCHEMA = "rosy.site_map/1"
#: A polyline end may sit this far from its place (generated graphs end exactly on the node).
ENDPOINT_TOL_M = 0.05
MAX_PLACES = 500
MAX_EDGES = 1000
MAX_POINTS = 20_000
#: A lane pinned onto its places must be longer than this, and two places must be farther
#: apart than ``ENDPOINT_TOL_M``: a zero-length lane has no direction to plan with.
MIN_EDGE_M = 0.10
#: lane_graph.yaml lane half-width is 92.5 mm (docs/validation map-v2-fleet keep run).
IMPORT_WIDTH_M = 0.185
#: Import default only; the operator edits it per edge in the console.
IMPORT_SPEED_CAP_MPS = 0.2

#: ``start`` (D-513): a demo start slot. Its ``yaw`` is required and fixes the departure heading.
#: ``bend`` (D-507 addendum): a lane bend CORE passes on odometry. ``(x, y)`` is the vertex of
#: the two centre lines, ``yaw`` the entering heading as the edge is drawn, ``exit_yaw`` the
#: leaving heading and ``radius_m`` the centre-line arc; driven the other way it is the same
#: bend entered at ``exit_yaw + pi``. Bends do not split edges.
PlaceKind = Literal["park", "charge", "stop", "junction", "turnaround", "start", "bend"]
#: A bend turns at least this much (a smaller one is the expected window's, D-507 2) and at most 90.
BEND_MIN_DEG, BEND_MAX_DEG = 15.0, 90.0

#: D-573 1 crosswalk limits. A crosswalk or waiting band is a polygon of 3-32 points, at least
#: 1 cm^2 and at most this far across. A band must reach its lane and stay on the D-507 9 site
#: floor (every lane plus 0.30 m); beyond the floor is "wall" and would hold the robot forever.
MAX_CROSSWALKS = 50
MAX_APPROACH = 4
CROSSWALK_MAX_SPAN_M = 3.0
CROSSWALK_MIN_AREA_M2 = 1e-4
SITE_FLOOR_MARGIN_M = 0.30

Id = Field(pattern=r"^[A-Za-z0-9_.-]{1,32}$")
Finite = Field(allow_inf_nan=False)


class SitePlace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Id
    name: str = Field(min_length=1, max_length=64)
    x: float = Finite
    y: float = Finite
    yaw: Optional[float] = Field(default=None, ge=-math.pi, le=math.pi, allow_inf_nan=False)
    kind: PlaceKind = "junction"
    exit_yaw: Optional[float] = Field(default=None, ge=-math.pi, le=math.pi, allow_inf_nan=False)
    radius_m: Optional[float] = Field(default=None, gt=0.0, le=0.5, allow_inf_nan=False)

    @model_validator(mode="after")
    def _start_heading(self) -> "SitePlace":
        if self.kind == "start" and self.yaw is None:
            raise ValueError(f"start place {self.id} needs a yaw")
        if self.kind != "bend":
            if self.exit_yaw is not None or self.radius_m is not None:
                raise ValueError(f"place {self.id}: exit_yaw and radius_m belong to a bend")
            return self
        if None in (self.yaw, self.exit_yaw, self.radius_m):
            raise ValueError(f"bend place {self.id} needs yaw, exit_yaw and radius_m")
        turn = abs(math.degrees(math.remainder(self.exit_yaw - self.yaw, math.tau)))
        if not BEND_MIN_DEG <= turn <= BEND_MAX_DEG:
            raise ValueError(f"bend place {self.id} turns {turn:.1f} deg, not {BEND_MIN_DEG}-{BEND_MAX_DEG}")
        return self


class SiteEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Id
    from_: str = Field(alias="from", pattern=r"^[A-Za-z0-9_.-]{1,32}$")
    to: str = Id
    polyline: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_POINTS)
    direction: Literal["one_way", "two_way"] = "one_way"
    width_m: float = Field(gt=0.0, le=10.0, allow_inf_nan=False)
    speed_cap_mps: float = Field(gt=0.0, le=5.0, allow_inf_nan=False)
    drive_mode: Literal["lane", "free"] = "lane"
    robot_kinds: Optional[list[Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,32}$")]]] = Field(
        default=None, max_length=16)

    @model_validator(mode="after")
    def _finite(self) -> "SiteEdge":
        if any(not math.isfinite(v) for point in self.polyline for v in point):
            raise ValueError(f"edge {self.id} polyline must be finite")
        if sum(math.dist(a, b) for a, b in zip(self.polyline, self.polyline[1:])) <= 0.0:
            raise ValueError(f"edge {self.id} polyline has zero length")
        return self


Polygon = Annotated[list[tuple[float, float]], Field(min_length=3, max_length=32)]


def _polygon_problem(points) -> Optional[str]:
    if any(not math.isfinite(v) for point in points for v in point):
        return "must be finite"
    area = abs(sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]))) / 2
    if area < CROSSWALK_MIN_AREA_M2:
        return f"is smaller than {CROSSWALK_MIN_AREA_M2} m^2"
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    if math.hypot(max(xs) - min(xs), max(ys) - min(ys)) > CROSSWALK_MAX_SPAN_M:
        return f"spans more than {CROSSWALK_MAX_SPAN_M} m"
    return None


def _inside(point, polygon) -> bool:
    x, y = point
    hit = False
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def _point_segment(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _segments_cross(a, b, c, d) -> bool:
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def _polyline_polygon_gap(polyline, polygon) -> float:
    """0 when the polyline enters the polygon, else the closest gap between them."""
    ring = list(zip(polygon, polygon[1:] + polygon[:1]))
    if any(_inside(p, polygon) for p in polyline):
        return 0.0
    gap = math.inf
    for a, b in zip(polyline, polyline[1:]):
        for c, d in ring:
            if _segments_cross(a, b, c, d):
                return 0.0
            gap = min(gap, _point_segment(a, c, d), _point_segment(b, c, d),
                      _point_segment(c, a, b), _point_segment(d, a, b))
    return gap


class SiteCrosswalk(BaseModel):
    """D-573 1: one crosswalk area. ``lanes`` is derived by ``SiteMap``: a submitted value is replaced."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Id
    polygon: Polygon
    approach: list[Polygon] = Field(default_factory=list, max_length=MAX_APPROACH)
    lanes: list[str] = Field(default_factory=list, max_length=MAX_EDGES)
    revision: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _shapes(self) -> "SiteCrosswalk":
        for name, points in (("polygon", self.polygon), *((f"approach {i}", b) for i, b in enumerate(self.approach))):
            problem = _polygon_problem(list(points))
            if problem:
                raise ValueError(f"crosswalk {self.id} {name} {problem}")
        return self


class TurnBan(BaseModel):
    """D-489 3: no turn from edge ``from_edge`` into edge ``to_edge`` at place ``at``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    at: str = Id
    from_edge: str = Id
    to_edge: str = Id


class SiteMap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_id: Literal["rosy.site_map/1"] = Field(default=SCHEMA, alias="schema")
    map_id: str = Field(default="site", pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    places: list[SitePlace] = Field(max_length=MAX_PLACES)
    edges: list[SiteEdge] = Field(max_length=MAX_EDGES)
    turn_bans: list[TurnBan] = Field(default_factory=list, max_length=MAX_EDGES)
    #: D-513 7: clockwise screen turn of the plain (+y up) map view. Display only; the one
    #: orientation every Fleet map and camera view follows.
    view_turn_deg: Literal[0, 90, 180, 270] = 0
    #: D-573 1: crosswalk areas (polygon from lane_graph.yaml, waiting bands from the editor).
    crosswalks: list[SiteCrosswalk] = Field(default_factory=list, max_length=MAX_CROSSWALKS)

    @model_validator(mode="after")
    def _references(self) -> "SiteMap":
        places = {place.id: place for place in self.places}
        if len(places) != len(self.places):
            raise ValueError("place ids must be unique")
        edges = {edge.id: edge for edge in self.edges}
        if len(edges) != len(self.edges):
            raise ValueError("edge ids must be unique")
        if sum(len(edge.polyline) for edge in self.edges) > MAX_POINTS:
            raise ValueError(f"site map holds more than {MAX_POINTS} points")
        ordered = sorted(self.places, key=lambda place: place.x)
        for index, place in enumerate(ordered):  # sweep on x: O(n log n) for the usual sparse map
            for other in ordered[index + 1:]:
                if other.x - place.x > ENDPOINT_TOL_M:
                    break
                if math.dist((place.x, place.y), (other.x, other.y)) <= ENDPOINT_TOL_M:
                    raise ValueError(f"places {place.id} and {other.id} are at the same point")
        for edge in self.edges:
            for end, point in ((edge.from_, edge.polyline[0]), (edge.to, edge.polyline[-1])):
                place = places.get(end)
                if place is None:
                    raise ValueError(f"edge {edge.id} names unknown place {end}")
                if math.dist(point, (place.x, place.y)) > ENDPOINT_TOL_M:
                    raise ValueError(f"edge {edge.id} polyline does not end at place {end}")
            start, finish = places[edge.from_], places[edge.to]
            if polyline_length(pinned(edge.polyline, (start.x, start.y), (finish.x, finish.y))) <= MIN_EDGE_M:
                raise ValueError(f"edge {edge.id} is shorter than {MIN_EDGE_M} m between its places")
        for ban in self.turn_bans:
            into, out = edges.get(ban.from_edge), edges.get(ban.to_edge)
            if ban.at not in places or into is None or out is None:
                raise ValueError("turn ban names an unknown place or edge")
            if ban.at not in (into.from_, into.to) or ban.at not in (out.from_, out.to):
                raise ValueError(f"turn ban edges do not meet at {ban.at}")
        self._crosswalks()
        return self

    def _crosswalks(self) -> None:
        """D-573 1: unique ids, on a lane, bands reach their lane and stay on the site floor."""
        if len({crosswalk.id for crosswalk in self.crosswalks}) != len(self.crosswalks):
            raise ValueError("crosswalk ids must be unique")
        derived = []
        for crosswalk in self.crosswalks:
            on = [edge for edge in self.edges if _polyline_polygon_gap(edge.polyline, list(crosswalk.polygon)) == 0.0]
            if not on:
                raise ValueError(f"crosswalk {crosswalk.id} is on no lane")
            for index, band in enumerate(crosswalk.approach):
                band = list(band)
                if not any(_polyline_polygon_gap(edge.polyline, band) <= edge.width_m / 2 for edge in on):
                    raise ValueError(f"crosswalk {crosswalk.id} approach {index} does not reach its lane")
                # ponytail: band vertices only; an edge bulging past a concave floor passes. Clip
                # against a floor outline if the D-507 9 floor ever becomes a drawn polygon.
                for point in band:
                    if not any(min(_point_segment(point, a, b) for a, b in zip(edge.polyline, edge.polyline[1:]))
                               <= edge.width_m / 2 + SITE_FLOOR_MARGIN_M for edge in self.edges):
                        raise ValueError(f"crosswalk {crosswalk.id} approach {index} leaves the site floor "
                                         f"(lane + {SITE_FLOOR_MARGIN_M} m, D-507 9)")
            derived.append(crosswalk.model_copy(update={"lanes": sorted(edge.id for edge in on)}))
        object.__setattr__(self, "crosswalks", derived)  # frozen model: lanes are derived here only

    def body(self) -> dict:
        body = self.model_dump(by_alias=True, mode="json")
        for place in body["places"]:  # bend fields only on bends: other stored maps stay byte-equal
            for key in ("exit_yaw", "radius_m"):
                if place[key] is None:
                    del place[key]
        if body["view_turn_deg"] == 0:  # keep stored maps readable by a Fleet without the field
            del body["view_turn_deg"]
        if not body["crosswalks"]:  # D-573: a map without crosswalks stays byte-equal
            del body["crosswalks"]
        return body


def from_lane_graph(path: Path | str, *, map_id: str = "site") -> SiteMap:
    """Nodes become junction places; segments become lane edges (``reverse`` → two_way).

    The parking spur and roundabout outline are not graph edges in this file and are
    left out: an address without an edge would be unreachable.
    """
    graph = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), dict) \
            or not isinstance(graph.get("segments"), dict):
        raise ValueError(f"{path} needs nodes and segments")
    places = [SitePlace(id=str(name), name=str(name), x=float(xy[0]), y=float(xy[1]))
              for name, xy in graph["nodes"].items()]
    edges = []
    for name, segment in graph["segments"].items():
        edges.append(SiteEdge(
            id=str(name), from_=str(segment["from"]), to=str(segment["to"]),
            polyline=[(float(p[0]), float(p[1])) for p in segment["points"]],
            direction="two_way" if "reverse" in (segment.get("directions") or []) else "one_way",
            width_m=IMPORT_WIDTH_M, speed_cap_mps=IMPORT_SPEED_CAP_MPS, drive_mode="lane"))
    return SiteMap(map_id=map_id, places=places, edges=edges, crosswalks=crosswalks_from_lane_graph(path))


def crosswalks_from_lane_graph(path: Path | str) -> list[SiteCrosswalk]:
    """D-573 1: ``lane_graph.yaml`` ``crosswalks[].polygon`` as is; ids ``cw1``.. in file order
    (or the entry's own ``id``); ``revision`` is ``lane_graph:<sha256[:12]>`` of the file.
    ``lanes`` is filled when they join a map; no waiting bands (the editor draws them)."""
    raw = Path(path).read_bytes()
    graph = yaml.safe_load(raw)
    revision = "lane_graph:" + hashlib.sha256(raw).hexdigest()[:12]
    rows = graph.get("crosswalks") if isinstance(graph, dict) else None
    return [SiteCrosswalk(id=str(row.get("id") or f"cw{index}"), revision=revision,
                          polygon=[(float(p[0]), float(p[1])) for p in row["polygon"]])
            for index, row in enumerate(rows or [], start=1)]
