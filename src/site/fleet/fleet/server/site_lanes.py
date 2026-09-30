"""Site lane geometry for the console map-fit overlay (D-375, display only).

Reads a generated ``lane_graph.yaml`` (map frame, metres) into plain polylines,
and optionally the lane paint mesh (``road_lines.stl``, the file Vision fits
with ``--map-paint``) into flat triangles, so the browser can project both onto
the ceiling camera image with a Vision map proposal. The centrelines run between
the paint lines; the paint triangles are what must sit on the white paint. Nothing here feeds sightings, ``CameraMap``, task acceptance or
motion — the lanes are drawn, never driven.
"""

from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

# A generated lane graph has ~900 points and road_lines.stl ~1.7k triangles; these cap
# what one browser read carries.
MAX_POINTS = 20_000
MAX_TRIANGLES = 20_000
_ROUNDABOUT_STEPS = 72


def _point(value, where: str) -> list[float]:
    if (not isinstance(value, (list, tuple)) or len(value) < 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                   for v in value[:2])):
        raise ValueError(f"{where} must be a finite [x, y] point")
    return [round(float(value[0]), 4), round(float(value[1]), 4)]


def _points(values, where: str) -> list[list[float]]:
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError(f"{where} must list at least two points")
    return [_point(value, f"{where}[{index}]") for index, value in enumerate(values)]


def load_lane_graph(path: Path | str) -> dict:
    """Parse a lane graph into ``{"polylines", "bounds_m", "lane_graph_sha256"}``.

    Segments become open polylines, the parking approach one more, and the
    roundabout (centre + radius) a closed polygon. Raises ``ValueError`` on a
    missing file or malformed geometry so a bad deploy fails at start-up.
    """
    graph_path = Path(path)
    try:
        raw = graph_path.read_bytes()
        graph = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read lane graph {graph_path}: {exc}") from exc
    if not isinstance(graph, dict) or not isinstance(graph.get("segments"), dict) or not graph["segments"]:
        raise ValueError(f"lane graph {graph_path} needs a non-empty segments mapping")
    polylines = []
    for name, segment in graph["segments"].items():
        if not isinstance(name, str) or not isinstance(segment, dict):
            raise ValueError(f"lane graph segment {name!r} must be a mapping")
        polylines.append({"id": name, "kind": "segment", "closed": False,
                          "points": _points(segment.get("points"), f"segments.{name}.points")})
    parking = graph.get("parking")
    if parking is not None:
        if not isinstance(parking, dict):
            raise ValueError("lane graph parking must be a mapping")
        polylines.append({"id": "parking", "kind": "parking", "closed": False,
                          "points": _points(parking.get("points"), "parking.points")})
    roundabout = graph.get("roundabout")
    if roundabout is not None:
        if not isinstance(roundabout, dict):
            raise ValueError("lane graph roundabout must be a mapping")
        cx, cy = _point(roundabout.get("centre"), "roundabout.centre")
        radius = roundabout.get("radius")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not 0 < radius < 1000:
            raise ValueError("lane graph roundabout.radius must be a positive number")
        ring = [[round(cx + radius * math.cos(2 * math.pi * k / _ROUNDABOUT_STEPS), 4),
                 round(cy + radius * math.sin(2 * math.pi * k / _ROUNDABOUT_STEPS), 4)]
                for k in range(_ROUNDABOUT_STEPS)]
        polylines.append({"id": "roundabout", "kind": "roundabout", "closed": True, "points": ring})
    total = sum(len(line["points"]) for line in polylines)
    if total > MAX_POINTS:
        raise ValueError(f"lane graph {graph_path} has {total} points; the console reads at most {MAX_POINTS}")
    xs = [p[0] for line in polylines for p in line["points"]]
    ys = [p[1] for line in polylines for p in line["points"]]
    return {
        "polylines": polylines,
        "bounds_m": {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)},
        "lane_graph_sha256": hashlib.sha256(raw).hexdigest(),
    }


def load_lane_paint(path: Path | str) -> dict:
    """Binary STL of floor paint in map metres (Z up) → ``{"paint_triangles", "paint_sha256"}``.

    Each triangle is ``[x1, y1, x2, y2, x3, y3]`` rounded to 0.1 mm. Same file and
    frame as Vision's ``--map-paint``; parsed without numpy (Fleet does not ship it).
    """
    paint_path = Path(path)
    try:
        data = paint_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read lane paint {paint_path}: {exc}") from exc
    count = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
    if count == 0 or len(data) != 84 + 50 * count:
        raise ValueError(f"lane paint {paint_path} is not a binary STL")
    if count > MAX_TRIANGLES:
        raise ValueError(f"lane paint {paint_path} has {count} triangles; the console reads at most "
                         f"{MAX_TRIANGLES}")
    triangles = []
    for index in range(count):
        v = struct.unpack_from("<9f", data, 84 + 50 * index + 12)
        if not all(math.isfinite(value) for value in v):
            raise ValueError(f"lane paint {paint_path} has non-finite vertices")
        triangles.append([round(v[0], 4), round(v[1], 4), round(v[3], 4), round(v[4], 4),
                          round(v[6], 4), round(v[7], 4)])
    return {"paint_triangles": triangles, "paint_sha256": hashlib.sha256(data).hexdigest()}


def _flag_value(flag: str, value: str) -> tuple[str | None, str]:
    map_id, sep, path = value.partition("=")
    key = map_id.strip() if sep else None
    if sep and (not key or not path):
        raise ValueError(f"{flag} {value!r}: expected MAP_ID=PATH or PATH")
    return key, (path if sep else value)


def parse_lane_graph_flags(values: Iterable[str] | None, paints: Iterable[str] | None = None
                           ) -> dict[str | None, dict]:
    """``--site-lane-graph``/``--site-lane-paint [MAP_ID=]PATH`` → lanes per map id (None: every map)."""
    lanes: dict[str | None, dict] = {}
    for flag, loader, items in (("--site-lane-graph", load_lane_graph, values),
                                ("--site-lane-paint", load_lane_paint, paints)):
        seen: set[str | None] = set()
        for value in items or ():
            key, path = _flag_value(flag, value)
            if key in seen:
                raise ValueError(f"{flag} given twice for {key or 'every map'}")
            seen.add(key)
            lanes.setdefault(key, {}).update(loader(path))
    return lanes


def site_lanes_payload(lanes: Mapping[str | None, dict], sources: Sequence) -> dict | None:
    """One entry per configured lane graph, with the sighting sources on that map."""
    if not lanes:
        return None
    maps = []
    for map_id, graph in lanes.items():
        source_ids = [source.source_id for source in sources
                      if map_id is None or source.map_id == map_id]
        entry = {"map_id": map_id, "frame": "map", "units": "m", "source_ids": source_ids,
                 "polylines": [], "paint_triangles": [], **graph}
        xs = [v for tri in entry["paint_triangles"] for v in tri[0::2]]
        ys = [v for tri in entry["paint_triangles"] for v in tri[1::2]]
        if xs:  # the paint reaches past the centrelines; the view frames both
            bounds = entry.get("bounds_m") or {"min_x": xs[0], "min_y": ys[0], "max_x": xs[0], "max_y": ys[0]}
            entry["bounds_m"] = {"min_x": min(bounds["min_x"], *xs), "min_y": min(bounds["min_y"], *ys),
                                 "max_x": max(bounds["max_x"], *xs), "max_y": max(bounds["max_y"], *ys)}
        maps.append(entry)
    return {"maps": maps}
