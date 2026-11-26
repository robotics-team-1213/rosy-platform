"""YAML-backed Staging Bays (임시칸) and Export/Takeout Stations (반출대) registry, plus the zone map.

A robot sent to a zone stands at its ``place_id`` in the active ``rosy.site_map/1``: no coordinate is stored for
these zones, so a zone can never disagree with the place it names. ``vehicle`` (the robot footprint) and
``areas`` (fixed equipment, site map frame, metres) are what the Fleet 구역 도면 draws in 2D and 3D.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from typing import Iterable
import json
import math
import yaml

from fleet.site_map import _inside, _polyline_polygon_gap, _polygon_problem

DEFAULT_YAML_PATH = Path(__file__).with_name("station_zones.yaml")
#: Read from the packaged file when an operator override (Cell page) predates the zone map.
_ZONE_MAP_KEYS = ("vehicle", "areas")
AREA_KINDS = ("worktop", "belt", "cell_zone")
AREA_STATUSES = ("measured", "cad_registered", "photo_estimated", "planned_unverified")
#: A fixed area may cut this far into a lane's nominal width: drawing and photo error, not a collision.
AREA_LANE_TOLERANCE_M = 0.02


def _read(path: Path) -> dict[str, Any]:
    parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parsed if isinstance(parsed, dict) else {}


def _finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("zone map numbers must be finite")
    return float(value)


def parse_vehicle(raw: Any) -> dict[str, float] | None:
    """``{front_m, rear_m, half_width_m}`` in base_footprint (x forward, y left), or None when absent."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("vehicle must be a mapping")
    vehicle = {key: _finite(raw.get(key)) for key in ("front_m", "rear_m", "half_width_m")}
    if vehicle["front_m"] <= 0 or vehicle["rear_m"] >= 0 or vehicle["half_width_m"] <= 0:
        raise ValueError("vehicle needs front_m > 0 > rear_m and half_width_m > 0")
    return vehicle


