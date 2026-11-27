"""Rasterize the active site map's wall faces into a Nav2 occupancy map in the SITE frame (pure, stdlib only).

Ports the idea of `middleware/perception/map/map_260905_update_v2/scripts/generate_map.py` `rasterize()` (free inside
the walled arena, unknown outside, trinary PGM) to Fleet's `SiteWall` faces, without numpy (Fleet does not ship it).
A face has no thickness in the site map and real walls (10 mm) are thinner than a cell, so every face is drawn at
least one cell wide. The output is deterministic: the same faces always give the same bytes and sha256.
"""

from __future__ import annotations

import base64
import hashlib
import math
import struct
from typing import Iterable

from core_common.protocol.map_grid import occupancy_map_id

OCCUPIED, FREE, UNKNOWN = 0, 254, 205  # trinary PGM values Nav2 map_server reads with negate 0
DEFAULT_RESOLUTION_M = 0.025
OCCUPIED_THRESH = 0.65
FREE_THRESH = 0.25
MARGIN_M = 0.10  # unknown border around the walls, so the outside is never cut off
OFF_LANE_COST = 60  # graded non-lethal (<= 98) preference cost outside mapped lanes
SHOULDER_MAX_COST = 25
CENTER_BAND_RATIO = 0.25
PARKING_KINDS = frozenset({"charge", "park"})


class WallGridError(ValueError):
    """The faces cannot make a map (none given, or not finite)."""


def _dist_to_segment(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))


