"""D-488 ``rosy.site_map/1``: the site map Fleet owns — addresses (places) and directed lanes (edges).

Pure: pydantic and PyYAML only, no network, DB, or clock. The store and routes live in
``fleet.server.site_map_store`` / ``site_map_routes``; the planner reads this through
``fleet.routing.graph`` (D-490).

``from_lane_graph`` turns a generated ``lane_graph.yaml`` (map frame, metres) into the first
map of a site. The file path is site configuration (``--site-map-import``), never a repo path.
"""

from __future__ import annotations

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
        return self

    def body(self) -> dict:
        body = self.model_dump(by_alias=True, mode="json")
        for place in body["places"]:  # bend fields only on bends: other stored maps stay byte-equal
            for key in ("exit_yaw", "radius_m"):
                if place[key] is None:
                    del place[key]
        if body["view_turn_deg"] == 0:  # keep stored maps readable by a Fleet without the field
            del body["view_turn_deg"]
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
    return SiteMap(map_id=map_id, places=places, edges=edges)