def _is_convex(polygon) -> bool:
    """Every turn bends the same way (straight runs allowed): the ring is simple and convex, which the
    overlap check below needs of both of its inputs."""
    count = len(polygon)
    turns = [
        (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        for a, b, c in ((polygon[i], polygon[(i + 1) % count], polygon[(i + 2) % count]) for i in range(count))
    ]
    return all(turn >= -1e-12 for turn in turns) or all(turn <= 1e-12 for turn in turns)


def parse_areas(raw: Any) -> list[dict[str, Any]]:
    """Fixed areas in the site map frame. Raises ValueError on the first malformed entry."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("areas must be a list")
    areas: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError(f"area {index + 1} needs an id")
        name = str(item["id"])
        if name in seen:
            raise ValueError(f"area {name} is listed twice")
        seen.add(name)
        kind = str(item.get("kind") or "worktop")
        if kind not in AREA_KINDS:
            raise ValueError(f"area {name}: kind must be one of {', '.join(AREA_KINDS)}")
        status = str(item.get("status") or "planned_unverified")
        if status not in AREA_STATUSES:
            raise ValueError(f"area {name}: status must be one of {', '.join(AREA_STATUSES)}")
        points = item.get("polygon")
        if not isinstance(points, list) or not 3 <= len(points) <= 32:
            raise ValueError(f"area {name}: polygon needs 3 to 32 [x, y] points")
        try:
            polygon = [(_finite(point[0]), _finite(point[1])) for point in points]
        except (TypeError, IndexError, KeyError):
            raise ValueError(f"area {name}: polygon points must be [x, y] pairs") from None
        problem = _polygon_problem(polygon)
        if problem:
            raise ValueError(f"area {name}: polygon {problem}")
        if not _is_convex(polygon):
            raise ValueError(f"area {name}: polygon must be convex (split a concave area into convex parts)")
        height = item.get("height_m")
        areas.append({
            "id": name, "name": str(item.get("name") or name),
            "short_name": str(item.get("short_name") or item.get("name") or name),
            "kind": kind, "status": status,
            "polygon": polygon, "height_m": None if height is None else _finite(height),
            "evidence": str(item.get("evidence") or ""), "zone_id": str(item.get("zone_id") or ""),
        })
        if areas[-1]["height_m"] is not None and areas[-1]["height_m"] <= 0:
            raise ValueError(f"area {name}: height_m must be positive")
    return areas


def _crosses(a, b, c, d) -> bool:
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def _point_segment(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _strictly_inside(point, polygon, eps: float = 1e-6) -> bool:
    ring_ = polygon + polygon[:1]
    return _inside(point, polygon) and min(_point_segment(point, c, d) for c, d in zip(ring_, ring_[1:])) > eps


def _signed_area(polygon) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1])) / 2


def _line_crossing(p, q, a, b):
    """Where the segment p->q meets the infinite line a->b."""
    denominator = (a[0] - b[0]) * (p[1] - q[1]) - (a[1] - b[1]) * (p[0] - q[0])
    t = 0.0 if denominator == 0 else ((a[0] - p[0]) * (p[1] - q[1]) - (a[1] - p[1]) * (p[0] - q[0])) / denominator
    return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])


def _clipped(subject, clip) -> list:
    """``subject`` cut by the convex ``clip`` polygon (Sutherland-Hodgman); empty when they share no area."""
    fence = clip[::-1] if _signed_area(clip) < 0 else clip
    output = list(subject)
    for a, b in zip(fence, fence[1:] + fence[:1]):
        inputs, output = output, []
        if not inputs:
            break
        inside = lambda p: (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0
        previous = inputs[-1]
        for current in inputs:
            if inside(current):
                if not inside(previous):
                    output.append(_line_crossing(previous, current, a, b))
                output.append(current)
            elif inside(previous):
                output.append(_line_crossing(previous, current, a, b))
            previous = current
    return output


#: Two shapes overlap when they share more area than this (1 mm^2).
_OVERLAP_M2 = 1e-6


def _overlaps(a, b) -> bool:
    """The interiors share more than a sliver of area. Both polygons are convex (``parse_areas`` refuses
    others), so cutting either out of the other is exact. Vertex and edge tests alone miss two rectangles
    that overlap in a third rectangle (no vertex inside, edges meeting in T-junctions), so the shared area
    is measured. Two areas that only touch along an edge (adjacent worktops) do not overlap."""
    ring_a, ring_b = a + a[:1], b + b[:1]
    return (abs(_signed_area(_clipped(a, b))) > _OVERLAP_M2 or abs(_signed_area(_clipped(b, a))) > _OVERLAP_M2
            or any(_strictly_inside(point, b) for point in a) or any(_strictly_inside(point, a) for point in b)
            or any(_crosses(x, y, c, d) for x, y in zip(ring_a, ring_a[1:]) for c, d in zip(ring_b, ring_b[1:])))


def _contains(outer, inner) -> bool:
    """``inner`` lies wholly in ``outer``: cut out, it keeps its whole area (vertex tests wobble on a shared edge)."""
    return abs(abs(_signed_area(_clipped(inner, outer))) - abs(_signed_area(inner))) <= _OVERLAP_M2


def active_lanes(active_map) -> list[tuple[str, list, float]]:
    """Lanes of the active site map as ``(id, centre polyline, width_m)``, the shape ``area_conflicts`` reads.
    ``active_map`` is the route helper that raises its 404 ``NO_ACTIVE_MAP`` on a site without an active map;
    there is then no lane to check against, so the save keeps its earlier behaviour. Any other error, a
    different 404 included, is a fault and propagates. No fastapi import: nothing in this layer uses it."""
    try:
        active = active_map()
    except Exception as error:  # noqa: BLE001
        detail = getattr(error, "detail", None)
        if getattr(error, "status_code", None) != 404 or not (
                isinstance(detail, dict) and detail.get("code") == "NO_ACTIVE_MAP"):
            raise
        return []
    return [(edge.id, list(edge.polyline), edge.width_m) for edge in active[1].edges]


def area_conflicts(areas: Iterable[dict[str, Any]], lanes: Iterable[tuple[str, list, float]] = ()) -> list[str]:
    """Why these areas cannot be saved: a partial overlap between two areas, or an area cutting deeper than
    ``AREA_LANE_TOLERANCE_M`` into a lane's nominal width. ``lanes`` are ``(id, centre polyline, width_m)``.
    An area inside another (a cell zone on its worktop) is intended and is not a conflict."""
    areas = list(areas)
    found: list[str] = []
    for index, first in enumerate(areas):
        for second in areas[index + 1:]:
            a, b = first["polygon"], second["polygon"]
            if _overlaps(a, b) and not (_contains(a, b) or _contains(b, a)):
                found.append(f"area {first['id']} partially overlaps area {second['id']}")
    for area in areas:
        for lane_id, polyline, width in lanes:
            cut = width / 2 - _polyline_polygon_gap(polyline, area["polygon"])
            if cut > AREA_LANE_TOLERANCE_M:
                found.append(
                    f"area {area['id']} overlaps lane {lane_id} by {cut * 1000:.0f} mm "
                    f"(more than {AREA_LANE_TOLERANCE_M * 1000:.0f} mm)")
    return found


def load_station_zones(override_path: Path | None = None) -> dict[str, Any]:
    """Load station zones from override or default YAML; the packaged ``vehicle``/``areas`` fill in when an
    override predates the zone map. Malformed areas are reported in ``area_errors`` and left out."""
    use_override = bool(override_path and override_path.is_file())
    path = override_path if use_override else DEFAULT_YAML_PATH
    parsed = _read(path)
    if use_override:
        for key in _ZONE_MAP_KEYS:
            parsed.setdefault(key, _read(DEFAULT_YAML_PATH).get(key))
    staging = list(parsed.get("staging_bays") or [])
    exports = list(parsed.get("export_stations") or [])
    by_id: dict[str, dict[str, Any]] = {}
    for item in staging + exports:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = dict(item)
    area_errors: list[str] = []
    try:
        vehicle, areas = parse_vehicle(parsed.get("vehicle")), parse_areas(parsed.get("areas"))
    except ValueError as exc:
        vehicle, areas, area_errors = None, [], [str(exc)]
    return {
        "schema": parsed.get("schema", "rosy.station-zones.v1"),
        "site_id": parsed.get("site_id", "world_261026"),
        "staging_bays": staging,
        "export_stations": exports,
        "zones_by_id": by_id,
        "vehicle": vehicle,
        "areas": areas,
        "area_errors": area_errors,
        "yaml_text": path.read_text(encoding="utf-8"),
        "source_path": str(path),
    }


# Legacy warehouse station ids -> cell site map ids (shared/web/cell-site-map.json).
# None = no cell place; "not_places:*" = a non-place entry of the map (belt feed).
_SITE_ALIASES: dict[str, str | None] = {
    "EXP_S1": "stand:r1-s1",
    "EXP_S5_PALLET": "yard",
    "EXP_S3_BELT": "not_places:belt",
    "STG_C2": None,
    "STG_S3_WAIT": None,
}


def resolve_site_alias(old_id: str) -> str | None:
    """Read-only lookup of a legacy station zone id; unknown ids also give None."""
    return _SITE_ALIASES.get(old_id)


def save_station_zones_yaml(yaml_text: str, target_path: Path, *,
                            lanes: Iterable[tuple[str, list, float]] = ()) -> dict[str, Any]:
    """Validate and persist updated YAML text. ``lanes`` of the active site map are ``(id, polyline, width_m)``;
    an area that overlaps another area or cuts into a lane is refused before anything is written."""
    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict):
        raise ValueError("YAML root must be a mapping")
    if "staging_bays" not in parsed and "export_stations" not in parsed:
        raise ValueError("YAML must define staging_bays or export_stations")
    try:
        json.dumps(parsed, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("station zones must contain finite JSON values") from None
    parse_vehicle(parsed.get("vehicle"))
    areas = parse_areas(parsed.get("areas"))
    conflicts = area_conflicts(areas, lanes)
    if conflicts:
        raise ValueError("; ".join(conflicts))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(yaml_text, encoding="utf-8")
    # The same merged view the next GET gives (packaged vehicle/areas when the text omits them).
    return load_station_zones(target_path)