def rasterize(faces: Iterable[tuple[tuple[float, float], tuple[float, float]]],
              resolution: float = DEFAULT_RESOLUTION_M) -> dict:
    """Faces in site metres -> `{width, height, origin, rows}`; rows are bottom-up lists of 0 / 254 / 205."""
    faces = [(tuple(a), tuple(b)) for a, b in faces]
    if not faces or resolution <= 0 or not all(math.isfinite(v) for f in faces for p in f for v in p):
        raise WallGridError("need at least one finite wall face and a positive resolution")
    xs = [p[0] for f in faces for p in f]
    ys = [p[1] for f in faces for p in f]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    ix0, iy0 = math.floor((x0 - MARGIN_M) / resolution), math.floor((y0 - MARGIN_M) / resolution)
    width = math.ceil((x1 + MARGIN_M) / resolution) - ix0
    height = math.ceil((y1 + MARGIN_M) / resolution) - iy0
    ox, oy = round(ix0 * resolution, 6), round(iy0 * resolution, 6)
    rows = [[UNKNOWN] * width for _ in range(height)]

    def centre(c: int, r: int) -> tuple[float, float]:
        return ox + (c + 0.5) * resolution, oy + (r + 0.5) * resolution

    for r in range(height):  # free = inside the walls' bounding box; closed or not, the arena is never unknown
        for c in range(width):
            x, y = centre(c, r)
            if x0 < x < x1 and y0 < y < y1:
                rows[r][c] = FREE
    reach = resolution  # cells whose centre is within half a cell of the face, plus one cell of search
    for a, b in faces:
        c_lo, c_hi = int((min(a[0], b[0]) - ox) // resolution) - 1, int((max(a[0], b[0]) - ox) // resolution) + 1
        r_lo, r_hi = int((min(a[1], b[1]) - oy) // resolution) - 1, int((max(a[1], b[1]) - oy) // resolution) + 1
        for r in range(max(r_lo, 0), min(r_hi, height - 1) + 1):
            for c in range(max(c_lo, 0), min(c_hi, width - 1) + 1):
                x, y = centre(c, r)
                if _dist_to_segment(x, y, a, b) <= reach / 2 + 1e-9:
                    rows[r][c] = OCCUPIED
    return {"width": width, "height": height, "origin": (ox, oy), "rows": rows}


def pgm_bytes(grid: dict) -> bytes:
    """P5 bytes; pgm row 0 is the top, so the bottom-up rows are written reversed."""
    body = b"".join(bytes(row) for row in reversed(grid["rows"]))
    return f"P5\n{grid['width']} {grid['height']}\n255\n".encode() + body


def nav2_grid_id(grid: dict, resolution: float) -> str:
    """Content id of this trinary artifact as delivered in a ROS OccupancyGrid."""
    values = {}
    for value in (OCCUPIED, FREE, UNKNOWN):
        occupancy = 1.0 - value / 255
        values[value] = 100 if occupancy > OCCUPIED_THRESH else 0 if occupancy < FREE_THRESH else -1
    # OccupancyGrid metadata carries resolution as float32, unlike the YAML input.
    wire_resolution = struct.unpack("<f", struct.pack("<f", resolution))[0]
    return occupancy_map_id({
        "width": grid["width"], "height": grid["height"], "resolution": wire_resolution,
        "origin": {"x": grid["origin"][0], "y": grid["origin"][1], "yaw": 0.0},
        "data": [values[pixel] for row in grid["rows"] for pixel in row],
    })


def build(map_id: str, version: int, faces, resolution: float = DEFAULT_RESOLUTION_M) -> dict:
    """The artifact Fleet serves: pgm bytes, the Nav2 yaml as a dict, its sha256 and the file stem."""
    grid = rasterize(faces, resolution)
    stem = f"wall_{map_id}_v{version}"
    pgm = pgm_bytes(grid)
    return {"map_id": map_id, "version": version, "resolution": resolution, "file_stem": stem,
            "pgm": pgm, "sha256": hashlib.sha256(pgm).hexdigest(), "grid_id": nav2_grid_id(grid, resolution),
            "yaml": {"image": f"{stem}.pgm", "mode": "trinary", "resolution": resolution,
                     "origin": [grid["origin"][0], grid["origin"][1], 0.0], "negate": 0,
                     "occupied_thresh": OCCUPIED_THRESH, "free_thresh": FREE_THRESH},
            "width": grid["width"], "height": grid["height"]}


def _get(obj, key: str, alt: str | None = None, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default if alt is None else obj.get(alt, default))
    val = getattr(obj, key, default)
    return val if val is not None or alt is None else getattr(obj, alt, default)


def _bay_place_ids(edges, places) -> set[str]:
    kind_of = {_get(p, "id"): _get(p, "kind") for p in places}
    bay_places: set[str] = set()
    for edge in edges:
        eid = _get(edge, "id", default="")
        if isinstance(eid, str) and eid.startswith("bay_"):
            for pid in (_get(edge, "from_", "from"), _get(edge, "to")):
                if pid and kind_of.get(pid) != "stop":
                    bay_places.add(pid)
    return bay_places | {pid for pid, kind in kind_of.items() if kind in PARKING_KINDS}


def build_lane_mask(map_id: str, version: int, walls, edges, places=(),
                    resolution: float = DEFAULT_RESOLUTION_M) -> dict:
    """Site-frame Nav2 KeepoutFilter scale mask matching ``wall_<map_id>_v<version>`` origin/size (non-lethal)."""
    wall_faces = [(tuple(a), tuple(b)) for a, b in walls]
    edge_list = list(edges)
    if not wall_faces or resolution <= 0 or not all(math.isfinite(v) for f in wall_faces for p in f for v in p):
        raise WallGridError("need at least one finite wall face and a positive resolution")
    if not edge_list:
        raise WallGridError("need at least one lane edge to build a lane mask")
    xs = [p[0] for f in wall_faces for p in f]
    ys = [p[1] for f in wall_faces for p in f]
    ix0, iy0 = math.floor((min(xs) - MARGIN_M) / resolution), math.floor((min(ys) - MARGIN_M) / resolution)
    width = math.ceil((max(xs) + MARGIN_M) / resolution) - ix0
    height = math.ceil((max(ys) + MARGIN_M) / resolution) - iy0
    ox, oy = round(ix0 * resolution, 6), round(iy0 * resolution, 6)
    costs = [[OFF_LANE_COST] * width for _ in range(height)]
    park_places = _bay_place_ids(edge_list, places)
    for edge in edge_list:
        poly = [tuple(p) for p in (_get(edge, "polyline") or ())]
        width_m = float(_get(edge, "width_m", default=0.0))
        if len(poly) < 2 or not math.isfinite(width_m) or width_m <= 0.0:
            raise WallGridError("each lane edge needs a valid polyline and positive width_m")
        half = width_m / 2.0
        center = width_m * CENTER_BAND_RATIO
        eid = _get(edge, "id", default="")
        is_parking = (isinstance(eid, str) and eid.startswith("bay_")) or any(
            pid in park_places for pid in (_get(edge, "from_", "from"), _get(edge, "to")) if pid)
        for a, b in zip(poly, poly[1:]):
            c_lo = max(0, int((min(a[0], b[0]) - half - ox) // resolution) - 1)
            c_hi = min(width - 1, int((max(a[0], b[0]) + half - ox) // resolution) + 1)
            r_lo = max(0, int((min(a[1], b[1]) - half - oy) // resolution) - 1)
            r_hi = min(height - 1, int((max(a[1], b[1]) + half - oy) // resolution) + 1)
            for r in range(r_lo, r_hi + 1):
                for c in range(c_lo, c_hi + 1):
                    d = _dist_to_segment(ox + (c + 0.5) * resolution, oy + (r + 0.5) * resolution, a, b)
                    if d <= half:
                        if is_parking or d <= center:
                            cost = 0
                        else:
                            cost = int(round(SHOULDER_MAX_COST * (d - center) / max(1e-9, half - center)))
                        if cost < costs[r][c]:
                            costs[r][c] = cost
    rows = [[max(1, min(255, round(255 * (1.0 - cost / 100.0)))) for cost in row] for row in costs]
    stem = f"lane_mask_{map_id}_v{version}"
    pgm = pgm_bytes({"width": width, "height": height, "rows": rows})
    return {"map_id": map_id, "version": version, "resolution": resolution, "file_stem": stem,
            "pgm": pgm, "sha256": hashlib.sha256(pgm).hexdigest(),
            "yaml": {"image": f"{stem}.pgm", "mode": "scale", "resolution": resolution,
                     "origin": [ox, oy, 0.0], "negate": 0, "occupied_thresh": 1.0, "free_thresh": 0.0},
            "filter_info": {"type": 0, "filter_mask_topic": "/keepout_filter_mask", "base": 0.0, "multiplier": 1.0},
            "width": width, "height": height}


def grid_route_response(active, kind: str, error_fn) -> dict:
    """Shared HTTP payload builder for /site-map/wall-grid and /site-map/lane-mask."""
    if active is None:
        raise error_fn(404, "SITE_MAP_NOT_ACTIVE", "activate a site map first")
    version, site = active[:2]
    if not site.walls:
        raise error_fn(404, "SITE_MAP_NO_WALLS", "the active site map has no walls")
    walls = [w.face for w in site.walls]
    if kind == "wall":
        built = build(site.map_id, version, walls)
    else:
        if not site.edges:
            raise error_fn(404, "SITE_MAP_NO_EDGES", "the active site map has no lane edges")
        built = build_lane_mask(site.map_id, version, walls, site.edges, site.places)
    pgm = built.pop("pgm")
    return {**built, "pgm_base64": base64.b64encode(pgm).decode("ascii")}
