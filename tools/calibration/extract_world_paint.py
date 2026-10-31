"""261026 world CAD STL -> lane paint mesh in the ROS site frame (ROS-free, stdlib only).

The source is the whole team world (track mat, lane paint, OMX cell plates, arms, conveyor):
binary STL, millimetres, Y-up, about 85 MB, kept out of Git (its sha256 is pinned below).
The mat top is the largest upward face; lane paint is a 1 mm layer on it. Only the paint's
upward faces are kept. Same transform as map_v2_fleet: R_x(+90 deg), mm -> m, centred on
the mat, never a mirror.

    python tools/calibration/extract_world_paint.py <261026_World.STL>
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

SOURCE_SHA256 = "dd91457a4a8d17d7fbb4fbfdb12dff9c2ae98e92e74760231c9ec08aa377f3cc"
MM = 0.001
#: Upward faces only (normal y component), and the paint layer's height band above the mat top.
UP_MIN = 0.95
PAINT_ABOVE_MAT_MM = (0.5, 1.5)
BUNDLE = Path(__file__).resolve().parents[2] / "middleware/perception/map/map_world_261026"


def _triangles(data: bytes):
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError("not a binary STL: size does not match triangle count")
    for i in range(count):
        v = struct.unpack_from("<12f", data, 84 + 50 * i)
        yield v[1], ((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11]))


def _area(t) -> float:
    (ax, _, az), (bx, _, bz), (cx, _, cz) = t
    return abs((bx - ax) * (cz - az) - (cx - ax) * (bz - az)) / 2.0


def extract(data: bytes) -> dict:
    up = [t for ny, t in _triangles(data) if ny >= UP_MIN]
    # The mat is the height with the most upward area.
    by_height: dict[float, float] = {}
    for t in up:
        key = round(sum(v[1] for v in t) / 3.0, 1)
        by_height[key] = by_height.get(key, 0.0) + _area(t)
    mat_y = max(by_height, key=by_height.get)
    mat = [t for t in up if abs(sum(v[1] for v in t) / 3.0 - mat_y) < 0.05]
    xs = [v[0] for t in mat for v in t]
    zs = [v[2] for t in mat for v in t]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
    lo, hi = PAINT_ABOVE_MAT_MM
    paint = [t for t in up
             if lo <= sum(v[1] for v in t) / 3.0 - mat_y <= hi
             and all(x0 <= v[0] <= x1 and z0 <= v[2] <= z1 for v in t)]
    if not paint:
        raise ValueError("no lane paint found above the mat")

    def ros(v):
        return ((v[0] - cx) * MM, -(v[2] - cz) * MM, (v[1] - mat_y) * MM)

    return {
        "mat_size_m": ((x1 - x0) * MM, (z1 - z0) * MM),
        "mat_height_mm": mat_y,
        "paint_area_m2": sum(_area(t) for t in paint) * MM * MM,
        "lines": [tuple(ros(v) for v in t) for t in paint],
    }


def write_mesh(lines, path: Path) -> None:
    header = b"rosy map_world_261026 road_lines (metres, Z-up)".ljust(80, b" ")
    body = bytearray(header + struct.pack("<I", len(lines)))
    for t in lines:
        body += struct.pack("<12fH", 0.0, 0.0, 1.0, *t[0], *t[1], *t[2], 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(body))


def main(argv: list[str]) -> int:
    data = Path(argv[1]).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if SOURCE_SHA256 != "replace-after-first-run" and digest != SOURCE_SHA256:
        print(f"source sha256 {digest} is not the pinned 261026 world", file=sys.stderr)
        return 1
    scene = extract(data)
    write_mesh(scene["lines"], BUNDLE / "meshes" / "road_lines.stl")
    meta = {"source_sha256": digest, "mat_size_m": [round(v, 4) for v in scene["mat_size_m"]],
            "mat_height_mm": scene["mat_height_mm"], "paint_area_m2": round(scene["paint_area_m2"], 4),
            "paint_triangles": len(scene["lines"])}
    (BUNDLE / "meshes" / "road_lines.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
