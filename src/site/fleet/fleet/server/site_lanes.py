"""Site lane geometry for the console map-fit overlay (D-375, display only).

Reads a generated ``lane_graph.yaml`` (map frame, metres) into plain polylines
the browser can project onto the ceiling camera image with a Vision map
proposal. Nothing here feeds sightings, ``CameraMap``, task acceptance or
motion — the lanes are drawn, never driven.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

# A generated lane graph has ~900 points; this caps what one browser read carries.
MAX_POINTS = 20_000
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


def parse_lane_graph_flags(values: Iterable[str] | None) -> dict[str | None, dict]:
    """``--site-lane-graph [MAP_ID=]PATH`` values → lanes per map id (None: every map)."""
    lanes: dict[str | None, dict] = {}
    for value in values or ():
        map_id, sep, path = value.partition("=")
        key = map_id.strip() if sep else None
        if sep and (not key or not path):
            raise ValueError(f"--site-lane-graph {value!r}: expected MAP_ID=PATH or PATH")
        if key in lanes:
            raise ValueError(f"--site-lane-graph given twice for {key or 'every map'}")
        lanes[key] = load_lane_graph(path if sep else value)
    return lanes


def site_lanes_payload(lanes: Mapping[str | None, dict], sources: Sequence) -> dict | None:
    """One entry per configured lane graph, with the sighting sources on that map."""
    if not lanes:
        return None
    maps = []
    for map_id, graph in lanes.items():
        source_ids = [source.source_id for source in sources
                      if map_id is None or source.map_id == map_id]
        maps.append({"map_id": map_id, "frame": "map", "units": "m", "source_ids": source_ids,
                     **graph})
    return {"maps": maps}
