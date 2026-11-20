"""Rasterize the active site map's wall faces into a Nav2 occupancy map in the SITE frame (pure, stdlib only).

Ports the idea of `middleware/perception/map/map_260905_update_v2/scripts/generate_map.py` `rasterize()` (free inside
the walled arena, unknown outside, trinary PGM) to Fleet's `SiteWall` faces, without numpy (Fleet does not ship it).
A face has no thickness in the site map and real walls (10 mm) are thinner than a cell, so every face is drawn at
least one cell wide. The output is deterministic: the same faces always give the same bytes and sha256.
"""

from __future__ import annotations

import hashlib
import math
from typing import Iterable

OCCUPIED, FREE, UNKNOWN = 0, 254, 205  # trinary PGM values Nav2 map_server reads with negate 0
DEFAULT_RESOLUTION_M = 0.025
MARGIN_M = 0.10  # unknown border around the walls, so the outside is never cut off


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


def build(map_id: str, version: int, faces, resolution: float = DEFAULT_RESOLUTION_M) -> dict:
    """The artifact Fleet serves: pgm bytes, the Nav2 yaml as a dict, its sha256 and the file stem."""
    grid = rasterize(faces, resolution)
    stem = f"wall_{map_id}_v{version}"
    pgm = pgm_bytes(grid)
    return {"map_id": map_id, "version": version, "resolution": resolution, "file_stem": stem,
            "pgm": pgm, "sha256": hashlib.sha256(pgm).hexdigest(),
            "yaml": {"image": f"{stem}.pgm", "mode": "trinary", "resolution": resolution,
                     "origin": [grid["origin"][0], grid["origin"][1], 0.0], "negate": 0,
                     "occupied_thresh": 0.65, "free_thresh": 0.25},
            "width": grid["width"], "height": grid["height"]}
