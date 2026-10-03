"""MAP v2 fleet — 260919 CAD STL to a ROS-frame road scene (ROS-free).

The STL is millimetres, Y-up. Floor paint (lane lines, roundabout, crosswalks)
is 0.1 mm thick; the only tall solid is a 5 mm perimeter wall ring. Nothing is
reshaped: geometry is rotated R_x(+90 deg), scaled to metres and centred.
"""

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

MM = 0.001
#: Floor paint is 0.1 mm; anything taller than 1 mm is a solid.
FLOOR_MAX_UP_MM = 1.0

Vertex = tuple[float, float, float]
Triangle = tuple[Vertex, Vertex, Vertex]


@dataclass(frozen=True)
class WallBox:
    cx: float
    cy: float
    size_x: float
    size_y: float
    height: float


@dataclass(frozen=True)
class RoadScene:
    source_sha256: str
    triangle_count: int
    wall_triangle_count: int
    size_x: float
    size_y: float
    lines: tuple[Triangle, ...]
    walls: tuple[WallBox, ...]


def stl_to_ros(p: Vertex, centre: tuple[float, float]) -> Vertex:
    """(x, y_up, z) mm -> ROS (x, y, z) m. Proper rotation, never a mirror."""
    x, y, z = p
    return ((x - centre[0]) * MM, -(z - centre[1]) * MM, y * MM)


def _read_triangles(data: bytes) -> list[Triangle]:
    if len(data) < 84:
        raise ValueError("not a binary STL: shorter than the 84-byte header")
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError("not a binary STL: size does not match triangle count")
    triangles = []
    for i in range(count):
        v = struct.unpack_from("<12f", data, 84 + 50 * i)
        triangles.append(((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11])))
    return triangles


def _ring_walls(tall: list[Triangle]) -> tuple[tuple[WallBox, ...], tuple[float, float], float, float]:
    """Rebuild the perimeter ring as four boxes and fail closed otherwise."""
    xs = sorted({round(v[0], 3) for t in tall for v in t})
    zs = sorted({round(v[2], 3) for t in tall for v in t})
    heights = {round(v[1], 3) for t in tall for v in t}
    if len(xs) != 4 or len(zs) != 4 or len(heights) != 2:
        raise ValueError("tall geometry is not a single rectangular wall ring")
    if abs(min(heights)) > 1e-3:
        raise ValueError("wall ring does not sit on the floor (base is not at y=0)")
    thick_x, thick_z = xs[1] - xs[0], zs[1] - zs[0]
    if abs(thick_x - (xs[3] - xs[2])) > 1e-3 or abs(thick_z - (zs[3] - zs[2])) > 1e-3:
        raise ValueError("wall ring thickness is not uniform")
    height = max(heights) * MM
    x0, x1, z0, z1 = xs[0], xs[3], zs[0], zs[3]
    cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
    lx, lz = (x1 - x0) * MM, (z1 - z0) * MM
    tx, tz = thick_x * MM, thick_z * MM
    return (
        WallBox(0.0, (lz - tz) / 2.0, lx, tz, height),    # STL z0 side -> ROS +y
        WallBox(0.0, -(lz - tz) / 2.0, lx, tz, height),   # STL z1 side -> ROS -y
        WallBox(-(lx - tx) / 2.0, 0.0, tx, lz, height),
        WallBox((lx - tx) / 2.0, 0.0, tx, lz, height),
    ), (cx, cz), lx, lz


def load_scene(path: Path | str) -> RoadScene:
    data = Path(path).read_bytes()
    triangles = _read_triangles(data)
    tall = [t for t in triangles if max(v[1] for v in t) > FLOOR_MAX_UP_MM]
    floor = [t for t in triangles if max(v[1] for v in t) <= FLOOR_MAX_UP_MM]
    walls, centre, size_x, size_y = _ring_walls(tall)
    lines = tuple(tuple(stl_to_ros(v, centre) for v in t) for t in floor)
    return RoadScene(
        source_sha256=hashlib.sha256(data).hexdigest(),
        triangle_count=len(triangles),
        wall_triangle_count=len(tall),
        size_x=size_x,
        size_y=size_y,
        lines=lines,
        walls=walls,
    )
